from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _BACKEND_ROOT / "data" / "autodoc.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = f"sqlite:///{_DEFAULT_DB.as_posix()}"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Provider de IA usado pelos agentes (core/llm.py): "openai" ou "anthropic"
    llm_provider: str = "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Vazio = modo fallback: jobs rodam in-process e eventos ficam em memória.
    # Preenchido (ex.: redis://localhost:6379/0) = fila arq + pub/sub via Redis.
    redis_url: str = ""

    # Orçamento por run de agente
    agent_max_output_tokens: int = 8_000
    agent_timeout_seconds: float = 600.0

    # Execução dos testes gerados pelo agente gerador_testes:
    #   none   (padrão) — gera e valida a sintaxe, mas NÃO executa;
    #   docker — container efêmero sem rede (requer acesso ao daemon Docker);
    #   local  — subprocess local com timeout; só em máquina de dev, para
    #            código de sua confiança.
    testgen_execution: Literal["none", "docker", "local"] = "none"

    github_token: str = ""


settings = Settings()
