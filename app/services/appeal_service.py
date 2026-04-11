"""
app/services/appeal_service.py

The Appeal Service — Python (The Enforcer) + LLM (The Reasoner).

This module orchestrates Phase 8: Appeals Handling.
    - Python enforces the appeal window (strict deadline check)
    - Python computes file hashes for immutability proof
    - LLM extracts grievances from the appeal PDF
    - LLM drafts counter-explanations using original audit trail
    - Python logs everything to the immutable audit trail

Architecture Rules:
    1. Python NEVER accepts appeals outside the defined window.
    2. All LLM calls return strictly constrained JSON (Pydantic validated).
    3. All state changes are atomic with their audit logs.
    4. Committee retains final authority (human-in-the-loop).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Appeal, AppealStatus, AuditLog, Offer, OfferStatus, Tender
from app.db.models.tender import TenderStatus
from app.llm.client import call_llm
from app.schemas.appeal_schemas import (
    AppealCounterExplanation,
    AppealGrievanceExtraction,
    create_empty_counter_explanation,
    create_empty_grievance_extraction,
)
from app.utils.audit_logger import ActionType, log_event
from app.utils.file_parser import extract_text_from_pdf

# =============================================================================
# Configuration
# =============================================================================

APPEAL_WINDOW_DAYS: int = 14  # Appeals accepted within 14 days of tender close


# =============================================================================
# Phase 8: Appeal Submission (Python The Enforcer)
# =============================================================================


class AppealSubmissionResult:
    """Result container for appeal submission."""

    def __init__(
        self,
        success: bool,
        appeal: Appeal | None,
        message: str,
        error_code: str | None = None,
    ):
        self.success = success
        self.appeal = appeal
        self.message = message
        self.error_code = error_code


async def submit_appeal(
    db: AsyncSession,
    tender_id: int,
    offer_id: int,
    appellant_name: str,
    appellant_email: str | None,
    pdf_bytes: bytes,
    original_filename: str,
    storage_path: str,
) -> AppealSubmissionResult:
    """
    Submit a new appeal against an offer.

    ## The Enforcer's Rules:

    1. **Tender Status Check**: Tender must be CLOSED to accept appeals.
    2. **Appeal Window**: Current time must be within APPEAL_WINDOW_DAYS of tender closure.
    3. **Offer Eligibility**: Offer must be REJECTED_FINAL or AWARDED (final states).
    4. **Immutability**: SHA-256 hash computed and stored for evidence.
    5. **Audit Trail**: Every submission logged atomically.
    """
    logger.info(
        "Processing appeal submission for offer {offer_id} (tender {tender_id})",
        offer_id=offer_id,
        tender_id=tender_id,
    )

    # --- Step 1: Fetch Tender and Offer ---
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        return AppealSubmissionResult(
            success=False,
            appeal=None,
            message=f"Tender {tender_id} not found.",
            error_code="TENDER_NOT_FOUND",
        )

    offer_result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = offer_result.scalar_one_or_none()

    if offer is None:
        return AppealSubmissionResult(
            success=False,
            appeal=None,
            message=f"Offer {offer_id} not found.",
            error_code="OFFER_NOT_FOUND",
        )

    # --- Step 2: Validate Tender Status ---
    if tender.status != TenderStatus.CLOSED:
        return AppealSubmissionResult(
            success=False,
            appeal=None,
            message=(
                f"Appeals only accepted for CLOSED tenders. "
                f"Current status: {tender.status}"
            ),
            error_code="TENDER_NOT_CLOSED",
        )

    # --- Step 3: Validate Offer Status ---
    if offer.status not in (OfferStatus.REJECTED_FINAL, OfferStatus.AWARDED):
        return AppealSubmissionResult(
            success=False,
            appeal=None,
            message=(
                f"Appeals only accepted for final-status offers "
                f"(AWARDED or REJECTED_FINAL). Current status: {offer.status}"
            ),
            error_code="OFFER_NOT_FINAL",
        )

    # --- Step 4: Validate Appeal Window (Python Enforced) ---
    # Use tender's updated_at as proxy for closure time, or check audit logs
    # For now, use a configurable offset from tender deadline
    now = datetime.now(timezone.utc)
    tender_deadline = tender.deadline
    appeal_window_deadline = tender_deadline + timedelta(days=APPEAL_WINDOW_DAYS)

    if now > appeal_window_deadline:
        # STRICT FORBIDDEN - Outside appeal window
        await log_event(
            db_session=db,
            action=ActionType.APPEAL_REJECTED,
            actor="SYSTEM",
            offer_id=offer_id,
            new_state="APPEAL_REJECTED_WINDOW_EXPIRED",
            context={
                "tender_id": tender_id,
                "submitted_at": now.isoformat(),
                "window_deadline": appeal_window_deadline.isoformat(),
                "days_late": (now - appeal_window_deadline).days,
            },
        )
        await db.commit()

        return AppealSubmissionResult(
            success=False,
            appeal=None,
            message=(
                f"Appeal window has expired. Deadline was "
                f"{appeal_window_deadline.isoformat()}."
            ),
            error_code="APPEAL_WINDOW_EXPIRED",
        )

    # --- Step 5: Compute SHA-256 Hash (Immutable Proof) ---
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    # --- Step 6: Create Appeal Record ---
    submitted_at = datetime.now(timezone.utc)

    appeal = Appeal(
        tender_id=tender_id,
        offer_id=offer_id,
        appellant_name=appellant_name,
        appellant_email=appellant_email,
        file_hash_sha256=file_hash,
        original_filename=original_filename,
        storage_path=storage_path,
        status=AppealStatus.RECEIVED,
        submitted_at=submitted_at,
        appeal_window_deadline=appeal_window_deadline,
    )

    db.add(appeal)

    # Update offer status
    old_offer_status = offer.status
    offer.status = OfferStatus.APPEALED

    # --- Step 7: Audit Log ---
    await log_event(
        db_session=db,
        action=ActionType.APPEAL_RECEIVED,
        actor="SYSTEM",
        offer_id=offer_id,
        old_state=old_offer_status,
        new_state="APPEALED",
        context={
            "appeal_id": None,  # Will be set after commit
            "tender_id": tender_id,
            "appellant_name": appellant_name,
            "file_hash": file_hash,
            "original_filename": original_filename,
            "storage_path": storage_path,
            "appeal_window_deadline": appeal_window_deadline.isoformat(),
        },
    )

    await db.commit()
    await db.refresh(appeal)

    # Update the audit log with the appeal_id now that we have it
    # (In a real implementation, you might query and update the context)

    logger.info(
        "Appeal {appeal_id} created for offer {offer_id} (tender {tender_id})",
        appeal_id=appeal.id,
        offer_id=offer_id,
        tender_id=tender_id,
    )

    return AppealSubmissionResult(
        success=True,
        appeal=appeal,
        message="Appeal submitted successfully. Under review.",
    )


# =============================================================================
# Phase 8: LLM Grievance Extraction (The Reasoner)
# =============================================================================


class GrievanceExtractionResult:
    """Result container for grievance extraction."""

    def __init__(
        self,
        success: bool,
        extraction: AppealGrievanceExtraction,
        error: str | None = None,
    ):
        self.success = success
        self.extraction = extraction
        self.error = error


async def extract_appeal_grievances(
    db: AsyncSession,
    appeal: Appeal,
) -> GrievanceExtractionResult:
    """
    Phase 8 Step 2: LLM extracts grievances from appeal PDF.

    The LLM reads the appeal document and outputs structured JSON
    containing each distinct grievance raised by the appellant.
    """
    logger.info("Extracting grievances from appeal {appeal_id}", appeal_id=appeal.id)

    # --- Step 1: Extract text from appeal PDF ---
    try:
        if not appeal.storage_path:
            raise ValueError("Appeal has no stored file path")

        pdf_path = Path(appeal.storage_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"Appeal PDF not found at {pdf_path}")

        appeal_text = extract_text_from_pdf(pdf_path)

        if not appeal_text or len(appeal_text.strip()) < 50:
            logger.warning(
                "Appeal PDF text extraction yielded minimal content for appeal {id}",
                id=appeal.id,
            )

    except Exception as exc:
        logger.error(
            "Failed to extract appeal PDF text for appeal {id}: {error}",
            id=appeal.id,
            error=str(exc),
        )
        return GrievanceExtractionResult(
            success=False,
            extraction=create_empty_grievance_extraction(),
            error=f"PDF extraction failed: {str(exc)}",
        )

    # --- Step 2: Call LLM for grievance extraction ---
    try:
        extraction = await _call_llm_extract_grievances(appeal_text)
    except Exception as exc:
        logger.error(
            "LLM grievance extraction failed for appeal {id}: {error}",
            id=appeal.id,
            error=str(exc),
        )
        await log_event(
            db_session=db,
            action=ActionType.APPEAL_EXTRACTION_FAILED,
            actor="LLM",
            offer_id=appeal.offer_id,
            new_state="EXTRACTION_FAILED",
            context={
                "appeal_id": appeal.id,
                "error": str(exc),
            },
        )
        await db.commit()
        return GrievanceExtractionResult(
            success=False,
            extraction=create_empty_grievance_extraction(),
            error=f"LLM extraction failed: {str(exc)}",
        )

    # --- Step 3: Update appeal record ---
    appeal.status = AppealStatus.UNDER_REVIEW
    appeal.llm_grievances_extracted = [
        {
            "type": g.grievance_type.value,
            "summary": g.summary,
            "claims": g.specific_claims,
        }
        for g in extraction.grievances
    ]

    await log_event(
        db_session=db,
        action=ActionType.APPEAL_GRIEVANCES_EXTRACTED,
        actor="LLM",
        offer_id=appeal.offer_id,
        new_state="UNDER_REVIEW",
        context={
            "appeal_id": appeal.id,
            "grievance_count": len(extraction.grievances),
            "extraction_confidence": extraction.extraction_confidence,
            "grievance_types": [g.grievance_type.value for g in extraction.grievances],
        },
    )
    await db.commit()

    logger.info(
        "Grievance extraction complete for appeal {id}: {count} grievances found",
        id=appeal.id,
        count=len(extraction.grievances),
    )

    return GrievanceExtractionResult(
        success=True,
        extraction=extraction,
    )


async def _call_llm_extract_grievances(appeal_text: str) -> AppealGrievanceExtraction:
    """
    Call LLM to extract structured grievances from appeal text.

    Returns strictly validated AppealGrievanceExtraction.
    """
    system_prompt = """You are an expert legal assistant specializing in procurement appeals.

Your task is to read an appeal document and extract structured grievances.

RULES:
1. Identify each distinct grievance raised by the appellant
2. Classify each grievance into one of these types:
   - TECHNICAL_SCORING: Dispute over technical evaluation scores
   - FINANCIAL_SCORING: Dispute over financial/bid price evaluation
   - COMPLIANCE_DECISION: Dispute over administrative compliance ruling
   - PROCEDURAL_IRREGULARITY: Allegations of process violations
   - CONFLICT_OF_INTEREST: Allegations of bias or conflict
   - DOCUMENTATION_ERROR: Claims of errors in evaluation records
   - OTHER: Other types of grievances

3. For each grievance, provide:
   - A clear summary (20-500 characters)
   - Detailed description (50-2000 characters)
   - Specific factual claims made
   - Any requested relief
   - Relevant document references

4. Output ONLY valid JSON matching the AppealGrievanceExtraction schema.
5. Include an overall summary of all grievances.
6. Assess your confidence in the extraction (HIGH, MEDIUM, or LOW).

Be thorough but objective. Do not add information not present in the document."""

    user_message = f"""Please extract structured grievances from the following appeal document:

--- APPEAL DOCUMENT ---
{appeal_text[:30000]}  # Limit to avoid token limits
--- END DOCUMENT ---

Extract all grievances and return them as structured JSON."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=4000,
    )

    # Parse and validate
    data = json.loads(raw_response)
    extraction = AppealGrievanceExtraction(**data)

    return extraction


# =============================================================================
# Phase 8: LLM Counter-Explanation Drafting (The Reasoner)
# =============================================================================


class CounterExplanationResult:
    """Result container for counter-explanation drafting."""

    def __init__(
        self,
        success: bool,
        counter_explanation: AppealCounterExplanation,
        error: str | None = None,
    ):
        self.success = success
        self.counter_explanation = counter_explanation
        self.error = error


async def draft_counter_explanation(
    db: AsyncSession,
    appeal: Appeal,
    grievances: AppealGrievanceExtraction,
) -> CounterExplanationResult:
    """
    Phase 8 Step 3: LLM drafts counter-explanation for committee.

    The LLM combines:
    1. The extracted grievances from the appeal
    2. The original evaluation audit trail for the offer
    3. The tender requirements and rubric

    To produce a structured, official counter-explanation for committee review.
    """
    logger.info(
        "Drafting counter-explanation for appeal {appeal_id}",
        appeal_id=appeal.id,
    )

    # --- Step 1: Retrieve Original Audit Trail ---
    audit_result = await db.execute(
        select(AuditLog)
        .where(AuditLog.offer_id == appeal.offer_id)
        .order_by(AuditLog.timestamp.asc())
    )
    audit_logs = audit_result.scalars().all()

    audit_summary = _format_audit_trail_for_llm(audit_logs)

    # --- Step 2: Fetch Tender Info ---
    tender_result = await db.execute(
        select(Tender).where(Tender.id == appeal.tender_id)
    )
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        return CounterExplanationResult(
            success=False,
            counter_explanation=create_empty_counter_explanation(),
            error="Tender not found",
        )

    # --- Step 3: Call LLM for counter-explanation drafting ---
    try:
        counter_exp = await _call_llm_draft_counter_explanation(
            appeal_appellant=appeal.appellant_name,
            tender_title=tender.title,
            tender_reference=tender.reference_number or "N/A",
            grievances=grievances,
            audit_trail=audit_summary,
        )
    except Exception as exc:
        logger.error(
            "LLM counter-explanation drafting failed for appeal {id}: {error}",
            id=appeal.id,
            error=str(exc),
        )
        return CounterExplanationResult(
            success=False,
            counter_explanation=create_empty_counter_explanation(
                appeal_reference=f"APPEAL-{appeal.id}",
                tender_title=tender.title,
                appellant_name=appeal.appellant_name,
            ),
            error=f"LLM drafting failed: {str(exc)}",
        )

    # --- Step 4: Update appeal record ---
    appeal.status = AppealStatus.RESPONSE_DRAFTED
    appeal.llm_counter_explanation = counter_exp.executive_summary

    await log_event(
        db_session=db,
        action=ActionType.APPEAL_RESPONSE_DRAFTED,
        actor="LLM",
        offer_id=appeal.offer_id,
        new_state="RESPONSE_DRAFTED",
        context={
            "appeal_id": appeal.id,
            "grievance_count": len(counter_exp.responses),
            "committee_position": counter_exp.overall_committee_position,
            "confidence_level": counter_exp.confidence_level,
        },
    )
    await db.commit()

    logger.info(
        "Counter-explanation drafted for appeal {id}: {position} ({confidence})",
        id=appeal.id,
        position=counter_exp.overall_committee_position,
        confidence=counter_exp.confidence_level,
    )

    return CounterExplanationResult(
        success=True,
        counter_explanation=counter_exp,
    )


async def _call_llm_draft_counter_explanation(
    appeal_appellant: str,
    tender_title: str,
    tender_reference: str,
    grievances: AppealGrievanceExtraction,
    audit_trail: str,
) -> AppealCounterExplanation:
    """
    Call LLM to draft counter-explanation combining grievances and audit trail.

    Returns strictly validated AppealCounterExplanation.
    """
    system_prompt = """You are an expert procurement committee advisor.

Your task is to draft an official counter-explanation to an appeal, addressing each grievance raised by the appellant using the original evaluation audit trail.

RULES:
1. For each grievance, provide:
   - A clear restatement of the grievance
   - A detailed committee response based on the audit trail
   - Factual findings that support the committee's position
   - Relevant procedural or regulatory references
   - A clear conclusion on that specific grievance

2. Provide an overall executive summary of the committee's position.

3. State the recommended overall committee position (UPHELD or OVERTURNED).

4. Include a summary of the original evaluation scores and methodology.

5. Output ONLY valid JSON matching the AppealCounterExplanation schema.

6. Be professional, objective, and thorough. Address every grievance raised.

7. Do NOT invent facts not present in the audit trail."""

    grievances_json = grievances.model_dump_json(indent=2)

    user_message = f"""Please draft a counter-explanation for the following appeal:

--- APPEAL DETAILS ---
Appellant: {appeal_appellant}
Tender: {tender_title} (Ref: {tender_reference})

--- EXTRACTED GRIEVANCES ---
{grievances_json}

--- ORIGINAL EVALUATION AUDIT TRAIL ---
{audit_trail}

--- END MATERIALS ---

Draft a complete counter-explanation addressing each grievance. Return as structured JSON."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=6000,
    )

    # Parse and validate
    data = json.loads(raw_response)
    counter_exp = AppealCounterExplanation(**data)

    return counter_exp


def _format_audit_trail_for_llm(audit_logs: list[AuditLog]) -> str:
    """Format audit logs into a readable summary for the LLM."""
    if not audit_logs:
        return "No audit trail available."

    lines = ["EVALUATION AUDIT TRAIL:", "=" * 50]

    for log in audit_logs:
        lines.append(f"\n[{log.timestamp.isoformat()}] {log.actor} | {log.action_type}")
        if log.old_state:
            lines.append(f"  FROM: {log.old_state}")
        if log.new_state:
            lines.append(f"  TO: {log.new_state}")
        if log.context:
            # Summarize context
            ctx_summary = _summarize_context(log.context)
            lines.append(f"  CONTEXT: {ctx_summary}")

    return "\n".join(lines)


def _summarize_context(context: dict[str, Any] | None) -> str:
    """Summarize audit context for LLM consumption."""
    if not context:
        return "None"

    # Filter out verbose fields
    important_keys = [
        "technical_score",
        "financial_score",
        "combined_score",
        "missing_documents",
        "abnormal_price_flag",
        "justification",
        "reason",
    ]

    summary_parts = []
    for key in important_keys:
        if key in context:
            value = context[key]
            if isinstance(value, (list, dict)):
                summary_parts.append(f"{key}={str(value)[:100]}...")
            else:
                summary_parts.append(f"{key}={value}")

    return ", ".join(summary_parts) if summary_parts else "See full audit log"


# =============================================================================
# Phase 8: Committee Resolution (Human The Decider)
# =============================================================================


class AppealResolutionResult:
    """Result container for appeal resolution."""

    def __init__(
        self,
        success: bool,
        appeal: Appeal | None,
        message: str,
    ):
        self.success = success
        self.appeal = appeal
        self.message = message


async def resolve_appeal(
    db: AsyncSession,
    appeal_id: int,
    committee_decision: str,
    justification: str,
    committee_member_id: str,
) -> AppealResolutionResult:
    """
    Phase 8 Final Step: Committee resolves the appeal.

    ## The Decider's Rules:

    1. **Mandatory Justification**: Written justification is required.
    2. **Decision Options**: UPHELD (original decision stands) or OVERTURNED.
    3. **Audit Trail**: Full resolution details logged.
    4. **Final Authority**: Human committee has final say over LLM recommendations.
    """
    logger.info(
        "Resolving appeal {appeal_id} with decision: {decision}",
        appeal_id=appeal_id,
        decision=committee_decision,
    )

    # --- Step 1: Fetch Appeal ---
    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = result.scalar_one_or_none()

    if appeal is None:
        return AppealResolutionResult(
            success=False,
            appeal=None,
            message=f"Appeal {appeal_id} not found.",
        )

    # --- Step 2: Validate Decision ---
    if committee_decision not in ("UPHELD", "OVERTURNED"):
        return AppealResolutionResult(
            success=False,
            appeal=appeal,
            message="Decision must be either UPHELD or OVERTURNED.",
        )

    # --- Step 3: Apply Resolution ---
    old_status = appeal.status
    appeal.status = AppealStatus.RESOLVED
    appeal.committee_decision = committee_decision
    appeal.decision_justification = justification
    appeal.resolved_at = datetime.now(timezone.utc)

    # --- Step 4: Audit Log ---
    await log_event(
        db_session=db,
        action=ActionType.APPEAL_RESOLVED,
        actor=committee_member_id,
        offer_id=appeal.offer_id,
        old_state=old_status.value if old_status else None,
        new_state="RESOLVED",
        context={
            "appeal_id": appeal_id,
            "committee_decision": committee_decision,
            "justification": justification,
            "decided_by": committee_member_id,
            "resolved_at": appeal.resolved_at.isoformat(),
        },
    )
    await db.commit()

    logger.info(
        "Appeal {appeal_id} resolved: {decision} by {member}",
        appeal_id=appeal_id,
        decision=committee_decision,
        member=committee_member_id,
    )

    return AppealResolutionResult(
        success=True,
        appeal=appeal,
        message=f"Appeal resolved successfully. Decision: {committee_decision}",
    )


# =============================================================================
# Statistics for Reporting
# =============================================================================


async def get_appeal_statistics(db: AsyncSession, tender_id: int) -> dict[str, Any]:
    """
    Get appeal statistics for a tender (used in Phase 9 closure reports).
    """
    from sqlalchemy import func

    result = await db.execute(
        select(
            func.count(Appeal.id).label("total_appeals"),
            func.sum((Appeal.status == AppealStatus.RESOLVED).cast(int)).label(
                "resolved"
            ),
            func.sum((Appeal.committee_decision == "UPHELD").cast(int)).label("upheld"),
            func.sum((Appeal.committee_decision == "OVERTURNED").cast(int)).label(
                "overturned"
            ),
        ).where(Appeal.tender_id == tender_id)
    )

    row = result.fetchone()

    return {
        "total_appeals": row.total_appeals or 0,
        "resolved": row.resolved or 0,
        "upheld": row.upheld or 0,
        "overturned": row.overturned or 0,
        "pending": (row.total_appeals or 0) - (row.resolved or 0),
    }
