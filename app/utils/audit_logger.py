"""
app/utils/audit_logger.py

Immutable Audit Trail — the forensic backbone of the Auto Tender Writer.

Golden Rule: EVERY state change in the system must pass through this module.
No service.py file may update offer status or scores without first calling
log_event() here.

Design constraints:
  - Append-only: rows are NEVER updated or deleted.
  - All writes are synchronous within the DB transaction of the caller
    (no fire-and-forget) so the audit record always commits with the change.
  - Actor labels: use "SYSTEM" for automated actions, "LLM" for LLM-sourced
    events, and the human user ID for committee actions.

Usage:
    from app.utils.audit_logger import log_event, ActionType
    await log_event(
        db_session,
        action=ActionType.OFFER_RECEIVED,
        actor="SYSTEM",
        offer_id=offer.id,
        new_state="RECEIVED",
        context={"file_hash": offer.file_hash_sha256},
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog


class ActionType(StrEnum):
    """Controlled vocabulary for audit event types."""

    # Phase 0 - Tender Management
    TENDER_CREATED = "TENDER_CREATED"
    TENDER_PUBLISHED = "TENDER_PUBLISHED"
    TENDER_CLOSED = "TENDER_CLOSED"
    TENDER_CANCELLED = "TENDER_CANCELLED"
    # Phase 1
    OFFER_RECEIVED = "OFFER_RECEIVED"
    OFFER_REJECTED_LATE = "OFFER_REJECTED_LATE"
    OFFER_REJECTED_NOT_PUBLISHED = "OFFER_REJECTED_NOT_PUBLISHED"
    OFFER_REJECTED_DUPLICATE_HASH = "OFFER_REJECTED_DUPLICATE_HASH"
    FILE_HASH_COMPUTED = "FILE_HASH_COMPUTED"
    # Phase 2
    COMPLIANCE_CHECKED = "COMPLIANCE_CHECKED"
    OFFER_DISQUALIFIED = "OFFER_DISQUALIFIED"
    COMPLIANCE_EXTRACTION_FAILED = "COMPLIANCE_EXTRACTION_FAILED"
    # Phase 3
    TECHNICAL_SCORING_STARTED = "TECHNICAL_SCORING_STARTED"
    TECHNICAL_SCORED = "TECHNICAL_SCORED"
    SCORE_BOUNDS_VIOLATED = "SCORE_BOUNDS_VIOLATED"
    # Phase 4
    FINANCIAL_EXTRACTED = "FINANCIAL_EXTRACTED"
    ABNORMAL_PRICE_FLAGGED = "ABNORMAL_PRICE_FLAGGED"
    # Phase 5
    COMBINED_SCORE_COMPUTED = "COMBINED_SCORE_COMPUTED"
    CLOSE_TIE_FLAGGED = "CLOSE_TIE_FLAGGED"
    # Phase 6
    SCORE_OVERRIDDEN = "SCORE_OVERRIDDEN"
    # Phase 7
    OFFER_AWARDED = "OFFER_AWARDED"
    OFFER_REJECTED_FINAL = "OFFER_REJECTED_FINAL"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    # Phase 8
    APPEAL_RECEIVED = "APPEAL_RECEIVED"
    APPEAL_RESPONSE_DRAFTED = "APPEAL_RESPONSE_DRAFTED"


async def log_event(
    db_session: AsyncSession,
    action: ActionType,
    actor: str,
    *,
    offer_id: int | None = None,
    old_state: Any = None,
    new_state: Any = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Record an immutable audit event to the database.

    This function:
        1. Creates an AuditLog ORM object
        2. Adds it to the current transaction
        3. Logs to structured stdout (for log aggregation)

    IMPORTANT: This does NOT commit the transaction. The caller must commit
    the db_session for the audit record to persist. This ensures audit logs
    are atomic with the business logic they record.

    Args:
        db_session: The async SQLAlchemy session (part of caller's transaction)
        action: A member of ActionType — the type of event
        actor: "SYSTEM", "LLM", or a human user ID string
        offer_id: FK to the Offer being affected (if applicable)
        old_state: The previous value / status (for diff tracking)
        new_state: The new value / status after the action
        context: Arbitrary extra metadata dict (flagging reasons, file hashes, etc.)

    Returns:
        The created AuditLog instance (added to session but not yet committed)
    """
    timestamp = datetime.now(timezone.utc)

    # Prepare context JSON (PostgreSQL will store as JSONB, SQLite as TEXT)
    context_json = context if context else None

    # Create the audit log record
    audit_record = AuditLog(
        timestamp=timestamp,
        actor=actor,
        action_type=action.value,
        offer_id=offer_id,
        old_state=str(old_state) if old_state is not None else None,
        new_state=str(new_state) if new_state is not None else None,
        context=context_json,
    )

    # Add to the current transaction
    db_session.add(audit_record)

    # Also emit to structured logging for real-time observability
    logger.info(
        "[AUDIT] ts={ts} | actor={actor} | action={action} | "
        "offer={offer_id} | {old} → {new} | ctx={ctx}",
        ts=timestamp.isoformat(),
        actor=actor,
        action=action,
        offer_id=offer_id,
        old=old_state,
        new=new_state,
        ctx=context or {},
    )

    return audit_record


async def log_system_event(
    db_session: AsyncSession,
    action: ActionType,
    *,
    offer_id: int | None = None,
    old_state: Any = None,
    new_state: Any = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """
    Convenience wrapper for logging automated system events.

    Automatically sets actor="SYSTEM" for deterministic Python-enforced actions.
    """
    return await log_event(
        db_session=db_session,
        action=action,
        actor="SYSTEM",
        offer_id=offer_id,
        old_state=old_state,
        new_state=new_state,
        context=context,
    )
