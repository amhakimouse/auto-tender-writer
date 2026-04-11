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
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from loguru import logger


class ActionType(StrEnum):
    """Controlled vocabulary for audit event types."""
    # Phase 1
    OFFER_RECEIVED          = "OFFER_RECEIVED"
    OFFER_REJECTED_LATE     = "OFFER_REJECTED_LATE"
    FILE_HASH_COMPUTED      = "FILE_HASH_COMPUTED"
    # Phase 2
    COMPLIANCE_CHECKED      = "COMPLIANCE_CHECKED"
    OFFER_DISQUALIFIED      = "OFFER_DISQUALIFIED"
    # Phase 3
    TECHNICAL_SCORED        = "TECHNICAL_SCORED"
    SCORE_BOUNDS_VIOLATED   = "SCORE_BOUNDS_VIOLATED"
    # Phase 4
    FINANCIAL_EXTRACTED     = "FINANCIAL_EXTRACTED"
    ABNORMAL_PRICE_FLAGGED  = "ABNORMAL_PRICE_FLAGGED"
    # Phase 5
    COMBINED_SCORE_COMPUTED = "COMBINED_SCORE_COMPUTED"
    CLOSE_TIE_FLAGGED       = "CLOSE_TIE_FLAGGED"
    # Phase 6
    SCORE_OVERRIDDEN        = "SCORE_OVERRIDDEN"
    # Phase 7
    OFFER_AWARDED           = "OFFER_AWARDED"
    OFFER_REJECTED_FINAL    = "OFFER_REJECTED_FINAL"
    NOTIFICATION_SENT       = "NOTIFICATION_SENT"
    # Phase 8
    APPEAL_RECEIVED         = "APPEAL_RECEIVED"
    APPEAL_RESPONSE_DRAFTED = "APPEAL_RESPONSE_DRAFTED"


def log_event(
    action: ActionType,
    actor: str,
    *,
    offer_id: int | None = None,
    old_state: Any = None,
    new_state: Any = None,
    context: dict | None = None,
) -> None:
    """
    Record an audit event.

    In Milestone 1 this writes to the logger (stdout/file).
    In Milestone 1+ it will additionally INSERT a row into the AuditLog
    table via the async DB session passed by the caller.

    Args:
        action:    A member of ActionType — the type of event.
        actor:     "SYSTEM", "LLM", or a human user ID string.
        offer_id:  FK to the Offer being affected (if applicable).
        old_state: The previous value / status (for diff tracking).
        new_state: The new value / status after the action.
        context:   Arbitrary extra metadata dict (flagging reasons, etc.).
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Structured log entry — picked up by loguru / log aggregators.
    logger.info(
        "[AUDIT] ts={ts} | actor={actor} | action={action} | "
        "offer={offer_id} | {old} → {new} | ctx={ctx}",
        ts=timestamp,
        actor=actor,
        action=action,
        offer_id=offer_id,
        old=old_state,
        new=new_state,
        ctx=context or {},
    )

    # TODO (Milestone 1): Also INSERT into AuditLog DB table.
    # async with db_session.begin():
    #     db_session.add(AuditLog(
    #         timestamp=datetime.now(timezone.utc),
    #         actor=actor,
    #         action_type=action,
    #         offer_id=offer_id,
    #         old_state=str(old_state) if old_state is not None else None,
    #         new_state=str(new_state) if new_state is not None else None,
    #         context=json.dumps(context or {}),
    #     ))
