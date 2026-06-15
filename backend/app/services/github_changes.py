"""Consulta commits e conteúdo de arquivos no GitHub para avaliar staleness da documentação."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.services.github_archive import GitHubArchiveError, parse_github_url
from app.services.github_commit import GitHubCommitError, _headers, _resolve_branch, _validate_target_path

GITHUB_API = "https://api.github.com"

SKIP_PATH_PARTS = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        "__pycache__",
        ".venv",
        "venv",
        "target",
        ".gradle",
    }
)

MAX_PATCH_CHARS = 800
MAX_FILES_IN_SUMMARY = 25


@dataclass
class ChangedFile:
    filename: str
    status: str
    patch_summary: str


@dataclass
class LatestCommitInfo:
    sha: str
    message: str
    html_url: str


@dataclass
class RepoDocSnapshot:
    target_path: str
    branch: str
    content: str | None
    doc_exists: bool


@dataclass
class CommitAnalysisContext:
    owner: str
    repo: str
    branch: str
    target_path: str
    latest_commit: LatestCommitInfo
    doc: RepoDocSnapshot
    changed_files: list[ChangedFile]


def fetch_commit_analysis_context(
    *,
    github_url: str,
    github_token: str,
    branch: str | None = None,
    target_path: str = "README.md",
) -> CommitAnalysisContext:
    token = github_token.strip()
    if not token:
        raise GitHubCommitError("Token GitHub não informado.")

    try:
        owner, repo, url_branch = parse_github_url(github_url)
    except GitHubArchiveError as e:
        raise GitHubCommitError(str(e)) from e

    path = _validate_target_path(target_path)

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        ref = _resolve_branch(
            client,
            owner=owner,
            repo=repo,
            branch=branch or url_branch,
            token=token,
        )
        latest = _fetch_latest_commit(client, owner=owner, repo=repo, branch=ref, token=token)
        changed = _fetch_commit_files(
            client,
            owner=owner,
            repo=repo,
            sha=latest.sha,
            token=token,
            exclude_path=path,
        )
        doc_content = _fetch_file_content(
            client,
            owner=owner,
            repo=repo,
            path=path,
            branch=ref,
            token=token,
        )

    return CommitAnalysisContext(
        owner=owner,
        repo=repo,
        branch=ref,
        target_path=path,
        latest_commit=latest,
        doc=RepoDocSnapshot(
            target_path=path,
            branch=ref,
            content=doc_content,
            doc_exists=doc_content is not None,
        ),
        changed_files=changed,
    )


def _fetch_latest_commit(
    client: httpx.Client,
    *,
    owner: str,
    repo: str,
    branch: str,
    token: str,
) -> LatestCommitInfo:
    r = client.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits",
        headers=_headers(token),
        params={"sha": branch, "per_page": 1},
        timeout=30.0,
    )
    if r.status_code == 404:
        raise GitHubCommitError("Branch ou repositório não encontrado.")
    if r.status_code != 200:
        raise GitHubCommitError(f"GitHub API erro {r.status_code} ao obter último commit.")
    data = r.json()
    if not isinstance(data, list) or not data:
        raise GitHubCommitError("Nenhum commit encontrado no branch.")
    item = data[0]
    sha = str(item.get("sha") or "")
    commit = item.get("commit") or {}
    message = str(commit.get("message") or "").split("\n")[0]
    html_url = str(item.get("html_url") or "")
    if not sha:
        raise GitHubCommitError("GitHub não retornou SHA do último commit.")
    return LatestCommitInfo(sha=sha, message=message, html_url=html_url)


def _should_skip_file(filename: str, exclude_path: str) -> bool:
    norm = filename.replace("\\", "/").lstrip("/")
    if norm == exclude_path:
        return True
    parts = {p.lower() for p in norm.split("/")}
    if parts & SKIP_PATH_PARTS:
        return True
    return False


def _fetch_commit_files(
    client: httpx.Client,
    *,
    owner: str,
    repo: str,
    sha: str,
    token: str,
    exclude_path: str,
) -> list[ChangedFile]:
    r = client.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/commits/{sha}",
        headers=_headers(token),
        timeout=30.0,
    )
    if r.status_code != 200:
        raise GitHubCommitError(f"GitHub API erro {r.status_code} ao obter arquivos do commit.")
    files = r.json().get("files") or []
    result: list[ChangedFile] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "")
        if not filename or _should_skip_file(filename, exclude_path):
            continue
        status = str(item.get("status") or "modified")
        patch = str(item.get("patch") or "")
        if len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS] + "\n…(truncado)"
        result.append(ChangedFile(filename=filename, status=status, patch_summary=patch))
        if len(result) >= MAX_FILES_IN_SUMMARY:
            break
    return result


def _fetch_file_content(
    client: httpx.Client,
    *,
    owner: str,
    repo: str,
    path: str,
    branch: str,
    token: str,
) -> str | None:
    encoded_path = quote(path, safe="/")
    r = client.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{encoded_path}",
        headers=_headers(token),
        params={"ref": branch},
        timeout=30.0,
    )
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise GitHubCommitError(
            f"Não foi possível ler {path} no repositório (HTTP {r.status_code})."
        )
    data = r.json()
    if isinstance(data, list):
        raise GitHubCommitError("O caminho informado aponta para um diretório, não um arquivo.")
    encoding = str(data.get("encoding") or "")
    raw = data.get("content") or ""
    if encoding == "base64" and raw:
        try:
            return base64.b64decode(raw.replace("\n", "")).decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="replace")
    return str(raw) if raw else None
