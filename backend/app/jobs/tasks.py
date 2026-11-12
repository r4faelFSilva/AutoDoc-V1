"""Execução de runs de agente — o coração do worker.

execute_agent_run é a única task da fila: carrega o run, resolve o agente no
registry, invoca o grafo LangGraph e materializa status/eventos no banco.
A mesma função roda no worker arq (Redis) e no fallback in-process.

Garantias:
- todo run termina como completed ou failed, com evento final gravado;
- o grafo inteiro tem limite de tempo (AGENT_RUN_TIMEOUT_SECONDS /
  AGENT_RUN_TIMEOUT_DEEP_SECONDS);
- runs interrompidos (servidor reiniciado, task cancelada) são marcados como
  falha, na hora ou na próxima inicialização (fail_orphan_runs).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from app.config import settings
from app.core import contracts
from app.core.events import get_event_bus
from app.database import SessionLocal
from app.models.agent_run import AgentRun, RunEvent

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "Execução interrompida: o servidor foi reiniciado."


def run_timeout_seconds(agent: str, run_input: dict[str, Any] | str | None) -> float:
    """Limite total do run: quick para o documentador rápido; deep para o resto."""
    if isinstance(run_input, str):
        try:
            run_input = json.loads(run_input)
        except json.JSONDecodeError:
            run_input = {}
    depth = (run_input or {}).get("depth")
    if agent == "documentador" and depth != "deep":
        return settings.agent_run_timeout_seconds
    return settings.agent_run_timeout_deep_seconds


def _describe_duration(seconds: float) -> str:
    if seconds >= 60 and seconds % 60 == 0:
        minutes = int(seconds // 60)
        return f"{minutes} minuto" if minutes == 1 else f"{minutes} minutos"
    return f"{seconds:g} s"


def _timeout_message(agent: str, run_input: dict[str, Any], limit: float) -> str:
    if agent == "documentador":
        hint = " Tente novamente ou use o modo rápido." if run_input.get("depth") == "deep" else " Tente novamente."
        return f"A geração excedeu o limite de {_describe_duration(limit)} e foi interrompida.{hint}"
    return f"A execução excedeu o limite de {_describe_duration(limit)} e foi interrompida. Tente novamente."


def _persist_event(
    run_id: int,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> int:
    """Grava o evento em run_events e devolve o seq (síncrono)."""
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
        return seq
    finally:
        db.close()


async def emit(
    run_id: int,
    kind: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Persiste o evento em run_events e publica no bus (SSE ao vivo)."""
    seq = _persist_event(run_id, kind, message, data)
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


def _mark_failed_sync(run_id: int, message: str) -> None:
    """Marca falha sem await (usável durante cancelamento); nunca levanta."""
    try:
        _update_run(run_id, status="failed", error=message, finished_at=datetime.utcnow())
        _persist_event(run_id, "failed", f"Run falhou: {message}")
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível marcar o run %s como falho.", run_id)


async def _fail(run_id: int, message: str) -> None:
    """Grava a falha e publica o evento final; erros aqui só vão para o log."""
    try:
        _update_run(run_id, status="failed", error=message, finished_at=datetime.utcnow())
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível gravar a falha do run %s.", run_id)
    try:
        await emit(run_id, "failed", f"Run falhou: {message}")
    except Exception:  # noqa: BLE001
        logger.exception("Não foi possível emitir o evento de falha do run %s.", run_id)


async def execute_agent_run(_ctx: Any, run_id: int, github_token: str | None = None) -> None:
    try:
        run = _load_run(run_id)
        if run is None:
            return
        if run.status not in ("queued",):
            return  # idempotência: reentrega da fila não reexecuta
        run_input: dict[str, Any] = json.loads(run.input_json)
        limit = run_timeout_seconds(run.agent, run_input)

        _update_run(run_id, status="running", started_at=datetime.utcnow())
        await emit(run_id, "progress", f"Agente `{run.agent}` iniciado.")

        spec = contracts.get_agent(run.agent)
        graph = spec.build_graph()
        state: dict[str, Any] = dict(run_input)
        state["run_id"] = run_id
        state["user_id"] = run.user_id
        # Só no estado em memória do grafo; não vai para input_json nem eventos.
        state["github_token"] = github_token

        try:
            async with asyncio.timeout(limit) as deadline:
                final = await graph.ainvoke(
                    state,
                    config={"configurable": {"thread_id": f"run-{run_id}"}},
                )
        except TimeoutError:
            if not deadline.expired():
                raise  # TimeoutError vindo de dentro do grafo: falha comum
            logger.warning("Run %s (%s) excedeu o limite de %ss.", run_id, run.agent, limit)
            await _fail(run_id, _timeout_message(run.agent, run_input, limit))
            return

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
    except asyncio.CancelledError:
        # Servidor desligando ou task cancelada: registra antes de propagar.
        logger.warning("Run %s cancelado antes de terminar.", run_id)
        _mark_failed_sync(run_id, INTERRUPTED_MESSAGE)
        raise
    except Exception as e:  # noqa: BLE001 — falha do run é dado, não crash do worker
        logger.exception("Run %s falhou.", run_id)
        await _fail(run_id, str(e) or f"Erro inesperado ({type(e).__name__}).")


def fail_orphan_runs(*, started_before: datetime | None = None) -> int:
    """Marca como falha runs que ficaram queued/running sem processo executando.

    Sem `started_before` (modo in-process, na inicialização da API): todo run
    queued/running é órfão, porque morreu junto com o processo anterior.
    Com `started_before` (worker arq): só runs running iniciados antes desse
    instante — mais antigos que o maior limite de tempo possível.
    """
    db = SessionLocal()
    try:
        query = db.query(AgentRun.id)
        if started_before is None:
            query = query.filter(AgentRun.status.in_(("queued", "running")))
        else:
            query = query.filter(AgentRun.status == "running", AgentRun.started_at < started_before)
        orphan_ids = [row.id for row in query.all()]
    finally:
        db.close()
    for orphan_id in orphan_ids:
        _mark_failed_sync(orphan_id, INTERRUPTED_MESSAGE)
    if orphan_ids:
        logger.warning("Runs órfãos marcados como falha: %s", orphan_ids)
    return len(orphan_ids)
