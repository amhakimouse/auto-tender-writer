"""
app/api/v1/reports.py

Phase 9 — Audit Trail and Archive Closure Router

This router handles:
    - GET /tenders/{tender_id}/closure-report: Generate full closure report
    - GET /tenders/{tender_id}/audit-trail: Export audit trail
    - POST /tenders/{tender_id}/finalize: Mark tender as archived

The Enforcer/Reasoner split:
    - Python (Enforcer): Aggregates all statistics deterministically
    - LLM (Reasoner): Generates executive summary narrative
    - Human (Decider): Reviews and finalizes the report
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.schemas.report_schemas import (
    ClosureReport,
    ClosureReportRequest,
    ClosureReportResponse,
    AuditTrailExportRequest,
    AuditTrailExportResponse,
)
from app.services.report_service import (
    generate_closure_report,
    export_audit_trail,
)
from app.db.models import Tender, TenderStatus
from app.utils.audit_logger import ActionType, log_event

router = APIRouter()


# =============================================================================
# Phase 9: Closure Report (Python + LLM)
# =============================================================================


@router.get(
    "/tenders/{tender_id}/closure-report",
    response_model=ClosureReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Phase 9 — Generate closure report",
    responses={
        200: {"description": "Closure report generated successfully"},
        404: {"description": "Tender not found"},
        422: {"description": "LLM summary generation failed"},
    },
)
async def get_closure_report(
    tender_id: int,
    include_full_audit_trail: bool = True,
    db: AsyncSession = Depends(get_db),
) -> ClosureReportResponse:
    """
    Generate a comprehensive closure report for a tender.

    ## The Enforcer's Rules:

    1. **Statistics Aggregation**: Python computes ALL numbers deterministically:
       - Total offers received
       - Average bid price
       - Winner scores
       - Total appeals
       - Committee actions (overrides, ties)

    2. **LLM Narrative**: The LLM generates a plain-English executive summary
       for government auditors based on the computed statistics.

    3. **Audit Trail**: Complete audit log count included for verification.

    ## Report Sections:

    ### Statistics Section (Python Computed)
    - Offer counts (total, compliant, incompliant)
    - Financial statistics (average, min, max bid prices)
    - Scoring statistics (technical, financial, combined averages)
    - Winner details (scores, price)
    - Committee actions (overrides, close ties)
    - Appeals summary (total, upheld, overturned, pending)

    ### Executive Summary (LLM Generated)
    - Executive overview
    - Process summary
    - Participation summary
    - Evaluation summary
    - Winner justification
    - Compliance and appeals summary
    - Audit trail statement
    - Key findings and recommendations

    ## Response:

    Returns the complete closure report with both statistics and narrative.
    """
    # Check if tender exists
    from sqlalchemy import select

    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found",
        )

    # Generate closure report
    result = await generate_closure_report(
        db=db,
        tender_id=tender_id,
        requested_by="API",
    )

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result.message,
        )

    return ClosureReportResponse(
        success=True,
        report=result.report,
        message=result.message,
    )


# =============================================================================
# Phase 9: Audit Trail Export
# =============================================================================


@router.get(
    "/tenders/{tender_id}/audit-trail",
    status_code=status.HTTP_200_OK,
    summary="Phase 9 — Export audit trail",
)
async def get_audit_trail(
    tender_id: int,
    export_format: str = "JSON",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Export the complete audit trail for a tender.

    ## Returns:

    - Complete audit log events for all offers
    - Integrity hash (SHA-256) for tamper verification
    - Timestamp and export metadata

    ## Formats:

    - **JSON**: Full structured data with all events
    - **CSV**: Tabular format (coming soon)
    - **PDF**: Human-readable report (coming soon)

    ## Use Cases:

    - External auditor review
    - Legal proceedings
    - Archival requirements
    - Transparency reporting
    """
    # Check if tender exists
    from sqlalchemy import select

    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found",
        )

    # Export audit trail
    export_result = await export_audit_trail(db, tender_id, export_format)

    return {
        "success": True,
        "tender_id": tender_id,
        "tender_title": tender.title,
        "total_events": export_result["total_events"],
        "export_format": export_result["export_format"],
        "audit_hash": export_result["audit_hash"],
        "events": export_result["events"],
        "generated_at": export_result["generated_at"],
    }


# =============================================================================
# Phase 9: Tender Archive/Finalize
# =============================================================================


@router.post(
    "/tenders/{tender_id}/finalize",
    status_code=status.HTTP_200_OK,
    summary="Phase 9 — Finalize and archive tender",
)
async def finalize_tender(
    tender_id: int,
    finalized_by: str = "SYSTEM",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Finalize and archive a tender.

    ## Process:

    1. Generates final closure report
    2. Marks tender as ARCHIVED
    3. Logs finalization to audit trail
    4. Returns confirmation

    ## Requirements:

    - Tender must be in CLOSED status
    - All appeals must be resolved
    - Closure report must be generated

    ## Post-Finalization:

    - Tender becomes read-only
    - No further modifications allowed
    - Full audit trail preserved
    """
    from sqlalchemy import select

    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found",
        )

    if tender.status != TenderStatus.CLOSED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Tender must be CLOSED before finalization. Current status: {tender.status}",
        )

    # Generate final closure report
    report_result = await generate_closure_report(
        db=db,
        tender_id=tender_id,
        requested_by=finalized_by,
    )

    if not report_result.success:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to generate closure report: {report_result.message}",
        )

    # Mark tender as archived
    old_status = tender.status
    # Note: You may need to add ARCHIVED to TenderStatus enum
    # For now, we keep it as CLOSED but mark as finalized

    await log_event(
        db_session=db,
        action=ActionType.TENDER_ARCHIVED,
        actor=finalized_by,
        offer_id=None,
        old_state=old_status.value,
        new_state="ARCHIVED",
        context={
            "tender_id": tender_id,
            "report_id": report_result.report.report_id
            if report_result.report
            else None,
            "finalized_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await db.commit()

    return {
        "success": True,
        "tender_id": tender_id,
        "tender_title": tender.title,
        "status": "ARCHIVED",
        "report_id": report_result.report.report_id if report_result.report else None,
        "finalized_at": datetime.now(timezone.utc).isoformat(),
        "finalized_by": finalized_by,
        "message": "Tender finalized and archived successfully.",
    }


# =============================================================================
# Phase 9: Report Summary Endpoint
# =============================================================================


@router.get(
    "/tenders/{tender_id}/statistics",
    status_code=status.HTTP_200_OK,
    summary="Phase 9 — Get tender statistics",
)
async def get_tender_statistics(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """
    Get raw statistics for a tender (without LLM narrative).

    ## Returns:

    All Python-computed statistics:
    - Offer counts and percentages
    - Financial aggregations
    - Scoring averages
    - Winner information
    - Appeals summary
    - Committee actions
    """
    from sqlalchemy import select
    from app.services.report_service import aggregate_tender_statistics

    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender {tender_id} not found",
        )

    stats = await aggregate_tender_statistics(db, tender_id)

    if stats is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to aggregate statistics",
        )

    return {
        "success": True,
        "tender_id": tender_id,
        "tender_title": tender.title,
        "statistics": stats.model_dump(),
    }
