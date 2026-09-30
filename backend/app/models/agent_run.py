from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AgentRun(Base):
    """Execução de um agente: input, output, status e custo."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    agent: Mapped[str] = mapped_column(String(64))
    # queued | running | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), default="queued")
    input_json: Mapped[str] = mapped_column(Text())
    output_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    events: Mapped[list["RunEvent"]] = relationship(
        "RunEvent", back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["Artifact"]] = relationship(
        "Artifact", back_populates="run", cascade="all, delete-orphan"
    )


class RunEvent(Base):
    """Trilha nó-a-nó de um run, para SSE e auditoria/replay."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"))
    seq: Mapped[int] = mapped_column(Integer)
    # progress | node_started | node_finished | completed | failed
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text())
    data_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="events")


class Artifact(Base):
    """Saída tipada de um run: doc, testes, ADR, diagrama, changelog."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"))
    kind: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(512))
    content: Mapped[str] = mapped_column(Text())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="artifacts")


class Evaluation(Base):
    """Métrica de qualidade de um run — base dos resultados quantitativos."""

    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"))
    metric: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    details_json: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
