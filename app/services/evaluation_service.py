"""
app/services/evaluation_service.py

The Evaluation Service — Python The Enforcer.

This module orchestrates the evaluation workflow (Phases 2-5):
    - Phase 2: Administrative Compliance Check
    - Phase 3: Technical Scoring
    - Phase 4: Financial Evaluation (lowest-price formula + abnormal price flag)
    - Phase 5: Combined Scoring & Ranking (weighted formula + close-tie detection)

Architecture Rules:
    1. Python NEVER trusts the LLM output without validation.
    2. All LLM calls go through the orchestrator.
    3. All DB state changes are atomic with their audit logs.
    4. Disqualification decisions are made by Python, never the LLM.
    5. All exceptions are caught and logged; service never crashes.

If the LLM hallucinates bad JSON, Pydantic catches it and we:
    - Log the error with context
    - Mark the evaluation as failed
    - Set the offer to a safe state (DISQUALIFIED or ERROR)
    - Continue processing other offers (don't fail the whole batch)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Offer, Tender
from app.db.models.offer import OfferStatus
from app.llm.orchestrator import (
    evaluate_compliance as llm_evaluate_compliance,
    score_technical_section as llm_score_technical,
    extract_financial_data as llm_extract_financial,
)
from app.schemas.llm_schemas import (
    ComplianceChecklist,
    TechnicalScore,
    FinancialData,
    create_empty_compliance_result,
    create_empty_technical_score,
)
from app.utils.audit_logger import ActionType, log_event
from app.utils.file_parser import extract_text_from_pdf


# =============================================================================
# Phase 2: Administrative Compliance Check
# =============================================================================


class ComplianceEvaluationResult:
    """Result container for compliance evaluation."""

    def __init__(
        self,
        passed: bool,
        checklist: ComplianceChecklist,
        missing_mandatory: list[str],
        error: str | None = None,
    ):
        self.passed = passed
        self.checklist = checklist
        self.missing_mandatory = missing_mandatory
        self.error = error


async def evaluate_offer_compliance(
    db: AsyncSession,
    offer: Offer,
    tender: Tender,
) -> ComplianceEvaluationResult:
    """
    Phase 2: Administrative compliance check.

    The Enforcer's Rules:
        1. Extract text from the PDF
        2. Call LLM to evaluate compliance checklist
        3. Validate LLM output against Pydantic schema
        4. If ANY mandatory document is missing → DISQUALIFIED
        5. Log the decision to audit trail
        6. Return result (success or failure details)
    """
    logger.info(
        "Starting compliance evaluation for offer {offer_id} (tender {tender_id})",
        offer_id=offer.id,
        tender_id=tender.id,
    )

    # --- Step 1: Extract text from PDF ---
    try:
        if not offer.storage_path:
            raise ValueError("Offer has no stored file path")

        pdf_path = Path(offer.storage_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found at {pdf_path}")

        pdf_text = extract_text_from_pdf(pdf_path)

        if not pdf_text or len(pdf_text.strip()) < 100:
            logger.warning(
                "PDF text extraction yielded minimal content for offer {id}",
                id=offer.id,
            )

    except Exception as exc:
        logger.error(
            "Failed to extract PDF text for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )
        await log_event(
            db_session=db,
            action=ActionType.OFFER_DISQUALIFIED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=offer.status,
            new_state="DISQUALIFIED_EXTRACTION_FAILED",
            context={"reason": f"PDF text extraction failed: {str(exc)}"},
        )
        offer.status = OfferStatus.INCOMPLIANT
        offer.compliance_passed = False
        offer.disqualification_reason = f"PDF extraction failed: {str(exc)}"
        await db.commit()
        return ComplianceEvaluationResult(
            passed=False,
            checklist=create_empty_compliance_result(),
            missing_mandatory=["PDF_EXTRACTION_FAILED"],
            error=f"PDF extraction failed: {str(exc)}",
        )

    # --- Step 2: Call LLM for compliance evaluation ---
    try:
        compliance_result: ComplianceChecklist = await llm_evaluate_compliance(
            pdf_text=pdf_text,
        )
    except (ValidationError, Exception) as exc:
        logger.error(
            "LLM compliance call failed for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )
        await log_event(
            db_session=db,
            action=ActionType.OFFER_DISQUALIFIED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=offer.status,
            new_state="DISQUALIFIED_LLM_ERROR",
            context={"reason": f"LLM compliance call failed: {str(exc)}"},
        )
        offer.status = OfferStatus.INCOMPLIANT
        offer.compliance_passed = False
        offer.disqualification_reason = f"Compliance check failed: {str(exc)}"
        await db.commit()
        return ComplianceEvaluationResult(
            passed=False,
            checklist=create_empty_compliance_result(),
            missing_mandatory=["LLM_CALL_FAILED"],
            error=f"LLM call failed: {str(exc)}",
        )

    # --- Step 3: The Enforcer checks mandatory items ---
    mandatory_checks = {
        "Tax Document": compliance_result.has_tax_document,
        "Company Registration": compliance_result.has_company_registration,
        "Bid Bond": compliance_result.has_bid_bond,
        "Signature": compliance_result.has_signature,
    }
    missing_mandatory = [
        doc_name for doc_name, present in mandatory_checks.items() if not present
    ]

    # --- Step 4: Python makes the disqualification decision ---
    if missing_mandatory:
        logger.warning(
            "Offer {id} DISQUALIFIED: Missing mandatory documents: {missing}",
            id=offer.id,
            missing=missing_mandatory,
        )
        old_status = offer.status
        offer.status = OfferStatus.INCOMPLIANT
        offer.compliance_passed = False
        offer.disqualification_reason = (
            f"Missing mandatory documents: {', '.join(missing_mandatory)}. "
            f"Notes: {compliance_result.compliance_notes or 'None'}"
        )
        await log_event(
            db_session=db,
            action=ActionType.OFFER_DISQUALIFIED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=old_status,
            new_state="INCOMPLIANT",
            context={
                "missing_documents": missing_mandatory,
                "compliance_checklist": compliance_result.model_dump(),
            },
        )
        await db.commit()
        return ComplianceEvaluationResult(
            passed=False,
            checklist=compliance_result,
            missing_mandatory=missing_mandatory,
        )

    # --- Step 5: COMPLIANT ---
    old_status = offer.status
    offer.status = OfferStatus.COMPLIANT
    offer.compliance_passed = True
    await log_event(
        db_session=db,
        action=ActionType.COMPLIANCE_CHECKED,
        actor="SYSTEM",
        offer_id=offer.id,
        old_state=old_status,
        new_state="COMPLIANT",
        context={
            "compliance_checklist": compliance_result.model_dump(),
            "documents_found": compliance_result.documents_found,
        },
    )
    await db.commit()
    return ComplianceEvaluationResult(
        passed=True,
        checklist=compliance_result,
        missing_mandatory=[],
    )


# =============================================================================
# Phase 3: Technical Scoring
# =============================================================================


class TechnicalEvaluationResult:
    """Result container for technical evaluation."""

    def __init__(
        self,
        success: bool,
        score: TechnicalScore,
        normalized_score: float,
        error: str | None = None,
    ):
        self.success = success
        self.score = score
        self.normalized_score = normalized_score
        self.error = error


async def evaluate_technical_score(
    db: AsyncSession,
    offer: Offer,
    tender: Tender,
    rubric: str,
) -> TechnicalEvaluationResult:
    """
    Phase 3: Technical scoring.
    LLM scores against rubric; Python validates bounds and normalises.
    """
    logger.info("Starting technical scoring for offer {offer_id}", offer_id=offer.id)

    if offer.status != OfferStatus.COMPLIANT:
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"Offer not eligible for scoring (status: {offer.status})",
        )

    # Extract PDF text
    try:
        if not offer.storage_path:
            raise ValueError("Offer has no stored file path")
        pdf_text = extract_text_from_pdf(Path(offer.storage_path))
    except Exception as exc:
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"PDF extraction failed: {str(exc)}",
        )

    # Call LLM
    try:
        technical_result: TechnicalScore = await llm_score_technical(
            pdf_text=pdf_text,
            rubric=rubric,
        )
    except Exception as exc:
        await log_event(
            db_session=db,
            action=ActionType.SCORE_BOUNDS_VIOLATED,
            actor="SYSTEM",
            offer_id=offer.id,
            new_state="TECHNICAL_SCORING_FAILED",
            context={"reason": str(exc)},
        )
        await db.commit()
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"LLM call/validation failed: {str(exc)}",
        )

    # Python enforces score bounds
    calculated_total = technical_result.calculate_total()
    final_total = technical_result.total_raw_score or calculated_total
    normalized_score = float(max(0, min(100, final_total)))

    old_status = offer.status
    offer.status = OfferStatus.TECHNICAL_SCORED
    offer.technical_score = normalized_score

    await log_event(
        db_session=db,
        action=ActionType.TECHNICAL_SCORED,
        actor="SYSTEM",
        offer_id=offer.id,
        old_state=old_status,
        new_state="TECHNICAL_SCORED",
        context={
            "technical_score": normalized_score,
            "key_strengths": technical_result.key_strengths,
            "key_weaknesses": technical_result.key_weaknesses,
        },
    )
    await db.commit()

    logger.info(
        "Technical scoring complete for offer {id}: {score}/100",
        id=offer.id,
        score=normalized_score,
    )
    return TechnicalEvaluationResult(
        success=True,
        score=technical_result,
        normalized_score=normalized_score,
    )


# =============================================================================
# Phase 4: Financial Evaluation
# =============================================================================


class FinancialEvaluationResult:
    """Result container for financial evaluation."""

    def __init__(
        self,
        success: bool,
        financial_score: float,
        bid_price: float,
        currency: str,
        abnormal_price_flag: bool = False,
        error: str | None = None,
    ):
        self.success = success
        self.financial_score = financial_score
        self.bid_price = bid_price
        self.currency = currency
        self.abnormal_price_flag = abnormal_price_flag
        self.error = error


def compute_financial_score_lowest_price(
    bid_price: float,
    lowest_price: float,
) -> float:
    """
    Phase 4 — Lowest-Price Financial Scoring Formula (The Enforcer).

    Formula (public procurement standard):
        financial_score = (lowest_bid / this_bid) × 100

    This gives:
      - The cheapest bid: 100 points
      - All others: proportionally less
      - Python computes this — the LLM is never involved.
    """
    if bid_price <= 0:
        return 0.0
    score = (lowest_price / bid_price) * 100
    return round(min(100.0, max(0.0, score)), 2)


def compute_combined_score(technical: float, financial: float) -> float:
    """
    Phase 5 — Weighted Combined Score Formula (The Enforcer).

    combined = (technical × TECH_WEIGHT) + (financial × FIN_WEIGHT)

    Weights come from settings (DEFAULT_TECHNICAL_WEIGHT) — never from the LLM.
    """
    tech_weight = settings.DEFAULT_TECHNICAL_WEIGHT
    fin_weight = settings.financial_weight
    combined = (technical * tech_weight) + (financial * fin_weight)
    return round(min(100.0, max(0.0, combined)), 2)


async def evaluate_financial_score(
    db: AsyncSession,
    offer: Offer,
    tender: Tender,
    all_bid_prices: list[float],
) -> FinancialEvaluationResult:
    """
    Phase 4: Financial evaluation.

    Steps:
        1. LLM extracts the bid price from the PDF (text only, no math)
        2. Python computes the lowest-price score (formula above)
        3. Python flags abnormally low bids (< ABNORMALLY_LOW_PRICE_THRESHOLD_PCT
           below the average of all bids)
    """
    logger.info("Starting financial evaluation for offer {id}", id=offer.id)

    if offer.status not in (OfferStatus.TECHNICAL_SCORED, OfferStatus.COMPLIANT):
        return FinancialEvaluationResult(
            success=False,
            financial_score=0.0,
            bid_price=0.0,
            currency="UNKNOWN",
            error=f"Offer not in eligible status ({offer.status})",
        )

    # Extract PDF text
    try:
        if not offer.storage_path:
            raise ValueError("Offer has no stored file path")
        pdf_text = extract_text_from_pdf(Path(offer.storage_path))
    except Exception as exc:
        return FinancialEvaluationResult(
            success=False,
            financial_score=0.0,
            bid_price=0.0,
            currency="UNKNOWN",
            error=f"PDF extraction failed: {str(exc)}",
        )

    # LLM extracts the bid price (text extraction only — no math)
    try:
        financial_data: FinancialData = await llm_extract_financial(pdf_text=pdf_text)
    except Exception as exc:
        logger.error(
            "LLM financial extraction failed for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )
        return FinancialEvaluationResult(
            success=False,
            financial_score=0.0,
            bid_price=0.0,
            currency="UNKNOWN",
            error=f"LLM extraction failed: {str(exc)}",
        )

    bid_price = financial_data.total_bid_price or 0.0

    if bid_price <= 0:
        return FinancialEvaluationResult(
            success=False,
            financial_score=0.0,
            bid_price=bid_price,
            currency=financial_data.currency,
            error="Bid price is zero or negative — cannot score.",
        )

    # Python computes financial score using the lowest-price formula
    valid_prices = [p for p in all_bid_prices if p > 0]
    lowest_price = min(valid_prices) if valid_prices else bid_price
    financial_score = compute_financial_score_lowest_price(bid_price, lowest_price)

    # Abnormal low-price flag (Python math, not LLM)
    abnormal_flag = False
    if len(valid_prices) > 1:
        avg_price = sum(valid_prices) / len(valid_prices)
        pct_below_avg = ((avg_price - bid_price) / avg_price) * 100
        if pct_below_avg > settings.ABNORMALLY_LOW_PRICE_THRESHOLD_PCT:
            abnormal_flag = True
            logger.warning(
                "Abnormally low price detected for offer {id}: "
                "{price} is {pct:.1f}% below average {avg}",
                id=offer.id,
                price=bid_price,
                pct=pct_below_avg,
                avg=avg_price,
            )
            await log_event(
                db_session=db,
                action=ActionType.ABNORMAL_PRICE_FLAGGED,
                actor="SYSTEM",
                offer_id=offer.id,
                old_state=None,
                new_state="ABNORMAL_PRICE_FLAGGED",
                context={
                    "bid_price": bid_price,
                    "average_price": round(avg_price, 2),
                    "pct_below_avg": round(pct_below_avg, 2),
                    "threshold_pct": settings.ABNORMALLY_LOW_PRICE_THRESHOLD_PCT,
                    "requires_committee_review": True,
                },
            )

    # Update offer
    old_status = offer.status
    offer.financial_score = financial_score
    offer.status = OfferStatus.FINANCIAL_EXTRACTED

    await log_event(
        db_session=db,
        action=ActionType.FINANCIAL_EXTRACTED,
        actor="SYSTEM",
        offer_id=offer.id,
        old_state=old_status,
        new_state="FINANCIAL_EXTRACTED",
        context={
            "bid_price": bid_price,
            "currency": financial_data.currency,
            "financial_score": financial_score,
            "lowest_price_in_pool": lowest_price,
            "abnormal_price_flag": abnormal_flag,
        },
    )
    await db.commit()

    logger.info(
        "Financial evaluation complete for offer {id}: "
        "price={price} {curr}, score={score}/100",
        id=offer.id,
        price=bid_price,
        curr=financial_data.currency,
        score=financial_score,
    )

    return FinancialEvaluationResult(
        success=True,
        financial_score=financial_score,
        bid_price=bid_price,
        currency=financial_data.currency,
        abnormal_price_flag=abnormal_flag,
    )


# =============================================================================
# Phase 5: Combined Scoring & Ranking
# =============================================================================


async def compute_combined_scoring(
    db: AsyncSession,
    offer: Offer,
    tender: Tender,
) -> dict:
    """
    Phase 5: Compute the weighted combined score for an offer.

    Python runs this formula — only runs when both technical and financial
    scores are available. Returns a summary dict.
    """
    if offer.technical_score is None or offer.financial_score is None:
        return {
            "success": False,
            "error": "Both technical and financial scores required.",
        }

    technical = float(offer.technical_score)
    financial = float(offer.financial_score)
    combined = compute_combined_score(technical, financial)

    old_status = offer.status
    offer.total_score = combined
    offer.status = OfferStatus.COMBINED_SCORED

    await log_event(
        db_session=db,
        action=ActionType.COMBINED_SCORE_COMPUTED,
        actor="SYSTEM",
        offer_id=offer.id,
        old_state=old_status,
        new_state="COMBINED_SCORED",
        context={
            "technical_score": technical,
            "financial_score": financial,
            "combined_score": combined,
            "technical_weight": settings.DEFAULT_TECHNICAL_WEIGHT,
            "financial_weight": settings.financial_weight,
        },
    )
    await db.commit()

    logger.info(
        "Combined score computed for offer {id}: {combined}/100 "
        "(tech={t}×{tw} + fin={f}×{fw})",
        id=offer.id,
        combined=combined,
        t=technical,
        tw=settings.DEFAULT_TECHNICAL_WEIGHT,
        f=financial,
        fw=settings.financial_weight,
    )

    return {
        "success": True,
        "offer_id": offer.id,
        "technical_score": technical,
        "financial_score": financial,
        "combined_score": combined,
    }


# =============================================================================
# Batch Evaluation Entry Point (Phases 2–5)
# =============================================================================


async def evaluate_tender_offers(
    db: AsyncSession,
    tender_id: int,
    technical_rubric: str | None = None,
) -> dict:
    """
    Evaluate all eligible offers for a tender — Phases 2, 3, 4, and 5.

    Orchestration:
        1. Phase 2 (compliance) → all RECEIVED offers
        2. Phase 3 (technical)  → only compliant offers, only if rubric provided
        3. Phase 4 (financial)  → compliant offers; prices pooled for formula
        4. Phase 5 (combined)   → only when both scores exist
    """
    logger.info("Starting batch evaluation for tender {tender_id}", tender_id=tender_id)

    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()
    if tender is None:
        raise ValueError(f"Tender with ID {tender_id} not found")

    offers_result = await db.execute(
        select(Offer)
        .where(
            Offer.tender_id == tender_id,
            Offer.status.in_(
                [
                    OfferStatus.RECEIVED,
                    OfferStatus.COMPLIANT,
                    OfferStatus.TECHNICAL_SCORED,
                ]
            ),
        )
        .order_by(Offer.id)
    )
    offers = offers_result.scalars().all()

    if not offers:
        return {
            "tender_id": tender_id,
            "total_offers": 0,
            "processed": 0,
            "passed_compliance": 0,
            "failed_compliance": 0,
            "technical_scored": 0,
            "financial_scored": 0,
            "combined_scored": 0,
            "errors": [],
            "message": "No offers found for evaluation",
        }

    results: dict = {
        "tender_id": tender_id,
        "total_offers": len(offers),
        "processed": 0,
        "passed_compliance": 0,
        "failed_compliance": 0,
        "technical_scored": 0,
        "financial_scored": 0,
        "combined_scored": 0,
        "errors": [],
    }

    compliant_offers: list[Offer] = []

    # ── Phase 2: Compliance ───────────────────────────────────────────────────
    for offer in offers:
        try:
            compliance_result = await evaluate_offer_compliance(db, offer, tender)
            results["processed"] += 1
            if compliance_result.passed:
                results["passed_compliance"] += 1
                compliant_offers.append(offer)
            else:
                results["failed_compliance"] += 1
        except Exception as exc:
            logger.exception("Unexpected error in compliance for offer {id}", id=offer.id)
            results["errors"].append(
                {"offer_id": offer.id, "phase": "compliance", "error": str(exc)}
            )

    # ── Phase 3: Technical Scoring ────────────────────────────────────────────
    technically_scored: list[Offer] = []
    if technical_rubric and compliant_offers:
        for offer in compliant_offers:
            try:
                tech = await evaluate_technical_score(db, offer, tender, technical_rubric)
                if tech.success:
                    results["technical_scored"] += 1
                    technically_scored.append(offer)
                else:
                    results["errors"].append(
                        {"offer_id": offer.id, "phase": "technical", "error": tech.error}
                    )
            except Exception as exc:
                logger.exception("Technical scoring error for offer {id}", id=offer.id)
                results["errors"].append(
                    {"offer_id": offer.id, "phase": "technical", "error": str(exc)}
                )

    # ── Phase 4: Financial Evaluation ─────────────────────────────────────────
    # First pass: collect all bid prices for the pool (needed for lowest-price formula)
    financial_pool: dict[int, float] = {}  # offer_id → bid_price placeholder
    # We'll do a two-pass approach: extract prices first, then score
    price_extraction_results: dict[int, FinancialEvaluationResult] = {}

    for_financial = technically_scored if technical_rubric else compliant_offers

    # Extract prices (pass 1)
    for offer in for_financial:
        try:
            fin = await evaluate_financial_score(
                db, offer, tender, all_bid_prices=[]  # no pool yet
            )
            price_extraction_results[offer.id] = fin
            if fin.success:
                financial_pool[offer.id] = fin.bid_price
        except Exception as exc:
            results["errors"].append(
                {"offer_id": offer.id, "phase": "financial_extraction", "error": str(exc)}
            )

    all_prices = list(financial_pool.values())

    # Re-score using the full price pool (pass 2) — updates financial_score
    for offer in for_financial:
        if offer.id in financial_pool and all_prices:
            old_score = offer.financial_score
            new_score = compute_financial_score_lowest_price(
                financial_pool[offer.id], min(all_prices)
            )
            if abs((old_score or 0) - new_score) > 0.01:
                offer.financial_score = new_score
                await db.commit()
            results["financial_scored"] += 1

    # ── Phase 5: Combined Scoring ─────────────────────────────────────────────
    await db.refresh  # re-read fresh state
    for offer in for_financial:
        if offer.id in financial_pool:
            try:
                await db.refresh(offer)
                combined = await compute_combined_scoring(db, offer, tender)
                if combined.get("success"):
                    results["combined_scored"] += 1
            except Exception as exc:
                results["errors"].append(
                    {"offer_id": offer.id, "phase": "combined_score", "error": str(exc)}
                )

    logger.info(
        "Batch evaluation complete for tender {tid}: "
        "{pass_}/{total} compliant, {tech} technical, {fin} financial, {comb} combined",
        tid=tender_id,
        pass_=results["passed_compliance"],
        total=results["total_offers"],
        tech=results["technical_scored"],
        fin=results["financial_scored"],
        comb=results["combined_scored"],
    )

    return results
