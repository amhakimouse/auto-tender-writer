"""
app/services/evaluation_service.py

Person 2 — Validation + Refinement Loop (Business Logic Layer)

This service is the "enforcer" for the validation pipeline:
  1. Call the LLM orchestrator to validate the dossier.
  2. If score < REFINEMENT_THRESHOLD → trigger a refinement pass.
  3. Re-validate the refined dossier (max MAX_REFINEMENT_ATTEMPTS times).
  4. Return the final ValidationReportResponse to the API layer.

Golden Rule: This service never writes to the DB and never calls the LLM
directly. All LLM calls go through app/llm/orchestrator.py.
"""

from __future__ import annotations

from loguru import logger

from app.llm import orchestrator
from app.schemas.evaluation import ValidationReportResponse
from app.schemas.llm_output import ValidationReportLLM

# ── Tuneable constants ────────────────────────────────────────────────────────

# Score below which refinement is automatically triggered (matches scoring rules)
REFINEMENT_THRESHOLD: int = 60

# Maximum refinement iterations to avoid infinite loops at 3 AM 😅
MAX_REFINEMENT_ATTEMPTS: int = 2


# ── Public API ────────────────────────────────────────────────────────────────

async def validate_and_refine(
    requirements: dict,
    dossier: dict,
) -> ValidationReportResponse:
    """
    Full Person 2 pipeline:
      1. Validate dossier against requirements (LLM call #1)
      2. If score < 60 → refine dossier (LLM call #2)
      3. Re-validate refined dossier (LLM call #3)
      4. Return the best ValidationReportResponse

    Args:
        requirements : extracted tender requirements dict (Person 1A output)
        dossier      : generated response dossier dict (Person 1B output)

    Returns:
        ValidationReportResponse ready to be serialised by the FastAPI router.
    """
    # ── Step 1: Initial validation ────────────────────────────────────────
    logger.info("=== Validation pipeline start ===")
    report: ValidationReportLLM = await orchestrator.validate_dossier(
        requirements=requirements,
        dossier=dossier,
    )

    logger.info(
        "Initial score: {score}/100  verdict: {verdict}  "
        "eliminating clauses: {n}",
        score=report.score,
        verdict=report.verdict,
        n=len(report.clauses_eliminatoires),
    )

    # ── Step 2: Refinement loop ───────────────────────────────────────────
    current_dossier = dossier
    refinement_attempts = 0

    while report.score < REFINEMENT_THRESHOLD and refinement_attempts < MAX_REFINEMENT_ATTEMPTS:
        refinement_attempts += 1
        logger.info(
            "Score {score} < {threshold} — refinement attempt {attempt}/{max}",
            score=report.score,
            threshold=REFINEMENT_THRESHOLD,
            attempt=refinement_attempts,
            max=MAX_REFINEMENT_ATTEMPTS,
        )

        try:
            # Ask the LLM to fix the failing sections
            refined_dossier = await orchestrator.refine_dossier(
                dossier=current_dossier,
                validation_report=report,
                requirements=requirements,
            )

            # Merge: keep refinement keys, fall back to original for any missing keys
            current_dossier = {**current_dossier, **refined_dossier}

            # Re-validate the improved dossier
            report = await orchestrator.validate_dossier(
                requirements=requirements,
                dossier=current_dossier,
            )
            logger.info(
                "Post-refinement score: {score}/100  verdict: {verdict}",
                score=report.score,
                verdict=report.verdict,
            )

        except Exception as exc:
            # Refinement failed — log and break rather than crashing the request
            logger.error(
                "Refinement attempt {n} failed: {err} — keeping best result so far",
                n=refinement_attempts,
                err=str(exc),
            )
            break

    logger.info(
        "=== Validation pipeline end — final score: {score}  refined: {r} ===",
        score=report.score,
        r=refinement_attempts > 0,
    )

    # ── Step 3: Project LLM model → API response model ───────────────────
    return _to_api_response(report, refinement_attempts)


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
    )
