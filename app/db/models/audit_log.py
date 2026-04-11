"""
app/db/models/audit_log.py

SQLAlchemy model for the immutable AuditLog table.

The Golden Rule: This table is APPEND-ONLY.
    - Rows are INSERTED never UPDATED or DELETED.
    - Every state change in the system MUST be recorded here.
    - The actor field identifies WHO caused the change (SYSTEM, LLM, or user).

This table serves as the forensic backbone of the application, providing
a complete, tamper-evident history of every significant event.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base, IntPk


# Use JSONB on PostgreSQL, TEXT (JSON string) on SQLite
class JSONType(TypeDecorator):
    """Platform-agnostic JSON column type."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(Text)


class AuditLog(Base):
    """
    Immutable audit trail record.

    Attributes:
        id: Primary key (auto-increment, never reused)
        timestamp: UTC datetime when the event occurred (microsecond precision)
        actor: Identity responsible for the action:
               - "SYSTEM": automated deterministic checks
               - "LLM": AI-generated outputs (scores, extractions)
               - "user:{id}": human committee member action
        action_type: Controlled vocabulary from ActionType enum
        offer_id: Optional FK to the Offer affected (if applicable)
        old_state: Previous value/status (for diff tracking)
        new_state: New value/status after the change
        context: Arbitrary JSON metadata (reasons, flags, etc.)

    Indexes:
        - ix_audit_log_timestamp: Time-series queries
        - ix_audit_log_offer_id: Per-offer history lookup
        - ix_audit_log_action_type: Filter by event type
    """

    __tablename__ = "audit_logs"

    id: Mapped[IntPk]
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="UTC timestamp when event was recorded (immutable)",
    )
    actor: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment='"SYSTEM", "LLM", or user identifier',
    )
    action_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
        comment="Controlled vocabulary (see ActionType)",
    )
    offer_id: Mapped[int | None] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Affected offer (null for global/system events)",
    )
    old_state: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Previous state/value before change",
    )
    new_state: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="New state/value after change",
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(
        JSONType,
        nullable=True,
        comment="Arbitrary JSON metadata for the event",
    )

    # Relationships
    offer: Mapped["Offer | None"] = relationship("Offer", back_populates="audit_logs")

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action_type}, "
            f"actor={self.actor}, offer_id={self.offer_id})>"
        )


# Additional composite indexes for common query patterns
Index(
    "ix_audit_log_timestamp",
    AuditLog.timestamp.desc(),
)
Index(
    "ix_audit_log_actor_action",
    AuditLog.actor,
    AuditLog.action_type,
)
