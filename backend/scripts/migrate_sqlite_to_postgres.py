"""Copia os dados do SQLite local para o Postgres do Compose.

Uso (a partir de backend/, com o Compose de infra/ rodando):

    .venv\\Scripts\\python scripts/migrate_sqlite_to_postgres.py ^
        --sqlite data/autodoc.db ^
        --postgres postgresql+psycopg://autodoc:autodoc@localhost:5432/autodoc

Idempotente por tabela: só copia tabelas que estiverem vazias no destino.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, insert, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    AgentRun,
    Artifact,
    DocumentationRecord,
    Evaluation,
    Project,
    RunEvent,
    Template,
    User,
)

# Ordem respeita as FKs
ORDERED_MODELS = [User, Template, Project, DocumentationRecord, AgentRun, RunEvent, Artifact, Evaluation]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", default="data/autodoc.db", help="caminho do arquivo SQLite")
    parser.add_argument("--postgres", required=True, help="URL SQLAlchemy do Postgres destino")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        print(f"ERRO: {sqlite_path} não existe.")
        return 1

    src = create_engine(f"sqlite:///{sqlite_path.as_posix()}")
    dst = create_engine(args.postgres)

    Base.metadata.create_all(bind=dst)

    with src.connect() as s, dst.begin() as d:
        for model in ORDERED_MODELS:
            table = model.__table__
            if table.name not in _existing_tables(s):
                print(f"- {table.name}: ausente na origem, pulando")
                continue
            dst_count = d.execute(select(func.count()).select_from(table)).scalar() or 0
            if dst_count > 0:
                print(f"- {table.name}: destino já tem {dst_count} linhas, pulando")
                continue
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            if rows:
                d.execute(insert(table), rows)
            print(f"- {table.name}: {len(rows)} linhas copiadas")

        # Ajusta as sequences do Postgres para os ids já copiados
        for model in ORDERED_MODELS:
            table = model.__table__
            if "id" in table.c:
                d.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table.name}), 0) + 1, false)"
                    )
                )

    print("Migração concluída.")
    return 0


def _existing_tables(conn) -> set[str]:
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
    return {r[0] for r in rows}


if __name__ == "__main__":
    raise SystemExit(main())
