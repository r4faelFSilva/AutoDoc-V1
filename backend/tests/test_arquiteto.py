"""E2E do agente arquiteto com provider roteirizado."""

import json
import time

from app.core.llm import ChatResult

PROPOSED_ARCH = {
    "nodes": [
        {"id": "client", "type": "client", "label": "Clientes", "tech": "", "props": {}},
        {"id": "api", "type": "service", "label": "API", "tech": "FastAPI",
         "props": {"replicas": 2, "rps_capacity": 200}},
        {"id": "db", "type": "db", "label": "Postgres", "tech": "PostgreSQL",
         "props": {"replicas": 1, "rps_capacity": 300}},
        {"id": "fantasma", "type": "alienigena", "label": "Tipo inválido", "tech": "",
         "props": {"replicas": "abc"}},
    ],
    "edges": [
        {"from": "client", "to": "api", "protocol": "https", "sync": True, "weight": 1.0},
        {"from": "api", "to": "db", "protocol": "tcp", "sync": True, "weight": 1.0},
        {"from": "api", "to": "inexistente", "weight": 1.0},
    ],
}


class FakeArchProvider:
    def __init__(self):
        self.calls: list[str] = []

    async def chat(self, *, system_prompt, user_content, json_mode=False, max_output_tokens=None, temperature=0.3):
        if "requisitos não-funcionais de uma especificação" in system_prompt:
            self.calls.append("estimate")
            text = json.dumps(
                {"expected_rps": 500, "peak_multiplier": 2.0, "latency_target_ms": 200,
                 "assumptions": ["premissa de teste"]}
            )
        elif "Proponha UMA arquitetura" in system_prompt:
            self.calls.append("propose")
            text = json.dumps(PROPOSED_ARCH)
        elif "revisor adversarial" in system_prompt:
            self.calls.append("critique")
            text = json.dumps(
                {"risks": [
                    {"target": "db", "kind": "spof", "severity": "high",
                     "message": "Banco sem réplica de leitura."},
                    {"target": "nao-existe", "kind": "cost", "severity": "low", "message": "x"},
                ]}
            )
        elif "ADR" in system_prompt:
            self.calls.append("decide")
            text = "# ADR 001 — Arquitetura proposta\n\n## Contexto\n\nTeste."
        else:
            self.calls.append("other")
            text = "{}"
        return ChatResult(text=text, model="fake-arch", input_tokens=3, output_tokens=4)


def _wait_terminal(client, headers, run_id, timeout=20.0):
    deadline = time.monotonic() + timeout
    run = None
    while time.monotonic() < deadline:
        run = client.get(f"/api/runs/{run_id}", headers=headers).json()
        if run["status"] in ("completed", "failed", "cancelled"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run não terminou: {run}")


def test_arquiteto_registrado(client, auth_headers):
    resp = client.get("/api/agents", headers=auth_headers)
    assert "arquiteto" in [a["name"] for a in resp.json()]


def test_arquiteto_spec_completo(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeArchProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    resp = client.post(
        "/api/agents/arquiteto/runs",
        headers=auth_headers,
        json={"input": {"spec": "Sistema de pedidos online com picos de tráfego.", "expected_rps": 500}},
    )
    assert resp.status_code == 202, resp.text
    run = _wait_terminal(client, auth_headers, resp.json()["id"])
    assert run["status"] == "completed", run
    assert provider.calls == ["estimate", "propose", "critique", "decide"]

    out = run["output"]
    arch = out["architecture"]
    ids = {n["id"] for n in arch["nodes"]}
    # sanitização: tipo inválido vira service, aresta para nó inexistente é descartada
    assert "fantasma" in ids
    fantasma = next(n for n in arch["nodes"] if n["id"] == "fantasma")
    assert fantasma["type"] == "service"
    assert all(e["to"] != "inexistente" for e in arch["edges"])

    # análise determinística: 500*2.0=1000 RPS; API 2x200=400 → gargalo; DB 300 → gargalo
    bottlenecks = {a["target"] for a in out["annotations"] if a["kind"] == "bottleneck"}
    assert {"api", "db"} <= bottlenecks
    # crítica LLM incorporada; risco com target inválido vira "geral"
    spofs = [a for a in out["annotations"] if a["kind"] == "spof" and a["target"] == "db"]
    assert spofs
    assert out["loads"]["api"] == 1000.0
    assert out["adr_markdown"].startswith("# ADR")

    # artifacts persistidos
    from app.database import SessionLocal
    from app.models.agent_run import Artifact

    db = SessionLocal()
    try:
        kinds = {
            a.kind for a in db.query(Artifact).filter(Artifact.run_id == run["id"]).all()
        }
    finally:
        db.close()
    assert {"architecture", "adr"} <= kinds


def test_arquiteto_recritica_respeita_grafo_do_usuario(client, auth_headers, monkeypatch):
    import app.core.llm as llm

    provider = FakeArchProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: provider)

    base = {
        "nodes": [
            {"id": "client", "type": "client", "label": "Web", "props": {}},
            {"id": "mono", "type": "service", "label": "Monolito", "props": {"replicas": 1, "rps_capacity": 50}},
        ],
        "edges": [{"from": "client", "to": "mono", "weight": 1.0}],
    }
    resp = client.post(
        "/api/agents/arquiteto/runs",
        headers=auth_headers,
        json={"input": {"base_architecture": base, "expected_rps": 200}},
    )
    run = _wait_terminal(client, auth_headers, resp.json()["id"])
    assert run["status"] == "completed", run
    # propose NÃO foi chamado — o grafo do usuário foi mantido
    assert "propose" not in provider.calls
    assert {n["id"] for n in run["output"]["architecture"]["nodes"]} == {"client", "mono"}


def test_arquiteto_input_vazio_rejeitado(client, auth_headers):
    resp = client.post(
        "/api/agents/arquiteto/runs",
        headers=auth_headers,
        json={"input": {"expected_rps": 100}},
    )
    assert resp.status_code == 422
