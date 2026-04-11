"""
app/core/config.py

Centralised application configuration via Pydantic BaseSettings.
All values are read from environment variables (or .env file).
The single `settings` singleton is imported everywhere else — never
read os.environ directly in the application code.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional, Dict

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

    # ── LLM Provider (Default / Global) ────────────────────────────────────
    LLM_BASE_URL: AnyHttpUrl = Field(
        default="http://localhost:11434/v1",
        description="Base URL for the primary LLM API."
    )
    LLM_API_KEY: str = Field(default="ollama")
    LLM_MODEL: str = Field(default="kimi-k2")
    LLM_TEMPERATURE: float = Field(default=0.0)
    LLM_MAX_TOKENS: int = Field(default=4096)
    LLM_REQUEST_TIMEOUT: int = Field(default=120)

    # ── Gemini (Generation Phase) ──────────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = Field(default=None)
    GEMINI_MODEL: str = Field(default="gemini-flash-latest")

    # ── Featherless / Mistral (Validation Phase) ───────────────────────────
    FEATHERLESS_API_KEY: Optional[str] = Field(default=None)
    FEATHERLESS_BASE_URL: AnyHttpUrl = Field(default="https://api.featherless.ai/v1")
    FEATHERLESS_MODEL: str = Field(default="mistralai/Mistral-7B-Instruct-v0.3")

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
