from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AgentInfoResponse(BaseModel):
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]


class CreateRunRequest(BaseModel):
    input: dict[str, Any]


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    agent: str
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # Limite de tempo total do run no servidor, em segundos
    timeout_seconds: float | None = None


class RunEventResponse(BaseModel):
    seq: int
    kind: str
    message: str
    data: dict[str, Any] | None = None
    created_at: datetime
