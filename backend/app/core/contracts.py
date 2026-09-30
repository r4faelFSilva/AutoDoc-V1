"""Contrato comum de agente e registry.

Todo agente declara nome, schemas de entrada/saída (Pydantic) e uma fábrica
de grafo LangGraph compilado. Adicionar um agente novo = registrar um
AgentSpec; API, worker e MCP descobrem os agentes por aqui.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel


@dataclass(frozen=True)
class AgentSpec:
    name: str
    title: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    build_graph: Callable[[], Any]  # -> grafo LangGraph compilado (CompiledGraph)


_REGISTRY: dict[str, AgentSpec] = {}


class UnknownAgentError(Exception):
    pass


def register(spec: AgentSpec) -> AgentSpec:
    _REGISTRY[spec.name] = spec
    return spec


def get_agent(name: str) -> AgentSpec:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownAgentError(f"Agente desconhecido: {name!r}") from None


def all_agents() -> list[AgentSpec]:
    return sorted(_REGISTRY.values(), key=lambda s: s.name)
