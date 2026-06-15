"""Commit de arquivos Markdown em repositórios GitHub via Contents API (PAT efêmero do request)."""

from __future__ import annotations

import base64
import re
from urllib.parse import quote

import httpx

from app.services.github_archive import GitHubArchiveError, parse_github_url

GITHUB_API = "https://api.github.com"

_TARGET_PATH_RE = re.compile(r"^[a-zA-Z0-9_./-]+\.md$")


class GitHubCommitError(Exception):
    pass


def _validate_target_path(path: str) -> str:
    p = path.strip().lstrip("/")
    if not p or ".." in p or not _TARGET_PATH_RE.match(p):
        raise GitHubCommitError(
            "Caminho inválido. Use apenas letras, números, /, _ e -, terminando em .md (ex.: README.md)."
        )
    return p


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "AutoDocTCC/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _resolve_branch(client: httpx.Client, *, owner: str, repo: str, branch: str | None, token: str) -> str:
    if branch and branch.strip():
        return branch.strip()
    r = client.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=_headers(token),
        follow_redirects=True,
        timeout=30.0,
    )
    if r.status_code == 404:
        raise GitHubCommitError("Repositório não encontrado ou sem acesso com este token.")
    if r.status_code == 401:
        raise GitHubCommitError("Token GitHub inválido ou expirado.")
    if r.status_code == 403:
        raise GitHubCommitError("Token sem permissão para acessar este repositório.")
    if r.status_code != 200:
        raise GitHubCommitError(f"GitHub API erro {r.status_code} ao obter repositório.")
    return str(r.json().get("default_branch") or "main")


def _get_existing_sha(
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
        follow_redirects=True,
        timeout=30.0,
    )
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise GitHubCommitError(
            f"Não foi possível verificar o arquivo existente (HTTP {r.status_code})."
        )
    data = r.json()
    if isinstance(data, list):
        raise GitHubCommitError("O caminho informado aponta para um diretório, não um arquivo.")
    sha = data.get("sha")
    return str(sha) if sha else None


def _fetch_existing_content(
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
        follow_redirects=True,
        timeout=30.0,
    )
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, list):
        return None
    raw = data.get("content") or ""
    if data.get("encoding") == "base64" and raw:
        try:
            return base64.b64decode(raw.replace("\n", "")).decode("utf-8")
        except UnicodeDecodeError:
            return base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="replace")
    return str(raw) if raw else None


def commit_markdown_file(
    *,
    github_url: str,
    content: str,
    github_token: str,
    branch: str | None = None,
    target_path: str = "README.md",
    commit_message: str = "docs: atualiza documentação via AutoDoc",
) -> dict[str, str]:
    """
    Cria ou atualiza um arquivo .md no repositório.
    Retorna commit_sha, commit_url, target_path, branch.
    """
    token = github_token.strip()
    if not token:
        raise GitHubCommitError("Token GitHub não informado.")

    try:
        owner, repo, url_branch = parse_github_url(github_url)
    except GitHubArchiveError as e:
        raise GitHubCommitError(str(e)) from e

    path = _validate_target_path(target_path)
    message = commit_message.strip() or "docs: atualiza documentação via AutoDoc"

    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        ref = _resolve_branch(
            client,
            owner=owner,
            repo=repo,
            branch=branch or url_branch,
            token=token,
        )
        existing_sha = _get_existing_sha(
            client,
            owner=owner,
            repo=repo,
            path=path,
            branch=ref,
            token=token,
        )

        if existing_sha:
            existing_content = _fetch_existing_content(
                client,
                owner=owner,
                repo=repo,
                path=path,
                branch=ref,
                token=token,
            )
            if existing_content is not None and existing_content.strip() == content.strip():
                raise GitHubCommitError(
                    "SKIP_UNCHANGED: o conteúdo gerado é idêntico ao arquivo remoto; commit não necessário."
                )

        body: dict[str, str] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": ref,
        }
        if existing_sha:
            body["sha"] = existing_sha

        encoded_path = quote(path, safe="/")
        r = client.put(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{encoded_path}",
            headers=_headers(token),
            json=body,
            timeout=60.0,
        )

        if r.status_code == 401:
            raise GitHubCommitError("Token GitHub inválido ou expirado.")
        if r.status_code == 403:
            raise GitHubCommitError(
                "Token sem permissão para escrever neste repositório. "
                "Use um PAT com escopo 'repo' (privado) ou 'public_repo' (público)."
            )
        if r.status_code == 404:
            raise GitHubCommitError("Repositório, branch ou caminho não encontrado.")
        if r.status_code not in (200, 201):
            detail = r.text[:300] if r.text else ""
            raise GitHubCommitError(f"Falha ao publicar no GitHub (HTTP {r.status_code}). {detail}")

        data = r.json()
        commit = data.get("commit") or {}
        commit_sha = str(commit.get("sha") or "")
        commit_url = str(commit.get("html_url") or "")
        if not commit_sha:
            raise GitHubCommitError("GitHub não retornou identificador do commit.")

        return {
            "commit_sha": commit_sha,
            "commit_url": commit_url,
            "target_path": path,
            "branch": ref,
        }
