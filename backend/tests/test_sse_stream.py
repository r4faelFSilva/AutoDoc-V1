"""Regressão: o SSE de /api/runs/{id}/events sempre termina com o evento final.

Antes da correção, o primeiro timeout de keep-alive encerrava a assinatura do
bus e o stream fechava sem `completed`/`failed` — a tela ficava esperando para
sempre em qualquer run com mais de 15 s sem eventos.
"""

import asyncio
import json
from datetime import datetime

from app.core.llm import ChatResult


class SlowProvider:
    """Responde depois de `delay` segundos, sem emitir eventos no meio."""

    def __init__(self, delay: float):
        self.delay = delay

    async def chat(self, **_kw):
        await asyncio.sleep(self.delay)
        return ChatResult(text="# Doc\n\nGerada pelo provider lento.", model="fake-slow", input_tokens=1, output_tokens=1)


def _read_stream(client, headers, run_id) -> tuple[list[dict], int]:
    events: list[dict] = []
    keepalives = 0
    with client.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith(": keep-alive"):
                keepalives += 1
            elif line.startswith("data:"):
                events.append(json.loads(line[5:]))
    return events, keepalives


def test_run_lento_recebe_evento_final_depois_dos_keepalives(client, auth_headers, monkeypatch):
    import app.core.llm as llm
    from app.api.routers import runs

    monkeypatch.setattr(runs, "KEEPALIVE_SECONDS", 0.2)
    monkeypatch.setattr(llm, "get_provider", lambda: SlowProvider(delay=1.5))

    resp = client.post(
        "/api/agents/documentador/runs",
        headers=auth_headers,
        json={"input": {"source": "paste", "code": "def f():\n    return 1\n", "template_id": 1}},
    )
    assert resp.status_code == 202, resp.text

    events, keepalives = _read_stream(client, auth_headers, resp.json()["id"])

    assert keepalives >= 2, "o cenário precisa passar por vários timeouts de keep-alive"
    assert events[-1]["kind"] == "completed", events
    assert events[-1]["data"]["doc_id"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(set(seqs)), "eventos duplicados ou fora de ordem"


def test_run_terminado_sem_evento_final_gera_evento_a_partir_do_banco(client, auth_headers):
    from app.database import SessionLocal
    from app.models.agent_run import AgentRun

    me = client.get("/api/runs", headers=auth_headers)  # garante usuário válido
    assert me.status_code == 200
    db = SessionLocal()
    try:
        from app.models.user import User

        user = db.query(User).filter(User.email == "demo@autodoc.dev").one()
        run = AgentRun(
            user_id=user.id,
            agent="documentador",
            status="failed",
            input_json="{}",
            error="falha registrada sem evento",
            created_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    events, _ = _read_stream(client, auth_headers, run_id)
    assert len(events) == 1
    assert events[0]["kind"] == "failed"
    assert "falha registrada sem evento" in events[0]["message"]
