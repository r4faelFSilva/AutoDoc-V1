import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  Template,
  CreateTemplateRequest,
  GenerateTemplateFromExampleRequest,
  GeneratedTemplateSuggestion,
} from '../models/template.model';

const API_BASE = '/api';

@Injectable({ providedIn: 'root' })
export class TemplateService {
  constructor(private http: HttpClient) {}

  getAll(): Observable<Template[]> {
    return this.http.get<Template[]>(`${API_BASE}/templates`);
  }

  create(data: CreateTemplateRequest): Observable<Template> {
    return this.http.post<Template>(`${API_BASE}/templates`, data);
  }

  update(id: string, data: CreateTemplateRequest): Observable<Template> {
    return this.http.put<Template>(`${API_BASE}/templates/${id}`, data);
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/templates/${id}`);
  }

  generateFromExample(body: GenerateTemplateFromExampleRequest): Observable<GeneratedTemplateSuggestion> {
    return this.http.post<GeneratedTemplateSuggestion>(`${API_BASE}/templates/generate-from-example`, body);
  }
}
