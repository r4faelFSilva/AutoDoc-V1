from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class AuthConfigResponse(BaseModel):
    allow_registration: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
