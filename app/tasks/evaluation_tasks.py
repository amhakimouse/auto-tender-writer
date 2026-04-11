"""
app/tasks/evaluation_tasks.py

Celery background tasks for the automated evaluation pipeline (Phases 2-5).

Why background tasks?
  LLM evaluation of a single offer takes 5-60 seconds depending on PDF length
  and model latency. For tenders with 20+ offers, sequential evaluation would
  make the API hang for minutes. Celery runs each offer asynchronously.

Task design rules (Architecture Golden Rules):
  1. Tasks are THIN — they only set up a DB session and call service functions.
  2. All LLM calls and DB mutations happen inside the service layer.
  3. Tasks are idempotent — re-running on already-evaluated offers is safe
     (the service checks offer.status before processing).
  4. Retry on transient LLM or DB errors (max 3 retries, 30s delay).

Usage from a router:
  from app.tasks.evaluation_tasks import evaluate_offer_task
  task = evaluate_offer_task.delay(offer_id=42, rubric="...")
  return {"task_id": task.id, "status": "accepted"}
"""

from __future__ import annotations

import asyncio

from celery import shared_task
from loguru import logger


@shared_task(
    name="app.tasks.evaluation_tasks.evaluate_offer_task",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def evaluate_offer_task(
    self,
    offer_id: int,
    technical_rubric: str | None = None,
) -> dict:
    """
    Background task: run full evaluation pipeline (Phase 2-5) for a single offer.

    Args:
        offer_id:         The ID of the offer to evaluate.
        technical_rubric: Optional rubric JSON string for Phase 3 scoring.
                          If None, only compliance (Phase 2) is run.

    Returns:
        Dict with evaluation summary (passed_compliance, technical_score, etc.)

    Raises:
        Retried up to 3 times on transient exceptions (LLM timeout, DB errors).
    """
    async def _run():
        from sqlalchemy import select
        from app.db.session import async_session_factory
        from app.db.models import Offer, Tender
        from app.services.evaluation_service import (
            evaluate_offer_compliance,
            evaluate_technical_score,
        )

        async with async_session_factory() as db:
            # Load offer + tender
            offer_result = await db.execute(select(Offer).where(Offer.id == offer_id))
            offer = offer_result.scalar_one_or_none()

            if offer is None:
                logger.warning("evaluate_offer_task: offer {id} not found", id=offer_id)
                return {"error": f"Offer {offer_id} not found"}

            tender_result = await db.execute(
                select(Tender).where(Tender.id == offer.tender_id)
            )
            tender = tender_result.scalar_one_or_none()

            if tender is None:
                return {"error": f"Tender for offer {offer_id} not found"}

            # Phase 2: Compliance
            compliance = await evaluate_offer_compliance(db, offer, tender)
            result: dict = {
                "offer_id": offer_id,
                "compliance_passed": compliance.passed,
                "missing_documents": compliance.missing_mandatory,
                "technical_score": None,
            }

            # Phase 3: Technical (only if compliant + rubric provided)
            if compliance.passed and technical_rubric:
                tech = await evaluate_technical_score(db, offer, tender, technical_rubric)
                result["technical_score"] = tech.normalized_score if tech.success else None

            return result

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "evaluate_offer_task failed for offer {id}: {err}",
            id=offer_id,
            err=str(exc),
        )
        raise self.retry(exc=exc)


@shared_task(
    name="app.tasks.evaluation_tasks.evaluate_tender_batch_task",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def evaluate_tender_batch_task(
    self,
    tender_id: int,
    technical_rubric: str | None = None,
) -> dict:
    """
    Background task: run batch evaluation (Phase 2-5) for ALL offers in a tender.

    This is the high-level task triggered by POST /evaluation/tenders/{id}/evaluate
    when Celery is configured. Returns a summary dict.
    """
    async def _run():
        from app.db.session import async_session_factory
        from app.services.evaluation_service import evaluate_tender_offers

        async with async_session_factory() as db:
            return await evaluate_tender_offers(
                db=db,
                tender_id=tender_id,
                technical_rubric=technical_rubric,
            )

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "evaluate_tender_batch_task failed for tender {id}: {err}",
            id=tender_id,
            err=str(exc),
        )
        raise self.retry(exc=exc)
