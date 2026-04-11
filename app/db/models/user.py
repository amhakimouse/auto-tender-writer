"""
app/db/models/user.py

SQLAlchemy model for User accounts.

Basic user model to support:
    - Audit trail attribution (who created tenders, made decisions)
    - Future authentication/authorization (Milestone 4)

This is a minimal implementation for Milestone 1; full auth will be added later.
"""

from enum import StrEnum

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPk, TimestampMixin


class UserRole(StrEnum):
    """Role-based access control levels."""

    ADMIN = "ADMIN"
    COMMITTEE_CHAIR = "COMMITTEE_CHAIR"
    COMMITTEE_MEMBER = "COMMITTEE_MEMBER"
    REVIEWER = "REVIEWER"
    READONLY = "READONLY"


class User(Base, TimestampMixin):
    """
    Represents a system user (committee member, admin, etc.).

    Attributes:
        id: Primary key
        email: Unique email address (used for login)
        name: Full name for display and audit logs
        role: Access level determining permissions
        is_active: Soft-delete flag (disabled users cannot log in)
        hashed_password: For future authentication (Milestone 4)
    """

    __tablename__ = "users"

    id: Mapped[IntPk]
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(30), nullable=False, default=UserRole.READONLY
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    hashed_password: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="For future authentication"
    )

    # Relationships
    tenders: Mapped[list["Tender"]] = relationship(
        "Tender",
        back_populates="created_by_user",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
