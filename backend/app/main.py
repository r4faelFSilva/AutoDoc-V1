from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import app.agents  # noqa: F401 — registra os agentes no registry
from app.api.routers import auth, documentation, runs, templates
from app.config import check_security, settings
from app.database import Base, SessionLocal, engine
from app.models import agent_run, documentation_record, project, template, user  # noqa: F401
from app.jobs.tasks import fail_orphan_runs
from app.services.seed import run_seed


def _bootstrap_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()


check_security(settings)
_bootstrap_db()
if not settings.redis_url:
    # Sem Redis os runs executam dentro da API: os que ficaram queued/running
    # morreram com o processo anterior.
    fail_orphan_runs()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="AutoDoc API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(documentation.router, prefix="/api")
app.include_router(runs.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
