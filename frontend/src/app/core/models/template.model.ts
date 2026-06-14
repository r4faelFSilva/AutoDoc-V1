export type TemplateType = 'technical' | 'functional';

export interface Template {
  id: string;
  name: string;
  description: string;
  content: string;
  type: TemplateType;
  created_at: string;
  updated_at?: string;
}

export interface CreateTemplateRequest {
  name: string;
  description: string;
  content: string;
  type: TemplateType;
}

export interface GenerateTemplateFromExampleRequest {
  example_markdown: string;
  type: TemplateType;
}

/** Resposta da IA ao transformar um exemplo em modelo com placeholders ''...'' */
export interface GeneratedTemplateSuggestion {
  name: string;
  description: string;
  content: string;
  type: TemplateType;
}
