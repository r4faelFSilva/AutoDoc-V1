from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas.auth import AuthConfigResponse, LoginRequest, LoginResponse, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config", response_model=AuthConfigResponse)
def auth_config() -> AuthConfigResponse:
    """Configuração pública usada pela tela de login (sem autenticação)."""
    return AuthConfigResponse(allow_registration=settings.allow_registration)


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    result = auth_service.authenticate(db, body)
    if not result:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")
    return result


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> LoginResponse:
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="O cadastro está desativado neste servidor. Peça a um administrador para criar sua conta.",
        )
    result = auth_service.register(db, body)
    if not result:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email já cadastrado")
    return result
