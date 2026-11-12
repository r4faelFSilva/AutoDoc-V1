export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';

export interface AgentRun {
  id: number;
  agent: string;
  status: RunStatus;
  output: Record<string, unknown> | null;
  error: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Limite de tempo total do run no servidor, em segundos. */
  timeout_seconds?: number | null;
}

export interface RunEvent {
  seq: number;
  kind: 'progress' | 'node_started' | 'node_finished' | 'completed' | 'failed';
  message: string;
  data?: Record<string, unknown> | null;
  created_at?: string;
}

export interface AgentInfo {
  name: string;
  title: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface DocumentadorInput {
  source: 'paste' | 'upload' | 'github';
  template_id: number;
  output_type: 'technical' | 'functional';
  /** 'deep' é opt-in: análise profunda com maior custo de IA. */
  depth?: 'quick' | 'deep';
  code?: string;
  filename?: string;
  github_url?: string;
  branch?: string;
}
