"""
app/tasks/notification_tasks.py

Celery background tasks for Phase 7 (Award Letters) and Phase 8 (Appeal Acks).

Design principle: the LLM drafts the letter text; Python decides what to do with
it (log it, send it, store it). Tasks here are the glue between the award/appeal
decision and the actual letter generation + delivery.
"""

from __future__ import annotations

import asyncio

from celery import shared_task
from loguru import logger


@shared_task(
    name="app.tasks.notification_tasks.draft_award_letters_task",
    bind=True,
    max_retries=3,
    default_retry_delay=15,
    acks_late=True,
)
def draft_award_letters_task(
    self,
    tender_id: int,
    winner_offer_id: int,
    loser_offer_ids: list[int],
) -> dict:
    """
    Background task: use LLM (Gemini) to draft award and rejection letters
    for all offers in a just-decided tender.

    Args:
        tender_id:        The tender that was just awarded.
        winner_offer_id:  The winning offer — gets an award letter.
        loser_offer_ids:  All other offers — get rejection letters.

    Returns:
        Dict mapping offer_id → letter_text.
    """
    async def _run() -> dict:
        from sqlalchemy import select
        from app.db.session import async_session_factory
        from app.db.models import Offer, Tender
        from app.llm.orchestrator import draft_narrative

        letters: dict = {}

        async with async_session_factory() as db:
            tender_result = await db.execute(
                select(Tender).where(Tender.id == tender_id)
            )
            tender = tender_result.scalar_one_or_none()
            if not tender:
                return {"error": f"Tender {tender_id} not found"}

            # Draft award letter for winner
            winner_result = await db.execute(
                select(Offer).where(Offer.id == winner_offer_id)
            )
            winner = winner_result.scalar_one_or_none()
            if winner:
                try:
                    award_letter = await draft_narrative(
                        system_prompt=(
                            "You are a procurement officer drafting a formal award "
                            "notification letter. Be professional and concise. "
                            "Return ONLY the letter body — no JSON, no subject line."
                        ),
                        user_prompt=(
                            f"Tender: {tender.title} (Ref: {tender.reference_number or 'N/A'})\n"
                            f"Winning Bidder: {winner.bidder_name}\n"
                            f"Final Score: {float(winner.total_score or 0):.1f}/100\n\n"
                            "Draft an award notification letter congratulating the bidder, "
                            "confirming the award, and requesting they contact the procurement "
                            "office within 5 working days for contract signing."
                        ),
                        temperature=0.3,
                        max_tokens=500,
                    )
                    letters[winner_offer_id] = award_letter
                except Exception as exc:
                    logger.warning(
                        "Award letter generation failed for offer {id}: {err}",
                        id=winner_offer_id,
                        err=str(exc),
                    )

            # Draft rejection letters for all losers
            for loser_id in loser_offer_ids:
                loser_result = await db.execute(
                    select(Offer).where(Offer.id == loser_id)
                )
                loser = loser_result.scalar_one_or_none()
                if not loser:
                    continue
                try:
                    rejection_letter = await draft_narrative(
                        system_prompt=(
                            "You are a procurement officer drafting a formal bid rejection "
                            "letter. Be professional and respectful. Do NOT reveal the winner's "
                            "name or score. Return ONLY the letter body."
                        ),
                        user_prompt=(
                            f"Tender: {tender.title} (Ref: {tender.reference_number or 'N/A'})\n"
                            f"Bidder: {loser.bidder_name}\n"
                            f"Their Score: {float(loser.total_score or 0):.1f}/100\n\n"
                            "Inform them of the unsuccessful bid, thank them for participating, "
                            "and advise they may request evaluation feedback within 30 days."
                        ),
                        temperature=0.3,
                        max_tokens=400,
                    )
                    letters[loser_id] = rejection_letter
                except Exception as exc:
                    logger.warning(
                        "Rejection letter failed for offer {id}: {err}",
                        id=loser_id,
                        err=str(exc),
                    )

        return letters

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "draft_award_letters_task failed for tender {id}: {err}",
            id=tender_id,
            err=str(exc),
        )
        raise self.retry(exc=exc)


@shared_task(
    name="app.tasks.notification_tasks.draft_appeal_ack_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    acks_late=True,
)
def draft_appeal_ack_task(
    self,
    offer_id: int,
    case_reference: str,
    appeal_grounds: str,
) -> dict:
    """
    Background task: use LLM to draft an appeal acknowledgement letter (Phase 8).

    Args:
        offer_id:        The offer that was appealed.
        case_reference:  The unique case reference (APP-{id}-{hash}).
        appeal_grounds:  The bidder's stated grounds (truncated for LLM call).

    Returns:
        Dict with offer_id and the generated acknowledgement_text.
    """
    async def _run() -> dict:
        from sqlalchemy import select
        from app.db.session import async_session_factory
        from app.db.models import Offer
        from app.llm.orchestrator import draft_narrative

        async with async_session_factory() as db:
            offer_result = await db.execute(
                select(Offer).where(Offer.id == offer_id)
            )
            offer = offer_result.scalar_one_or_none()
            if not offer:
                return {"error": f"Offer {offer_id} not found"}

            ack = await draft_narrative(
                system_prompt=(
                    "You are a procurement officer drafting a formal appeal acknowledgement. "
                    "Be professional, neutral, and do NOT pre-judge the appeal outcome. "
                    "Return ONLY the letter body."
                ),
                user_prompt=(
                    f"Bidder: {offer.bidder_name}\n"
                    f"Offer ID: {offer_id}\n"
                    f"Case Reference: {case_reference}\n"
                    f"Appeal Grounds (summary): {appeal_grounds[:500]}\n\n"
                    "Confirm receipt of the appeal, provide the case reference, "
                    "state it will be reviewed within 15 working days, and advise "
                    "the bidder to submit any supporting documents."
                ),
                temperature=0.3,
                max_tokens=400,
            )

        return {
            "offer_id": offer_id,
            "case_reference": case_reference,
            "acknowledgement_text": ack,
        }

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "draft_appeal_ack_task failed for offer {id}: {err}",
            id=offer_id,
            err=str(exc),
        )
        raise self.retry(exc=exc)
