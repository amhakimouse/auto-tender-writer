"""
app/api/v1/evaluation.py

Phase 2 — Administrative Compliance Check
Phase 3 — Technical Evaluation
Phase 4 — Financial Evaluation
Phase 5 — Combined Scoring & Ranking

Blueprint rules enforced here by Python (The Enforcer):
  - Python validates LLM scores fit within the defined rubric max range.
  - Python runs the lowest-price scoring formula (Phase 4 math).
  - Python applies weights (DEFAULT_TECHNICAL_WEIGHT from settings).
  - Python flags close ties (< CLOSE_TIE_THRESHOLD_PCT difference).
  - Python flags abnormally low bids (< ABNORMALLY_LOW_PRICE_THRESHOLD_PCT).

The LLM only reads text and generates structured JSON.
Python makes ALL decisions about disqualification, scoring, and ranking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models import Offer, Tender
from app.db.models.offer import OfferStatus
from app.db.models.tender import TenderStatus
from app.schemas.evaluation import EvaluationResult, EvaluationStatus
from app.services.evaluation_service import evaluate_tender_offers
from app.utils.audit_logger import ActionType, log_event

router = APIRouter()


# =============================================================================
# Pydantic Schemas for API
# =============================================================================


class EvaluationTriggerRequest(BaseModel):
    """Request body for triggering evaluation."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "technical_rubric": '{"criteria": [{"name": "Methodology", "weight": 40}, {"name": "Experience", "weight": 30}]}',
                "auto_disqualify": True,
            }
        }
    )

    technical_rubric: str | None = Field(
        default=None,
        description="JSON string containing the technical evaluation rubric",
    )
    auto_disqualify: bool = Field(
        default=True,
        description="Whether to automatically disqualify non-compliant offers",
    )


class CriterionScore(BaseModel):
    """Score for a single criterion."""

    criterion: str
    max_score: int
    raw_score: int
    justification: str


class OfferEvaluationDetail(BaseModel):
    """Detailed evaluation result for a single offer."""

    offer_id: int
    bidder_name: str
    status: str
    compliance_passed: bool | None
    missing_documents: list[str] | None
    technical_score: float | None
    financial_score: float | None
    total_score: float | None
    disqualification_reason: str | None


class EvaluationSummaryResponse(BaseModel):
    """Summary of batch evaluation results."""

    model_config = ConfigDict(from_attributes=True)

    tender_id: int
    tender_title: str
    evaluation_timestamp: str
    total_offers: int
    processed: int
    passed_compliance: int
    failed_compliance: int
    technical_scored: int
    errors: list[dict]
    disqualification_summary: list[dict]
    top_offers: list[OfferEvaluationDetail]


class SingleOfferEvaluateRequest(BaseModel):
    """Request to evaluate a single offer."""

    technical_rubric: str | None = Field(
        default=None,
        description="Technical evaluation rubric (JSON string)",
    )


# =============================================================================
# API Endpoints
# =============================================================================


@router.post(
    "/tenders/{tender_id}/evaluate",
    response_model=EvaluationSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Evaluate all pending offers for a tender",
    responses={
        200: {"description": "Evaluation completed successfully"},
        404: {"description": "Tender not found"},
        409: {"description": "Tender is not in a valid state for evaluation"},
    },
)
async def evaluate_tender(
    tender_id: int,
    request: EvaluationTriggerRequest,
    db: AsyncSession = Depends(get_db),
) -> EvaluationSummaryResponse:
    """
    Trigger automated evaluation for all pending offers in a tender.

    ## Evaluation Process:

    1. **Phase 2 — Compliance Check**:
       - Extract text from each offer PDF
       - LLM checks for mandatory documents (tax, registration, bond, signature)
       - **Python The Enforcer**: If any mandatory document missing → DISQUALIFIED
       - Audit log records the decision

    2. **Phase 3 — Technical Scoring** (if rubric provided):
       - Only compliant offers proceed to technical scoring
       - LLM scores against rubric criteria
       - **Python The Enforcer**: Validates score bounds, calculates normalized score

    ## Parameters:
        - tender_id: The tender to evaluate
        - technical_rubric: Optional JSON rubric for technical scoring
        - auto_disqualify: If True (default), non-compliant offers are automatically disqualified

    ## Returns:
        Summary of evaluation results including pass/fail counts and top-scoring offers.
    """
    # Verify tender exists
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # Tender should be closed or closing to evaluate
    if tender.status not in (TenderStatus.PUBLISHED, TenderStatus.CLOSED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot evaluate tender in {tender.status} status. "
            "Tender must be PUBLISHED or CLOSED.",
        )

    # Log evaluation start
    await log_event(
        db_session=db,
        action=ActionType("TENDER_EVALUATION_STARTED"),  # Will be defined
        actor="SYSTEM",
        offer_id=None,
        new_state="EVALUATION_STARTED",
        context={
            "tender_id": tender_id,
            "tender_title": tender.title,
            "has_technical_rubric": request.technical_rubric is not None,
            "auto_disqualify": request.auto_disqualify,
        },
    )
    await db.commit()

    try:
        # Run evaluation
        results = await evaluate_tender_offers(
            db=db,
            tender_id=tender_id,
            technical_rubric=request.technical_rubric,
        )

    except Exception as exc:
        logger.exception("Evaluation failed for tender {id}", id=tender_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Evaluation failed: {str(exc)}",
        )

    # Get detailed results for response
    offers_result = await db.execute(
        select(Offer)
        .where(Offer.tender_id == tender_id)
        .order_by(Offer.total_score.desc().nulls_last())
    )
    offers = offers_result.scalars().all()

    # Build disqualification summary
    disqualifications = [
        {
            "offer_id": o.id,
            "bidder_name": o.bidder_name,
            "reason": o.disqualification_reason,
        }
        for o in offers
        if o.status == OfferStatus.INCOMPLIANT
    ]

    # Build top offers list (compliant, scored)
    top_offers = [
        OfferEvaluationDetail(
            offer_id=o.id,
            bidder_name=o.bidder_name,
            status=o.status,
            compliance_passed=o.compliance_passed,
            missing_documents=None,  # Would need to fetch from audit log
            technical_score=float(o.technical_score) if o.technical_score else None,
            financial_score=float(o.financial_score) if o.financial_score else None,
            total_score=float(o.total_score) if o.total_score else None,
            disqualification_reason=o.disqualification_reason,
        )
        for o in offers[:5]  # Top 5
        if o.status in (OfferStatus.COMPLIANT, OfferStatus.TECHNICAL_SCORED)
    ]

    # Log evaluation completion
    await log_event(
        db_session=db,
        action=ActionType("TENDER_EVALUATION_COMPLETED"),
        actor="SYSTEM",
        offer_id=None,
        old_state="EVALUATION_STARTED",
        new_state="EVALUATION_COMPLETED",
        context={
            "tender_id": tender_id,
            "total_offers": results["total_offers"],
            "passed_compliance": results["passed_compliance"],
            "failed_compliance": results["failed_compliance"],
            "errors_count": len(results["errors"]),
        },
    )
    await db.commit()

    return EvaluationSummaryResponse(
        tender_id=tender_id,
        tender_title=tender.title,
        evaluation_timestamp=datetime.now(timezone.utc).isoformat(),
        total_offers=results["total_offers"],
        processed=results["processed"],
        passed_compliance=results["passed_compliance"],
        failed_compliance=results["failed_compliance"],
        technical_scored=results["technical_scored"],
        errors=results["errors"],
        disqualification_summary=disqualifications,
        top_offers=top_offers,
    )


@router.post(
    "/offers/{offer_id}/evaluate",
    response_model=OfferEvaluationDetail,
    summary="Evaluate a single offer",
)
async def evaluate_single_offer(
    offer_id: int,
    request: SingleOfferEvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> OfferEvaluationDetail:
    """
    Evaluate a single offer (compliance check + optional technical scoring).

    This is useful for re-evaluating an offer after corrections or
    for testing the evaluation pipeline.
    """
    from app.services.evaluation_service import (
        evaluate_offer_compliance,
        evaluate_technical_score,
    )

    # Get offer
    offer_result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = offer_result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer with ID {offer_id} not found",
        )

    # Get tender
    tender_result = await db.execute(select(Tender).where(Tender.id == offer.tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender for offer not found",
        )

    # Phase 2: Compliance
    compliance_result = await evaluate_offer_compliance(db, offer, tender)

    # Phase 3: Technical (if compliant and rubric provided)
    if compliance_result.passed and request.technical_rubric:
        tech_result = await evaluate_technical_score(
            db, offer, tender, request.technical_rubric
        )

    await db.refresh(offer)

    return OfferEvaluationDetail(
        offer_id=offer.id,
        bidder_name=offer.bidder_name,
        status=offer.status,
        compliance_passed=offer.compliance_passed,
        missing_documents=compliance_result.missing_mandatory
        if not compliance_result.passed
        else None,
        technical_score=float(offer.technical_score) if offer.technical_score else None,
        financial_score=float(offer.financial_score) if offer.financial_score else None,
        total_score=float(offer.total_score) if offer.total_score else None,
        disqualification_reason=offer.disqualification_reason,
    )


@router.get(
    "/tenders/{tender_id}/results",
    response_model=list[OfferEvaluationDetail],
    summary="Get evaluation results for a tender",
)
async def get_evaluation_results(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[OfferEvaluationDetail]:
    """
    Get the current evaluation results for all offers in a tender.

    Results are ordered by total score (highest first).
    """
    # Verify tender exists
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # Get all offers with evaluation data
    offers_result = await db.execute(
        select(Offer)
        .where(Offer.tender_id == tender_id)
        .order_by(
            Offer.total_score.desc().nulls_last(),
            Offer.submitted_at.asc(),
        )
    )
    offers = offers_result.scalars().all()

    return [
        OfferEvaluationDetail(
            offer_id=o.id,
            bidder_name=o.bidder_name,
            status=o.status,
            compliance_passed=o.compliance_passed,
            missing_documents=None,  # Would fetch from audit log
            technical_score=float(o.technical_score) if o.technical_score else None,
            financial_score=float(o.financial_score) if o.financial_score else None,
            total_score=float(o.total_score) if o.total_score else None,
            disqualification_reason=o.disqualification_reason,
        )
        for o in offers
    ]


# Import logger at module level
from loguru import logger


@router.get(
    "/",
    summary="List evaluation endpoints",
)
async def list_evaluation_endpoints():
    """List available evaluation endpoints."""
    return {
        "endpoints": [
            {
                "path": "/tenders/{tender_id}/evaluate",
                "method": "POST",
                "description": "Evaluate all pending offers for a tender",
            },
            {
                "path": "/offers/{offer_id}/evaluate",
                "method": "POST",
                "description": "Evaluate a single offer",
            },
            {
                "path": "/tenders/{tender_id}/results",
                "method": "GET",
                "description": "Get evaluation results for a tender",
            },
        ]
    }
