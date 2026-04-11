"""
app/db/models/offer.py

SQLAlchemy model for Offer (Bid/Submission) records.

An Offer represents a bidder's response to a Tender. The Enforcer (Python)
guarantees immutability of the submitted file via SHA-256 hash and strict
deadline enforcement.

Immutable fields (set once at creation):
    - tender_id (which tender this responds to)
    - file_hash_sha256 (cryptographic proof of file integrity)
    - submitted_at (server-side timestamp at intake)
    - original_filename (name provided by uploader, for reference only)

Mutable fields (updated during evaluation workflow):
    - status (RECEIVED → COMPLIANT/INCOMPLIANT → SCORED → AWARDED/REJECTED)
    - compliance_passed, technical_score, financial_score, total_score
    - storage_path (filesystem location, may be archived/moved)
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IntPk, TimestampMixin


class OfferStatus(StrEnum):
    """
        Workflow states for an Offer.

        RECEIVED          → Initial state, file hash computed, pending compliance
        REJECTED_LATE     → Dead-letter: arrived after tender.deadline
        COMPLIANCE_PENDING→ Awaiting administrative checklist validation
        COMPLIANT         → Passed Phase 2 checks, eligible for scoring
        INCOMPLIANT       → Failed mandatory requirements, disqualified
        TECHNICAL_SCORING → Phase 3 in progress
        TECHNICAL_SCORED  → Phase 3 complete
        FINANCIAL_EXTRACTED→ Phase 4 complete (price extracted)
        COMBINED_SCORED   → Phase 5 complete (weighted total computed)
        COMMITTEE_REVIEW  → Phase 6 (close ties or anomalies flagged)
        AWARDED           → Phase 7 complete, winner selected
        REJECTED_FINAL    → Phase 7 complete, not selected
        APPEALED          → Phase 8 (bidder contesting result)
    """

    RECEIVED = "RECEIVED"
    REJECTED_LATE = "REJECTED_LATE"
    COMPLIANCE_PENDING = "COMPLIANCE_PENDING"
    COMPLIANT = "COMPLIANT"
    INCOMPLIANT = "INCOMPLIANT"
    TECHNICAL_SCORING = "TECHNICAL_SCORING"
    TECHNICAL_SCORED = "TECHNICAL_SCORED"
    FINANCIAL_EXTRACTED = "FINANCIAL_EXTRACTED"
    COMBINED_SCORED = "COMBINED_SCORED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    AWARDED = "AWARDED"
    REJECTED_FINAL = "REJECTED_FINAL"
    APPEALED = "APPEALED"


class Offer(Base, TimestampMixin):
    """
        Represents a single bid/submission received from a vendor.

        Attributes:
            id: Primary key
            tender_id: FK to the Tender this is a response to
            bidder_name: Name of the submitting organization
            bidder_email: Contact email for this submission
            file_hash_sha256: SHA-256 hex digest of the uploaded PDF (immutable proof)
            submitted_at: Server-side UTC timestamp when received (immutable)
            original_filename: Client-provided filename (reference only)
            storage_path: Absolute path to stored file in secure vault
            status: Current workflow state (see OfferStatus)
            compliance_passed: Result of Phase 2 administrative check
            technical_score: Phase 3 score (0-100, None if not yet scored)
            financial_score: Phase 4 normalized score (0-100, None if not yet extracted)
            total_score: Phase 5 weighted combination (None if incomplete)
    """

    __tablename__ = "offers"

    # --- Identity & Linkage ---
    id: Mapped[IntPk]
    tender_id: Mapped[int] = mapped_column(
        ForeignKey("tenders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bidder_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bidder_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- File Integrity (Immutable) ---
    file_hash_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="Hex digest of SHA-256 over the uploaded file bytes",
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Server-side UTC timestamp captured at upload time",
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Absolute path in secure file vault",
    )

    # --- Workflow State ---
    status: Mapped[OfferStatus] = mapped_column(
        String(30),
        nullable=False,
        default=OfferStatus.RECEIVED,
    )

    # --- Evaluation Results (populated in subsequent phases) ---
    compliance_passed: Mapped[bool | None] = mapped_column(
        nullable=True,
        comment="Phase 2: administrative compliance check result",
    )
    technical_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Phase 3: technical evaluation score (0-100)",
    )
    financial_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Phase 4: normalized financial score (0-100)",
    )
    total_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2),
        nullable=True,
        comment="Phase 5: weighted combined score",
    )

    # --- Disqualification / Flags ---
    disqualification_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Human-readable reason if disqualified"
    )
    committee_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Phase 6: notes from manual review"
    )

    # Relationships
    tender: Mapped["Tender"] = relationship("Tender", back_populates="offers")
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="offer",
        lazy="selectin",
    )
    appeals: Mapped[list["Appeal"]] = relationship(
        "Appeal",
        back_populates="offer",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"<Offer(id={self.id}, tender_id={self.tender_id}, "
            f"status={self.status}, hash={self.file_hash_sha256[:16]}...)>"
        )
