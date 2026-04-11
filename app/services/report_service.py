"""
app/services/report_service.py

The Report Service — Phase 9: Audit Trail and Archive Closure.

This module orchestrates:
    - Python (The Enforcer): Aggregates all tender statistics deterministically
    - LLM (The Reasoner): Generates plain-English executive summaries for auditors

Architecture Rules:
    1. Python NEVER trusts the LLM for statistics — all numbers computed deterministically.
    2. LLM only generates narrative text from the provided statistics.
    3. All state changes logged to audit trail.
    4. Reports are immutable once finalized.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Appeal, AuditLog, Offer, OfferStatus, Tender
from app.db.models.tender import TenderStatus
from app.llm.client import call_llm
from app.schemas.report_schemas import (
    ClosureReport,
    ExecutiveSummary,
    TenderStatistics,
    create_empty_executive_summary,
)
from app.services.appeal_service import get_appeal_statistics
from app.utils.audit_logger import ActionType, log_event


# =============================================================================
# Phase 9: Statistics Aggregation (Python The Enforcer)
# =============================================================================


async def aggregate_tender_statistics(
    db: AsyncSession,
    tender_id: int,
) -> TenderStatistics | None:
    """
    Aggregate all deterministic statistics for a tender.

    ## The Enforcer's Rules:

    1. Fetch all offers for the tender
    2. Compute mathematical aggregates (counts, averages, min/max)
    3. Count committee actions (overrides, ties)
    4. Count appeals
    5. Return strictly validated TenderStatistics
    """
    logger.info("Aggregating statistics for tender {tender_id}", tender_id=tender_id)

    # --- Step 1: Fetch Tender ---
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        logger.warning(
            "Tender {tender_id} not found for statistics", tender_id=tender_id
        )
        return None

    # --- Step 2: Fetch All Offers ---
    offers_result = await db.execute(select(Offer).where(Offer.tender_id == tender_id))
    offers = offers_result.scalars().all()

    # --- Step 3: Compute Offer Counts ---
    total_offers = len(offers)
    offers_compliant = sum(
        1
        for o in offers
        if o.status
        in (
            OfferStatus.COMPLIANT,
            OfferStatus.TECHNICAL_SCORED,
            OfferStatus.TECHNICAL_SCORED,
            OfferStatus.FINANCIAL_EXTRACTED,
            OfferStatus.COMBINED_SCORED,
            OfferStatus.COMMITTEE_REVIEW,
            OfferStatus.AWARDED,
            OfferStatus.REJECTED_FINAL,
            OfferStatus.APPEALED,
        )
    )
    offers_incompliant = sum(1 for o in offers if o.status == OfferStatus.INCOMPLIANT)
    offers_technically_scored = sum(1 for o in offers if o.technical_score is not None)
    offers_financially_scored = sum(1 for o in offers if o.financial_score is not None)
    offers_combined_scored = sum(1 for o in offers if o.total_score is not None)

    # --- Step 4: Compute Financial Statistics ---
    compliant_offers = [o for o in offers if o.status != OfferStatus.INCOMPLIANT]
    bid_prices = []
    for o in compliant_offers:
        # Get bid price from audit log (financial extraction event)
        price = await _get_offer_bid_price(db, o.id)
        if price and price > 0:
            bid_prices.append(price)

    average_bid_price = sum(bid_prices) / len(bid_prices) if bid_prices else None
    lowest_bid_price = min(bid_prices) if bid_prices else None
    highest_bid_price = max(bid_prices) if bid_prices else None

    # --- Step 5: Compute Scoring Statistics ---
    technical_scores = [
        float(o.technical_score) for o in offers if o.technical_score is not None
    ]
    financial_scores = [
        float(o.financial_score) for o in offers if o.financial_score is not None
    ]
    combined_scores = [
        float(o.total_score) for o in offers if o.total_score is not None
    ]

    average_technical_score = (
        sum(technical_scores) / len(technical_scores) if technical_scores else None
    )
    average_financial_score = (
        sum(financial_scores) / len(financial_scores) if financial_scores else None
    )
    average_combined_score = (
        sum(combined_scores) / len(combined_scores) if combined_scores else None
    )

    # --- Step 6: Find Winner ---
    winner = next((o for o in offers if o.status == OfferStatus.AWARDED), None)

    # --- Step 7: Count Committee Actions ---
    committee_overrides = await _count_committee_overrides(db, tender_id)
    close_tie = await _check_close_tie_flag(db, tender_id)

    # --- Step 8: Get Appeal Statistics ---
    appeal_stats = await get_appeal_statistics(db, tender_id)

    # --- Step 9: Compute Timing ---
    days_open = 0
    if tender.deadline and tender.created_at:
        days_open = (tender.deadline - tender.created_at).days

    # --- Step 10: Build Statistics Object ---
    stats = TenderStatistics(
        tender_id=tender_id,
        tender_title=tender.title,
        tender_reference=tender.reference_number,
        total_offers_received=total_offers,
        offers_compliant=offers_compliant,
        offers_incompliant=offers_incompliant,
        offers_technically_scored=offers_technically_scored,
        offers_financially_scored=offers_financially_scored,
        offers_combined_scored=offers_combined_scored,
        average_bid_price=average_bid_price,
        lowest_bid_price=lowest_bid_price,
        highest_bid_price=highest_bid_price,
        price_currency="USD",  # Default, could be extracted from audit logs
        average_technical_score=average_technical_score,
        average_financial_score=average_financial_score,
        average_combined_score=average_combined_score,
        winner_offer_id=winner.id if winner else None,
        winner_bidder_name=winner.bidder_name if winner else None,
        winner_technical_score=float(winner.technical_score)
        if winner and winner.technical_score
        else None,
        winner_financial_score=float(winner.financial_score)
        if winner and winner.financial_score
        else None,
        winner_combined_score=float(winner.total_score)
        if winner and winner.total_score
        else None,
        winner_bid_price=await _get_offer_bid_price(db, winner.id) if winner else None,
        total_score_overrides=committee_overrides,
        close_tie_detected=close_tie,
        total_appeals=appeal_stats["total_appeals"],
        appeals_upheld=appeal_stats["upheld"],
        appeals_overturned=appeal_stats["overturned"],
        appeals_pending=appeal_stats["pending"],
        tender_deadline=tender.deadline,
        tender_closed_at=tender.updated_at
        if tender.status == TenderStatus.CLOSED
        else None,
        days_open_for_bids=max(0, days_open),
    )

    logger.info(
        "Statistics aggregated for tender {tender_id}: "
        "{offers} offers, {appeals} appeals, winner={winner}",
        tender_id=tender_id,
        offers=total_offers,
        appeals=appeal_stats["total_appeals"],
        winner=winner.bidder_name if winner else "N/A",
    )

    return stats


async def _get_offer_bid_price(db: AsyncSession, offer_id: int | None) -> float | None:
    """Retrieve bid price from audit log for an offer."""
    if offer_id is None:
        return None

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.offer_id == offer_id,
            AuditLog.action_type == ActionType.FINANCIAL_EXTRACTED.value,
        )
        .order_by(AuditLog.timestamp.desc())
    )
    log = result.scalar_one_or_none()

    if log and log.context:
        return log.context.get("bid_price")

    return None


async def _count_committee_overrides(db: AsyncSession, tender_id: int) -> int:
    """Count score override events for a tender's offers."""
    result = await db.execute(
        select(func.count(AuditLog.id))
        .select_from(Offer)
        .join(AuditLog, Offer.id == AuditLog.offer_id)
        .where(
            Offer.tender_id == tender_id,
            AuditLog.action_type == ActionType.SCORE_OVERRIDDEN.value,
        )
    )
    return result.scalar() or 0


async def _check_close_tie_flag(db: AsyncSession, tender_id: int) -> bool:
    """Check if a close tie was flagged for this tender."""
    result = await db.execute(
        select(AuditLog)
        .select_from(Offer)
        .join(AuditLog, Offer.id == AuditLog.offer_id)
        .where(
            Offer.tender_id == tender_id,
            AuditLog.action_type == ActionType.CLOSE_TIE_FLAGGED.value,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# =============================================================================
# Phase 9: LLM Executive Summary Generation (The Reasoner)
# =============================================================================


class ExecutiveSummaryResult:
    """Result container for executive summary generation."""

    def __init__(
        self,
        success: bool,
        summary: ExecutiveSummary,
        error: str | None = None,
    ):
        self.success = success
        self.summary = summary
        self.error = error


async def generate_executive_summary(
    db: AsyncSession,
    statistics: TenderStatistics,
) -> ExecutiveSummaryResult:
    """
    Phase 9 Step 2: LLM generates plain-English executive summary.

    ## The Reasoner's Task:

    1. Read the computed statistics
    2. Generate narrative sections suitable for government auditors
    3. Highlight key findings and any anomalies
    4. Provide recommendations for future procurements
    """
    logger.info(
        "Generating executive summary for tender {tender_id}",
        tender_id=statistics.tender_id,
    )

    try:
        summary = await _call_llm_generate_summary(statistics)
    except Exception as exc:
        logger.error(
            "LLM executive summary generation failed for tender {id}: {error}",
            id=statistics.tender_id,
            error=str(exc),
        )
        return ExecutiveSummaryResult(
            success=False,
            summary=create_empty_executive_summary(
                tender_reference=statistics.tender_reference
                or str(statistics.tender_id)
            ),
            error=f"LLM summary generation failed: {str(exc)}",
        )

    await log_event(
        db_session=db,
        action=ActionType.CLOSURE_REPORT_GENERATED,
        actor="LLM",
        offer_id=None,
        new_state="EXECUTIVE_SUMMARY_GENERATED",
        context={
            "tender_id": statistics.tender_id,
            "total_offers": statistics.total_offers_received,
            "winner_id": statistics.winner_offer_id,
            "generation_confidence": summary.generation_confidence,
        },
    )
    await db.commit()

    logger.info(
        "Executive summary generated for tender {tender_id} (confidence: {confidence})",
        tender_id=statistics.tender_id,
        confidence=summary.generation_confidence,
    )

    return ExecutiveSummaryResult(
        success=True,
        summary=summary,
    )


async def _call_llm_generate_summary(statistics: TenderStatistics) -> ExecutiveSummary:
    """
    Call LLM to generate executive summary from statistics.

    Returns strictly validated ExecutiveSummary.
    """
    system_prompt = """You are a senior procurement auditor preparing a closure report for government review.

Your task is to read the provided tender statistics and generate a comprehensive, plain-English executive summary suitable for government auditors.

RULES:
1. Write professionally and objectively — this is an official government document.
2. Address each required section with thorough, fact-based narrative.
3. Do NOT invent statistics — use ONLY the numbers provided.
4. Highlight any anomalies or concerns for auditor attention.
5. Provide actionable recommendations for future procurements.
6. Output ONLY valid JSON matching the ExecutiveSummary schema.

TONE: Formal, objective, thorough, and compliant with public procurement transparency requirements."""

    # Format statistics for LLM
    avg_tech = (
        f"{statistics.average_technical_score:.2f}"
        if statistics.average_technical_score
        else "N/A"
    )
    avg_fin = (
        f"{statistics.average_financial_score:.2f}"
        if statistics.average_financial_score
        else "N/A"
    )
    avg_comb = (
        f"{statistics.average_combined_score:.2f}"
        if statistics.average_combined_score
        else "N/A"
    )
    avg_price = (
        f"{statistics.average_bid_price:,.2f}"
        if statistics.average_bid_price
        else "N/A"
    )
    low_price = (
        f"{statistics.lowest_bid_price:,.2f}" if statistics.lowest_bid_price else "N/A"
    )
    high_price = (
        f"{statistics.highest_bid_price:,.2f}"
        if statistics.highest_bid_price
        else "N/A"
    )

    stats_text = f"""
TENDER STATISTICS SUMMARY
=========================

Tender ID: {statistics.tender_id}
Title: {statistics.tender_title}
Reference: {statistics.tender_reference or "N/A"}

PARTICIPATION:
- Total Offers Received: {statistics.total_offers_received}
- Offers Compliant: {statistics.offers_compliant}
- Offers Incompliant: {statistics.offers_incompliant}
- Days Open for Bids: {statistics.days_open_for_bids}

EVALUATION:
- Technically Scored: {statistics.offers_technically_scored}
- Financially Scored: {statistics.offers_financially_scored}
- Combined Scored: {statistics.offers_combined_scored}
- Average Technical Score: {avg_tech}
- Average Financial Score: {avg_fin}
- Average Combined Score: {avg_comb}

FINANCIAL:
- Average Bid Price: {avg_price} {statistics.price_currency or ""}
- Lowest Bid Price: {low_price}
- Highest Bid Price: {high_price}

WINNER:
- Bidder: {statistics.winner_bidder_name or "N/A"}
- Offer ID: {statistics.winner_offer_id or "N/A"}
- Technical Score: {statistics.winner_technical_score or "N/A"}
- Financial Score: {statistics.winner_financial_score or "N/A"}
- Combined Score: {statistics.winner_combined_score or "N/A"}
- Bid Price: {statistics.winner_bid_price or "N/A"}

COMMITTEE ACTIONS:
- Score Overrides: {statistics.total_score_overrides}
- Close Tie Detected: {"Yes" if statistics.close_tie_detected else "No"}

APPEALS:
- Total Appeals: {statistics.total_appeals}
- Upheld: {statistics.appeals_upheld}
- Overturned: {statistics.appeals_overturned}
- Pending: {statistics.appeals_pending}

TIMING:
- Tender Deadline: {statistics.tender_deadline.isoformat() if statistics.tender_deadline else "N/A"}
- Tender Closed At: {statistics.tender_closed_at.isoformat() if statistics.tender_closed_at else "N/A"}
"""

    user_message = f"""Generate an executive summary for the following tender statistics.

Write a comprehensive closure report suitable for government auditors. Address all sections:

1. Executive Overview: High-level summary of the procurement
2. Process Summary: How the evaluation was conducted
3. Participation Summary: Competition level and bidder participation
4. Evaluation Summary: Technical and financial scoring results
5. Winner Justification: Why the winner was selected
6. Compliance and Appeals Summary: Any issues or appeals
7. Audit Trail Statement: Confirmation of audit completeness
8. Key Findings: Important observations
9. Recommendations: Suggestions for future procurements
10. Anomalies or Concerns: Anything requiring auditor attention
11. Final Statement: Official closure statement

STATISTICS:
{stats_text}

Generate the executive summary as structured JSON."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=6000,
    )

    # Parse and validate
    data = json.loads(raw_response)
    summary = ExecutiveSummary(**data)

    return summary


# =============================================================================
# Phase 9: Full Closure Report Generation
# =============================================================================


class ClosureReportResult:
    """Result container for full closure report generation."""

    def __init__(
        self,
        success: bool,
        report: ClosureReport | None,
        message: str,
        error_code: str | None = None,
    ):
        self.success = success
        self.report = report
        self.message = message
        self.error_code = error_code


async def generate_closure_report(
    db: AsyncSession,
    tender_id: int,
    requested_by: str = "SYSTEM",
) -> ClosureReportResult:
    """
    Generate complete Phase 9 closure report.

    ## Process:

    1. Python aggregates all statistics (deterministic)
    2. LLM generates executive summary (narrative)
    3. Audit trail events counted
    4. Combined into immutable ClosureReport
    """
    logger.info(
        "Generating closure report for tender {tender_id} (requested by {user})",
        tender_id=tender_id,
        user=requested_by,
    )

    # --- Step 1: Aggregate Statistics (Python) ---
    statistics = await aggregate_tender_statistics(db, tender_id)

    if statistics is None:
        return ClosureReportResult(
            success=False,
            report=None,
            message=f"Tender {tender_id} not found.",
            error_code="TENDER_NOT_FOUND",
        )

    # --- Step 2: Generate Executive Summary (LLM) ---
    summary_result = await generate_executive_summary(db, statistics)

    if not summary_result.success:
        logger.warning(
            "LLM summary generation failed for tender {tender_id}, using fallback",
            tender_id=tender_id,
        )

    # --- Step 3: Count Audit Events ---
    total_audits = await _count_total_audit_events(db, tender_id)

    # --- Step 4: Build Report ---
    report_id = f"CR-{tender_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    report = ClosureReport(
        tender_id=tender_id,
        report_id=report_id,
        generated_at=datetime.now(timezone.utc),
        generated_by=requested_by,
        statistics=statistics,
        executive_summary=summary_result.summary,
        total_audit_events=total_audits,
        status="DRAFT",
    )

    # Log report generation
    await log_event(
        db_session=db,
        action=ActionType.CLOSURE_REPORT_GENERATED,
        actor=requested_by,
        offer_id=None,
        new_state="REPORT_GENERATED",
        context={
            "tender_id": tender_id,
            "report_id": report_id,
            "total_offers": statistics.total_offers_received,
            "total_appeals": statistics.total_appeals,
            "summary_confidence": summary_result.summary.generation_confidence,
        },
    )
    await db.commit()

    logger.info(
        "Closure report {report_id} generated for tender {tender_id}",
        report_id=report_id,
        tender_id=tender_id,
    )

    return ClosureReportResult(
        success=True,
        report=report,
        message="Closure report generated successfully.",
    )


async def _count_total_audit_events(db: AsyncSession, tender_id: int) -> int:
    """Count total audit events for a tender's offers."""
    result = await db.execute(
        select(func.count(AuditLog.id))
        .select_from(Offer)
        .join(AuditLog, Offer.id == AuditLog.offer_id)
        .where(Offer.tender_id == tender_id)
    )
    return result.scalar() or 0


# =============================================================================
# Phase 9: Audit Trail Export
# =============================================================================


async def export_audit_trail(
    db: AsyncSession,
    tender_id: int,
    export_format: str = "JSON",
) -> dict[str, Any]:
    """
    Export complete audit trail for a tender.
    """
    logger.info(
        "Exporting audit trail for tender {tender_id} in {format} format",
        tender_id=tender_id,
        format=export_format,
    )

    # Fetch all audit events for this tender
    result = await db.execute(
        select(AuditLog, Offer.bidder_name)
        .select_from(Offer)
        .join(AuditLog, Offer.id == AuditLog.offer_id)
        .where(Offer.tender_id == tender_id)
        .order_by(AuditLog.timestamp.asc())
    )
    rows = result.all()

    events = []
    for log, bidder_name in rows:
        events.append(
            {
                "timestamp": log.timestamp.isoformat(),
                "actor": log.actor,
                "action_type": log.action_type,
                "offer_id": log.offer_id,
                "bidder_name": bidder_name,
                "old_state": log.old_state,
                "new_state": log.new_state,
                "context": log.context,
            }
        )

    # Generate hash for integrity
    export_data = json.dumps(events, sort_keys=True, default=str)
    audit_hash = hashlib.sha256(export_data.encode()).hexdigest()

    await log_event(
        db_session=db,
        action=ActionType.AUDIT_TRAIL_EXPORTED,
        actor="SYSTEM",
        offer_id=None,
        new_state="AUDIT_EXPORTED",
        context={
            "tender_id": tender_id,
            "export_format": export_format,
            "total_events": len(events),
            "audit_hash": audit_hash,
        },
    )
    await db.commit()

    return {
        "tender_id": tender_id,
        "total_events": len(events),
        "export_format": export_format,
        "audit_hash": audit_hash,
        "events": events if export_format == "JSON" else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
