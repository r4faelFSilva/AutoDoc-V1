from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services import auth_service

security = HTTPBearer(auto_error=False)


def optional_github_token(
    body_token: SecretStr | None,
    header_token: str | None,
) -> str | None:
    """Token do GitHub enviado pelo usuário (header tem prioridade), se houver."""
    if header_token and header_token.strip():
        return header_token.strip()
    if body_token is not None:
        value = body_token.get_secret_value().strip()
        if value:
            return value
    return None


def resolve_github_token(
    body_token: SecretStr | None,
    header_token: str | None,
) -> str:
    token = optional_github_token(body_token, header_token)
    if token:
        return token
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Token GitHub não informado. Use o campo github_token ou o header X-GitHub-Token.",
    )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Não autenticado.")
    sub = auth_service.decode_token(credentials.credentials)
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido ou expirado.")
    try:
        uid = int(sub)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido.")
    user = auth_service.get_user_by_id(db, uid)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuário não encontrado.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]
