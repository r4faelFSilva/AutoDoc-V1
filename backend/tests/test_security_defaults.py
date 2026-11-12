"""Padrões seguros: JWT, cadastro, usuário demo e token do GitHub do servidor."""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config
from app.config import DEFAULT_JWT_SECRET, InsecureConfigError, Settings, check_security

BACKEND_ROOT = Path(__file__).resolve().parent.parent
STRONG_SECRET = "x" * 48


# --- JWT ---------------------------------------------------------------------


def test_producao_recusa_jwt_padrao():
    with pytest.raises(InsecureConfigError, match="JWT_SECRET"):
        check_security(Settings(_env_file=None, app_env="production", jwt_secret=DEFAULT_JWT_SECRET))


def test_producao_recusa_valor_do_env_example():
    cfg = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret="change-me-in-production-use-long-random-string",
    )
    with pytest.raises(InsecureConfigError):
        check_security(cfg)


def test_producao_recusa_jwt_curto():
    with pytest.raises(InsecureConfigError, match="mínimo"):
        check_security(Settings(_env_file=None, app_env="production", jwt_secret="curto-demais"))


def test_producao_aceita_jwt_forte_e_desenvolvimento_aceita_padrao():
    check_security(Settings(_env_file=None, app_env="production", jwt_secret=STRONG_SECRET))
    check_security(Settings(_env_file=None, app_env="development", jwt_secret=DEFAULT_JWT_SECRET))


def test_padroes_seguros(monkeypatch):
    for var in ("APP_ENV", "SEED_DEMO_USER", "DEMO_PASSWORD", "ALLOW_REGISTRATION", "ALLOW_SERVER_GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    cfg = Settings(_env_file=None)
    assert cfg.app_env == "production"
    assert cfg.seed_demo_user is False
    assert cfg.allow_registration is False
    assert cfg.allow_server_github_token is False
    assert cfg.jwt_expire_minutes == 24 * 60
    assert cfg.cors_origin_list == ["http://localhost:4200"]


def test_api_nao_inicia_com_jwt_padrao_em_producao(tmp_path):
    """Importa app.main num processo limpo, como o uvicorn faria."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("APP_", "JWT_", "SEED_", "DEMO_"))}
    env.update(
        APP_ENV="production",
        JWT_SECRET=DEFAULT_JWT_SECRET,
        DATABASE_URL=f"sqlite:///{(tmp_path / 'prod.db').as_posix()}",
        PYTHONPATH=str(BACKEND_ROOT),
    )
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,  # longe do backend/.env local
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert "InsecureConfigError" in proc.stderr
    assert "JWT_SECRET" in proc.stderr
    assert not (tmp_path / "prod.db").exists()  # recusou antes de criar o banco


# --- Cadastro ----------------------------------------------------------------


def test_cadastro_bloqueado_por_padrao(client, monkeypatch):
    monkeypatch.setattr(config.settings, "allow_registration", False)
    assert client.get("/api/auth/config").json() == {"allow_registration": False}

    resp = client.post("/api/auth/register", json={"email": "novo@exemplo.com", "password": "senha-segura"})
    assert resp.status_code == 403
    assert "cadastro está desativado" in resp.json()["detail"]


def test_cadastro_liberado_com_flag(client, monkeypatch):
    monkeypatch.setattr(config.settings, "allow_registration", True)
    assert client.get("/api/auth/config").json() == {"allow_registration": True}

    resp = client.post("/api/auth/register", json={"email": "liberado@exemplo.com", "password": "senha-segura"})
    assert resp.status_code == 201
    assert resp.json()["access_token"]


# --- Usuário demo ------------------------------------------------------------


@pytest.fixture
def fresh_db():
    import app.models  # noqa: F401 — registra as tabelas
    from app.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_demo_nao_e_criado_por_padrao(fresh_db, monkeypatch):
    from app.models.template import Template
    from app.models.user import User
    from app.services.seed import run_seed

    monkeypatch.setattr(config.settings, "seed_demo_user", False)
    run_seed(fresh_db)
    assert fresh_db.query(User).count() == 0
    assert fresh_db.query(Template).count() > 0  # templates continuam sendo semeados


def test_demo_sem_senha_definida_gera_senha_aleatoria(fresh_db, monkeypatch, caplog):
    from app.models.user import User
    from app.services.auth_service import verify_password
    from app.services.seed import DEMO_EMAIL, run_seed

    monkeypatch.setattr(config.settings, "seed_demo_user", True)
    monkeypatch.setattr(config.settings, "demo_password", "")
    with caplog.at_level(logging.WARNING, logger="app.services.seed"):
        run_seed(fresh_db)
        run_seed(fresh_db)  # segunda inicialização: não recria nem mostra de novo

    user = fresh_db.query(User).filter(User.email == DEMO_EMAIL).one()
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1
    password = messages[0].split("senha gerada: ")[1].split(" ")[0]
    assert password != "demo"
    assert verify_password(password, user.hashed_password)


# --- Token do GitHub do servidor --------------------------------------------


@pytest.fixture
def github_spy(monkeypatch):
    """Intercepta as chamadas do github_archive; responde 404, como a API faz para repo privado."""
    from app.services import github_archive

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404, json={"message": "Not Found"})

    real_client = httpx.Client
    monkeypatch.setattr(
        github_archive.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(config.settings, "github_token", "token-do-servidor")
    return seen


def _fetch(**kw):
    from app.services.github_archive import fetch_repo_files

    return fetch_repo_files(owner="dono", repo="privado", branch=None, **kw)


def test_token_do_servidor_nao_e_usado_por_padrao(github_spy, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "allow_server_github_token", False)
    with pytest.raises(GitHubArchiveError, match="informe o seu token"):
        _fetch()
    assert github_spy, "nenhuma chamada ao GitHub foi feita"
    assert all("authorization" not in r.headers for r in github_spy)


def test_token_do_usuario_e_usado(github_spy, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "allow_server_github_token", False)
    with pytest.raises(GitHubArchiveError, match="não tem acesso"):
        _fetch(github_token="token-do-usuario")
    assert {r.headers["authorization"] for r in github_spy} == {"Bearer token-do-usuario"}


def test_token_do_servidor_so_com_flag(github_spy, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "allow_server_github_token", True)
    with pytest.raises(GitHubArchiveError):
        _fetch()
    assert {r.headers["authorization"] for r in github_spy} == {"Bearer token-do-servidor"}


def test_agente_recebe_token_do_header_sem_persistir(client, auth_headers, monkeypatch):
    from app.agents.documentador import graph as documentador
    from app.database import SessionLocal
    from app.models.agent_run import AgentRun
    from app.services.github_archive import GitHubArchiveError

    received: dict = {}

    def fake_fetch(**kw):
        received.update(kw)
        raise GitHubArchiveError("parado no teste")

    monkeypatch.setattr(documentador, "fetch_repo_files", fake_fetch)
    resp = client.post(
        "/api/agents/documentador/runs",
        headers={**auth_headers, "X-GitHub-Token": "token-do-usuario"},
        json={"input": {"source": "github", "github_url": "https://github.com/dono/privado", "template_id": 1}},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if client.get(f"/api/runs/{run_id}", headers=auth_headers).json()["status"] == "failed":
            break
        time.sleep(0.1)

    assert received["github_token"] == "token-do-usuario"
    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).one()
        assert "token-do-usuario" not in run.input_json
        assert "token-do-usuario" not in (run.error or "")
    finally:
        db.close()
