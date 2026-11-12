"""Limites de tempo, erros da IA, limites do GitHub e runs órfãos."""

import asyncio
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app import config
from app.core.llm import ChatResult

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class SlowProvider:
    def __init__(self, delay: float):
        self.delay = delay

    async def chat(self, **_kw):
        await asyncio.sleep(self.delay)
        return ChatResult(text="# Doc", model="fake-slow", input_tokens=1, output_tokens=1)


def _wait_terminal(client, headers, run_id, timeout=20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run não terminou: {run}")


def _new_run(status: str, *, started_at: datetime | None = None, agent: str = "documentador") -> int:
    from app.database import SessionLocal
    from app.models.agent_run import AgentRun
    from app.models.user import User

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "demo@autodoc.dev").one()
        run = AgentRun(
            user_id=user.id,
            agent=agent,
            status=status,
            input_json=json.dumps(
                {"source": "paste", "code": "x = 1", "template_id": 1, "output_type": "technical", "depth": "quick"}
            ),
            created_at=datetime.utcnow(),
            started_at=started_at,
        )
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _get_run(run_id: int):
    from app.database import SessionLocal
    from app.models.agent_run import AgentRun, RunEvent

    db = SessionLocal()
    try:
        run = db.query(AgentRun).filter(AgentRun.id == run_id).one()
        events = db.query(RunEvent).filter(RunEvent.run_id == run_id).order_by(RunEvent.seq).all()
        return run, [(e.kind, e.message) for e in events]
    finally:
        db.close()


# --- Limite total do run (item 2) -------------------------------------------


def test_run_que_excede_o_limite_falha_com_mensagem_clara(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    monkeypatch.setattr(config.settings, "agent_run_timeout_seconds", 0.5)
    monkeypatch.setattr(llm, "get_provider", lambda: SlowProvider(delay=10))

    started = time.monotonic()
    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={"input": {"source": "paste", "code": "def f():\n    return 1\n", "template_id": 1}},
    )
    assert resp.status_code == 202
    assert resp.json()["timeout_seconds"] == 0.5
    run = _wait_terminal(client, auth_headers, resp.json()["id"])

    assert time.monotonic() - started < 8, "o limite não interrompeu a chamada lenta"
    assert run["status"] == "failed"
    assert run["error"] == "A geração excedeu o limite de 0.5 s e foi interrompida. Tente novamente."
    _, events = _get_run(run["id"])
    assert events[-1] == ("failed", f"Run falhou: {run['error']}")


def test_limites_por_modo_e_agente(monkeypatch):
    from app.jobs.tasks import _timeout_message, run_timeout_seconds

    monkeypatch.setattr(config.settings, "agent_run_timeout_seconds", 300.0)
    monkeypatch.setattr(config.settings, "agent_run_timeout_deep_seconds", 900.0)
    assert run_timeout_seconds("documentador", {"depth": "quick"}) == 300.0
    assert run_timeout_seconds("documentador", '{"source": "paste"}') == 300.0
    assert run_timeout_seconds("documentador", {"depth": "deep"}) == 900.0
    assert run_timeout_seconds("arquiteto", {}) == 900.0
    assert run_timeout_seconds("gerador_testes", {}) == 900.0
    assert _timeout_message("documentador", {"depth": "quick"}, 300.0) == (
        "A geração excedeu o limite de 5 minutos e foi interrompida. Tente novamente."
    )
    assert _timeout_message("documentador", {"depth": "deep"}, 900.0) == (
        "A geração excedeu o limite de 15 minutos e foi interrompida. Tente novamente ou use o modo rápido."
    )


def test_padroes_dos_limites(monkeypatch):
    for var in ("AGENT_RUN_TIMEOUT_SECONDS", "AGENT_RUN_TIMEOUT_DEEP_SECONDS", "LLM_TIMEOUT_SECONDS",
                "LLM_MAX_RETRIES", "GITHUB_DOWNLOAD_TIMEOUT_SECONDS", "GITHUB_MAX_DOWNLOAD_MB"):
        monkeypatch.delenv(var, raising=False)
    cfg = config.Settings(_env_file=None)
    assert (cfg.agent_run_timeout_seconds, cfg.agent_run_timeout_deep_seconds) == (300.0, 900.0)
    assert (cfg.llm_timeout_seconds, cfg.llm_max_retries) == (120.0, 1)
    assert (cfg.github_download_timeout_seconds, cfg.github_max_download_mb) == (60.0, 50)


# --- Chamadas à IA (item 3) --------------------------------------------------


def test_timeout_da_openai_vira_mensagem_clara_e_usa_limites_configurados(monkeypatch):
    import openai

    from app.core.llm import LLMError, OpenAIProvider

    created: dict = {}

    class FakeCompletions:
        async def create(self, **_kw):
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))

    class FakeAsyncOpenAI:
        def __init__(self, **kw):
            created.update(kw)
            self.chat = type("Chat", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(config.settings, "llm_timeout_seconds", 120.0)
    monkeypatch.setattr(config.settings, "llm_max_retries", 1)

    with pytest.raises(LLMError, match=r"A IA \(OpenAI\) não respondeu em 120 s\."):
        asyncio.run(OpenAIProvider(api_key="k", model="m").chat(system_prompt="s", user_content="u"))
    assert created["timeout"] == 120.0
    assert created["max_retries"] == 1


def test_chave_invalida_vira_mensagem_clara():
    import openai

    from app.core.llm import describe_llm_error

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    error = openai.AuthenticationError("bad key", response=httpx.Response(401, request=request), body=None)
    assert describe_llm_error(error, "OpenAI") == "A chave da OpenAI (OPENAI_API_KEY) é inválida ou foi revogada."


# --- Runs interrompidos e órfãos (item 4) ------------------------------------


def test_run_cancelado_e_marcado_como_interrompido(client, auth_headers, monkeypatch):
    import app.core.llm as llm
    from app.jobs.tasks import INTERRUPTED_MESSAGE, execute_agent_run

    monkeypatch.setattr(llm, "get_provider", lambda: SlowProvider(delay=30))
    run_id = _new_run("queued")

    async def scenario():
        task = asyncio.create_task(execute_agent_run(None, run_id))
        await asyncio.sleep(0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    run, events = _get_run(run_id)
    assert run.status == "failed"
    assert run.error == INTERRUPTED_MESSAGE
    assert events[-1] == ("failed", f"Run falhou: {INTERRUPTED_MESSAGE}")


def test_fail_orphan_runs_modo_in_process(client):
    from app.jobs.tasks import INTERRUPTED_MESSAGE, fail_orphan_runs

    running = _new_run("running", started_at=datetime.utcnow())
    queued = _new_run("queued")
    done = _new_run("completed")

    assert fail_orphan_runs() >= 2
    for run_id in (running, queued):
        run, events = _get_run(run_id)
        assert (run.status, run.error) == ("failed", INTERRUPTED_MESSAGE)
        assert events[-1][0] == "failed"
    assert _get_run(done)[0].status == "completed"


def test_fail_orphan_runs_modo_worker_so_pega_runs_antigos(client):
    from app.jobs.tasks import fail_orphan_runs

    old = _new_run("running", started_at=datetime.utcnow() - timedelta(hours=2))
    recent = _new_run("running", started_at=datetime.utcnow())

    fail_orphan_runs(started_before=datetime.utcnow() - timedelta(hours=1))
    assert _get_run(old)[0].status == "failed"
    assert _get_run(recent)[0].status == "running"  # pode estar em outro worker


def test_api_marca_runs_orfaos_ao_iniciar(tmp_path):
    """Sobe app.main num processo novo sobre um banco com um run 'running' deixado para trás."""
    db_url = f"sqlite:///{(tmp_path / 'orfao.db').as_posix()}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("APP_", "SEED_", "DEMO_"))}
    env.update(
        APP_ENV="development", DATABASE_URL=db_url, REDIS_URL="", PYTHONPATH=str(BACKEND_ROOT), PYTHONIOENCODING="utf-8"
    )
    prepare = (
        "from datetime import datetime\n"
        "import app.models\n"
        "from app.database import Base, SessionLocal, engine\n"
        "from app.models.agent_run import AgentRun\n"
        "from app.models.user import User\n"
        "Base.metadata.create_all(bind=engine)\n"
        "db = SessionLocal(); u = User(email='a@b.com', hashed_password='x'); db.add(u); db.commit()\n"
        "db.add(AgentRun(user_id=u.id, agent='documentador', status='running', input_json='{}',"
        " created_at=datetime.utcnow(), started_at=datetime.utcnow())); db.commit()\n"
    )
    check = (
        "import app.main\n"
        "from app.database import SessionLocal\n"
        "from app.models.agent_run import AgentRun\n"
        "r = SessionLocal().query(AgentRun).one()\n"
        "print(r.status, '|', r.error)\n"
    )
    for code in (prepare, check):
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "failed | Execução interrompida: o servidor foi reiniciado."


# --- Download do GitHub (item 5) ---------------------------------------------


def _tarball(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(f"dono-repo-abc123/{name}")
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


@pytest.fixture
def github_mock(monkeypatch):
    """Instala um handler para as requisições do github_archive."""
    from app.services import github_archive

    real_client = httpx.Client
    monkeypatch.setattr(config.settings, "allow_server_github_token", False)

    def install(handler):
        monkeypatch.setattr(
            github_archive.httpx,
            "Client",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        )

    return install


def _fetch():
    from app.services.github_archive import fetch_repo_files

    return fetch_repo_files(owner="dono", repo="repo", branch="main")


def test_github_extrai_so_arquivos_de_codigo(github_mock):
    body = _tarball({
        "README.md": b"# Repo",
        "src/app.py": b"print('oi')",
        "node_modules/lib/index.js": b"module.exports = 1",
        "assets/video.mp4": b"\x00" * 1000,
    })
    github_mock(lambda request: httpx.Response(200, content=body))
    _ref, files, _warnings = _fetch()
    assert sorted(path for path, _ in files) == ["README.md", "src/app.py"]


def test_github_repositorio_grande_demais(github_mock, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "github_max_download_mb", 1)
    github_mock(lambda request: httpx.Response(200, content=os.urandom(2 * 1024 * 1024)))
    with pytest.raises(GitHubArchiveError, match=r"O repositório é grande demais \(> 1 MB\)\."):
        _fetch()


def test_github_extraido_grande_demais(github_mock, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "github_max_download_mb", 1)
    # 5 MB de código repetitivo comprime para poucos KB, mas passa de 4x o limite ao extrair
    body = _tarball({"src/gerado.py": b"x = 1\n" * (5 * 1024 * 1024 // 6)})
    assert len(body) < 1024 * 1024
    github_mock(lambda request: httpx.Response(200, content=body))
    with pytest.raises(GitHubArchiveError, match="grande demais"):
        _fetch()


def test_github_sem_resposta(github_mock):
    from app.services.github_archive import GitHubArchiveError

    def handler(request):
        raise httpx.ReadTimeout("sem resposta", request=request)

    github_mock(handler)
    with pytest.raises(GitHubArchiveError, match=r"O GitHub não respondeu em 60 s\."):
        _fetch()


def test_github_prazo_total(github_mock, monkeypatch):
    from app.services.github_archive import GitHubArchiveError

    monkeypatch.setattr(config.settings, "github_download_timeout_seconds", 0)
    github_mock(lambda request: httpx.Response(200, content=_tarball({"a.py": b"x = 1"})))
    with pytest.raises(GitHubArchiveError, match=r"O GitHub não respondeu em 0 s\."):
        _fetch()
