import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, of, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  DocumentationRecord,
  GenerateRequest,
  GenerateGithubRequest,
  DashboardStats,
  SearchResult,
  CommitGithubReadmeRequest,
  CommitGithubReadmeResponse,
} from '../models/documentation.model';

const API_BASE = '/api';

@Injectable({ providedIn: 'root' })
export class DocumentationService {
  constructor(private http: HttpClient) {}

  generate(request: GenerateRequest): Observable<DocumentationRecord> {
    return this.http.post<DocumentationRecord>(`${API_BASE}/generate`, request);
  }

  generateFromGithub(request: GenerateGithubRequest): Observable<DocumentationRecord> {
    return this.http.post<DocumentationRecord>(`${API_BASE}/generate/github`, request);
  }

  getHistory(): Observable<DocumentationRecord[]> {
    return this.http.get<DocumentationRecord[]>(`${API_BASE}/history`);
  }

  getById(id: string): Observable<DocumentationRecord | undefined> {
    return this.http.get<DocumentationRecord>(`${API_BASE}/history/${id}`).pipe(
      catchError((err: HttpErrorResponse) => {
        if (err.status === 404) {
          return of(undefined);
        }
        return throwError(() => err);
      }),
    );
  }

  updateContent(id: string, content: string): Observable<DocumentationRecord> {
    return this.http.patch<DocumentationRecord>(`${API_BASE}/history/${id}`, { content });
  }

  delete(id: string): Observable<void> {
    return this.http.delete<void>(`${API_BASE}/history/${id}`);
  }

  search(query: string, limit = 8): Observable<SearchResult[]> {
    return this.http.get<SearchResult[]>(`${API_BASE}/search`, {
      params: { q: query, limit: String(limit) },
    });
  }

  getStats(): Observable<DashboardStats> {
    return this.http.get<DashboardStats>(`${API_BASE}/stats`);
  }

  commitGithubReadme(request: CommitGithubReadmeRequest): Observable<CommitGithubReadmeResponse> {
    return this.http.post<CommitGithubReadmeResponse>(`${API_BASE}/generate/github/commit`, request);
  }
}
