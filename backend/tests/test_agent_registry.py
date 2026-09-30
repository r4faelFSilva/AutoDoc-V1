import pytest
from pydantic import ValidationError

import app.agents  # noqa: F401 — registra os agentes
from app.core import contracts
from app.agents.documentador.graph import DocumentadorInput


def test_documentador_registrado():
    spec = contracts.get_agent("documentador")
    assert spec.name == "documentador"
    assert spec.input_schema is DocumentadorInput
    assert "documentador" in [s.name for s in contracts.all_agents()]


def test_agente_desconhecido():
    with pytest.raises(contracts.UnknownAgentError):
        contracts.get_agent("nao-existe")


def test_input_schema_valida_source():
    ok = DocumentadorInput(source="paste", template_id=1, code="print(1)")
    assert ok.output_type == "technical"  # default
    with pytest.raises(ValidationError):
        DocumentadorInput(source="ftp", template_id=1)
    with pytest.raises(ValidationError):
        DocumentadorInput(source="paste", template_id=1, output_type="poetico")


def test_grafo_compila():
    spec = contracts.get_agent("documentador")
    graph = spec.build_graph()
    assert graph is not None
