"""Fixtures dos testes.

IMPORTANTE: o banco de teste é definido via env var ANTES de qualquer import
de app.* — settings e engine são criados no import de app.config/app.database.
"""

import os
import tempfile
from pathlib import Path

_TEST_DB = Path(tempfile.mkdtemp(prefix="autodoc-test-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.as_posix()}"
os.environ["REDIS_URL"] = ""  # força modo fallback (jobs in-process)
os.environ["OPENAI_API_KEY"] = "test-key-nao-usada"
# a suíte loga com o usuário demo; fora disso, valem os padrões seguros
os.environ["APP_ENV"] = "development"
os.environ["SEED_DEMO_USER"] = "true"
os.environ["DEMO_PASSWORD"] = "demo"
# permite ao gerador de testes executar unittest local (conteúdo controlado pelos testes)
os.environ["TESTGEN_EXECUTION"] = "local"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    resp = client.post("/api/auth/login", json={"email": "demo@autodoc.dev", "password": "demo"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
