"""Agente arquiteto — da ideia (ou do repo) ao desenho criticado.

intake → estimate → propose → critique → analyze → decide → render

- Entrada: especificação livre, repositório GitHub (engenharia reversa via
  mapa de código) ou um grafo já editado no canvas (re-crítica).
- `analyze` é o propagador de carga determinístico (loadflow.py): gargalo é
  calculado, não perguntado ao LLM.
- Saída: contrato JSON nodes/edges/annotations (consumido pelo canvas),
  ADR em Markdown e artifacts persistidos.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, model_validator

from app.core import contracts, llm
from app.database import SessionLocal
from app.index.code_map import build_code_map
from app.jobs.tasks import emit
from app.models.agent_run import Artifact
from app.services.github_archive import (
    GitHubArchiveError,
    fetch_repo_files,
    parse_github_url,
)
from app.agents.arquiteto.loadflow import analyze_load

NODE_TYPES = ("client", "gateway", "service", "worker", "db", "cache", "queue", "storage", "external")


class ArquitetoInput(BaseModel):
    spec: str | None = Field(default=None, max_length=20_000)
    github_url: str | None = None
    branch: str | None = None
    expected_rps: float = Field(default=100.0, gt=0, le=10_000_000)
    # Grafo editado no canvas para re-crítica (pula o propose)
    base_architecture: dict | None = None

    @model_validator(mode="after")
    def require_some_input(self) -> "ArquitetoInput":
        if not (self.spec or self.github_url or self.base_architecture):
            raise ValueError("Informe spec, github_url ou base_architecture.")
        return self


class ArquitetoOutput(BaseModel):
    architecture: dict
    annotations: list
    loads: dict
    nfrs: dict
    adr_markdown: str


class ArchState(TypedDict, total=False):
    run_id: int
    user_id: int
    spec: str | None
    github_url: str | None
    branch: str | None
    expected_rps: float
    base_architecture: dict | None
    # intermediários
    context_text: str
    nfrs: dict
    architecture: dict
    critique_risks: list
    load_result: dict
    adr_markdown: str
    output: dict
    usage: dict


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


def _sanitize_architecture(raw: dict) -> dict:
    """Valida e normaliza o grafo vindo do LLM (ou do canvas)."""
    nodes: list[dict] = []
    seen: set[str] = set()
    for n in raw.get("nodes", []):
        nid = str(n.get("id") or "").strip()
        if not nid or nid in seen:
            continue
        seen.add(nid)
        ntype = str(n.get("type") or "service").lower()
        if ntype not in NODE_TYPES:
            ntype = "service"
        props = n.get("props") or {}
        clean_props: dict[str, Any] = {}
        if props.get("replicas") is not None:
            try:
                clean_props["replicas"] = max(int(props["replicas"]), 1)
            except (TypeError, ValueError):
                pass
        if props.get("rps_capacity") is not None:
            try:
                clean_props["rps_capacity"] = max(float(props["rps_capacity"]), 0.0)
            except (TypeError, ValueError):
                pass
        nodes.append(
            {
                "id": nid,
                "type": ntype,
                "label": str(n.get("label") or nid),
                "tech": str(n.get("tech") or ""),
                "props": clean_props,
            }
        )
    edges: list[dict] = []
    for e in raw.get("edges", []):
        src, dst = str(e.get("from") or ""), str(e.get("to") or "")
        if src not in seen or dst not in seen or src == dst:
            continue
        try:
            weight = min(max(float(e.get("weight", 1.0)), 0.0), 10.0)
        except (TypeError, ValueError):
            weight = 1.0
        edges.append(
            {
                "from": src,
                "to": dst,
                "protocol": str(e.get("protocol") or "http"),
                "sync": bool(e.get("sync", True)),
                "weight": weight,
            }
        )
    if not nodes:
        raise ValueError("A proposta de arquitetura não contém nós válidos.")
    return {"nodes": nodes, "edges": edges}


ARCH_JSON_SPEC = (
    "Formato do JSON de arquitetura:\n"
    '{"nodes": [{"id": string, "type": string, "label": string, "tech": string, '
    '"props": {"replicas": int, "rps_capacity": number}}], '
    '"edges": [{"from": string, "to": string, "protocol": string, "sync": boolean, '
    '"weight": number}]}\n'
    f"Tipos de nó permitidos: {', '.join(NODE_TYPES)}.\n"
    "weight = fração do tráfego do nó de origem que segue por essa aresta (0.0 a 1.0; "
    "use >1.0 apenas para fan-out real, ex.: 1 request gera N mensagens).\n"
    "SEMPRE inclua um nó type=client como origem do tráfego. "
    "SEMPRE estime rps_capacity realista por réplica para services, dbs, caches e queues."
)


# ---------------------------------------------------------------- nós

async def intake(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    parts: list[str] = []
    if state.get("spec"):
        parts.append(f"ESPECIFICAÇÃO DO USUÁRIO:\n{state['spec']}")

    if state.get("github_url"):
        await emit(run_id, "progress", f"Analisando repositório {state['github_url']}…")
        try:
            owner, repo, url_branch = parse_github_url(state["github_url"])
            _ref, files, _warnings = await asyncio.to_thread(
                fetch_repo_files,
                owner=owner,
                repo=repo,
                branch=url_branch or state.get("branch"),
                max_files=200,
                max_total_chars=400_000,
            )
        except GitHubArchiveError as e:
            raise ValueError(str(e)) from e
        cmap = await asyncio.to_thread(build_code_map, files)
        parts.append(
            f"SISTEMA EXISTENTE (engenharia reversa de {owner}/{repo}):\n{cmap.summary_text()}"
        )

    if state.get("base_architecture"):
        parts.append(
            "ARQUITETURA ATUAL (editada pelo usuário no canvas — critique-a, não a substitua):\n"
            + json.dumps(state["base_architecture"], ensure_ascii=False)
        )

    await emit(run_id, "node_finished", "Contexto coletado.")
    return {"context_text": "\n\n".join(parts)}


async def estimate(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Estimando requisitos não-funcionais…")
    provider = llm.get_provider()
    system = (
        "Você extrai requisitos não-funcionais de uma especificação de sistema.\n"
        "Responda APENAS com JSON válido:\n"
        '{"expected_rps": number, "peak_multiplier": number, "latency_target_ms": number, '
        '"assumptions": [string]}\n'
        "Se a especificação não disser, use o RPS de referência informado e explicite a "
        "premissa em assumptions. Seja realista e conservador."
    )
    user = (
        f"RPS de referência informado pelo usuário: {state.get('expected_rps', 100.0)}\n\n"
        f"{state['context_text'][:20_000]}"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=800, temperature=0.1
    )
    usage = _merge_usage(state.get("usage"), result)
    try:
        data = _extract_json(result.text)
        nfrs = {
            "expected_rps": float(data.get("expected_rps") or state.get("expected_rps", 100.0)),
            "peak_multiplier": float(data.get("peak_multiplier") or 2.0),
            "latency_target_ms": float(data.get("latency_target_ms") or 300.0),
            "assumptions": [str(a) for a in (data.get("assumptions") or [])][:10],
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        nfrs = {
            "expected_rps": state.get("expected_rps", 100.0),
            "peak_multiplier": 2.0,
            "latency_target_ms": 300.0,
            "assumptions": ["Estimativa automática indisponível; usados valores padrão."],
        }
    await emit(
        run_id,
        "node_finished",
        f"Requisitos estimados: {nfrs['expected_rps']:.0f} RPS (pico {nfrs['peak_multiplier']:.1f}x).",
    )
    return {"nfrs": nfrs, "usage": usage}


async def propose(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    if state.get("base_architecture"):
        # Re-crítica: respeita o desenho do usuário
        architecture = _sanitize_architecture(state["base_architecture"])
        await emit(run_id, "node_finished", "Usando a arquitetura editada no canvas.")
        return {"architecture": architecture}

    await emit(run_id, "progress", "Propondo arquitetura…")
    provider = llm.get_provider()
    system = (
        "Você é um arquiteto de software sênior. Proponha UMA arquitetura para o sistema "
        "descrito, dimensionada para os requisitos não-funcionais.\n"
        "Responda APENAS com JSON válido.\n\n" + ARCH_JSON_SPEC
    )
    user = (
        f"Requisitos não-funcionais: {json.dumps(state['nfrs'], ensure_ascii=False)}\n\n"
        f"{state['context_text'][:20_000]}"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=2500, temperature=0.3
    )
    architecture = _sanitize_architecture(_extract_json(result.text))
    await emit(
        run_id,
        "node_finished",
        f"Arquitetura proposta: {len(architecture['nodes'])} componentes, "
        f"{len(architecture['edges'])} conexões.",
        data={"components": [n["label"] for n in architecture["nodes"]]},
    )
    return {"architecture": architecture, "usage": _merge_usage(state.get("usage"), result)}


async def critique(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Criticando a proposta (agente adversarial)…")
    provider = llm.get_provider()
    system = (
        "Você é um revisor adversarial de arquiteturas. Ataque a proposta: pontos únicos de "
        "falha, acoplamento, custo, consistência, segurança, operabilidade.\n"
        "NÃO aponte gargalos de capacidade/RPS — isso é calculado deterministicamente por "
        "outra etapa.\n"
        "Responda APENAS com JSON válido:\n"
        '{"risks": [{"target": string (id do nó ou "geral"), "kind": '
        '"spof"|"coupling"|"cost"|"security"|"consistency"|"operational", '
        '"severity": "high"|"medium"|"low", "message": string}]}\n'
        "Máximo 8 riscos, os mais relevantes primeiro. Mensagens objetivas em português."
    )
    user = (
        f"Requisitos: {json.dumps(state['nfrs'], ensure_ascii=False)}\n\n"
        f"Arquitetura:\n{json.dumps(state['architecture'], ensure_ascii=False)}"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, json_mode=True, max_output_tokens=1500, temperature=0.4
    )
    usage = _merge_usage(state.get("usage"), result)
    risks: list[dict] = []
    try:
        data = _extract_json(result.text)
        node_ids = {n["id"] for n in state["architecture"]["nodes"]}
        for r in data.get("risks", [])[:8]:
            target = str(r.get("target") or "geral")
            risks.append(
                {
                    "target": target if target in node_ids else "geral",
                    "kind": str(r.get("kind") or "operational"),
                    "severity": str(r.get("severity") or "medium"),
                    "message": str(r.get("message") or ""),
                }
            )
    except json.JSONDecodeError:
        pass
    await emit(run_id, "node_finished", f"Crítica concluída: {len(risks)} riscos apontados.")
    return {"critique_risks": risks, "usage": usage}


async def analyze(state: ArchState) -> ArchState:
    """Propagação de carga determinística — sem LLM."""
    run_id = state["run_id"]
    rps = float(state["nfrs"]["expected_rps"]) * float(state["nfrs"].get("peak_multiplier", 1.0))
    result = analyze_load(state["architecture"], input_rps=rps)
    bottlenecks = [a for a in result["annotations"] if a["kind"] == "bottleneck"]
    await emit(
        run_id,
        "node_finished",
        f"Análise de carga a {rps:.0f} RPS (pico): {len(bottlenecks)} gargalos, "
        f"{len(result['annotations']) - len(bottlenecks)} avisos.",
    )
    return {"load_result": result}


async def decide(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    await emit(run_id, "progress", "Redigindo o ADR…")
    provider = llm.get_provider()
    system = (
        "Você redige um ADR (Architecture Decision Record) em Markdown, português do Brasil.\n"
        "Estrutura: # título; ## Contexto; ## Decisão (componentes e porquês); "
        "## Consequências; ## Riscos e mitigações (incorpore a crítica e a análise de carga); "
        "## Premissas.\n"
        "Seja específico e cite os componentes pelo label. Não invente números além dos fornecidos."
    )
    user = (
        f"Requisitos: {json.dumps(state['nfrs'], ensure_ascii=False)}\n\n"
        f"Arquitetura: {json.dumps(state['architecture'], ensure_ascii=False)}\n\n"
        f"Riscos da crítica: {json.dumps(state['critique_risks'], ensure_ascii=False)}\n\n"
        f"Análise de carga (determinística): {json.dumps(state['load_result'], ensure_ascii=False)}"
    )
    result = await provider.chat(
        system_prompt=system, user_content=user, max_output_tokens=2500, temperature=0.3
    )
    await emit(run_id, "node_finished", "ADR redigido.")
    return {"adr_markdown": result.text, "usage": _merge_usage(state.get("usage"), result)}


async def render(state: ArchState) -> ArchState:
    run_id = state["run_id"]
    annotations = list(state["load_result"]["annotations"])
    for r in state["critique_risks"]:
        annotations.append(
            {
                "target": r["target"],
                "kind": r["kind"],
                "severity": r["severity"],
                "message": r["message"],
            }
        )

    output = ArquitetoOutput(
        architecture=state["architecture"],
        annotations=annotations,
        loads=state["load_result"]["loads"],
        nfrs=state["nfrs"],
        adr_markdown=state["adr_markdown"],
    ).model_dump()

    db = SessionLocal()
    try:
        db.add(
            Artifact(
                run_id=run_id,
                kind="architecture",
                name="architecture.json",
                content=json.dumps(
                    {"architecture": state["architecture"], "annotations": annotations},
                    ensure_ascii=False,
                ),
                created_at=datetime.utcnow(),
            )
        )
        db.add(
            Artifact(
                run_id=run_id,
                kind="adr",
                name="adr.md",
                content=state["adr_markdown"],
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()

    return {"output": output}


def build_graph():
    g = StateGraph(ArchState)
    g.add_node("intake", intake)
    g.add_node("estimate", estimate)
    g.add_node("propose", propose)
    g.add_node("critique", critique)
    g.add_node("analyze", analyze)
    g.add_node("decide", decide)
    g.add_node("render", render)

    g.set_entry_point("intake")
    g.add_edge("intake", "estimate")
    g.add_edge("estimate", "propose")
    g.add_edge("propose", "critique")
    g.add_edge("critique", "analyze")
    g.add_edge("analyze", "decide")
    g.add_edge("decide", "render")
    g.add_edge("render", END)
    return g.compile()


SPEC = contracts.register(
    contracts.AgentSpec(
        name="arquiteto",
        title="Arquiteto",
        description=(
            "Propõe e critica arquiteturas a partir de uma especificação, de um repositório "
            "GitHub (engenharia reversa) ou de um desenho editado no canvas. Análise de "
            "gargalos determinística + ADR em Markdown."
        ),
        input_schema=ArquitetoInput,
        output_schema=ArquitetoOutput,
        build_graph=build_graph,
    )
)
