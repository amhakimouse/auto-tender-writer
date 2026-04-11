"""
app/db/init_db.py

Database initialization utilities.

Provides functions to create all tables on startup (development mode)
and to run migrations in production.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import (  # noqa: F401 - imports register models with Base.metadata
    AuditLog,
    Offer,
    Tender,
    User,
)
from app.db.session import engine


async def init_db() -> None:
    """
        Create all database tables based on SQLAlchemy models.

    n    WARNING: This uses create_all() which is NOT suitable for production.
        In production, use Alembic migrations instead.

        This is safe for development with SQLite as it only creates missing tables.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the database engine (cleanup on shutdown)."""
    await engine.dispose()
