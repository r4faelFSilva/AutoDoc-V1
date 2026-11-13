"""Os fluxos clássicos (geração, avaliação de commit, template a partir de exemplo)
usam o provider configurado em LLM_PROVIDER, e não mais só a OpenAI."""

from __future__ import annotations

import asyncio

import pytest

from app import config
from app.core import llm
from app.services import ai_text


class RecordingProvider:
    """Provider fake que registra as chamadas e devolve um texto fixo."""

    def __init__(self, text: str = "# Doc gerada", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls: list[dict] = []

    async def chat(self, **kwargs) -> llm.ChatResult:
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return llm.ChatResult(text=self.text, model="fake", input_tokens=1, output_tokens=1)


@pytest.fixture
def provider(monkeypatch):
    p = RecordingProvider()
    monkeypatch.setattr(llm, "get_provider", lambda: p)
    return p


# --- ai_text --------------------------------------------------------------------


def test_generate_markdown_usa_o_provider_configurado(provider):
    out = ai_text.generate_markdown(system_prompt="sys", user_content="code")
    assert out == "# Doc gerada"
    call = provider.calls[0]
    assert call["system_prompt"] == "sys"
    assert call["user_content"] == "code"
    assert call["json_mode"] is False
    assert call["temperature"] == 0.3
    assert "timeout_seconds" not in call  # só é repassado quando definido


def test_generate_json_pede_modo_json_e_repassa_limites(provider):
    ai_text.generate_json(system_prompt="s", user_content="u", timeout_seconds=180.0, max_completion_tokens=16384)
    call = provider.calls[0]
    assert call["json_mode"] is True
    assert call["temperature"] == 0.2
    assert call["timeout_seconds"] == 180.0
    assert call["max_output_tokens"] == 16384


def test_erro_do_provider_vira_aiserviceerror(monkeypatch):
    p = RecordingProvider(error=llm.LLMError("Limite de uso da Anthropic atingido."))
    monkeypatch.setattr(llm, "get_provider", lambda: p)
    with pytest.raises(ai_text.AIServiceError, match="Limite de uso da Anthropic"):
        ai_text.generate_markdown(system_prompt="s", user_content="u")


def test_provider_mal_configurado_vira_aiserviceerror(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(config.settings, "openai_compatible_base_url", "")
    with pytest.raises(ai_text.AIServiceError, match="OPENAI_COMPATIBLE_BASE_URL"):
        ai_text.generate_markdown(system_prompt="s", user_content="u")


def test_resposta_vazia_vira_erro(monkeypatch):
    p = RecordingProvider(text="   ")
    monkeypatch.setattr(llm, "get_provider", lambda: p)
    with pytest.raises(ai_text.AIServiceError, match="Resposta vazia"):
        ai_text.generate_markdown(system_prompt="s", user_content="u")


def test_funciona_dentro_de_um_event_loop(provider):
    # Ex.: chamado a partir de um job assíncrono. Não pode quebrar o loop atual.
    async def dentro_do_loop():
        return ai_text.generate_markdown(system_prompt="s", user_content="u")

    assert asyncio.run(dentro_do_loop()) == "# Doc gerada"


@pytest.mark.parametrize(
    "raw",
    [
        '{"needs_update": true}',
        '```json\n{"needs_update": true}\n```',
        'Claro! Aqui está:\n{"needs_update": true}\nEspero ter ajudado.',
        '```\n{"needs_update": true}\n```',
    ],
)
def test_parse_json_object_tolerante(raw):
    assert ai_text.parse_json_object(raw) == {"needs_update": True}


@pytest.mark.parametrize("raw", ["", "não sei", "[1, 2]", "{quebrado"])
def test_parse_json_object_invalido(raw):
    with pytest.raises(ValueError):
        ai_text.parse_json_object(raw)


# --- Fluxos clássicos ponta a ponta ---------------------------------------------


def test_avaliador_aceita_json_em_bloco_de_codigo(monkeypatch):
    """Anthropic e muitos compatíveis não têm modo JSON nativo e envolvem a
    resposta em ```json. Antes, isso virava 'Resposta da IA em formato inválido'."""
    from app.services.documentation_evaluator import evaluate_documentation_update
    from app.services.github_changes import ChangedFile
    from tests.test_evaluator_heuristics import _ctx

    p = RecordingProvider(text='```json\n{"needs_update": false, "reason": "Só estilo.", "confidence": "low"}\n```')
    monkeypatch.setattr(llm, "get_provider", lambda: p)

    ctx = _ctx(changed_files=[ChangedFile(filename="app/main.py", status="modified", patch_summary="- x\n+ x ")])
    result = evaluate_documentation_update(ctx)

    assert result["needs_update"] is False
    assert result["confidence"] == "low"
    assert p.calls[0]["json_mode"] is True


def test_template_a_partir_de_exemplo_aceita_texto_em_volta_do_json(monkeypatch):
    from app.services.template_ai_skeleton import suggest_from_example

    p = RecordingProvider(
        text=(
            "Segue o template solicitado:\n"
            '{"name": "Técnico", "description": "Modelo técnico", '
            '"content": "# \'\'nome do sistema\'\'\\n\\nDescreva...", "suggested_filename": "tecnico.md"}'
        )
    )
    monkeypatch.setattr(llm, "get_provider", lambda: p)

    example = "# Projeto X\n\n## Visão geral\n\n" + "texto " * 40
    data = suggest_from_example(example_markdown=example, doc_type="technical")

    assert data["name"] == "Técnico"
    assert data["suggested_filename"] == "tecnico.md"
    assert p.calls[0]["timeout_seconds"] == 180.0


def test_endpoint_generate_funciona_com_anthropic_sem_chave_openai(client, auth_headers, monkeypatch):
    """O bug original: com LLM_PROVIDER=anthropic a geração clássica ainda exigia
    OPENAI_API_KEY e falhava. Agora a chamada vai para o provider configurado."""
    import anthropic

    captured: dict = {}

    class FakeMessages:
        async def create(self, **kw):
            captured.update(kw)
            block = type("Block", (), {"type": "text", "text": "# Documentação via Anthropic"})()
            usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 5})()
            return type("Msg", (), {"content": [block], "model": kw["model"], "usage": usage})()

    class FakeAsyncAnthropic:
        def __init__(self, **_kw):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAsyncAnthropic)
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-ant-teste")
    monkeypatch.setattr(config.settings, "openai_api_key", "")

    templates = client.get("/api/templates", headers=auth_headers).json()
    resp = client.post(
        "/api/generate",
        headers=auth_headers,
        json={
            "code": "def soma(a, b):\n    return a + b\n",
            "template_id": str(templates[0]["id"]),
            "output_type": "technical",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["content"] == "# Documentação via Anthropic"
    assert "soma" in captured["messages"][0]["content"]
