import io
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

GITHUB_API = "https://api.github.com"

ALLOWED_SUFFIXES = frozenset({
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".cs",
    ".php",
    ".rb",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".rs",
    ".kt",
    ".swift",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".sh",
    ".toml",
})

SKIP_DIR_PARTS = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        "target",
        ".gradle",
    }
)

MAX_FILES = 80
MAX_TOTAL_CHARS = 120_000
MAX_FILE_CHARS = 12_000


class GitHubArchiveError(Exception):
    pass


def _headers() -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutoDocTCC/1.0",
    }
    if settings.github_token:
        h["Authorization"] = f"Bearer {settings.github_token}"
    return h


def parse_github_url(url: str) -> tuple[str, str, str | None]:
    u = url.strip()
    parsed = urlparse(u)
    if parsed.netloc not in ("github.com", "www.github.com"):
        raise GitHubArchiveError("URL deve ser do domínio github.com.")
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        raise GitHubArchiveError("Formato esperado: https://github.com/dono/repositorio")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    branch: str | None = None
    if len(parts) >= 4 and parts[2] == "tree":
        branch = parts[3]
    return owner, repo, branch


def _fetch_default_branch(client: httpx.Client, owner: str, repo: str) -> str:
    r = client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers(), follow_redirects=True, timeout=30.0)
    if r.status_code == 404:
        raise GitHubArchiveError("Repositório não encontrado ou sem acesso.")
    if r.status_code != 200:
        raise GitHubArchiveError(f"GitHub API erro {r.status_code}: {r.text[:200]}")
    data = r.json()
    return str(data.get("default_branch") or "main")


def fetch_repo_text_bundle(*, owner: str, repo: str, branch: str | None) -> tuple[str, list[tuple[str, str]], list[str]]:
    """
    Returns (resolved_ref, list of (relpath, content), warnings).
    """
    warnings: list[str] = []
    with httpx.Client(follow_redirects=True, timeout=120.0) as client:
        ref = branch or _fetch_default_branch(client, owner, repo)
        tarball_url = f"{GITHUB_API}/repos/{owner}/{repo}/tarball/{ref}"
        r = client.get(tarball_url, headers=_headers())
        if r.status_code != 200:
            raise GitHubArchiveError(
                f"Falha ao baixar o repositório (HTTP {r.status_code}). "
                "Verifique a URL, o branch e se o repo é público ou use GITHUB_TOKEN."
            )
        data = r.content

    files: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            try:
                tf.extractall(tmp, filter="data")
            except TypeError:
                tf.extractall(tmp)
        root = Path(tmp)
        subdirs = [p for p in root.iterdir() if p.is_dir()]
        if len(subdirs) != 1:
            raise GitHubArchiveError("Arquivo do repositório em formato inesperado.")
        extract_root = subdirs[0]
        root_prefix = extract_root.name

        candidates: list[Path] = []
        for p in extract_root.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(extract_root).as_posix()
            parts_lower = {x.lower() for x in p.parts}
            if parts_lower & SKIP_DIR_PARTS:
                continue
            if p.suffix.lower() not in ALLOWED_SUFFIXES and p.name not in ("README", "README.md", "Dockerfile"):
                continue
            candidates.append(p)

        def priority(path: Path) -> int:
            s = path.as_posix().lower()
            if "readme" in s:
                return 0
            if "/src/" in s or s.startswith("src/"):
                return 1
            if "main." in s or "app." in s or "/app/" in s:
                return 2
            return 5

        candidates.sort(key=lambda p: (priority(p), len(p.read_bytes())))

        total_chars = 0
        for p in candidates:
            if len(files) >= MAX_FILES:
                warnings.append(f"Limite de {MAX_FILES} arquivos atingido; demais foram omitidos.")
                break
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = p.relative_to(extract_root).as_posix()
            if len(raw) > MAX_FILE_CHARS:
                raw = raw[:MAX_FILE_CHARS] + "\n\n…(truncado)\n"
                warnings.append(f"Arquivo truncado: {rel}")
            if total_chars + len(raw) > MAX_TOTAL_CHARS:
                warnings.append(f"Limite total de {MAX_TOTAL_CHARS} caracteres atingido.")
                break
            total_chars += len(raw)
            files.append((rel, raw))

    if not files:
        raise GitHubArchiveError("Nenhum arquivo de código reconhecido encontrado no repositório.")

    tree_lines = [fp for fp, _ in files[:200]]
    bundle = "\n\n".join(
        [f"### Arquivo: `{fp}`\n```\n{content}\n```" for fp, content in files],
    )
    header = (
        f"Repositório: {owner}/{repo} (ref: {ref})\n"
        f"Arquivos incluídos ({len(files)}): {', '.join(tree_lines[:30])}"
        + ("…" if len(tree_lines) > 30 else "")
        + "\n\n"
    )
    if warnings:
        header += "Avisos:\n- " + "\n- ".join(warnings) + "\n\n"
    return ref, header + bundle, warnings
