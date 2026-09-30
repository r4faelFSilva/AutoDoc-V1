import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { AgentInfo, AgentRun, RunEvent } from '../models/agent-run.model';
import { AuthService } from './auth.service';

const API_BASE = '/api';

@Injectable({ providedIn: 'root' })
export class AgentRunsService {
  constructor(
    private http: HttpClient,
    private auth: AuthService,
  ) {}

  listAgents(): Observable<AgentInfo[]> {
    return this.http.get<AgentInfo[]>(`${API_BASE}/agents`);
  }

  createRun(agent: string, input: Record<string, unknown>): Observable<AgentRun> {
    return this.http.post<AgentRun>(`${API_BASE}/agents/${agent}/runs`, { input });
  }

  getRun(runId: number): Observable<AgentRun> {
    return this.http.get<AgentRun>(`${API_BASE}/runs/${runId}`);
  }

  listRuns(): Observable<AgentRun[]> {
    return this.http.get<AgentRun[]>(`${API_BASE}/runs`);
  }

  /** Extrai texto de um documento de especificação (.txt/.md/.docx/.pdf). */
  extractSpecFile(file: File): Observable<{ filename: string; text: string; chars: number; truncated: boolean }> {
    const form = new FormData();
    form.append('file', file, file.name);
    return this.http.post<{ filename: string; text: string; chars: number; truncated: boolean }>(
      `${API_BASE}/agents/arquiteto/extract-spec`,
      form,
    );
  }

  /**
   * Stream SSE dos eventos do run.
   *
   * Usa fetch + ReadableStream (e não EventSource) para enviar o JWT no
   * header Authorization — token nunca vai em query string.
   */
  streamEvents(runId: number): Observable<RunEvent> {
    return new Observable<RunEvent>(subscriber => {
      const controller = new AbortController();
      const token = this.auth.getToken();

      const consume = async (): Promise<void> => {
        const response = await fetch(`${API_BASE}/runs/${runId}/events`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`SSE falhou: HTTP ${response.status}`);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          let sep: number;
          while ((sep = buffer.indexOf('\n\n')) >= 0) {
            const rawEvent = buffer.slice(0, sep);
            buffer = buffer.slice(sep + 2);
            for (const line of rawEvent.split('\n')) {
              if (!line.startsWith('data:')) continue; // ignora ": keep-alive"
              try {
                const event = JSON.parse(line.slice(5).trim()) as RunEvent;
                subscriber.next(event);
                if (event.kind === 'completed' || event.kind === 'failed') {
                  subscriber.complete();
                  return;
                }
              } catch {
                // linha malformada — ignora e segue o stream
              }
            }
          }
        }
        subscriber.complete();
      };

      consume().catch(err => {
        if (!controller.signal.aborted) {
          subscriber.error(err);
        }
      });

      return () => controller.abort();
    });
  }
}
