from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, documentation, templates
from app.database import Base, SessionLocal, engine
from app.models import documentation_record, template, user  # noqa: F401
from app.services.seed import run_seed


def _bootstrap_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()


_bootstrap_db()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield


app = FastAPI(title="AutoDoc API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(templates.router, prefix="/api")
app.include_router(documentation.router, prefix="/api")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
