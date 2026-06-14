from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User
from app.schemas.auth import LoginRequest, LoginResponse, RegisterRequest


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def create_access_token(sub: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": sub, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        sub = payload.get("sub")
        return str(sub) if sub else None
    except JWTError:
        return None


def authenticate(db: Session, body: LoginRequest) -> LoginResponse | None:
    user = db.query(User).filter(User.email == str(body.email)).first()
    if not user or not verify_password(body.password, user.hashed_password):
        return None
    token = create_access_token(str(user.id))
    return LoginResponse(access_token=token, token_type="bearer")


def register(db: Session, body: RegisterRequest) -> LoginResponse | None:
    existing = db.query(User).filter(User.email == str(body.email)).first()
    if existing:
        return None
    user = User(
        email=str(body.email),
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id))
    return LoginResponse(access_token=token, token_type="bearer")


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()
