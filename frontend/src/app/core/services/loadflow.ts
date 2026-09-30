/**
 * Propagador de carga determinístico — espelho em TypeScript de
 * backend/app/agents/arquiteto/loadflow.py.
 *
 * Roda no cliente para o "what-if" instantâneo do canvas (arrastar o slider
 * de RPS, editar réplicas) sem nenhuma chamada de IA ou de rede.
 * Mudanças de semântica aqui devem ser espelhadas no Python.
 */

import { ArchAnnotation, ArchitectureGraph } from '../models/architecture.model';

const ENTRY_TYPES = new Set(['client', 'entrypoint', 'user', 'external']);
const MAX_ITERATIONS = 50;
const WARN_THRESHOLD = 0.7;
const CRITICAL_THRESHOLD = 1.0;

export interface LoadAnalysis {
  loads: Record<string, number>;
  annotations: ArchAnnotation[];
}

export function analyzeLoad(architecture: ArchitectureGraph, inputRps: number): LoadAnalysis {
  const nodes = new Map(architecture.nodes.map(n => [n.id, n]));
  const edges = architecture.edges.filter(e => nodes.has(e.from) && nodes.has(e.to));

  const outEdges = new Map<string, typeof edges>();
  const incomingCount = new Map<string, number>();
  for (const id of nodes.keys()) incomingCount.set(id, 0);
  for (const e of edges) {
    if (!outEdges.has(e.from)) outEdges.set(e.from, []);
    outEdges.get(e.from)!.push(e);
    incomingCount.set(e.to, (incomingCount.get(e.to) ?? 0) + 1);
  }

  let entryIds = [...nodes.values()].filter(n => ENTRY_TYPES.has(n.type)).map(n => n.id);
  if (entryIds.length === 0) {
    entryIds = [...incomingCount.entries()].filter(([, c]) => c === 0).map(([id]) => id);
  }
  if (entryIds.length === 0 && nodes.size > 0) {
    entryIds = [architecture.nodes[0].id];
  }

  const loads: Record<string, number> = {};
  for (const id of nodes.keys()) loads[id] = 0;

  const frontier: Array<[string, number]> = entryIds.map(id => [id, inputRps / Math.max(entryIds.length, 1)]);
  const visits = new Map<string, number>();
  while (frontier.length > 0) {
    const [nid, rps] = frontier.shift()!;
    const count = (visits.get(nid) ?? 0) + 1;
    visits.set(nid, count);
    if (count > MAX_ITERATIONS) continue;
    loads[nid] += rps;
    for (const e of outEdges.get(nid) ?? []) {
      const weight = e.weight ?? 1.0;
      if (weight <= 0) continue;
      frontier.push([e.to, rps * weight]);
    }
  }

  const annotations: ArchAnnotation[] = [];
  for (const node of nodes.values()) {
    const capacity = node.props?.rps_capacity;
    if (capacity == null || capacity <= 0) continue;
    const replicas = Math.max(node.props?.replicas ?? 1, 1);
    const totalCapacity = capacity * replicas;
    const load = loads[node.id];
    const utilization = load / totalCapacity;
    if (utilization >= CRITICAL_THRESHOLD) {
      annotations.push({
        target: node.id,
        kind: 'bottleneck',
        severity: 'high',
        message:
          `${node.label}: carga estimada ${Math.round(load)} RPS excede a capacidade de ` +
          `${Math.round(totalCapacity)} RPS (${replicas}x ${Math.round(capacity)}). ` +
          `Utilização: ${Math.round(utilization * 100)}%.`,
      });
    } else if (utilization >= WARN_THRESHOLD) {
      annotations.push({
        target: node.id,
        kind: 'warning',
        severity: 'medium',
        message:
          `${node.label}: utilização em ${Math.round(utilization * 100)}% ` +
          `(${Math.round(load)}/${Math.round(totalCapacity)} RPS) — pouca folga para picos.`,
      });
    }
  }

  for (const node of nodes.values()) {
    const replicas = node.props?.replicas ?? 1;
    if (replicas <= 1 && loads[node.id] > 0 && !ENTRY_TYPES.has(node.type)) {
      annotations.push({
        target: node.id,
        kind: 'spof',
        severity: 'medium',
        message: `${node.label}: réplica única — ponto único de falha.`,
      });
    }
  }

  for (const id of Object.keys(loads)) loads[id] = Math.round(loads[id] * 100) / 100;
  return { loads, annotations };
}
