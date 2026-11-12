export interface LoginRequest {
  email: string;
  password: string;
}

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface AuthConfig {
  allow_registration: boolean;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface AuthUser {
  email: string;
  name?: string;
}
