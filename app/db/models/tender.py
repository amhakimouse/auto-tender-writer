"""
app/db/models/tender.py

SQLAlchemy model for Tender records.

A Tender represents a procurement opportunity published by the organization.
Offers (submissions) are linked to a Tender via foreign key.

Key business rules enforced in Python:
    - deadline is the hard cutoff for Offer submissions (Milestone 1)
    - published status gates visibility to bidders
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPk, TimestampMixin


class TenderStatus(StrEnum):
    """
    Lifecycle states for a Tender.

    DRAFT     → Not visible to external bidders
    PUBLISHED → Open for submissions (respects deadline)
    CLOSED    → Deadline passed, no new submissions accepted
    CANCELLED → Procurement terminated (archival only)
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Tender(Base, TimestampMixin):
    """
    Represents a procurement tender opportunity.

    Attributes:
        id: Primary key (auto-increment)
        title: Human-readable title of the tender
        description: Full text of the tender requirements
        reference_number: Organization's internal tracking code
        status: Current lifecycle state (DRAFT, PUBLISHED, etc.)
        deadline: Hard cutoff datetime for submissions (UTC, enforced by Python)
        created_by: FK to the user who created the tender
    """

    __tablename__ = "tenders"

    id: Mapped[IntPk]
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    status: Mapped[TenderStatus] = mapped_column(
        String(20),
        nullable=False,
        default=TenderStatus.DRAFT,
    )
    deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="UTC deadline after which submissions are rejected",
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    offers: Mapped[list["Offer"]] = relationship(
        "Offer",
        back_populates="tender",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    created_by_user: Mapped["User | None"] = relationship(
        "User",
        back_populates="tenders",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Tender(id={self.id}, ref={self.reference_number}, status={self.status})>"
        )
