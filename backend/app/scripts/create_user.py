"""Cria um usuário do AutoDoc pela linha de comando.

Uso (a partir de backend/):
    python -m app.scripts.create_user --email voce@exemplo.com

A senha é pedida de forma interativa, sem eco no terminal. É o caminho para
criar o primeiro usuário quando ALLOW_REGISTRATION=false e SEED_DEMO_USER=false.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from pydantic import ValidationError

import app.models  # noqa: F401 — registra todas as tabelas no metadata
from app.database import Base, SessionLocal, engine
from app.models.user import User
from app.schemas.auth import RegisterRequest
from app.services.auth_service import hash_password

MIN_PASSWORD_LENGTH = 8


def _read_password() -> str:
    password = getpass.getpass("Senha: ")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"A senha precisa ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if getpass.getpass("Confirme a senha: ") != password:
        sys.exit("As senhas não conferem.")
    return password


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cria um usuário do AutoDoc.")
    parser.add_argument("--email", required=True, help="e-mail de login do novo usuário")
    args = parser.parse_args(argv)

    try:
        email = str(RegisterRequest(email=args.email, password="-").email)
    except ValidationError:
        sys.exit(f"E-mail inválido: {args.email}")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(User).filter(User.email == email).first():
            sys.exit(f"Já existe um usuário com o e-mail {email}.")
        password = _read_password()
        db.add(User(email=email, hashed_password=hash_password(password)))
        db.commit()
    finally:
        db.close()

    print(f"Usuário {email} criado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
