export type OutputType = 'technical' | 'functional';
export type DocStatus = 'completed' | 'processing' | 'failed';

export interface GenerateRequest {
  code: string;
  template_id: string;
  output_type: OutputType;
  filename?: string;
}

export interface GenerateGithubRequest {
  github_url: string;
  template_id: string;
  output_type: OutputType;
  branch?: string;
}

export interface DocumentationRecord {
  id: string;
  content: string;
  filename: string;
  template_id: string;
  template_name: string;
  output_type: OutputType;
  status: DocStatus;
  created_at: string;
  github_url?: string | null;
}

export interface DashboardStats {
  total_docs: number;
  last_doc?: DocumentationRecord;
  available_templates: number;
}

export interface SearchResult {
  id: string;
  filename: string;
  template_name: string;
  output_type: OutputType;
  snippet: string;
  created_at: string;
}

export interface CommitGithubReadmeRequest {
  github_url: string;
  content: string;
  github_token: string;
  branch?: string;
  target_path?: string;
  commit_message?: string;
}

export interface CommitGithubReadmeResponse {
  commit_sha: string;
  commit_url: string;
  target_path: string;
  branch: string;
}
