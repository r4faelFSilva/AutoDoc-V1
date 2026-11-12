"""API de execução de agentes: criação de runs, consulta e stream SSE.

O SSE usa autenticação por header (Authorization: Bearer) — o frontend deve
consumir via fetch + ReadableStream, não via EventSource (que não envia
headers). Nunca passe o token em query string.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

import app.agents  # noqa: F401 — garante o registro dos agentes
from fastapi import APIRouter, Header, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core import contracts
from app.core.events import get_event_bus
from app.database import SessionLocal
from app.dependencies import CurrentUser, DbSession
from app.jobs.queue import enqueue_agent_run
from app.jobs.tasks import run_timeout_seconds
from app.models.agent_run import AgentRun, RunEvent
from app.schemas.runs import (
    AgentInfoResponse,
    AgentRunResponse,
    CreateRunRequest,
    RunEventResponse,
)

router = APIRouter(tags=["agents"])

TERMINAL_KINDS = frozenset({"completed", "failed"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
# Intervalo do keep-alive do SSE; a cada intervalo o banco é reconsultado.
KEEPALIVE_SECONDS = 15.0


def _to_run_response(run: AgentRun) -> AgentRunResponse:
    return AgentRunResponse(
        id=run.id,
        agent=run.agent,
        status=run.status,
        output=json.loads(run.output_json) if run.output_json else None,
        error=run.error,
        model=run.model,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        timeout_seconds=run_timeout_seconds(run.agent, run.input_json),
    )


@router.get("/agents", response_model=list[AgentInfoResponse])
def list_agents(user: CurrentUser) -> list[AgentInfoResponse]:
    return [
        AgentInfoResponse(
            name=s.name,
            title=s.title,
            description=s.description,
            input_schema=s.input_schema.model_json_schema(),
        )
        for s in contracts.all_agents()
    ]


@router.post(
    "/agents/{agent_name}/runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    agent_name: str,
    body: CreateRunRequest,
    user: CurrentUser,
    db: DbSession,
    x_github_token: str | None = Header(default=None, alias="X-GitHub-Token"),
) -> AgentRunResponse:
    try:
        spec = contracts.get_agent(agent_name)
    except contracts.UnknownAgentError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e

    try:
        validated = spec.input_schema(**body.input)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=json.loads(e.json()),
        ) from e

    run = AgentRun(
        user_id=user.id,
        agent=agent_name,
        status="queued",
        input_json=validated.model_dump_json(),
        created_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # O token do GitHub vai só para a execução, nunca para input_json.
    await enqueue_agent_run(run.id, github_token=(x_github_token or "").strip() or None)
    return _to_run_response(run)


MAX_SPEC_FILE_BYTES = 5 * 1024 * 1024
MAX_SPEC_CHARS = 20_000  # alinhado ao limite do campo spec do ArquitetoInput


def _extract_docx(data: bytes) -> str:
    import io

    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def _extract_pdf(data: bytes) -> str:
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@router.post("/agents/arquiteto/extract-spec")
async def extract_spec(file: UploadFile, user: CurrentUser) -> dict:
    """Extrai texto de um documento de especificação (.txt, .md, .docx, .pdf)."""
    data = await file.read()
    if len(data) > MAX_SPEC_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Arquivo maior que 5 MB.",
        )
    name = (file.filename or "").lower()
    try:
        if name.endswith((".txt", ".md")):
            text = data.decode("utf-8", errors="replace")
        elif name.endswith(".docx"):
            text = _extract_docx(data)
        elif name.endswith(".pdf"):
            text = _extract_pdf(data)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato não suportado. Use .txt, .md, .docx ou .pdf.",
            )
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — arquivo corrompido/ilegível
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Não foi possível ler o arquivo: {e}",
        ) from e

    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo não contém texto extraível.",
        )
    truncated = len(text) > MAX_SPEC_CHARS
    if truncated:
        text = text[:MAX_SPEC_CHARS]
    return {"filename": file.filename, "text": text, "chars": len(text), "truncated": truncated}


@router.get("/runs", response_model=list[AgentRunResponse])
def list_runs(user: CurrentUser, db: DbSession) -> list[AgentRunResponse]:
    rows = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user.id)
        .order_by(AgentRun.created_at.desc())
        .limit(100)
        .all()
    )
    return [_to_run_response(r) for r in rows]


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
def get_run(run_id: int, user: CurrentUser, db: DbSession) -> AgentRunResponse:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == user.id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run não encontrado.")
    return _to_run_response(run)


def _load_history(run_id: int) -> list[RunEventResponse]:
    db = SessionLocal()
    try:
        rows = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq.asc())
            .all()
        )
        return [
            RunEventResponse(
                seq=r.seq,
                kind=r.kind,
                message=r.message,
                data=json.loads(r.data_json) if r.data_json else None,
                created_at=r.created_at,
            )
            for r in rows
        ]
    finally:
        db.close()


def _load_run(run_id: int) -> AgentRun | None:
    db = SessionLocal()
    try:
        return db.query(AgentRun).filter(AgentRun.id == run_id).first()
    finally:
        db.close()


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


def _terminal_from_db(run: AgentRun, seq: int) -> dict:
    """Evento final montado a partir do run, quando ele terminou sem evento final gravado."""
    if run.status == "completed":
        return {
            "seq": seq,
            "kind": "completed",
            "message": "Run concluído.",
            "data": json.loads(run.output_json) if run.output_json else {},
        }
    return {
        "seq": seq,
        "kind": "failed",
        "message": f"Run falhou: {run.error}" if run.error else "Run falhou.",
        "data": {},
    }


async def _event_stream(run_id: int) -> AsyncIterator[str]:
    """Histórico + eventos ao vivo; só encerra depois de enviar completed/failed.

    A assinatura é feita ANTES de ler o histórico (nada se perde entre os dois)
    e o timeout de keep-alive cancela apenas o get(), não a assinatura.
    """
    subscription = await get_event_bus().subscribe(run_id)
    last_seq = 0

    def replay_new() -> tuple[list[str], bool]:
        """Eventos persistidos ainda não enviados; True se incluir o evento final."""
        nonlocal last_seq
        chunks: list[str] = []
        for ev in _load_history(run_id):
            if ev.seq <= last_seq:
                continue
            last_seq = ev.seq
            chunks.append(_sse(ev.model_dump()))
            if ev.kind in TERMINAL_KINDS:
                return chunks, True
        return chunks, False

    def finished_without_event() -> str | None:
        run = _load_run(run_id)
        if run is not None and run.status in TERMINAL_STATUSES:
            return _sse(_terminal_from_db(run, last_seq + 1))
        return None

    try:
        # 1) histórico persistido
        chunks, done = replay_new()
        for chunk in chunks:
            yield chunk
        if done:
            return
        final = finished_without_event()
        if final:
            yield final
            return

        # 2) ao vivo pelo bus; a cada keep-alive o banco é reconsultado
        while True:
            try:
                event = await asyncio.wait_for(subscription.get(), timeout=KEEPALIVE_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                # eventos que não chegaram pelo bus (ex.: worker em outro processo)
                chunks, done = replay_new()
                for chunk in chunks:
                    yield chunk
                if done:
                    return
                final = finished_without_event()
                if final:
                    yield final
                    return
                continue
            if event.get("seq", 0) <= last_seq:
                continue
            last_seq = event.get("seq", last_seq)
            yield _sse(event)
            if event.get("kind") in TERMINAL_KINDS:
                return
    finally:
        await subscription.close()


@router.get("/runs/{run_id}/events")
async def stream_run_events(run_id: int, user: CurrentUser, db: DbSession) -> StreamingResponse:
    run = db.query(AgentRun).filter(AgentRun.id == run_id, AgentRun.user_id == user.id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run não encontrado.")
    return StreamingResponse(
        _event_stream(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
