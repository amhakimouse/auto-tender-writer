"""
app/services/evaluation_service.py

The Evaluation Service — Python The Enforcer.

This module orchestrates the evaluation workflow (Phases 2-5):
    - Phase 2: Administrative Compliance Check
    - Phase 3: Technical Scoring
    - Phase 4: Financial Evaluation
    - Phase 5: Combined Scoring & Ranking
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from pathlib import Path

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
    validate_dossier as llm_validate_dossier,
    refine_dossier_specialized as llm_refine_dossier
)
from app.schemas.llm_schemas import (
    ComplianceChecklist,
    TechnicalScore,
    create_empty_compliance_result,
    create_empty_technical_score,
)
from app.schemas.llm_output import ValidationReportLLM
from app.schemas.evaluation import ValidationReportResponse
from app.utils.audit_logger import ActionType, log_event
from app.utils.file_parser import extract_text_from_pdf

if TYPE_CHECKING:
    from pathlib import Path


# =============================================================================
# Phase 2: Administrative Compliance Check (Batch)
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
    """
    logger.info(
        "Starting compliance evaluation for offer {offer_id} (tender {tender_id})",
        offer_id=offer.id,
        tender_id=tender.id,
    )

    try:
        if not offer.storage_path:
            raise ValueError("Offer has no stored file path")

        pdf_path = Path(offer.storage_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found at {pdf_path}")

        pdf_text = extract_text_from_pdf(pdf_path)

    except Exception as exc:
        logger.error("Failed to extract PDF text for offer {id}: {error}", id=offer.id, error=str(exc))
        return ComplianceEvaluationResult(
            passed=False,
            checklist=create_empty_compliance_result(),
            missing_mandatory=["PDF_EXTRACTION_FAILED"],
            error=str(exc),
        )

    try:
        compliance_result: ComplianceChecklist = await llm_evaluate_compliance(pdf_text=pdf_text)
        
        # Enforcer logic
        mandatory_checks = {
            "Tax Document": compliance_result.has_tax_document,
            "Company Registration": compliance_result.has_company_registration,
            "Bid Bond": compliance_result.has_bid_bond,
            "Signature": compliance_result.has_signature,
        }
        missing_mandatory = [doc for doc, present in mandatory_checks.items() if not present]
        
        passed = len(missing_mandatory) == 0
        offer.status = OfferStatus.COMPLIANT if passed else OfferStatus.INCOMPLIANT
        offer.compliance_passed = passed
        if not passed:
            offer.disqualification_reason = f"Missing: {', '.join(missing_mandatory)}"
        
        await db.commit()
        return ComplianceEvaluationResult(passed=passed, checklist=compliance_result, missing_mandatory=missing_mandatory)

    except Exception as exc:
        logger.error("Compliance evaluation failed: {error}", error=str(exc))
        return ComplianceEvaluationResult(False, create_empty_compliance_result(), ["LLM_ERROR"], str(exc))


# =============================================================================
# Person 2 Journey: Validate & Refine (Writer Loop)
# =============================================================================

async def validate_and_refine(
    requirements: dict,
    dossier: dict,
) -> tuple[ValidationReportResponse, dict]:
    """
    Full Person 2 pipeline:
      1. Validate dossier against requirements
      2. If score < 60 → refine dossier
      3. Return result and final dossier.
    """
    logger.info("Starting live dossier validation/refinement...")
    
    # Pass 1: Initial Validation
    report = await llm_validate_dossier(requirements, dossier)
    current_dossier = dossier
    refinement_attempts = 0

    if report.score < 60:
        logger.info("Score below threshold ({s}), attempting refinement...", s=report.score)
        current_dossier = await llm_refine_dossier(dossier, report, requirements)
        # Pass 2: Final Validation
        report = await llm_validate_dossier(requirements, current_dossier)
        refinement_attempts = 1

    return _to_api_response(report, refinement_attempts), current_dossier


def _to_api_response(
    report: ValidationReportLLM,
    refinement_attempts: int,
) -> ValidationReportResponse:
    """Map internal model to API response."""
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
    )


# =============================================================================
# Phase 3: Technical Scoring (Batch)
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
    """Technical scoring integration."""
    try:
        pdf_path = Path(offer.storage_path)
        pdf_text = extract_text_from_pdf(pdf_path)
        technical_result = await llm_score_technical(pdf_text=pdf_text, rubric=rubric)
        
        score = float(technical_result.total_raw_score or technical_result.calculate_total())
        offer.status = OfferStatus.TECHNICAL_SCORED
        offer.technical_score = min(max(score, 0), 100)
        await db.commit()
        
        return TechnicalEvaluationResult(True, technical_result, offer.technical_score)
    except Exception as exc:
        return TechnicalEvaluationResult(False, create_empty_technical_score(), 0.0, str(exc))

async def evaluate_tender_offers(
    db: AsyncSession,
    tender_id: int,
    technical_rubric: str | None = None,
) -> dict:
    """Batch evaluation entry point."""
    logger.info("Starting batch evaluation for tender {id}", id=tender_id)
    
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()
    if not tender: raise ValueError("Tender not found")

    offers_result = await db.execute(select(Offer).where(Offer.tender_id == tender_id))
    offers = offers_result.scalars().all()
    
    # Basic results tracking
    results = {"total": len(offers), "processed": 0, "passed": 0}
    for offer in offers:
        res = await evaluate_offer_compliance(db, offer, tender)
        if res.passed:
            results["passed"] += 1
            if technical_rubric:
                await evaluate_technical_score(db, offer, tender, technical_rubric)
        results["processed"] += 1
        
    return results
