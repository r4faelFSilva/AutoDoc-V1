import io
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath
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

# Fator sobre GITHUB_MAX_DOWNLOAD_MB para o total extraído (arquivos de código comprimem bem).
EXTRACTED_SIZE_FACTOR = 4

# Timeouts por operação; o prazo TOTAL do download é GITHUB_DOWNLOAD_TIMEOUT_SECONDS.
_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=15.0, write=15.0, pool=10.0)


class GitHubArchiveError(Exception):
    pass


_NEED_TOKEN_MSG = (
    "Repositório não encontrado ou privado. Se ele for privado, informe o seu token do "
    "GitHub (campo github_token ou header X-GitHub-Token)."
)
_NO_ACCESS_MSG = "Repositório não encontrado ou o token do GitHub informado não tem acesso a ele."


def resolve_token(user_token: str | None) -> str | None:
    """Token usado no download: o do usuário; o do servidor só com ALLOW_SERVER_GITHUB_TOKEN."""
    if user_token and user_token.strip():
        return user_token.strip()
    if settings.allow_server_github_token and settings.github_token:
        return settings.github_token
    return None


def _headers(token: str | None) -> dict[str, str]:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AutoDocTCC/1.0",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _access_error(response: httpx.Response, token: str | None) -> GitHubArchiveError:
    status_code = response.status_code
    if status_code == 401:
        return GitHubArchiveError("O token do GitHub informado é inválido ou expirou.")
    if status_code in (403, 429) and response.headers.get("x-ratelimit-remaining") == "0":
        return GitHubArchiveError(
            "Limite de requisições da API do GitHub atingido. Tente mais tarde ou informe "
            "o seu token do GitHub, que tem um limite maior."
        )
    if status_code in (403, 404):
        return GitHubArchiveError(_NO_ACCESS_MSG if token else _NEED_TOKEN_MSG)
    return GitHubArchiveError(f"Falha ao acessar o repositório no GitHub (HTTP {status_code}).")


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


def _timeout_error() -> GitHubArchiveError:
    return GitHubArchiveError(f"O GitHub não respondeu em {settings.github_download_timeout_seconds:g} s.")


def _too_big_error() -> GitHubArchiveError:
    return GitHubArchiveError(f"O repositório é grande demais (> {settings.github_max_download_mb} MB).")


def _wanted(member_name: str) -> bool:
    """Mesmo critério da seleção de arquivos: só código/README, fora de pastas ignoradas."""
    parts = PurePosixPath(member_name).parts[1:]  # remove a pasta raiz do tarball
    if not parts or {p.lower() for p in parts} & SKIP_DIR_PARTS:
        return False
    name = parts[-1]
    return PurePosixPath(name).suffix.lower() in ALLOWED_SUFFIXES or name in ("README", "README.md", "Dockerfile")


def _download_tarball(client: httpx.Client, url: str, token: str | None, deadline: float) -> bytes:
    """Baixa em partes, respeitando o prazo total e o tamanho máximo."""
    max_bytes = settings.github_max_download_mb * 1024 * 1024
    with client.stream("GET", url, headers=_headers(token)) as r:
        if r.status_code in (401, 403, 429) or (r.status_code == 404 and not token):
            raise _access_error(r, token)
        if r.status_code != 200:
            raise GitHubArchiveError(
                f"Falha ao baixar o repositório (HTTP {r.status_code}). "
                "Verifique a URL e o branch."
            )
        declared = r.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise _too_big_error()
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise _too_big_error()
            if time.monotonic() >= deadline:
                raise _timeout_error()
        return bytes(buf)


def _fetch_default_branch(client: httpx.Client, owner: str, repo: str, token: str | None) -> str:
    r = client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_headers(token), follow_redirects=True)
    if r.status_code != 200:
        raise _access_error(r, token)
    data = r.json()
    return str(data.get("default_branch") or "main")


def fetch_repo_files(
    *,
    owner: str,
    repo: str,
    branch: str | None,
    max_files: int = MAX_FILES,
    max_total_chars: int = MAX_TOTAL_CHARS,
    max_file_chars: int = MAX_FILE_CHARS,
    github_token: str | None = None,
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Baixa o tarball e retorna (ref_resolvido, [(caminho, conteúdo)], avisos).

    github_token é o token do próprio usuário; sem ele, só repositórios públicos
    (salvo ALLOW_SERVER_GITHUB_TOKEN=true).
    """
    token = resolve_token(github_token)
    warnings: list[str] = []
    deadline = time.monotonic() + settings.github_download_timeout_seconds
    try:
        with httpx.Client(follow_redirects=True, timeout=_HTTP_TIMEOUT) as client:
            ref = branch or _fetch_default_branch(client, owner, repo, token)
            tarball_url = f"{GITHUB_API}/repos/{owner}/{repo}/tarball/{ref}"
            data = _download_tarball(client, tarball_url, token, deadline)
    except httpx.TimeoutException as e:
        raise _timeout_error() from e

    files: list[tuple[str, str]] = []
    max_extracted = settings.github_max_download_mb * 1024 * 1024 * EXTRACTED_SIZE_FACTOR

    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
            # Extrai só o que será lido, com teto no total descompactado.
            members = []
            extracted = 0
            for member in tf.getmembers():
                if not member.isfile() or not _wanted(member.name):
                    continue
                extracted += member.size
                if extracted > max_extracted:
                    raise _too_big_error()
                members.append(member)
            if not members:
                raise GitHubArchiveError("Nenhum arquivo de código reconhecido encontrado no repositório.")
            try:
                tf.extractall(tmp, members=members, filter="data")
            except TypeError:
                tf.extractall(tmp, members=members)
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
            if len(files) >= max_files:
                warnings.append(f"Limite de {max_files} arquivos atingido; demais foram omitidos.")
                break
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = p.relative_to(extract_root).as_posix()
            if len(raw) > max_file_chars:
                raw = raw[:max_file_chars] + "\n\n…(truncado)\n"
                warnings.append(f"Arquivo truncado: {rel}")
            if total_chars + len(raw) > max_total_chars:
                warnings.append(f"Limite total de {max_total_chars} caracteres atingido.")
                break
            total_chars += len(raw)
            files.append((rel, raw))

    if not files:
        raise GitHubArchiveError("Nenhum arquivo de código reconhecido encontrado no repositório.")
    return ref, files, warnings


def fetch_repo_text_bundle(
    *, owner: str, repo: str, branch: str | None, github_token: str | None = None
) -> tuple[str, str, list[str]]:
    """Retorna (ref_resolvido, bundle_texto, avisos) — formato do modo quick."""
    ref, files, warnings = fetch_repo_files(owner=owner, repo=repo, branch=branch, github_token=github_token)

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
