"""
app/api/v1/committee.py

Phase 6 — Human Score Overrides
Phase 7 — Award Decision & Notification

Blueprint rules enforced here by Python (The Enforcer):
  - Override payloads MUST include a non-empty justification string.
  - Python clamps the override score to 0-100; LLM cannot override this.
  - Every override is written to AuditLog (old score → new score).
  - Award decision: Python selects the highest combined-score COMPLIANT offer.
  - LLM drafts the notification letter prose; Python controls the send.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.db.models import Offer, Tender
from app.db.models.offer import OfferStatus
from app.db.models.tender import TenderStatus
from app.utils.audit_logger import ActionType, log_event

router = APIRouter()


# =============================================================================
# Pydantic Schemas
# =============================================================================


class ScoreOverrideRequest(BaseModel):
    """
    Phase 6: Committee member overrides a technical or combined score.
    Justification is MANDATORY — the system refuses blank strings.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "offer_id": 3,
                "override_technical_score": 78.0,
                "justification": "LLM under-weighted the methodology section; "
                "confirmed with domain expert review.",
                "committee_member_id": "user:42",
            }
        }
    )

    offer_id: int = Field(..., gt=0, description="Offer to override")
    override_technical_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="New technical score (0-100). Leave None to keep existing.",
    )
    override_combined_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="New combined score (0-100). Leave None to keep existing.",
    )
    committee_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Notes to attach to this offer for the record.",
    )
    justification: str = Field(
        ...,
        min_length=20,
        max_length=2000,
        description="Mandatory justification for the override (≥20 chars).",
    )
    committee_member_id: str = Field(
        default="committee",
        description="Identity of the committee member making the override.",
    )


class ScoreOverrideResponse(BaseModel):
    """Response after applying a score override."""

    offer_id: int
    bidder_name: str
    previous_technical_score: float | None
    new_technical_score: float | None
    previous_combined_score: float | None
    new_combined_score: float | None
    justification: str
    overridden_at: str


class AwardRequest(BaseModel):
    """
    Phase 7: Trigger the final award decision for a closed tender.
    Python selects the winner — the committee must confirm.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tender_id": 1,
                "confirmed_by": "user:42",
                "use_llm_letters": True,
            }
        }
    )

    tender_id: int = Field(..., gt=0)
    confirmed_by: str = Field(
        ...,
        min_length=2,
        description="Committee member ID authorising this award.",
    )
    use_llm_letters: bool = Field(
        default=True,
        description="If True, use LLM to draft award/rejection letter text.",
    )


class AwardedOfferDetail(BaseModel):
    """Details of a single offer in the award response."""

    offer_id: int
    bidder_name: str
    bidder_email: str | None
    combined_score: float | None
    technical_score: float | None
    financial_score: float | None
    status: str
    letter_text: str | None = None


class AwardDecisionResponse(BaseModel):
    """Phase 7 response: full award decision record."""

    tender_id: int
    tender_title: str
    awarded_to: AwardedOfferDetail
    rejected: list[AwardedOfferDetail]
    decided_by: str
    decided_at: str
    close_tie_detected: bool


# =============================================================================
# Phase 6 Endpoints
# =============================================================================


@router.post(
    "/override",
    response_model=ScoreOverrideResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 6 — Override a technical or combined score",
    responses={
        200: {"description": "Override applied and audit-logged"},
        400: {"description": "No override values provided"},
        404: {"description": "Offer not found"},
        422: {"description": "Insufficient justification"},
    },
)
async def override_score(
    request: ScoreOverrideRequest,
    db: AsyncSession = Depends(get_db),
) -> ScoreOverrideResponse:
    """
    Apply a human committee override to an offer's technical or combined score.

    ## The Enforcer's Rules (Phase 6):

    1. **Mandatory justification**: `justification` must be ≥ 20 characters.
       Blank or vague strings are rejected at the schema level.

    2. **Score clamping**: Pydantic already validates 0 ≤ score ≤ 100.
       Python re-checks bounds before writing to DB.

    3. **Immutable audit trail**: The old score, new score, justification,
       and committee member identity are all written to `AuditLog` atomically.

    4. **Status update**: If a combined score is overridden, the offer is
       moved back to `COMMITTEE_REVIEW` status to reflect manual intervention.
    """
    # Fetch offer
    result = await db.execute(select(Offer).where(Offer.id == request.offer_id))
    offer = result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {request.offer_id} not found.",
        )

    if (
        request.override_technical_score is None
        and request.override_combined_score is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide at least one of: override_technical_score, override_combined_score.",
        )

    prev_technical = float(offer.technical_score) if offer.technical_score else None
    prev_combined = float(offer.total_score) if offer.total_score else None

    # Apply overrides (Python enforces bounds — belt & suspenders)
    if request.override_technical_score is not None:
        new_tech = max(0.0, min(100.0, request.override_technical_score))
        offer.technical_score = new_tech
    else:
        new_tech = prev_technical

    if request.override_combined_score is not None:
        new_combined = max(0.0, min(100.0, request.override_combined_score))
        offer.total_score = new_combined
    else:
        new_combined = prev_combined

    # Attach committee notes if provided
    if request.committee_notes:
        existing = offer.committee_notes or ""
        offer.committee_notes = (
            f"{existing}\n[{datetime.now(timezone.utc).isoformat()}] "
            f"{request.committee_member_id}: {request.committee_notes}"
        ).strip()

    # Flag offer as under committee review
    offer.status = OfferStatus.COMMITTEE_REVIEW

    override_at = datetime.now(timezone.utc).isoformat()

    await log_event(
        db_session=db,
        action=ActionType.SCORE_OVERRIDDEN,
        actor=request.committee_member_id,
        offer_id=offer.id,
        old_state=f"tech={prev_technical}, combined={prev_combined}",
        new_state=f"tech={new_tech}, combined={new_combined}",
        context={
            "prev_technical_score": prev_technical,
            "new_technical_score": new_tech,
            "prev_combined_score": prev_combined,
            "new_combined_score": new_combined,
            "justification": request.justification,
            "committee_member": request.committee_member_id,
            "overridden_at": override_at,
        },
    )

    await db.commit()

    return ScoreOverrideResponse(
        offer_id=offer.id,
        bidder_name=offer.bidder_name,
        previous_technical_score=prev_technical,
        new_technical_score=new_tech,
        previous_combined_score=prev_combined,
        new_combined_score=new_combined,
        justification=request.justification,
        overridden_at=override_at,
    )


@router.post(
    "/recalculate/{offer_id}",
    summary="Phase 6 — Recalculate combined score after override",
    status_code=status.HTTP_200_OK,
)
async def recalculate_combined_score(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Recalculate the combined score for an offer after a technical score override.

    Applies Python's weighted formula:
      combined = (technical × DEFAULT_TECHNICAL_WEIGHT) + (financial × financial_weight)
    """
    from app.core.config import settings
    from app.services.evaluation_service import compute_combined_score

    result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(status_code=404, detail=f"Offer {offer_id} not found.")

    if offer.technical_score is None or offer.financial_score is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Both technical_score and financial_score must exist before recalculating.",
        )

    new_combined = compute_combined_score(
        technical=float(offer.technical_score),
        financial=float(offer.financial_score),
    )
    offer.total_score = new_combined

    await log_event(
        db_session=db,
        action=ActionType.COMBINED_SCORE_COMPUTED,
        actor="SYSTEM",
        offer_id=offer_id,
        old_state=str(offer.total_score),
        new_state=str(new_combined),
        context={"trigger": "manual_recalculation_after_override"},
    )
    await db.commit()

    return {
        "offer_id": offer_id,
        "new_combined_score": new_combined,
        "technical_weight": settings.DEFAULT_TECHNICAL_WEIGHT,
        "financial_weight": settings.financial_weight,
    }


# =============================================================================
# Phase 7 Endpoints
# =============================================================================


@router.post(
    "/award",
    response_model=AwardDecisionResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 7 — Make final award decision",
    responses={
        200: {"description": "Award decision made and audit-logged"},
        404: {"description": "Tender not found"},
        409: {"description": "No scored offers available for award"},
    },
)
async def make_award_decision(
    request: AwardRequest,
    db: AsyncSession = Depends(get_db),
) -> AwardDecisionResponse:
    """
    Select and record the winning bidder for a tender.

    ## The Enforcer's Rules (Phase 7):

    1. **Python selects the winner** — the offer with the highest
       `total_score` among all COMPLIANT / COMBINED_SCORED / COMMITTEE_REVIEW
       offers. The LLM has no vote in this decision.

    2. **Close-tie detection**: If the top two offers differ by less than
       `CLOSE_TIE_THRESHOLD_PCT`, both are flagged in the response and
       a `CLOSE_TIE_FLAGGED` audit event is emitted for committee review.

    3. **Atomic status update**: Winner → AWARDED, all others → REJECTED_FINAL.
       All changes commit in a single transaction.

    4. **Full audit trail**: OFFER_AWARDED + OFFER_REJECTED_FINAL events are
       written for every offer affected.

    5. **LLM notification drafts** (optional): If `use_llm_letters=True`,
       the LLM drafts the award and rejection letter text. Python sends them.
    """
    from app.core.config import settings

    # Fetch tender
    tender_result = await db.execute(
        select(Tender).where(Tender.id == request.tender_id)
    )
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {request.tender_id} not found.",
        )

    # Fetch all scored offers, ordered by total_score descending
    ELIGIBLE_STATUSES = [
        OfferStatus.COMBINED_SCORED,
        OfferStatus.COMMITTEE_REVIEW,
        OfferStatus.TECHNICAL_SCORED,
        OfferStatus.COMPLIANT,
    ]
    offers_result = await db.execute(
        select(Offer)
        .where(
            Offer.tender_id == request.tender_id,
            Offer.status.in_(ELIGIBLE_STATUSES),
        )
        .order_by(Offer.total_score.desc().nulls_last())
    )
    offers = offers_result.scalars().all()

    if not offers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No eligible scored offers found for this tender. "
                "Run the evaluation pipeline first (POST /evaluation/tenders/{id}/evaluate)."
            ),
        )

    winner = offers[0]
    losers = offers[1:]

    # Close-tie detection (Python math, not LLM)
    close_tie = False
    if len(offers) >= 2:
        top_score = float(winner.total_score or 0)
        second_score = float(offers[1].total_score or 0)
        if top_score > 0:
            diff_pct = abs(top_score - second_score) / top_score * 100
            if diff_pct < settings.CLOSE_TIE_THRESHOLD_PCT:
                close_tie = True
                await log_event(
                    db_session=db,
                    action=ActionType.CLOSE_TIE_FLAGGED,
                    actor="SYSTEM",
                    offer_id=winner.id,
                    old_state=None,
                    new_state="CLOSE_TIE",
                    context={
                        "tender_id": request.tender_id,
                        "winner_id": winner.id,
                        "winner_score": top_score,
                        "runner_up_id": offers[1].id,
                        "runner_up_score": second_score,
                        "diff_pct": round(diff_pct, 2),
                        "threshold_pct": settings.CLOSE_TIE_THRESHOLD_PCT,
                    },
                )

    decided_at = datetime.now(timezone.utc).isoformat()

    # Optional: LLM-drafted letter text
    award_letter = None
    if request.use_llm_letters:
        award_letter = await _draft_award_letter(winner, tender)

    # Mark winner
    winner.status = OfferStatus.AWARDED
    await log_event(
        db_session=db,
        action=ActionType.OFFER_AWARDED,
        actor=request.confirmed_by,
        offer_id=winner.id,
        old_state=winner.status,
        new_state="AWARDED",
        context={
            "tender_id": tender.id,
            "tender_title": tender.title,
            "final_score": float(winner.total_score or 0),
            "close_tie": close_tie,
            "decided_at": decided_at,
            "confirmed_by": request.confirmed_by,
        },
    )

    rejected_details: list[AwardedOfferDetail] = []

    for loser in losers:
        rejection_letter = None
        if request.use_llm_letters:
            rejection_letter = await _draft_rejection_letter(loser, winner, tender)

        prev_status = loser.status
        loser.status = OfferStatus.REJECTED_FINAL
        await log_event(
            db_session=db,
            action=ActionType.OFFER_REJECTED_FINAL,
            actor=request.confirmed_by,
            offer_id=loser.id,
            old_state=prev_status,
            new_state="REJECTED_FINAL",
            context={
                "tender_id": tender.id,
                "winning_offer_id": winner.id,
                "final_score": float(loser.total_score or 0),
                "decided_at": decided_at,
            },
        )
        rejected_details.append(
            AwardedOfferDetail(
                offer_id=loser.id,
                bidder_name=loser.bidder_name,
                bidder_email=loser.bidder_email,
                combined_score=float(loser.total_score) if loser.total_score else None,
                technical_score=float(loser.technical_score) if loser.technical_score else None,
                financial_score=float(loser.financial_score) if loser.financial_score else None,
                status="REJECTED_FINAL",
                letter_text=rejection_letter,
            )
        )

    # Close the tender
    tender.status = TenderStatus.CLOSED

    await db.commit()

    return AwardDecisionResponse(
        tender_id=tender.id,
        tender_title=tender.title,
        awarded_to=AwardedOfferDetail(
            offer_id=winner.id,
            bidder_name=winner.bidder_name,
            bidder_email=winner.bidder_email,
            combined_score=float(winner.total_score) if winner.total_score else None,
            technical_score=float(winner.technical_score) if winner.technical_score else None,
            financial_score=float(winner.financial_score) if winner.financial_score else None,
            status="AWARDED",
            letter_text=award_letter,
        ),
        rejected=rejected_details,
        decided_by=request.confirmed_by,
        decided_at=decided_at,
        close_tie_detected=close_tie,
    )


@router.get(
    "/tenders/{tender_id}/scores",
    summary="Phase 6+7 — View all scores for a tender",
    status_code=status.HTTP_200_OK,
)
async def view_scores(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return all offers with their current scores, ordered highest-first.
    Used by the committee for pre-award review.
    """
    offers_result = await db.execute(
        select(Offer)
        .where(Offer.tender_id == tender_id)
        .order_by(Offer.total_score.desc().nulls_last())
    )
    offers = offers_result.scalars().all()

    if not offers:
        raise HTTPException(status_code=404, detail=f"No offers for tender {tender_id}.")

    return {
        "tender_id": tender_id,
        "total_offers": len(offers),
        "offers": [
            {
                "offer_id": o.id,
                "bidder_name": o.bidder_name,
                "status": o.status,
                "technical_score": float(o.technical_score) if o.technical_score else None,
                "financial_score": float(o.financial_score) if o.financial_score else None,
                "combined_score": float(o.total_score) if o.total_score else None,
                "committee_notes": o.committee_notes,
            }
            for o in offers
        ],
    }


@router.get("/", summary="Committee dashboard")
async def committee_dashboard(db: AsyncSession = Depends(get_db)) -> dict:
    """Committee dashboard — list tenders awaiting award decision."""
    return {
        "phase_6_endpoint": "POST /committee/override",
        "phase_7_endpoint": "POST /committee/award",
        "scores_endpoint": "GET /committee/tenders/{tender_id}/scores",
    }


# =============================================================================
# LLM Letter Drafting (Phase 7 helper)
# =============================================================================


async def _draft_award_letter(offer: Offer, tender: Tender) -> str | None:
    """Use LLM to draft an award notification letter."""
    try:
        from app.llm.client import call_llm

        system = (
            "You are a procurement officer drafting a formal award notification letter. "
            "Write professionally and concisely. Use formal business English. "
            "Return ONLY the letter body text — no subject lines, no JSON."
        )
        user = (
            f"Draft an award notification letter for:\n"
            f"Tender: {tender.title} (Ref: {tender.reference_number or 'N/A'})\n"
            f"Winning Bidder: {offer.bidder_name}\n"
            f"Final Score: {float(offer.total_score or 0):.1f}/100\n\n"
            "The letter should congratulate them, confirm the award, and instruct them "
            "to contact the procurement office within 5 working days to proceed with "
            "contract signing."
        )
        return await call_llm(system, user, temperature=0.3, max_tokens=500)
    except Exception:
        return None


async def _draft_rejection_letter(
    offer: Offer, winner: Offer, tender: Tender
) -> str | None:
    """Use LLM to draft a rejection notification letter."""
    try:
        from app.llm.client import call_llm

        system = (
            "You are a procurement officer drafting a formal bid rejection letter. "
            "Be professional, respectful, and compliant with procurement transparency rules. "
            "Do NOT reveal the winner's score or name. "
            "Return ONLY the letter body — no JSON."
        )
        user = (
            f"Draft a bid rejection letter for:\n"
            f"Tender: {tender.title} (Ref: {tender.reference_number or 'N/A'})\n"
            f"Bidder: {offer.bidder_name}\n"
            f"Their Score: {float(offer.total_score or 0):.1f}/100\n\n"
            "Inform them of the unsuccessful bid, thank them for participating, "
            "and advise they may request feedback within 30 days."
        )
        return await call_llm(system, user, temperature=0.3, max_tokens=400)
    except Exception:
        return None
