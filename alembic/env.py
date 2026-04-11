"""
alembic/env.py

Alembic migration environment — configured for async SQLAlchemy 2.0.

Key behaviour:
  - Reads DATABASE_URL from the environment variable (set by Docker Compose).
  - Falls back to the sqlalchemy.url in alembic.ini for local tooling.
  - Uses run_async_migrations() so it works with asyncpg and aiosqlite drivers.
  - In Milestone 1, import all SQLAlchemy models here so Alembic can
    auto-generate migration scripts with `alembic revision --autogenerate`.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic Config object (gives access to alembic.ini values) ───────────────
config = context.config

# ── Logging setup from alembic.ini ───────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Override sqlalchemy.url from environment variable ────────────────────────
# Docker Compose sets DATABASE_URL; this takes priority over alembic.ini.
database_url = os.getenv("DATABASE_URL")
if database_url:
    # asyncpg uses "postgresql+asyncpg://..." but Alembic's sync runner needs
    # "postgresql+psycopg2://...". We convert only when running offline migrations.
    config.set_main_option("sqlalchemy.url", database_url)

# ── Import your SQLAlchemy models here so Alembic sees them ──────────────────
# TODO (Milestone 1): Uncomment after db/models.py is implemented:
# from app.db.base import Base          # noqa: F401 — imports all models
# target_metadata = Base.metadata
target_metadata = None   # Stub — replace in Milestone 1


# ── Offline migrations (generates SQL without a live DB connection) ───────────
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online async migrations (runs against the live DB) ───────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations within it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,   # No connection pooling for migration runs
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
