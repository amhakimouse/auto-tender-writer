"""
app/db/session.py

Async SQLAlchemy engine and session configuration.

The engine is created with:
    - echo=False (production-safe; enable DEBUG in dev via env var)
    - pool_pre_ping=True (verify connections before use, prevents stale handles)
    - future=True (SQLAlchemy 2.0 style throughout)

SessionLocal is the async session factory used by get_db() in dependencies.py.
"""

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# -----------------------------------------------------------------------------
# Async Engine Configuration
# -----------------------------------------------------------------------------
# pool_pre_ping=True: validates connections from the pool before using them.
# This prevents "InterfaceError: connection closed" after DB restarts.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL statements in DEBUG mode only
    future=True,
    pool_pre_ping=True,
)

# -----------------------------------------------------------------------------
# Async Session Factory
# -----------------------------------------------------------------------------
# expire_on_commit=False: keeps attributes accessible after commit()
# (needed for FastAPI response serialization after DB operations)
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,  # Explicit flush for performance/predictability
    autocommit=False,  # Explicit transaction boundaries
)


async def get_async_session():
    """
        Yield an async session (used by FastAPI Depends).

    n    This is a lower-level generator. In practice, use get_db() from
        app.api.dependencies which wraps this with error handling.
    """
    async with AsyncSessionLocal() as session:
        yield session
