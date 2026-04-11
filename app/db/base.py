"""
app/db/base.py

SQLAlchemy 2.0 declarative base with common timestamp columns.

This module defines the shared base class for all ORM models and provides
the standard set of audit columns inherited by every table.
"""

from datetime import datetime, timezone
from typing import Annotated

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    Declarative base for all SQLAlchemy models.

    Provides:
        - Consistent table naming convention (snake_case via tablename automation)
        - Common audit columns (created_at, updated_at) via TimestampMixin
    """

    pass


# Type annotations for common column patterns
IntPk = Annotated[int, mapped_column(primary_key=True)]
CreatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
]
UpdatedAt = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    ),
]


class TimestampMixin:
    """
    Mixin providing standard audit timestamps.

    All application tables should inherit from this to ensure:
        - created_at: immutable record of insertion time (server-side)
        - updated_at: automatically refreshed on every UPDATE
    """

    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]


def utc_now() -> datetime:
    """Return the current UTC datetime with timezone info."""
    return datetime.now(timezone.utc)
