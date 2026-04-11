"""
app/db/models/appeal.py

SQLAlchemy model for Appeal records.

An Appeal represents a formal grievance submitted by a bidder contesting
the evaluation results. Appeals must be submitted within a defined window
after the tender closes.

Key business rules enforced in Python:
    - Appeals only accepted within APPEAL_WINDOW_DAYS of tender closure
    - Each appeal is linked to a specific offer and tender
    - Status tracks the appeal through resolution workflow
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPk, TimestampMixin
from app.db.models.audit_log import JSONType


class AppealStatus(StrEnum):
    """Workflow states for an Appeal."""

    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class Appeal(Base, TimestampMixin):
    """Represents a formal appeal against an evaluation result."""

    __tablename__ = "appeals"

    id: Mapped[IntPk]
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[int] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    appellant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    appellant_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    file_hash_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Hex digest of SHA-256 over the uploaded appeal PDF",
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[AppealStatus] = mapped_column(
        String(30),
        nullable=False,
        default=AppealStatus.RECEIVED,
    )

    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Server-side UTC timestamp captured at upload time",
    )
    appeal_window_deadline: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Hard deadline after which appeals are not accepted",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    committee_decision: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Final decision: UPHELD or OVERRULED"
    )
    decision_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_counter_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_grievances_extracted: Mapped[dict | None] = mapped_column(
        JSONType, nullable=True
    )

    # Relationships
    tender: Mapped["Tender"] = relationship("Tender", back_populates="appeals")
    offer: Mapped["Offer"] = relationship("Offer", back_populates="appeals")

    def __repr__(self) -> str:
        return (
            f"<Appeal(id={self.id}, tender_id={self.tender_id}, "
            f"offer_id={self.offer_id}, status={self.status})>"
        )
