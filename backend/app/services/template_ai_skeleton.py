"""Gera instruções de template (com placeholders) a partir de um markdown de exemplo, via IA."""

from __future__ import annotations

import json
import re

from app.services import ai_openai


class TemplateSkeletonError(Exception):
    pass


_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    m = _JSON_BLOCK.search(raw)
    if m:
        raw = m.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(raw[start : end + 1])
            except json.JSONDecodeError as e:
                raise TemplateSkeletonError(f"Resposta da IA não é JSON válido: {e}") from e
        else:
            raise TemplateSkeletonError("Resposta da IA não contém um objeto JSON reconhecível.") from None
    if not isinstance(data, dict):
        raise TemplateSkeletonError("Resposta da IA deve ser um objeto JSON.")
    return data


def suggest_from_example(*, example_markdown: str, doc_type: str) -> dict[str, str]:
    """
    Retorna dict com keys: name, description, content, type.
    O campo content é o prompt que a aplicação enviará à IA na geração de docs:
    estrutura semelhante ao exemplo, com trechos substituídos por instruções entre aspas simples duplas ''...''.
    """
    system = """Você é um assistente que ajuda a criar TEMPLATES de documentação para uma ferramenta que documenta código com IA.

O usuário enviará um markdown COMPLETO (exemplo de documentação já escrita sobre um código).

Sua tarefa:
1) Analise a estrutura (títulos, seções, listas) do exemplo.
2) Produza um NOVO texto em Markdown que sirva como INSTRUÇÃO para a IA gerar documentações futuras no MESMO FORMATO/ESTRUTURA do exemplo.
3) Onde o exemplo contém conteúdo específico do projeto (explicações, listas de funções reais, conclusões concretas), substitua por instruções em português delimitadas EXATAMENTE assim: duas aspas simples, texto, duas aspas simples — ou seja: ''instrução clara do que a IA deve preencher naquele bloco, com base no código que receber''.
4) Mantenha títulos e hierarquia (#, ##, ###) coerentes com o exemplo quando fizer sentido.
5) No início do conteúdo (campo content), inclua um parágrafo curto orientando: "Você receberá código-fonte abaixo; siga esta estrutura e preencha cada trecho entre aspas simples duplas com análise baseada nesse código."
6) Gere também um nome curto para o template (campo name) e uma descrição de uma linha (campo description), em português do Brasil.

Responda APENAS com um objeto JSON válido (sem markdown fora do JSON), com as chaves exatas:
{"name": "...", "description": "...", "content": "..."}
O campo content deve ser uma string JSON com quebras \\n escapadas ou use JSON real com newlines permitidos no string (UTF-8).

Não inclua comentários fora do JSON."""

    user = (
        f"Tipo de documentação desejada para o template: {doc_type} "
        "(technical = detalhes técnicos; functional = linguagem mais acessível/onboarding).\n\n"
        "Exemplo de documentação (markdown):\n\n"
        + example_markdown.strip()
    )

    try:
        raw = ai_openai.generate_markdown(
            system_prompt=system,
            user_content=user,
            timeout_seconds=180.0,
            max_completion_tokens=8192,
        )
    except ai_openai.AIServiceError as e:
        raise TemplateSkeletonError(str(e)) from e

    data = _parse_json_object(raw)
    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    content = str(data.get("content", "")).strip()
    if not name or not description or not content:
        raise TemplateSkeletonError("A IA retornou name, description ou content vazios.")
    return {"name": name, "description": description, "content": content, "type": doc_type}
