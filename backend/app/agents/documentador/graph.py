"""Agente documentador como grafo LangGraph — dois modos.

quick (padrão): prepare → generate → persist. Uma chamada de LLM, custo
mínimo — o comportamento validado no TCC.

deep (opt-in, selecionado pelo usuário): ingest → map_code → outline →
draft (paralelo por seção) → verify → assemble → persist → score.
Mapa de código determinístico como fonte de fatos, verificação
anti-alucinação e métricas gravadas em `evaluations`.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.config import settings
from app.core import contracts, llm
from app.database import SessionLocal
from app.index.code_map import build_code_map
from app.jobs.tasks import emit
from app.models.agent_run import Evaluation
from app.models.documentation_record import DocumentationRecord
from app.models.template import Template
from app.services.autodoc_marker import ensure_autodoc_marker
from app.services.github_archive import (
    GitHubArchiveError,
    fetch_repo_files,
    parse_github_url,
)

# Limites do modo profundo
DEEP_MAX_FILES = 300
DEEP_MAX_TOTAL_CHARS = 900_000
DEEP_MAX_FILE_CHARS = 24_000
MAX_SECTIONS = 8
MAX_REWRITES = 4
DRAFT_CONCURRENCY = 3
SECTION_CONTEXT_CHARS = 24_000


class DocumentadorInput(BaseModel):
    source: str = Field(pattern="^(paste|upload|github)$")
    template_id: int
    output_type: str = Field(default="technical", pattern="^(technical|functional)$")
    # "deep" é opt-in: custa múltiplas chamadas de LLM por documento
    depth: str = Field(default="quick", pattern="^(quick|deep)$")
    code: str | None = None
    filename: str | None = None
    github_url: str | None = None
    branch: str | None = None


class DocumentadorOutput(BaseModel):
    doc_id: int
    filename: str
    status: str
    depth: str = "quick"
    sections_planned: int | None = None
    sections_flagged: int | None = None


class DocState(TypedDict, total=False):
    # entrada + contexto do executor
    run_id: int
    user_id: int
    source: str
    template_id: int
    output_type: str
    depth: str
    code: str | None
    filename: str | None
    github_url: str | None
    branch: str | None
    # comuns
    system_prompt: str
    user_block: str
    markdown: str
    output: dict
    usage: dict
    # modo profundo
    files: list  # list[[path, content]]
    template_text: str
    map_summary: str
    map_facts: str
    mermaid: str | None
    sections: list  # [{title, goal, relevant_files}]
    drafts: dict  # title -> markdown
    issues: list  # [{section, problem}]


def _merge_usage(state_usage: dict | None, result: llm.ChatResult) -> dict:
    usage = dict(state_usage or {})
    usage["model"] = result.model
    usage["input_tokens"] = int(usage.get("input_tokens", 0)) + result.input_tokens
    usage["output_tokens"] = int(usage.get("output_tokens", 0)) + result.output_tokens
    return usage


def _extract_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", cleaned, flags=re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def _load_template(template_id: int) -> Template:
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == template_id).first()
    finally:
        db.close()
    if template is None:
        raise ValueError("Template não encontrado.")
    return template


def _system_prompt(*, template_text: str, output_type: str) -> str:
    mode = "técnica" if output_type == "technical" else "funcional (onboarding)"
    return (
        "Você é um assistente que gera documentação de software em Markdown, em português do Brasil.\n"
        f"O usuário pediu saída no modo {mode}.\n\n"
        "Instruções do template (siga com prioridade):\n"
        f"{template_text}\n\n"
        "Regras: responda apenas com Markdown válido; use títulos, listas e blocos de código quando útil."
    )


# ================================================================ modo quick

async def prepare(state: DocState) -> DocState:
    run_id = state["run_id"]
    template = _load_template(state["template_id"])
    system = _system_prompt(template_text=template.content, output_type=state["output_type"])

    if state["source"] == "github":
        github_url = state.get("github_url") or ""
        await emit(run_id, "progress", f"Baixando repositório {github_url}…")
        try:
            owner, repo, url_branch = parse_github_url(github_url)
            ref, files, _warnings = await asyncio.to_thread(
                fetch_repo_files,
                owner=owner,
                repo=repo,
                branch=url_branch or state.get("branch"),
            )
        except GitHubArchiveError as e:
            raise ValueError(str(e)) from e
        filename = f"{owner}-{repo}-doc.md"
        bundle = "\n\n".join(f"### Arquivo: `{fp}`\n```\n{content}\n```" for fp, content in files)
        user_block = (
            f"O código abaixo foi obtido do repositório público `{owner}/{repo}` (ref: `{ref}`).\n"
            "Gere uma documentação consolidada do projeto como um todo.\n\n" + bundle
        )
    else:
        filename = state.get("filename") or "codigo.txt"
        user_block = (
            f"Arquivo de referência: `{filename}`\n\n"
            "Conteúdo para analisar:\n\n"
            f"```\n{state.get('code') or ''}\n```\n"
        )

    await emit(run_id, "node_finished", "Contexto preparado.", data={"filename": filename})
    return {"system_prompt": system, "user_block": user_block, "filename": filename}


async def generate(state: DocState) -> DocState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Gerando documentação com IA…")
    provider = llm.get_provider()
    result = await provider.chat(
        system_prompt=state["system_prompt"],
        user_content=state["user_block"],
        temperature=0.3,
    )
    await emit(
        run_id,
        "node_finished",
        "Documentação gerada.",
        data={"model": result.model, "output_tokens": result.output_tokens},
    )
    return {"markdown": result.text, "usage": _merge_usage(state.get("usage"), result)}


# ================================================================ modo deep

async def ingest(state: DocState) -> DocState:
    run_id = state["run_id"]
    template = _load_template(state["template_id"])

    if state["source"] == "github":
        github_url = state.get("github_url") or ""
        await emit(run_id, "progress", f"Baixando repositório {github_url} (modo profundo)…")
        try:
            owner, repo, url_branch = parse_github_url(github_url)
            _ref, files, warnings = await asyncio.to_thread(
                fetch_repo_files,
                owner=owner,
                repo=repo,
                branch=url_branch or state.get("branch"),
                max_files=DEEP_MAX_FILES,
                max_total_chars=DEEP_MAX_TOTAL_CHARS,
                max_file_chars=DEEP_MAX_FILE_CHARS,
            )
        except GitHubArchiveError as e:
            raise ValueError(str(e)) from e
        filename = f"{owner}-{repo}-doc.md"
        if warnings:
            await emit(run_id, "progress", f"Avisos de ingestão: {len(warnings)}.")
    else:
        filename = state.get("filename") or "codigo.txt"
        files = [(filename, state.get("code") or "")]

    await emit(run_id, "node_finished", f"Ingestão concluída: {len(files)} arquivos.")
    return {
        "files": [[fp, content] for fp, content in files],
        "filename": filename,
        "template_text": template.content,
    }


async def map_code(state: DocState) -> DocState:
    run_id = state["run_id"]
    files = [(fp, content) for fp, content in state["files"]]
    await emit(run_id, "progress", f"Mapeando código ({len(files)} arquivos)…")
    cmap = await asyncio.to_thread(build_code_map, files)
    await emit(
        run_id,
        "node_finished",
        f"Mapa pronto: {len(cmap.files)} arquivos analisados, "
        f"{len(cmap.routes)} rotas, {len(cmap.env_vars)} variáveis de ambiente.",
    )
    return {
        "map_summary": cmap.summary_text(),
        "map_facts": cmap.facts_text(),
        "mermaid": cmap.mermaid_dependencies(),
    }


async def outline(state: DocState) -> DocState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Planejando a estrutura do documento…")
    provider = llm.get_provider()
    file_list = "\n".join(f"- {fp}" for fp, _ in state["files"][:200])
    system = (
        "Você planeja a estrutura de uma documentação técnica em português do Brasil.\n"
        "Responda APENAS com JSON válido no formato:\n"
        '{"sections": [{"title": string, "goal": string, "relevant_files": [string]}]}\n'
        f"Máximo de {MAX_SECTIONS} seções. relevant_files deve conter caminhos EXATOS da lista fornecida."
    )
    user = (
        "Instruções do template (a estrutura deve atendê-las):\n"
        f"{state['template_text']}\n\n"
        f"Resumo do código:\n{state['map_summary']}\n\n"
        f"Arquivos disponíveis:\n{file_list}"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=2000, temperature=0.2
    )
    data = _extract_json(result.text)
    sections = [
        {
            "title": str(s.get("title", f"Seção {i + 1}")),
            "goal": str(s.get("goal", "")),
            "relevant_files": [str(f) for f in (s.get("relevant_files") or [])][:8],
        }
        for i, s in enumerate(data.get("sections", [])[:MAX_SECTIONS])
    ]
    if not sections:
        raise ValueError("O planejamento de seções retornou vazio.")
    await emit(
        run_id,
        "node_finished",
        f"Estrutura planejada: {len(sections)} seções.",
        data={"sections": [s["title"] for s in sections]},
    )
    return {"sections": sections, "usage": _merge_usage(state.get("usage"), result)}


def _section_context(section: dict, files: list) -> str:
    by_path = {fp: content for fp, content in files}
    chosen: list[tuple[str, str]] = []
    for fp in section.get("relevant_files", []):
        if fp in by_path:
            chosen.append((fp, by_path[fp]))
    if not chosen:  # fallback: primeiros arquivos do repo
        chosen = [(fp, content) for fp, content in files[:4]]
    parts: list[str] = []
    remaining = SECTION_CONTEXT_CHARS
    for fp, content in chosen:
        chunk = content[: min(len(content), remaining, 10_000)]
        parts.append(f"### Arquivo: `{fp}`\n```\n{chunk}\n```")
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n".join(parts)


async def draft(state: DocState) -> DocState:
    run_id = state["run_id"]
    sections = state["sections"]
    provider = llm.get_provider()
    sem = asyncio.Semaphore(DRAFT_CONCURRENCY)
    done = 0

    async def draft_one(section: dict) -> tuple[str, llm.ChatResult]:
        nonlocal done
        async with sem:
            system = _system_prompt(
                template_text=state["template_text"], output_type=state["output_type"]
            ) + (
                "\n\nVocê está escrevendo UMA seção de um documento maior. "
                f'Comece com o título exato: "## {section["title"]}". '
                "Não escreva introdução ou conclusão do documento, apenas esta seção. "
                "Baseie-se SOMENTE no código e no resumo fornecidos; não invente nomes de "
                "arquivos, rotas ou variáveis."
            )
            user = (
                f"Objetivo da seção: {section['goal']}\n\n"
                f"Resumo geral do código:\n{state['map_summary'][:6_000]}\n\n"
                f"Arquivos relevantes:\n{_section_context(section, state['files'])}"
            )
            result = await provider.chat(
                system_prompt=system, user_content=user, max_output_tokens=3000, temperature=0.3
            )
            done += 1
            await emit(run_id, "progress", f"Seção {done}/{len(sections)} redigida: {section['title']}")
            return section["title"], result

    results = await asyncio.gather(*(draft_one(s) for s in sections))
    drafts = {title: r.text for title, r in results}
    usage = state.get("usage")
    for _title, r in results:
        usage = _merge_usage(usage, r)
    await emit(run_id, "node_finished", f"{len(drafts)} seções redigidas.")
    return {"drafts": drafts, "usage": usage}


_ROUTE_MENTION = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w/{}\-.:]*)")


async def verify(state: DocState) -> DocState:
    """Confere as afirmações das seções contra os fatos do mapa de código."""
    run_id = state["run_id"]
    await emit(run_id, "progress", "Verificando afirmações contra o código…")
    provider = llm.get_provider()
    drafts: dict[str, str] = dict(state["drafts"])
    issues: list[dict] = []

    # 1) checagem determinística: rotas citadas que não existem no mapa
    known_routes = set()
    for m in _ROUTE_MENTION.finditer(state["map_facts"]):
        known_routes.add((m.group(1).upper(), m.group(2).rstrip("/")))
    if known_routes:  # só checa se o mapa detectou rotas
        for title, text in drafts.items():
            for m in _ROUTE_MENTION.finditer(text):
                mention = (m.group(1).upper(), m.group(2).rstrip("/"))
                if mention not in known_routes:
                    issues.append(
                        {
                            "section": title,
                            "problem": f"Cita rota inexistente no código: {mention[0]} {mention[1]}",
                        }
                    )

    # 2) juiz LLM: divergências factuais gerais
    doc_text = "\n\n".join(drafts.values())[:40_000]
    system = (
        "Você audita documentação técnica comparando-a com fatos extraídos do código por parser.\n"
        "Responda APENAS com JSON válido: "
        '{"issues": [{"section": string, "problem": string}]}\n'
        "Aponte apenas divergências factuais (nomes de rotas, arquivos, variáveis, comandos, "
        "assinaturas que não existem nos fatos). Ignore estilo. Se estiver tudo correto, "
        'responda {"issues": []}.'
    )
    user = f"{state['map_facts']}\n\nDOCUMENTAÇÃO A AUDITAR:\n\n{doc_text}"
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=2000, temperature=0.0
    )
    usage = _merge_usage(state.get("usage"), result)
    try:
        data = _extract_json(result.text)
        for issue in data.get("issues", []):
            if str(issue.get("section", "")) in drafts:
                issues.append({"section": str(issue["section"]), "problem": str(issue.get("problem", ""))})
    except (json.JSONDecodeError, AttributeError):
        pass  # auditoria LLM ilegível → segue só com a checagem determinística

    # 3) reescreve as seções apontadas (limitado)
    flagged: dict[str, list[str]] = {}
    for issue in issues:
        flagged.setdefault(issue["section"], []).append(issue["problem"])
    to_rewrite = list(flagged.items())[:MAX_REWRITES]
    if to_rewrite:
        await emit(run_id, "progress", f"Corrigindo {len(to_rewrite)} seções com divergências…")
    for title, problems in to_rewrite:
        rewrite_system = (
            "Você corrige uma seção de documentação para alinhá-la aos fatos do código. "
            f'Mantenha o título "## {title}". Responda apenas com o Markdown corrigido da seção.'
        )
        rewrite_user = (
            f"{state['map_facts']}\n\n"
            f"Problemas detectados:\n- " + "\n- ".join(problems) + "\n\n"
            f"Seção atual:\n\n{drafts[title]}"
        )
        r = await provider.chat(
            system_prompt=rewrite_system, user_content=rewrite_user, max_output_tokens=3000, temperature=0.2
        )
        drafts[title] = r.text
        usage = _merge_usage(usage, r)

    await emit(
        run_id,
        "node_finished",
        f"Verificação concluída: {len(issues)} divergências, {len(to_rewrite)} seções corrigidas.",
        data={"issues": issues[:20]},
    )
    return {"drafts": drafts, "issues": issues, "usage": usage}


async def assemble(state: DocState) -> DocState:
    run_id = state["run_id"]
    parts: list[str] = []
    for section in state["sections"]:
        text = state["drafts"].get(section["title"], "")
        if text:
            parts.append(text)
    if state.get("mermaid"):
        parts.append("## Diagrama de dependências\n\n```mermaid\n" + state["mermaid"] + "\n```")
    markdown = ensure_autodoc_marker("\n\n".join(parts))
    await emit(run_id, "node_finished", "Documento montado.")
    return {"markdown": markdown}


async def score(state: DocState) -> DocState:
    """Grava métricas do run em `evaluations` — base dos resultados quantitativos."""
    run_id = state["run_id"]
    sections_planned = len(state.get("sections", []))
    drafted = len(state.get("drafts", {}))
    flagged_sections = len({i["section"] for i in state.get("issues", [])})
    coverage = drafted / sections_planned if sections_planned else 0.0
    verified_ratio = 1.0 - (flagged_sections / drafted) if drafted else 0.0

    db = SessionLocal()
    try:
        for metric, value in (
            ("sections_planned", float(sections_planned)),
            ("section_coverage", coverage),
            ("verified_ratio", verified_ratio),
            ("doc_chars", float(len(state.get("markdown", "")))),
        ):
            db.add(Evaluation(run_id=run_id, metric=metric, score=value, created_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()

    output = dict(state.get("output", {}))
    output["depth"] = "deep"
    output["sections_planned"] = sections_planned
    output["sections_flagged"] = flagged_sections
    await emit(
        run_id,
        "node_finished",
        f"Métricas registradas: cobertura {coverage:.0%}, verificação {verified_ratio:.0%}.",
    )
    return {"output": output}


# ================================================================ comum

async def persist(state: DocState) -> DocState:
    db = SessionLocal()
    try:
        template = db.query(Template).filter(Template.id == state["template_id"]).first()
        rec = DocumentationRecord(
            user_id=state["user_id"],
            content=state["markdown"],
            filename=state["filename"] or "codigo.txt",
            template_id=state["template_id"],
            template_name=template.name if template else "",
            output_type=state["output_type"],
            status="completed",
            created_at=datetime.utcnow(),
            github_url=(state.get("github_url") or "").strip() or None,
            source=state["source"],
        )
        db.add(rec)
        db.commit()
        db.refresh(rec)
        doc_id = rec.id
    finally:
        db.close()

    output = DocumentadorOutput(
        doc_id=doc_id,
        filename=state["filename"] or "codigo.txt",
        status="completed",
        depth=state.get("depth") or "quick",
    )
    return {"output": output.model_dump(exclude_none=True)}


def _route_depth(state: DocState) -> str:
    return "deep" if state.get("depth") == "deep" else "quick"


def _after_persist(state: DocState) -> str:
    return "score" if state.get("depth") == "deep" else "end"


def build_graph():
    g = StateGraph(DocState)
    # quick
    g.add_node("prepare", prepare)
    g.add_node("generate", generate)
    # deep
    g.add_node("ingest", ingest)
    g.add_node("map_code", map_code)
    g.add_node("outline", outline)
    g.add_node("draft", draft)
    g.add_node("verify", verify)
    g.add_node("assemble", assemble)
    g.add_node("score", score)
    # comum
    g.add_node("persist", persist)

    g.set_conditional_entry_point(_route_depth, {"quick": "prepare", "deep": "ingest"})
    g.add_edge("prepare", "generate")
    g.add_edge("generate", "persist")
    g.add_edge("ingest", "map_code")
    g.add_edge("map_code", "outline")
    g.add_edge("outline", "draft")
    g.add_edge("draft", "verify")
    g.add_edge("verify", "assemble")
    g.add_edge("assemble", "persist")
    g.add_conditional_edges("persist", _after_persist, {"score": "score", "end": END})
    g.add_edge("score", END)
    return g.compile()


SPEC = contracts.register(
    contracts.AgentSpec(
        name="documentador",
        title="Documentador",
        description=(
            "Gera documentação técnica/funcional a partir de código colado, upload ou repositório "
            "GitHub. Modo quick (padrão, 1 chamada) ou deep (opt-in: mapa de código, seções "
            "paralelas e verificação anti-alucinação)."
        ),
        input_schema=DocumentadorInput,
        output_schema=DocumentadorOutput,
        build_graph=build_graph,
    )
)
