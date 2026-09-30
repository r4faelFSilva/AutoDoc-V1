"""Fluxo ponta a ponta da fundação: cria run do documentador via API,
o job roda in-process (modo fallback), o LLM é stubado, e o resultado
aparece no run, nos eventos e no histórico de documentações."""

import time

from app.core.llm import ChatResult


class FakeProvider:
    async def chat(self, **kwargs):
        return ChatResult(
            text="# Doc gerada em teste\n\nConteúdo markdown.",
            model="fake-model",
            input_tokens=10,
            output_tokens=20,
        )


def _wait_terminal(client, headers, run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} não terminou em {timeout}s: {run}")


def test_lista_agentes(client, auth_headers):
    resp = client.get("/api/agents", headers=auth_headers)
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()]
    assert "documentador" in names


def test_run_documentador_paste_completa(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    monkeypatch.setattr(llm, "get_provider", lambda: FakeProvider())

    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={"input": {"source": "paste", "template_id": 1, "code": "def soma(a, b): return a + b"}},
    )
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["id"]
    assert resp.json()["status"] == "queued"

    run = _wait_terminal(client, auth_headers, run_id)
    assert run["status"] == "completed", run
    assert run["output"]["doc_id"] > 0
    assert run["model"] == "fake-model"
    assert run["output_tokens"] == 20

    # documento apareceu no histórico legado (mesma tela de sempre)
    doc_id = run["output"]["doc_id"]
    doc = client.get(f"/api/history/{doc_id}", headers=auth_headers)
    assert doc.status_code == 200
    assert "Doc gerada em teste" in doc.json()["content"]

    # eventos persistidos e stream SSE reproduz até o terminal
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=auth_headers) as s:
        assert s.status_code == 200
        body = ""
        for chunk in s.iter_text():
            body += chunk
            if '"kind": "completed"' in body or '"kind":"completed"' in body:
                break
    assert "iniciado" in body
    assert "completed" in body


def test_run_input_invalido_retorna_422(client, auth_headers):
    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={"input": {"source": "ftp", "template_id": 1}},
    )
    assert resp.status_code == 422


def test_agente_inexistente_retorna_404(client, auth_headers):
    resp = client.post(
        "/api/agents/inexistente/runs",
        headers=auth_headers,
        json={"input": {}},
    )
    assert resp.status_code == 404


def test_run_falha_quando_template_nao_existe(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    monkeypatch.setattr(llm, "get_provider", lambda: FakeProvider())

    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={"input": {"source": "paste", "template_id": 99999, "code": "x = 1"}},
    )
    assert resp.status_code == 202
    run = _wait_terminal(client, auth_headers, resp.json()["id"])
    assert run["status"] == "failed"
    assert "Template" in run["error"]
