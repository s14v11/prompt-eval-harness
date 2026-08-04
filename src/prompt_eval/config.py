"""Application settings, sourced from environment variables.

All secrets (API keys, credentials) must be supplied via environment
variables or an untracked `.env` file. Nothing sensitive is hardcoded.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application configuration.

    Attributes:
        app_name: Human-readable service name, used in logs and the API docs.
        environment: Deployment environment name (e.g. "development", "production").
        debug: Enables verbose logging and FastAPI debug mode.
        database_url: SQLAlchemy connection string for the primary datastore.
        redis_url: Connection string for the Redis instance backing Celery.
        celery_broker_url: Broker URL for Celery; defaults to `redis_url` if unset.
        celery_result_backend: Result backend URL for Celery; defaults to `redis_url`.
        openai_api_key: API key for OpenAI, used by the LLM client service.
        anthropic_api_key: API key for Anthropic Claude models.
        google_api_key: API key for Google Gemini models.
        cors_origins: Comma-separated list of allowed CORS origins for the frontend.
        default_judge_model: Model identifier used for LLM-as-judge evaluations.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "prompt-eval-harness"
    environment: str = "development"
    debug: bool = False

    database_url: str = "sqlite:///./prompt_eval.db"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    google_api_key: str | None = None

    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    default_judge_model: str = "gpt-4o-mini"

    @property
    def resolved_celery_broker_url(self) -> str:
        """Return the Celery broker URL, falling back to `redis_url`."""
        return self.celery_broker_url or self.redis_url

    @property
    def resolved_celery_result_backend(self) -> str:
        """Return the Celery result backend URL, falling back to `redis_url`."""
        return self.celery_result_backend or self.redis_url

    @property
    def cors_origin_list(self) -> list[str]:
        """Return `cors_origins` split into a list, trimming whitespace."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached `Settings` instance shared across the app."""
    return Settings()
