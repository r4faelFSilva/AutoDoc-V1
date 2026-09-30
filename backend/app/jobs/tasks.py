"""Execução de runs de agente — o coração do worker.

execute_agent_run é a única task da fila: carrega o run, resolve o agente no
registry, invoca o grafo LangGraph e materializa status/eventos no banco.
A mesma função roda no worker arq (Redis) e no fallback in-process.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core import contracts
from app.core.events import get_event_bus
from app.database import SessionLocal
from app.models.agent_run import AgentRun, RunEvent


async def emit(
    run_id: int,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Persiste o evento em run_events e publica no bus (SSE ao vivo)."""
    db = SessionLocal()
    try:
        seq = (
            db.query(RunEvent).filter(RunEvent.run_id == run_id).count() + 1
        )
        event_row = RunEvent(
            run_id=run_id,
            seq=seq,
            kind=kind,
            message=message,
            data_json=json.dumps(data, ensure_ascii=False) if data else None,
            created_at=datetime.utcnow(),
        )
        db.add(event_row)
        db.commit()
    finally:
        db.close()
    await get_event_bus().publish(
        run_id,
        {"seq": seq, "kind": kind, "message": message, "data": data or {}},
    )


def _load_run(run_id: int) -> AgentRun | None:
    db = SessionLocal()
    try:
        return db.query(AgentRun).filter(AgentRun.id == run_id).first()
    finally:
        db.close()


def _update_run(run_id: int, **fields: Any) -> None:
    db = SessionLocal()
    try:
        db.query(AgentRun).filter(AgentRun.id == run_id).update(fields)
        db.commit()
    finally:
        db.close()


async def execute_agent_run(_ctx: Any, run_id: int) -> None:
    run = _load_run(run_id)
    if run is None:
        return
    if run.status not in ("queued",):
        return  # idempotência: reentrega da fila não reexecuta

    _update_run(run_id, status="running", started_at=datetime.utcnow())
    await emit(run_id, "progress", f"Agente `{run.agent}` iniciado.")

    try:
        spec = contracts.get_agent(run.agent)
        graph = spec.build_graph()
        state: dict[str, Any] = json.loads(run.input_json)
        state["run_id"] = run_id
        state["user_id"] = run.user_id

        final = await graph.ainvoke(
            state,
            config={"configurable": {"thread_id": f"run-{run_id}"}},
        )

        output = final.get("output", {})
        usage = final.get("usage", {})
        _update_run(
            run_id,
            status="completed",
            output_json=json.dumps(output, ensure_ascii=False),
            model=usage.get("model"),
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            finished_at=datetime.utcnow(),
        )
        await emit(run_id, "completed", "Run concluído.", data=output)
    except Exception as e:  # noqa: BLE001 — falha do run é dado, não crash do worker
        _update_run(
            run_id,
            status="failed",
            error=str(e),
            finished_at=datetime.utcnow(),
        )
        await emit(run_id, "failed", f"Run falhou: {e}")
