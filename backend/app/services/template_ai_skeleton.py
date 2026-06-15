"""Gera instruções de template (com placeholders) a partir de um markdown de exemplo, via IA."""

from __future__ import annotations

import json
import re

from app.services import ai_openai


class TemplateSkeletonError(Exception):
    pass


_JSON_BLOCK = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

# Exemplos longos estouram o output JSON; enviamos índice + trecho truncado.
_MAX_EXAMPLE_CHARS = 10_000


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        raise TemplateSkeletonError("A IA retornou resposta vazia.")

    # Resposta json_object da OpenAI vem como JSON puro — parse direto primeiro.
    # Não aplicar regex de ``` antes: o campo content pode conter blocos de código.
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise TemplateSkeletonError("Resposta da IA deve ser um objeto JSON.")
    except json.JSONDecodeError:
        pass

    # Fallback: resposta envolta em ```json ... ```
    m = _JSON_BLOCK.search(raw)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError as e:
            raise TemplateSkeletonError(
                "A IA retornou JSON incompleto ou inválido. "
                "Tente um exemplo menor ou reduza seções antes de gerar o modelo."
            ) from e

    raise TemplateSkeletonError(
        "A IA não retornou um objeto JSON válido. "
        "Tente novamente ou use um exemplo de documentação menor."
    )


def _extract_outline(example_markdown: str) -> str:
    lines = [ln for ln in example_markdown.splitlines() if ln.lstrip().startswith("#")]
    return "\n".join(lines) if lines else "(sem títulos detectados)"


def _prepare_example_for_prompt(example_markdown: str) -> str:
    text = example_markdown.strip()
    outline = _extract_outline(text)

    if len(text) <= _MAX_EXAMPLE_CHARS:
        return text

    truncated = text[:_MAX_EXAMPLE_CHARS].rstrip()
    return (
        "IMPORTANTE: o exemplo abaixo foi truncado por tamanho. "
        "Você DEVE incluir no template TODAS as seções listadas no índice, "
        "mesmo que não apareçam no trecho.\n\n"
        f"Índice de seções (preservar hierarquia # / ## / ###):\n{outline}\n\n"
        f"Trecho inicial do exemplo:\n\n{truncated}\n\n"
        "[... conteúdo omitido — mantenha a estrutura completa do índice acima ...]"
    )


def _extract_example_names(example_markdown: str) -> list[str]:
    """Nomes próprios prováveis no exemplo (ex.: título 'Sistema NexusSync')."""
    names: list[str] = []
    for line in example_markdown.splitlines()[:8]:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        for sep in ("—", "–", " - "):
            if sep in title:
                suffix = title.split(sep, 1)[1].strip()
                if suffix:
                    names.append(suffix)
                    parts = suffix.split()
                    if len(parts) > 1:
                        names.append(parts[-1])
                break
        break
    # dedupe, longest first (para substituir "Sistema X" antes de "X")
    seen: set[str] = set()
    unique: list[str] = []
    for n in names:
        key = n.lower()
        if key not in seen and len(n) >= 3:
            seen.add(key)
            unique.append(n)
    return sorted(unique, key=len, reverse=True)


def _scrub_example_names(text: str, names: list[str]) -> str:
    if not names:
        return text
    out = text
    for name in names:
        out = re.sub(re.escape(name), "''nome do sistema''", out, flags=re.IGNORECASE)
    return out


def suggest_from_example(*, example_markdown: str, doc_type: str) -> dict[str, str]:
    """
    Retorna dict com keys: name, description, content, type, suggested_filename (opcional).
    O campo content é o prompt/template em Markdown que a aplicação enviará à IA na geração de docs.
    """
    prepared = _prepare_example_for_prompt(example_markdown)

    system = """Você cria TEMPLATES de documentação para uma ferramenta que documenta código com IA.

Entrada: markdown de exemplo (documentação já escrita sobre UM projeto fictício ou real).
Saída: UM objeto JSON com as chaves EXATAS: name, description, content, suggested_filename.

IMPORTANTE — generalização (obrigatório):
O exemplo ilustra FORMATO, não o projeto que será documentado depois. NUNCA preserve do exemplo:
- nomes de sistemas, produtos ou projetos (ex.: NexusSync, AutoDoc, etc.);
- nomes de empresas, equipes, pessoas, bases de dados ou APIs específicas do exemplo;
- URLs, hosts, tokens, IDs de job ou valores literais do exemplo.

Substitua TUDO isso por placeholders ''...'' ou rótulos genéricos.
Exemplos corretos:
- Título: # Documentação Técnica — ''nome do sistema ou projeto''
- Prose: O **''nome do sistema''** é responsável por ''descrever a finalidade...''
- Tabela: | **Projeto** | ''nome do projeto'' |
- Coluna "Uso no NexusSync" → "Uso no ''nome do sistema''"
- name (JSON): "Documentação Técnica de Projeto" (genérico, sem nome do exemplo)
- description (JSON): uma linha genérica sobre o tipo de doc, sem citar o projeto do exemplo
- suggested_filename: template-documentacao-tecnica-projeto.md (genérico, kebab-case)

Regras para o campo content (Markdown dentro do JSON):
1) Preserve a hierarquia de títulos do exemplo (use o índice de seções quando fornecido).
2) Substitua conteúdo específico por instruções entre aspas simples duplas: ''texto da instrução para a IA preencher com base no código''.
3) Tabelas: cabeçalho + UMA linha de exemplo com células ''...'' (não replique linhas fictícias do exemplo).
4) Blocos de código/SQL/JSON: apenas esqueleto com ''...'' — não copie payloads, queries ou nomes do exemplo.
5) Seja CONCISO: template esqueleto, não réplica integral do documento.
6) Início do content: parágrafo orientando que a IA receberá código-fonte e deve preencher cada ''...'' com dados do código analisado.
7) Revise o content antes de responder: se ainda existir nome próprio do exemplo, troque por placeholder.

Responda SOMENTE JSON válido conforme response_format."""

    user = (
        f"Tipo do template: {doc_type} "
        "(technical = detalhes técnicos; functional = linguagem acessível/onboarding).\n\n"
        f"Exemplo de documentação:\n\n{prepared}"
    )

    try:
        raw = ai_openai.generate_json(
            system_prompt=system,
            user_content=user,
            timeout_seconds=180.0,
            max_completion_tokens=16384,
        )
    except ai_openai.AIServiceError as e:
        raise TemplateSkeletonError(str(e)) from e

    data = _parse_json_object(raw)
    leaked_names = _extract_example_names(example_markdown)
    name = _scrub_example_names(str(data.get("name", "")).strip(), leaked_names)
    description = _scrub_example_names(str(data.get("description", "")).strip(), leaked_names)
    content = _scrub_example_names(str(data.get("content", "")).strip(), leaked_names)
    suggested_filename = str(data.get("suggested_filename", "")).strip() or None
    if suggested_filename:
        suggested_filename = _scrub_example_names(suggested_filename, leaked_names)
        suggested_filename = re.sub(r"''nome do sistema''", "projeto", suggested_filename, flags=re.IGNORECASE)
        suggested_filename = re.sub(r"[^a-z0-9._-]+", "-", suggested_filename.lower()).strip("-")
        if not suggested_filename or suggested_filename == ".md":
            suggested_filename = "template-documentacao-tecnica-projeto.md"
    if not name or not description or not content:
        raise TemplateSkeletonError("A IA retornou name, description ou content vazios.")
    result: dict[str, str] = {
        "name": name,
        "description": description,
        "content": content,
        "type": doc_type,
    }
    if suggested_filename:
        if not suggested_filename.lower().endswith(".md"):
            suggested_filename = f"{suggested_filename}.md"
        result["suggested_filename"] = suggested_filename
    return result
