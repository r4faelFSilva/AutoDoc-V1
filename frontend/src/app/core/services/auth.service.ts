import { Injectable, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, throwError } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';
import { LoginRequest, LoginResponse, RegisterRequest } from '../models/auth.model';

const TOKEN_KEY = 'autodoc_token';
const API_BASE = '/api';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private _isAuthenticated = signal(this.hasValidToken());

  readonly isAuthenticated = this._isAuthenticated.asReadonly();

  constructor(private http: HttpClient, private router: Router) {}

  login(credentials: LoginRequest): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${API_BASE}/auth/login`, credentials).pipe(
      tap(res => {
        localStorage.setItem(TOKEN_KEY, res.access_token);
        this._isAuthenticated.set(true);
      }),
      catchError((err: HttpErrorResponse) => {
        const msg =
          err.error?.detail && typeof err.error.detail === 'string'
            ? err.error.detail
            : 'Credenciais inválidas';
        return throwError(() => new Error(msg));
      }),
    );
  }

  register(data: RegisterRequest): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(`${API_BASE}/auth/register`, data).pipe(
      tap(res => {
        localStorage.setItem(TOKEN_KEY, res.access_token);
        this._isAuthenticated.set(true);
      }),
      catchError((err: HttpErrorResponse) => {
        const msg =
          err.error?.detail && typeof err.error.detail === 'string'
            ? err.error.detail
            : 'Erro ao criar conta';
        return throwError(() => new Error(msg));
      }),
    );
  }

  logout(): void {
    localStorage.removeItem(TOKEN_KEY);
    this._isAuthenticated.set(false);
    this.router.navigate(['/login']);
  }

  getToken(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  }

  private hasValidToken(): boolean {
    return !!localStorage.getItem(TOKEN_KEY);
  }
}
