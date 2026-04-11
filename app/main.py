"""
app/main.py

FastAPI application factory and top-level wiring.

Responsibilities (Python as Enforcer):
  - Create and configure the FastAPI instance.
  - Register all v1 API routers with correct prefixes.
  - Mount CORS middleware.
  - Expose a /health liveness probe (used by load-balancers and CI checks).
  - Run startup / shutdown lifecycle hooks (e.g., DB connection pools).

The LLM layer is NOT initialised here — each service that needs it
instantiates it lazily via app/llm/client.py.
"""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import settings
from app.db.init_db import close_db, init_db

# ── Router imports (will be populated in Milestone 1+) ────────────────────────
# We import them now so the module graph is wired; the routers themselves
# only contain stub responses until the respective Milestones are implemented.
from app.api.v1 import router as api_v1_router


# ── Lifespan context manager ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles application startup and shutdown events.

    Startup:
      - Log environment configuration.
      - (Milestone 1) Initialise async DB engine / create tables for dev.

    Shutdown:
      - Gracefully close DB connection pools.
    """
    # ── STARTUP ──────────────────────────────────────────────────────────
    logger.info(
        "🚀  Starting {name} v{version} [{env}]",
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENVIRONMENT,
    )
    logger.info("📂  File vault root: {dir}", dir=settings.DATA_DIR)
    logger.info("🤖  LLM endpoint   : {url}", url=settings.LLM_BASE_URL)
    logger.info("🗃️   Database DSN   : {dsn}", dsn=settings.DATABASE_URL)

    # Ensure the secure file vault directory exists at startup.
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize database tables (development mode)
    # In production, use Alembic migrations instead
    await init_db()
    logger.info("🗃️   Database tables initialized")

    yield  # ← Application runs here

    # ── SHUTDOWN ─────────────────────────────────────────────────────────
    await close_db()
    logger.info("🔻  Shutting down {name}", name=settings.APP_NAME)


# ── Application factory ───────────────────────────────────────────────────────
def create_app() -> FastAPI:
    """
    Construct and return the configured FastAPI application.

    Separating creation into a factory makes it easy to instantiate
    the app with test-specific overrides (e.g., in-memory SQLite).
    """
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Automated, auditable Tender Evaluation Pipeline.\n\n"
            "**Architecture:**\n"
            "- **Python (FastAPI)** — The Enforcer: deterministic routing, "
            "math, threshold checks, and audit logging.\n"
            "- **LLM** — The Reasoner: unstructured text extraction and "
            "narrative generation only. Always constrained by Pydantic schemas.\n"
            "- **Human Committee** — The Decider: overrides, final sign-off."
        ),
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=f"{settings.API_V1_PREFIX}/docs",
        redoc_url=f"{settings.API_V1_PREFIX}/redoc",
        lifespan=lifespan,
        debug=settings.DEBUG,
    )

    # ── CORS ─────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.ALLOWED_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────
    # All application routes live under /api/v1/ for explicit versioning.
    application.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)

    return application


# ── Module-level app instance (used by uvicorn) ───────────────────────────────
app: FastAPI = create_app()


# ── Root health-check ─────────────────────────────────────────────────────────
@app.get(
    "/health",
    tags=["System"],
    summary="Liveness probe",
    response_description="Service is alive and ready.",
)
async def health_check() -> JSONResponse:
    """
    Lightweight liveness probe.

    Returns HTTP 200 with a JSON payload confirming the service is up,
    the current version, and the active environment.  Used by:
      - Docker / Kubernetes readiness probes.
      - CI pipelines to verify deployment success.
      - Load-balancer health monitoring.
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "timestamp": time.time(),
        },
    )
