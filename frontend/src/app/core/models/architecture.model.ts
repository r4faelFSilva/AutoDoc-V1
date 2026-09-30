export type ArchNodeType =
  | 'client'
  | 'gateway'
  | 'service'
  | 'worker'
  | 'db'
  | 'cache'
  | 'queue'
  | 'storage'
  | 'external';

export interface ArchNodeProps {
  replicas?: number;
  rps_capacity?: number;
}

export interface ArchNode {
  id: string;
  type: ArchNodeType;
  label: string;
  tech: string;
  props: ArchNodeProps;
}

export interface ArchEdge {
  from: string;
  to: string;
  protocol: string;
  sync: boolean;
  weight: number;
}

export interface ArchitectureGraph {
  nodes: ArchNode[];
  edges: ArchEdge[];
}

export interface ArchAnnotation {
  target: string; // id do nó ou "geral"
  kind: 'bottleneck' | 'warning' | 'spof' | 'coupling' | 'cost' | 'security' | 'consistency' | 'operational' | string;
  severity: 'high' | 'medium' | 'low' | string;
  message: string;
}

export interface ArchNfrs {
  expected_rps: number;
  peak_multiplier: number;
  latency_target_ms: number;
  assumptions: string[];
}

/** Saída do agente arquiteto (run.output). */
export interface ArquitetoOutput {
  architecture: ArchitectureGraph;
  annotations: ArchAnnotation[];
  loads: Record<string, number>;
  nfrs: ArchNfrs;
  adr_markdown: string;
}
