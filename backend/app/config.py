from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB = _BACKEND_ROOT / "data" / "autodoc.db"

DEFAULT_JWT_SECRET = "change-me-in-production"
# Valores de exemplo publicados no repositório: nunca valem como segredo real.
_PLACEHOLDER_JWT_SECRETS = frozenset({
    DEFAULT_JWT_SECRET,
    "change-me-in-production-use-long-random-string",
})
MIN_JWT_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # "production" (padrão) exige configuração segura; "development" relaxa as
    # checagens de inicialização para uso local.
    app_env: Literal["development", "production"] = "production"

    database_url: str = f"sqlite:///{_DEFAULT_DB.as_posix()}"
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    # Origens aceitas pelo CORS, separadas por vírgula.
    cors_origins: str = "http://localhost:4200"

    # Cadastro público pela rota /api/auth/register. Desligado, contas são
    # criadas com: python -m app.scripts.create_user --email ...
    allow_registration: bool = False

    # Usuário demo (demo@autodoc.dev). Sem DEMO_PASSWORD, uma senha aleatória é
    # gerada e exibida uma única vez no log da inicialização.
    seed_demo_user: bool = False
    demo_password: str = ""

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Provider de IA usado em TODA a aplicação (core/llm.py): geração clássica,
    # avaliação de commit, template a partir de exemplo e agentes.
    #   "openai" | "anthropic" | "openai_compatible"
    llm_provider: Literal["openai", "anthropic", "openai_compatible"] = "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"

    # Qualquer API compatível com a Chat Completions da OpenAI (Groq, Gemini,
    # OpenRouter, Ollama, LM Studio, vLLM...). Usado com LLM_PROVIDER=openai_compatible.
    openai_compatible_base_url: str = ""
    # Opcional: servidores locais (Ollama, LM Studio) não exigem chave.
    openai_compatible_api_key: str = ""
    openai_compatible_model: str = ""
    # true = envia response_format={"type": "json_object"}. Nem todo provedor/modelo
    # aceita; com false, o formato JSON é pedido no prompt e a resposta é extraída
    # de forma tolerante (funciona em qualquer provedor).
    openai_compatible_json_mode: bool = False

    @field_validator("llm_provider", mode="before")
    @classmethod
    def _normalize_llm_provider(cls, v: object) -> object:
        # Aceita "OpenAI", " anthropic ", "openai-compatible" etc.
        if isinstance(v, str):
            return v.strip().lower().replace("-", "_") or "openai"
        return v

    # Vazio = modo fallback: jobs rodam in-process e eventos ficam em memória.
    # Preenchido (ex.: redis://localhost:6379/0) = fila arq + pub/sub via Redis.
    redis_url: str = ""

    # Orçamento por run de agente
    agent_max_output_tokens: int = 8_000

    # Limite de tempo TOTAL de um run (todas as etapas do grafo). Ao estourar, o
    # run é interrompido e marcado como falha com mensagem clara.
    #   AGENT_RUN_TIMEOUT_SECONDS:      documentador no modo quick
    #   AGENT_RUN_TIMEOUT_DEEP_SECONDS: documentador no modo deep, arquiteto e gerador de testes
    agent_run_timeout_seconds: float = 300.0
    agent_run_timeout_deep_seconds: float = 900.0

    # Cada chamada à IA (OpenAI/Anthropic): tempo máximo por tentativa e número
    # de novas tentativas automáticas do SDK.
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 1

    # Download de repositórios do GitHub: tempo total e tamanho máximo do
    # arquivo compactado (a extração aceita até 4x esse tamanho).
    github_download_timeout_seconds: float = 60.0
    github_max_download_mb: int = 50

    # Execução dos testes gerados pelo agente gerador_testes:
    #   none   (padrão) — gera e valida a sintaxe, mas NÃO executa;
    #   docker — container efêmero sem rede (requer acesso ao daemon Docker);
    #   local  — subprocess local com timeout; só em máquina de dev, para
    #            código de sua confiança.
    testgen_execution: Literal["none", "docker", "local"] = "none"

    # Token do GitHub do servidor. Só é usado em nome dos usuários com
    # ALLOW_SERVER_GITHUB_TOKEN=true; caso contrário, o download de repositórios
    # usa apenas o token enviado pelo próprio usuário (ou nenhum, para repos públicos).
    github_token: str = ""
    allow_server_github_token: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


class InsecureConfigError(RuntimeError):
    pass


def check_security(cfg: Settings) -> None:
    """Recusa configurações inseguras fora de APP_ENV=development."""
    if cfg.app_env == "development":
        return
    if cfg.jwt_secret in _PLACEHOLDER_JWT_SECRETS:
        raise InsecureConfigError(
            "JWT_SECRET está com o valor padrão de exemplo. Defina um segredo aleatório "
            f"com pelo menos {MIN_JWT_SECRET_LENGTH} caracteres (ex.: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))") '
            "ou use APP_ENV=development para desenvolvimento local."
        )
    if len(cfg.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise InsecureConfigError(
            f"JWT_SECRET tem {len(cfg.jwt_secret)} caracteres; o mínimo fora de "
            f"desenvolvimento é {MIN_JWT_SECRET_LENGTH}."
        )


settings = Settings()
