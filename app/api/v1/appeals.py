"""
app/api/v1/appeals.py

Phase 8 — Appeals Handling Router

This router handles:
    - POST /tenders/{tender_id}/appeals: Submit a new appeal (Python enforces window)
    - GET /appeals/{appeal_id}: View appeal details with LLM-extracted grievances
    - POST /appeals/{appeal_id}/extract: Trigger LLM grievance extraction
    - POST /appeals/{appeal_id}/draft-response: Trigger LLM counter-explanation drafting
    - POST /appeals/{appeal_id}/resolve: Committee resolves the appeal

The Enforcer/Reasoner/Decider split:
    - Python (Enforcer): Window validation, hash computation, audit logging
    - LLM (Reasoner): Grievance extraction, counter-explanation drafting
    - Human (Decider): Final resolution with mandatory justification
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.schemas.appeal_schemas import (
    AppealGrievanceExtraction,
    AppealCounterExplanation,
    AppealResolutionRequest,
    AppealResolutionResponse,
    AppealReviewResponse,
    AppealSubmissionRequest,
    AppealSubmissionResponse,
)
from app.services.appeal_service import (
    draft_counter_explanation,
    extract_appeal_grievances,
    get_appeal_statistics,
    resolve_appeal,
    submit_appeal,
)
from app.db.models import Appeal, AppealStatus
from app.utils.audit_logger import ActionType, log_event

router = APIRouter()


# =============================================================================
# Phase 8: Submit Appeal (Python The Enforcer)
# =============================================================================


@router.post(
    "/tenders/{tender_id}/appeals",
    response_model=AppealSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Phase 8 — Submit an appeal against an offer",
    responses={
        201: {"description": "Appeal submitted successfully"},
        403: {"description": "Appeal window has expired"},
        404: {"description": "Tender or offer not found"},
        409: {"description": "Offer not in final status or tender not closed"},
    },
)
async def submit_appeal_endpoint(
    tender_id: int,
    offer_id: Annotated[int, Form(..., description="ID of the offer being appealed")],
    appellant_name: Annotated[
        str,
        Form(
            ...,
            min_length=2,
            max_length=255,
            description="Name of the appellant organization",
        ),
    ],
    appellant_email: Annotated[
        str | None,
        Form(description="Contact email for appeal correspondence"),
    ] = None,
    appeal_file: UploadFile = File(
        ...,
        description="Appeal PDF document (signed, formal appeal letter)",
    ),
    db: AsyncSession = Depends(get_db),
) -> AppealSubmissionResponse:
    """
    Submit a formal appeal against an offer.

    ## The Enforcer's Rules:

    1. **Tender must be CLOSED**: Appeals only accepted after tender closure.
    2. **Appeal Window**: Must be within 14 days of tender deadline. **Strictly enforced.**
    3. **Offer Status**: Offer must be in a final state (AWARDED or REJECTED_FINAL).
    4. **Immutability**: SHA-256 hash computed for evidence integrity.
    5. **Audit Trail**: Every submission logged atomically.

    ## Process:

    1. Submit appeal PDF and appellant information
    2. Python validates the appeal window (403 Forbidden if expired)
    3. Python computes file hash and stores document
    4. Offer status updated to APPEALED
    5. Committee notified for review

    ## Response Codes:

    - **201**: Appeal accepted and under review
    - **403**: Appeal window expired (outside 14-day window)
    - **404**: Tender or offer not found
    - **409**: Offer not eligible (not in final status) or tender not closed
    """
    # Validate file type
    if appeal_file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files accepted. Got: {appeal_file.content_type}",
        )

    # Read file content
    file_content = await appeal_file.read()
    MAX_SIZE = 50 * 1024 * 1024  # 50MB

    if len(file_content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 50MB",
        )

    if len(file_content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Save to temporary storage (in production, use secure vault)
    temp_dir = Path(tempfile.gettempdir()) / "tender_appeals"
    temp_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_filename = f"appeal_t{tender_id}_o{offer_id}_{timestamp}.pdf"
    storage_path = temp_dir / safe_filename

    with open(storage_path, "wb") as f:
        f.write(file_content)

    # Submit appeal via service
    result = await submit_appeal(
        db=db,
        tender_id=tender_id,
        offer_id=offer_id,
        appellant_name=appellant_name,
        appellant_email=appellant_email,
        pdf_bytes=file_content,
        original_filename=appeal_file.filename or "appeal.pdf",
        storage_path=str(storage_path),
    )

    if not result.success:
        # Clean up temp file on failure
        storage_path.unlink(missing_ok=True)

        # Map error codes to HTTP status
        if result.error_code in ("TENDER_NOT_FOUND", "OFFER_NOT_FOUND"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.message,
            )
        elif result.error_code == "APPEAL_WINDOW_EXPIRED":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=result.message,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=result.message,
            )

    return AppealSubmissionResponse(
        success=True,
        appeal_id=result.appeal.id if result.appeal else None,
        tender_id=tender_id,
        offer_id=offer_id,
        status=result.appeal.status.value if result.appeal else None,
        appeal_window_deadline=result.appeal.appeal_window_deadline
        if result.appeal
        else None,
        message=result.message,
    )


# =============================================================================
# Phase 8: View Appeal (with LLM-extracted data)
# =============================================================================


@router.get(
    "/appeals/{appeal_id}",
    response_model=AppealReviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 8 — View appeal details",
)
async def view_appeal(
    appeal_id: int,
    db: AsyncSession = Depends(get_db),
) -> AppealReviewResponse:
    """
    Retrieve full appeal details including LLM-extracted grievances
    and drafted counter-explanations.
    """
    from sqlalchemy import select

    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = result.scalar_one_or_none()

    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal {appeal_id} not found",
        )

    # Parse stored grievances if available
    grievances = None
    if appeal.llm_grievances_extracted:
        try:
            from app.schemas.appeal_schemas import AppealGrievanceExtraction

            grievances = AppealGrievanceExtraction(
                grievances=[
                    {
                        "grievance_type": g.get("type", "OTHER"),
                        "summary": g.get("summary", ""),
                        "detailed_description": g.get(
                            "detailed_description", g.get("summary", "")
                        ),
                        "specific_claims": g.get("claims", []),
                    }
                    for g in appeal.llm_grievances_extracted
                ],
                overall_summary=f"Extracted {len(appeal.llm_grievances_extracted)} grievance(s)",
                extraction_confidence="HIGH",
            )
        except Exception:
            grievances = None

    # Parse counter-explanation if available
    counter_explanation = None
    if appeal.llm_counter_explanation:
        from app.schemas.appeal_schemas import (
            AppealCounterExplanation,
            CounterExplanationSection,
        )

        counter_explanation = AppealCounterExplanation(
            appeal_reference=f"APPEAL-{appeal.id}",
            tender_title=f"Tender {appeal.tender_id}",
            appellant_name=appeal.appellant_name,
            executive_summary=appeal.llm_counter_explanation,
            responses=[
                CounterExplanationSection(
                    grievance_id=1,
                    grievance_summary="See executive summary",
                    committee_response=appeal.llm_counter_explanation,
                    conclusion="Pending committee review",
                )
            ],
            overall_committee_position="PENDING",
        )

    return AppealReviewResponse(
        appeal_id=appeal.id,
        tender_id=appeal.tender_id,
        offer_id=appeal.offer_id,
        appellant_name=appeal.appellant_name,
        status=appeal.status.value,
        submitted_at=appeal.submitted_at,
        appeal_window_deadline=appeal.appeal_window_deadline,
        grievances=grievances,
        counter_explanation=counter_explanation,
        committee_decision=appeal.committee_decision,
        decision_justification=appeal.decision_justification,
        resolved_at=appeal.resolved_at,
    )


# =============================================================================
# Phase 8: LLM Grievance Extraction (The Reasoner)
# =============================================================================


@router.post(
    "/appeals/{appeal_id}/extract",
    status_code=status.HTTP_200_OK,
    summary="Phase 8 — Extract grievances from appeal (LLM)",
)
async def extract_grievances_endpoint(
    appeal_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger LLM extraction of grievances from the appeal PDF.

    ## The Reasoner's Task:

    1. Read the appeal PDF
    2. Identify each distinct grievance
    3. Classify grievance type (TECHNICAL_SCORING, FINANCIAL_SCORING, etc.)
    4. Extract specific claims and requested relief
    5. Output structured JSON (validated by Pydantic)

    ## Process:

    1. PDF text extraction
    2. LLM grievance analysis
    3. Structured output validation
    4. Appeal status updated to UNDER_REVIEW
    5. Results logged to audit trail
    """
    from sqlalchemy import select

    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = result.scalar_one_or_none()

    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal {appeal_id} not found",
        )

    # Call LLM service for extraction
    extraction_result = await extract_appeal_grievances(db, appeal)

    if not extraction_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Grievance extraction failed: {extraction_result.error}",
        )

    return {
        "appeal_id": appeal_id,
        "success": True,
        "grievance_count": len(extraction_result.extraction.grievances),
        "extraction_confidence": extraction_result.extraction.extraction_confidence,
        "grievances": [
            {
                "type": g.grievance_type.value,
                "summary": g.summary,
                "claims": g.specific_claims,
                "requested_relief": g.requested_relief,
            }
            for g in extraction_result.extraction.grievances
        ],
        "overall_summary": extraction_result.extraction.overall_summary,
    }


# =============================================================================
# Phase 8: LLM Counter-Explanation Drafting (The Reasoner)
# =============================================================================


@router.post(
    "/appeals/{appeal_id}/draft-response",
    status_code=status.HTTP_200_OK,
    summary="Phase 8 — Draft counter-explanation (LLM)",
)
async def draft_counter_explanation_endpoint(
    appeal_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Trigger LLM drafting of official counter-explanation for committee.

    ## The Reasoner's Task:

    1. Retrieve extracted grievances
    2. Fetch original evaluation audit trail
    3. Draft response addressing each grievance
    4. Reference specific audit events and scores
    5. Recommend committee position (UPHELD/OVERTURNED)

    ## Process:

    1. Load grievances and audit trail
    2. LLM drafts section-by-section response
    3. Structured output validation
    4. Appeal status updated to RESPONSE_DRAFTED
    5. Results logged to audit trail
    """
    from sqlalchemy import select

    result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = result.scalar_one_or_none()

    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal {appeal_id} not found",
        )

    if appeal.status not in (AppealStatus.UNDER_REVIEW, AppealStatus.RESPONSE_DRAFTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Appeal must be in UNDER_REVIEW status. Current: {appeal.status}",
        )

    # Load grievances
    from app.schemas.appeal_schemas import AppealGrievanceExtraction, Grievance

    if not appeal.llm_grievances_extracted:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Grievances must be extracted before drafting counter-explanation. Call /extract first.",
        )

    grievances = AppealGrievanceExtraction(
        grievances=[
            Grievance(
                grievance_type=g.get("type", "OTHER"),
                summary=g.get("summary", ""),
                detailed_description=g.get(
                    "detailed_description", g.get("summary", "")
                ),
                specific_claims=g.get("claims", []),
            )
            for g in appeal.llm_grievances_extracted
        ],
        overall_summary=f"Extracted {len(appeal.llm_grievances_extracted)} grievance(s)",
        extraction_confidence="HIGH",
    )

    # Call LLM service for counter-explanation
    drafting_result = await draft_counter_explanation(db, appeal, grievances)

    if not drafting_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Counter-explanation drafting failed: {drafting_result.error}",
        )

    return {
        "appeal_id": appeal_id,
        "success": True,
        "executive_summary": drafting_result.counter_explanation.executive_summary,
        "overall_position": drafting_result.counter_explanation.overall_committee_position,
        "recommended_action": drafting_result.counter_explanation.recommended_action,
        "confidence_level": drafting_result.counter_explanation.confidence_level,
        "section_count": len(drafting_result.counter_explanation.responses),
    }


# =============================================================================
# Phase 8: Committee Resolution (Human The Decider)
# =============================================================================


@router.post(
    "/appeals/{appeal_id}/resolve",
    response_model=AppealResolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 8 — Resolve appeal (Committee)",
)
async def resolve_appeal_endpoint(
    appeal_id: int,
    request: AppealResolutionRequest,
    db: AsyncSession = Depends(get_db),
) -> AppealResolutionResponse:
    """
    Committee resolves the appeal with final decision.

    ## The Decider's Rules:

    1. **Mandatory Justification**: Written justification ≥ 50 characters required.
    2. **Decision Options**: UPHELD (original stands) or OVERTURNED (appeal granted).
    3. **Human Override**: Committee may override LLM recommendations.
    4. **Audit Trail**: Full resolution details logged with committee member ID.

    ## Process:

    1. Review LLM-drafted counter-explanation (optional)
    2. Make final decision: UPHELD or OVERTURNED
    3. Provide written justification (mandatory)
    4. Record decision and close appeal
    """
    from sqlalchemy import select

    # Verify appeal exists
    appeal_result = await db.execute(select(Appeal).where(Appeal.id == appeal_id))
    appeal = appeal_result.scalar_one_or_none()

    if appeal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Appeal {appeal_id} not found",
        )

    # Resolve via service
    resolution = await resolve_appeal(
        db=db,
        appeal_id=appeal_id,
        committee_decision=request.committee_decision,
        justification=request.justification,
        committee_member_id=request.committee_member_id,
    )

    if not resolution.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=resolution.message,
        )

    return AppealResolutionResponse(
        appeal_id=appeal_id,
        tender_id=appeal.tender_id,
        offer_id=appeal.offer_id,
        committee_decision=request.committee_decision,
        decided_at=datetime.now(timezone.utc),
        decided_by=request.committee_member_id,
    )


# =============================================================================
# Phase 8: List Appeals (for Tender)
# =============================================================================


@router.get(
    "/tenders/{tender_id}/appeals",
    status_code=status.HTTP_200_OK,
    summary="Phase 8 — List all appeals for a tender",
)
async def list_appeals(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all appeals submitted for a tender with summary statistics."""
    from sqlalchemy import select

    result = await db.execute(
        select(Appeal)
        .where(Appeal.tender_id == tender_id)
        .order_by(Appeal.submitted_at.desc())
    )
    appeals = result.scalars().all()

    stats = await get_appeal_statistics(db, tender_id)

    return {
        "tender_id": tender_id,
        "total_appeals": len(appeals),
        "statistics": stats,
        "appeals": [
            {
                "appeal_id": a.id,
                "offer_id": a.offer_id,
                "appellant_name": a.appellant_name,
                "status": a.status.value,
                "submitted_at": a.submitted_at.isoformat(),
                "resolved": a.status == AppealStatus.RESOLVED,
                "decision": a.committee_decision,
            }
            for a in appeals
        ],
    }
