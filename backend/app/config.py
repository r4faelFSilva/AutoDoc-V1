from pathlib import Path

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

    # Execução de testes gerados SEM Docker (subprocess local com timeout).
    # Padrão False: sem Docker e sem este opt-in, o agente gera e valida a
    # sintaxe dos testes, mas não os executa. Ligue apenas em máquina de dev,
    # para código de sua confiança.
    allow_local_test_execution: bool = False

    github_token: str = ""


settings = Settings()
