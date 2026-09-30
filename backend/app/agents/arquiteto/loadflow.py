"""Propagador de carga determinístico sobre o grafo de arquitetura.

Regra de ouro do plano: gargalo é CALCULADO, não perguntado ao LLM.
Dado o RPS de entrada e a capacidade declarada de cada nó, propaga a carga
pelas arestas e marca saturação. Reprodutível, explicável e sem custo de
token — o LLM apenas narra o resultado.

O mesmo algoritmo existe em TypeScript no frontend (what-if instantâneo);
mudanças de semântica aqui devem ser espelhadas lá.

Contrato do grafo (ver docs/plano-expansao-autodoc.md §4.1):
    nodes: [{id, type, label, tech, props: {replicas, rps_capacity}}]
    edges: [{from, to, protocol, sync, weight}]  # weight = fração do tráfego (padrão 1.0)
"""

from __future__ import annotations

from typing import Any

# Tipos de nó que originam tráfego (recebem o RPS de entrada do cenário)
ENTRY_TYPES = {"client", "entrypoint", "user", "external"}

MAX_ITERATIONS = 50  # proteção contra ciclos
WARN_THRESHOLD = 0.7  # 70% da capacidade → aviso
CRITICAL_THRESHOLD = 1.0  # acima da capacidade → gargalo


def analyze_load(
    architecture: dict[str, Any],
    *,
    input_rps: float,
) -> dict[str, Any]:
    """Propaga o RPS pelo grafo e devolve {loads, annotations}.

    loads: {node_id: rps_estimado}
    annotations: lista no formato do contrato (kind=bottleneck|warning|info).
    """
    nodes = {n["id"]: n for n in architecture.get("nodes", [])}
    edges = [e for e in architecture.get("edges", []) if e.get("from") in nodes and e.get("to") in nodes]

    out_edges: dict[str, list[dict]] = {}
    incoming_count: dict[str, int] = {nid: 0 for nid in nodes}
    for e in edges:
        out_edges.setdefault(e["from"], []).append(e)
        incoming_count[e["to"]] += 1

    # Fontes de tráfego: tipo de entrada declarado ou nós sem arestas de entrada
    entry_ids = [nid for nid, n in nodes.items() if str(n.get("type", "")).lower() in ENTRY_TYPES]
    if not entry_ids:
        entry_ids = [nid for nid, count in incoming_count.items() if count == 0]
    if not entry_ids and nodes:
        # grafo cíclico sem entrada declarada — assume o primeiro nó como origem
        entry_ids = [next(iter(nodes))]

    loads: dict[str, float] = {nid: 0.0 for nid in nodes}
    frontier: list[tuple[str, float]] = [(nid, input_rps / max(len(entry_ids), 1)) for nid in entry_ids]

    # Propagação com contagem de visitas para tolerar ciclos
    visits: dict[str, int] = {}
    while frontier:
        nid, rps = frontier.pop(0)
        visits[nid] = visits.get(nid, 0) + 1
        if visits[nid] > MAX_ITERATIONS:
            continue
        loads[nid] += rps
        for e in out_edges.get(nid, []):
            weight = float(e.get("weight", 1.0))
            if weight <= 0:
                continue
            frontier.append((e["to"], rps * weight))

    annotations: list[dict[str, Any]] = []
    for nid, node in nodes.items():
        props = node.get("props") or {}
        capacity = props.get("rps_capacity")
        if capacity is None:
            continue  # sem capacidade declarada → nada a afirmar
        replicas = max(int(props.get("replicas", 1) or 1), 1)
        total_capacity = float(capacity) * replicas
        load = loads[nid]
        if total_capacity <= 0:
            continue
        utilization = load / total_capacity
        if utilization >= CRITICAL_THRESHOLD:
            annotations.append(
                {
                    "target": nid,
                    "kind": "bottleneck",
                    "severity": "high",
                    "message": (
                        f"{node.get('label', nid)}: carga estimada {load:.0f} RPS excede a capacidade "
                        f"de {total_capacity:.0f} RPS ({replicas}x {float(capacity):.0f}). "
                        f"Utilização: {utilization:.0%}."
                    ),
                }
            )
        elif utilization >= WARN_THRESHOLD:
            annotations.append(
                {
                    "target": nid,
                    "kind": "warning",
                    "severity": "medium",
                    "message": (
                        f"{node.get('label', nid)}: utilização em {utilization:.0%} "
                        f"({load:.0f}/{total_capacity:.0f} RPS) — pouca folga para picos."
                    ),
                }
            )

    # Aviso estrutural: ponto único de falha (réplica única com tráfego)
    for nid, node in nodes.items():
        props = node.get("props") or {}
        replicas = int(props.get("replicas", 1) or 1)
        ntype = str(node.get("type", "")).lower()
        if replicas <= 1 and loads[nid] > 0 and ntype not in ENTRY_TYPES:
            annotations.append(
                {
                    "target": nid,
                    "kind": "spof",
                    "severity": "medium",
                    "message": f"{node.get('label', nid)}: réplica única — ponto único de falha.",
                }
            )

    return {"loads": {k: round(v, 2) for k, v in loads.items()}, "annotations": annotations}
