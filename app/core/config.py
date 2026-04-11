"""
app/core/config.py

Centralised application configuration via Pydantic BaseSettings.
All values are read from environment variables (or .env file).
The single `settings` singleton is imported everywhere else — never
read os.environ directly in the application code.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Master settings object.  Every attribute maps 1-to-1 to an env var
    (or a matching key in .env).  Pydantic validates types at startup,
    so a misconfigured deployment fails fast rather than silently.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",           # Silently ignore unknown env vars
    )

    # ── Application identity ───────────────────────────────────────────────
    APP_NAME: str = "Auto Tender Writer"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = Field(default=True)

    # ── API Settings ───────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    # Comma-separated list of allowed origins for CORS
    ALLOWED_ORIGINS: list[AnyHttpUrl] = Field(default=["http://localhost:3000"])

    # ── Security ───────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(
        default="CHANGE_ME_IN_PRODUCTION_USE_A_LONG_RANDOM_STRING",
        description="Used for signing JWTs and session tokens.",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8   # 8-hour working day default

    # ── Database ───────────────────────────────────────────────────────────
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./auto_tender_writer.db",
        description=(
            "Async SQLAlchemy DSN. "
            "Use 'postgresql+asyncpg://...' for production."
        ),
    )

    # ── Celery / Redis (Background Tasks) ─────────────────────────────────
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis broker URL for Celery task queue.",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/1",
        description="Redis backend for Celery result storage.",
    )

    # ── LLM Provider ──────────────────────────────────────────────────────
    LLM_BASE_URL: AnyHttpUrl = Field(
        default="http://localhost:11434/v1",   # Default: local Ollama OpenAI-compat endpoint
        description=(
            "Base URL for the OpenAI-compatible LLM API. "
            "Swap to https://api.openai.com/v1 for OpenAI."
        ),
    )
    LLM_API_KEY: str = Field(
        default="ollama",
        description="API key for the LLM provider.  'ollama' for local Ollama.",
    )
    LLM_MODEL: str = Field(
        default="kimi-k2",
        description="Model identifier passed to litellm / openai client.",
    )
    LLM_TEMPERATURE: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description=(
            "LLM temperature — keep at 0.0 for deterministic JSON extraction. "
            "Only raise for narrative generation tasks."
        ),
    )
    LLM_MAX_TOKENS: int = Field(
        default=4096,
        description="Hard cap on tokens the LLM may return per call.",
    )
    LLM_REQUEST_TIMEOUT: int = Field(
        default=120,
        description="Seconds before an LLM HTTP request times out.",
    )

    # ── LLM Provider Selection ─────────────────────────────────────────────
    LLM_PROVIDER: Literal["ollama", "openai", "gemini"] = Field(
        default="ollama",
        description=(
            "Which LLM backend to use. "
            "'ollama' → local Ollama via litellm. "
            "'openai' → OpenAI-compatible API via litellm. "
            "'gemini' → Google Gemini via google-genai SDK (uses GEMINI_API_KEY)."
        ),
    )

    # ── Gemini-specific settings ───────────────────────────────────────────
    GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API key. Required when LLM_PROVIDER='gemini'.",
    )
    GEMINI_MODEL: str = Field(
        default="gemini-2.0-flash",
        description="Gemini model name. e.g. gemini-2.0-flash, gemini-1.5-pro.",
    )

    # ── File Storage ──────────────────────────────────────────────────────
    DATA_DIR: Path = Field(
        default=Path("data"),
        description="Root directory for secure file vault (uploaded PDFs).",
    )

    @field_validator("DATA_DIR", mode="before")
    @classmethod
    def resolve_data_dir(cls, v: str | Path) -> Path:
        """Ensure DATA_DIR is always an absolute Path."""
        return Path(v).resolve()

    # ── Tender Evaluation Thresholds (Golden Business Rules) ──────────────
    # These are the deterministic guard-rails enforced by Python — the LLM
    # never reads or applies these numbers directly.
    LATE_SUBMISSION_TOLERANCE_SECONDS: int = Field(
        default=0,
        description="Extra grace window after deadline. 0 = zero tolerance.",
    )
    ABNORMALLY_LOW_PRICE_THRESHOLD_PCT: float = Field(
        default=15.0,
        ge=0.0,
        le=100.0,
        description=(
            "If a bid is more than this percentage below the average of all bids, "
            "Python flags it for committee review (Phase 4)."
        ),
    )
    CLOSE_TIE_THRESHOLD_PCT: float = Field(
        default=3.0,
        ge=0.0,
        le=100.0,
        description=(
            "If the combined scores of two offers differ by less than this %, "
            "Python flags them as a 'close tie' for committee attention (Phase 5)."
        ),
    )
    DEFAULT_TECHNICAL_WEIGHT: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Default weighting for the Technical score in the combined evaluation. "
            "Financial weight = 1 - this value."
        ),
    )

    # ── Email / Notifications ─────────────────────────────────────────────
    SMTP_HOST: str = Field(default="localhost")
    SMTP_PORT: int = Field(default=587)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    EMAIL_FROM: str = Field(default="noreply@autotenderwriter.local")

    # ── Derived helpers (not env vars) ────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def financial_weight(self) -> float:
        """Derived: Financial weight is the complement of the Technical weight."""
        return round(1.0 - self.DEFAULT_TECHNICAL_WEIGHT, 10)


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    Usage:
        from app.core.config import get_settings
        settings = get_settings()

    The @lru_cache decorator ensures the .env file is only parsed once,
    making this safe to call at module import time across the app.
    """
    return Settings()


# Module-level singleton — most modules should import this directly.
settings: Settings = get_settings()
