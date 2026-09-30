"""E2E do gerador de testes: geração → execução local → reparo → métricas."""

import json
import time

from app.core.llm import ChatResult

SOURCE = "def soma(a, b):\n    return a + b\n\n\ndef dividir(a, b):\n    return a / b\n"

GOOD_TEST = """import unittest
from calculadora import soma, dividir


class TestCalculadora(unittest.TestCase):
    def test_soma_basica(self):
        self.assertEqual(soma(2, 3), 5)

    def test_dividir_por_zero_levanta_erro(self):
        with self.assertRaises(ZeroDivisionError):
            dividir(1, 0)


if __name__ == "__main__":
    unittest.main()
"""

BAD_TEST = GOOD_TEST.replace("self.assertEqual(soma(2, 3), 5)", "self.assertEqual(soma(2, 3), 6)")


class FakeTestgenProvider:
    """Roteirizado: a 1ª geração pode ser ruim; o reparo devolve a boa."""

    def __init__(self, first_test: str):
        self.first_test = first_test
        self.calls: list[str] = []

    async def chat(self, *, system_prompt, user_content, json_mode=False, max_output_tokens=None, temperature=0.3):
        if "corrige um arquivo de testes" in system_prompt:
            self.calls.append("repair")
            text = json.dumps({"test_code": GOOD_TEST})
        elif "unittest" in system_prompt:
            self.calls.append("generate")
            text = json.dumps({"test_code": self.first_test})
        else:
            self.calls.append("other")
            text = "{}"
        return ChatResult(text=text, model="fake-testgen", input_tokens=4, output_tokens=6)


def _run(client, headers, payload, timeout=60.0):
    resp = client.post("/api/agents/gerador_testes/runs", headers=headers, json={"input": payload})
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.15)
    raise AssertionError(f"run não terminou: {run}")


def test_geracao_que_passa_de_primeira(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeTestgenProvider(first_test=GOOD_TEST)
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    run = _run(
        client,
        auth_headers,
        {"source": "paste", "code": SOURCE, "filename": "calculadora.py"},
    )
    assert run["status"] == "completed", run
    out = run["output"]
    assert out["status"] == "passed"
    assert out["execution_mode"] == "local"
    assert out["attempts"] == 0
    assert out["test_filename"] == "test_calculadora.py"
    assert provider.calls == ["generate"]


def test_reparo_apos_falha(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeTestgenProvider(first_test=BAD_TEST)
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    run = _run(
        client,
        auth_headers,
        {"source": "paste", "code": SOURCE, "filename": "calculadora.py"},
    )
    assert run["status"] == "completed", run
    out = run["output"]
    assert out["status"] == "passed"
    assert out["attempts"] == 1
    assert provider.calls == ["generate", "repair"]
    assert "assertEqual(soma(2, 3), 5)" in out["test_code"]

    # artifacts e métricas
    from app.database import SessionLocal
    from app.models.agent_run import Artifact, Evaluation

    db = SessionLocal()
    try:
        artifact_kinds = {a.kind for a in db.query(Artifact).filter(Artifact.run_id == run["id"]).all()}
        metrics = {
            e.metric: e.score for e in db.query(Evaluation).filter(Evaluation.run_id == run["id"]).all()
        }
    finally:
        db.close()
    assert "tests" in artifact_kinds
    assert "test_execution" in artifact_kinds
    assert metrics["tests_passed"] == 1.0
    assert metrics["repair_attempts"] == 1.0


def test_sem_sandbox_vira_not_executed(client, auth_headers, monkeypatch):
    import app.core.llm as llm
    from app.agents.testgen import sandbox

    provider = FakeTestgenProvider(first_test=GOOD_TEST)
    monkeypatch.setattr(llm, "get_provider", lambda: provider)
    monkeypatch.setattr(sandbox, "resolve_mode", lambda: "none")

    run = _run(
        client,
        auth_headers,
        {"source": "paste", "code": SOURCE, "filename": "calculadora.py"},
    )
    assert run["status"] == "completed", run
    out = run["output"]
    assert out["status"] == "not_executed"
    assert "NÃO executados" in out["summary"]


def test_github_sem_target_path_rejeitado(client, auth_headers):
    resp = client.post(
        "/api/agents/gerador_testes/runs",
        headers=auth_headers,
        json={"input": {"source": "github", "github_url": "https://github.com/a/b"}},
    )
    assert resp.status_code == 422


def test_codigo_com_erro_de_sintaxe_falha_cedo(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeTestgenProvider(first_test=GOOD_TEST)
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    run = _run(
        client,
        auth_headers,
        {"source": "paste", "code": "def quebrado(:", "filename": "quebrado.py"},
    )
    assert run["status"] == "failed"
    assert "sintaxe" in run["error"]
    assert provider.calls == []  # nenhum token gasto
