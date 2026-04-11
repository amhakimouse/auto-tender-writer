"""
app/services/evaluation_service.py

The Evaluation Service — Python The Enforcer.

This module orchestrates the evaluation workflow (Phases 2-5):
    - Phase 2: Administrative Compliance Check
    - Phase 3: Technical Scoring
    - Phase 4: Financial Evaluation
    - Phase 5: Combined Scoring & Ranking

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
)
from app.schemas.llm_schemas import (
    ComplianceChecklist,
    TechnicalScore,
    create_empty_compliance_result,
    create_empty_technical_score,
)
from app.utils.audit_logger import ActionType, log_event
from app.utils.file_parser import extract_text_from_pdf

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# Phase 2: Administrative Compliance Check
# =============================================================================

<<<<<<< HEAD

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
=======
async def validate_and_refine(
    requirements: dict,
    dossier: dict,
) -> tuple[ValidationReportResponse, dict]:
    """
    Full Person 2 pipeline:
      1. Validate dossier against requirements (LLM call #1)
      2. If score < 60 → refine dossier (LLM call #2)
      3. Re-validate refined dossier (LLM call #3)
      4. Return the best ValidationReportResponse and the final dossier.
>>>>>>> 752ca9c (feat: implement automated tender dossier validation and refinement pipeline using multi-phase LLM orchestration)

    Args:
        db: Database session
        offer: The offer to evaluate
        tender: The tender this offer responds to

    Returns:
<<<<<<< HEAD
        ComplianceEvaluationResult with pass/fail status
=======
        tuple containing (ValidationReportResponse, final_dossier_dict).
>>>>>>> 752ca9c (feat: implement automated tender dossier validation and refinement pipeline using multi-phase LLM orchestration)
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

        # Log the extraction failure
        await log_event(
            db_session=db,
            action=ActionType.OFFER_DISQUALIFIED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=offer.status,
            new_state="DISQUALIFIED_EXTRACTION_FAILED",
            context={
                "reason": f"PDF text extraction failed: {str(exc)}",
                "error_type": type(exc).__name__,
            },
        )
        await db.commit()

        # Update offer status
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

    except ValidationError as exc:
        # LLM returned invalid JSON that doesn't match schema
        logger.error(
            "LLM compliance output failed Pydantic validation for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )

        await log_event(
            db_session=db,
            action=ActionType.OFFER_DISQUALIFIED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=offer.status,
            new_state="DISQUALIFIED_VALIDATION_ERROR",
            context={
                "reason": "LLM compliance output failed Pydantic validation",
                "validation_errors": exc.errors(),
            },
        )
        await db.commit()

        offer.status = OfferStatus.INCOMPLIANT
        offer.compliance_passed = False
        offer.disqualification_reason = (
            "Compliance check failed: LLM output validation error"
        )
        await db.commit()

        return ComplianceEvaluationResult(
            passed=False,
            checklist=create_empty_compliance_result(),
            missing_mandatory=["LLM_VALIDATION_FAILED"],
            error=f"Pydantic validation error: {str(exc)}",
        )

    except Exception as exc:
        # LLM call failed (network, timeout, etc.)
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
            context={
                "reason": f"LLM compliance call failed: {str(exc)}",
                "error_type": type(exc).__name__,
            },
        )
        await db.commit()

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
        # DISQUALIFIED: Missing mandatory documents
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
            f"Additional notes: {compliance_result.compliance_notes or 'None'}"
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
                "reason": f"Missing mandatory: {', '.join(missing_mandatory)}",
            },
        )
        await db.commit()

        return ComplianceEvaluationResult(
            passed=False,
            checklist=compliance_result,
            missing_mandatory=missing_mandatory,
        )

    # --- Step 5: COMPLIANT ---
    logger.info(
        "Offer {id} PASSED compliance check. Documents found: {found}",
        id=offer.id,
        found=compliance_result.documents_found,
    )

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
            "extraction_confidence": compliance_result.extraction_confidence,
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
        normalized_score: float,  # 0-100
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

    The Enforcer's Rules:
        1. Call LLM to score against rubric
        2. Validate LLM output (Pydantic + score bounds)
        3. Python calculates the normalized technical score (0-100)
        4. Store the score in offer.technical_score
        5. Log to audit trail

    Args:
        db: Database session
        offer: The compliant offer to score
        tender: The tender this offer responds to
        rubric: The evaluation rubric (JSON string or structured text)

    Returns:
        TechnicalEvaluationResult with score details
    """
    logger.info(
        "Starting technical scoring for offer {offer_id}",
        offer_id=offer.id,
    )

    # Only score compliant offers
    if offer.status != OfferStatus.COMPLIANT:
        logger.warning(
            "Cannot score non-compliant offer {id} (status: {status})",
            id=offer.id,
            status=offer.status,
        )
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"Offer not eligible for scoring (status: {offer.status})",
        )

    # Extract text from PDF
    try:
        if not offer.storage_path:
            raise ValueError("Offer has no stored file path")

        pdf_path = Path(offer.storage_path)
        pdf_text = extract_text_from_pdf(pdf_path)

    except Exception as exc:
        logger.error(
            "PDF extraction failed for technical scoring (offer {id}): {error}",
            id=offer.id,
            error=str(exc),
        )
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"PDF extraction failed: {str(exc)}",
        )

    # Call LLM for technical scoring
    try:
        technical_result: TechnicalScore = await llm_score_technical(
            pdf_text=pdf_text,
            rubric=rubric,
        )

    except ValidationError as exc:
        logger.error(
            "LLM technical scoring failed validation for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )

        await log_event(
            db_session=db,
            action=ActionType.SCORE_BOUNDS_VIOLATED,
            actor="SYSTEM",
            offer_id=offer.id,
            old_state=None,
            new_state="TECHNICAL_SCORING_FAILED",
            context={
                "reason": "Technical scoring validation failed",
                "validation_errors": exc.errors(),
            },
        )
        await db.commit()

        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"Validation error: {str(exc)}",
        )

    except Exception as exc:
        logger.error(
            "LLM technical scoring call failed for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )
        return TechnicalEvaluationResult(
            success=False,
            score=create_empty_technical_score(),
            normalized_score=0.0,
            error=f"LLM call failed: {str(exc)}",
        )

    # The Enforcer: Validate and normalize the score
    try:
        # Calculate total from criteria scores
        calculated_total = technical_result.calculate_total()

        # Use LLM's total if provided, otherwise calculated
        final_total = technical_result.total_raw_score or calculated_total

        # Ensure total is within bounds
        if final_total < 0:
            final_total = 0
        if final_total > 100:
            logger.warning(
                "LLM returned technical score {raw} > 100, capping at 100",
                raw=final_total,
            )
            final_total = 100

        normalized_score = float(final_total)

    except Exception as exc:
        logger.error(
            "Score normalization failed for offer {id}: {error}",
            id=offer.id,
            error=str(exc),
        )
        return TechnicalEvaluationResult(
            success=False,
            score=technical_result,
            normalized_score=0.0,
            error=f"Score normalization failed: {str(exc)}",
        )

    # Update offer
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
            "criteria_scores": [
                {
                    "criterion": c.criterion,
                    "score": c.raw_score,
                    "max": c.max_score,
                }
                for c in technical_result.criteria_scores
            ],
            "scoring_confidence": technical_result.scoring_confidence,
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

<<<<<<< HEAD
    return TechnicalEvaluationResult(
        success=True,
        score=technical_result,
        normalized_score=normalized_score,
=======
    # ── Step 3: Return result pair ────────────────────────────────────────
    return _to_api_response(report, refinement_attempts), current_dossier


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_api_response(
    report: ValidationReportLLM,
    refinement_attempts: int,
) -> ValidationReportResponse:
    """
    Map the internal LLM Pydantic model to the public API response schema.
    Keeps the two schemas decoupled so we can evolve them independently.
    """
    return ValidationReportResponse(
        score=report.score,
        verdict=report.verdict,
        sections_conformes=report.sections_conformes,
        sections_manquantes=report.sections_manquantes,
        clauses_eliminatoires=report.clauses_eliminatoires,
        points_faibles=report.points_faibles,
        recommandations=report.recommandations,
        refined=refinement_attempts > 0,
        refinement_attempts=refinement_attempts,
>>>>>>> 752ca9c (feat: implement automated tender dossier validation and refinement pipeline using multi-phase LLM orchestration)
    )


# =============================================================================
# Batch Evaluation Entry Point
# =============================================================================


async def evaluate_tender_offers(
    db: AsyncSession,
    tender_id: int,
    technical_rubric: str | None = None,
) -> dict:
    """
    Evaluate all eligible offers for a tender.

    This is the main entry point called by the evaluation API endpoint.

    Args:
        db: Database session
        tender_id: The tender to evaluate offers for
        technical_rubric: Optional rubric for technical scoring

    Returns:
        Summary of evaluation results
    """
    logger.info(
        "Starting batch evaluation for tender {tender_id}",
        tender_id=tender_id,
    )

    # Get tender
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise ValueError(f"Tender with ID {tender_id} not found")

    # Get all offers in RECEIVED status (ready for evaluation)
    offers_result = await db.execute(
        select(Offer)
        .where(
            Offer.tender_id == tender_id,
            Offer.status.in_([OfferStatus.RECEIVED, OfferStatus.COMPLIANT]),
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
            "message": "No offers found for evaluation",
        }

    # Process each offer
    results = {
        "tender_id": tender_id,
        "total_offers": len(offers),
        "processed": 0,
        "passed_compliance": 0,
        "failed_compliance": 0,
        "technical_scored": 0,
        "errors": [],
    }

    for offer in offers:
        try:
            # Phase 2: Compliance Check
            compliance_result = await evaluate_offer_compliance(db, offer, tender)
            results["processed"] += 1

            if compliance_result.passed:
                results["passed_compliance"] += 1

                # Phase 3: Technical Scoring (if rubric provided)
                if technical_rubric:
                    tech_result = await evaluate_technical_score(
                        db, offer, tender, technical_rubric
                    )
                    if tech_result.success:
                        results["technical_scored"] += 1
                    else:
                        results["errors"].append(
                            {
                                "offer_id": offer.id,
                                "phase": "technical_scoring",
                                "error": tech_result.error,
                            }
                        )
            else:
                results["failed_compliance"] += 1

        except Exception as exc:
            logger.exception(
                "Unexpected error evaluating offer {id}",
                id=offer.id,
            )
            results["errors"].append(
                {
                    "offer_id": offer.id,
                    "phase": "unknown",
                    "error": str(exc),
                }
            )

    logger.info(
        "Batch evaluation complete for tender {tender_id}: {passed}/{total} passed compliance",
        tender_id=tender_id,
        passed=results["passed_compliance"],
        total=results["total_offers"],
    )

    return results


# Import Path for type hints
from pathlib import Path
