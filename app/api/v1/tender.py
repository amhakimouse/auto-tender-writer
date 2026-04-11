"""
app/api/v1/tender.py

Tender Management Router

Phase 0 — Procurement Opportunity Setup

Provides endpoints for creating and managing tenders (procurement opportunities).
A Tender must be created and published before offers can be submitted.

The Enforcer's Rules:
  - Deadlines are set in UTC and strictly enforced (Phase 1)
  - Only PUBLISHED tenders accept submissions
  - Tender status lifecycle: DRAFT → PUBLISHED → CLOSED
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models import Tender
from app.db.models.tender import TenderStatus
from app.schemas.tender import (
    TenderCreate,
    TenderInDB,
    TenderListResponse,
    TenderResponse,
)
from app.utils.audit_logger import ActionType, log_event
from app.schemas.offer import OfferListResponse, OfferResponse, OfferFileInfo, FileHashAlgorithm
from app.db.models import Offer
from app.db.models.offer import OfferStatus

router = APIRouter()


@router.post(
    "/",
    response_model=TenderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new tender (procurement opportunity)",
    responses={
        201: {"description": "Tender created successfully"},
        400: {"description": "Invalid request data"},
    },
)
async def create_tender(
    tender_data: TenderCreate,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """
    Create a new procurement tender (initially in DRAFT status).

    The tender will be created with:
        - status = DRAFT (not yet accepting submissions)
        - created_at = current UTC time

    After creation, use `POST /tenders/{id}/publish` to open it for submissions.

    ## Returns:
        The created tender with its assigned ID.
    """
    # Validate deadline is in the future
    if tender_data.deadline <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deadline must be in the future",
        )

    # Create the tender
    tender = Tender(
        title=tender_data.title,
        description=tender_data.description,
        reference_number=tender_data.reference_number,
        status=TenderStatus.DRAFT,
        deadline=tender_data.deadline,
        created_by=None,  # Will be set from auth token in Milestone 4
    )

    db.add(tender)
    await db.commit()
    await db.refresh(tender)

    # Log the creation
    await log_event(
        db_session=db,
        action=ActionType("TENDER_CREATED"),  # Will be defined in audit_logger
        actor="SYSTEM",
        offer_id=None,
        new_state="DRAFT",
        context={
            "tender_id": tender.id,
            "title": tender.title,
            "reference_number": tender.reference_number,
            "deadline": tender.deadline.isoformat(),
        },
    )
    await db.commit()

    return TenderResponse.model_validate(tender)


@router.post(
    "/{tender_id}/publish",
    response_model=TenderResponse,
    summary="Publish a tender (open for submissions)",
    responses={
        200: {"description": "Tender published successfully"},
        400: {"description": "Tender cannot be published (e.g., deadline passed)"},
        404: {"description": "Tender not found"},
        409: {"description": "Tender is already published or closed"},
    },
)
async def publish_tender(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """
    Publish a DRAFT tender, making it available for offer submissions.

    ## Preconditions:
        - Tender must exist and be in DRAFT status
        - Deadline must not have already passed

    ## Effect:
        - status changes from DRAFT → PUBLISHED
        - Submissions are now accepted (subject to deadline)

    ## Returns:
        The updated tender.
    """
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # Check current status
    if tender.status == TenderStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tender is already published",
        )
    if tender.status in (TenderStatus.CLOSED, TenderStatus.CANCELLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot publish a tender in {tender.status} status",
        )

    # Check deadline hasn't passed
    if tender.deadline <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish a tender with a past deadline",
        )

    # Update status
    old_status = tender.status
    tender.status = TenderStatus.PUBLISHED

    await db.commit()
    await db.refresh(tender)

    # Log the state change
    await log_event(
        db_session=db,
        action=ActionType("TENDER_PUBLISHED"),
        actor="SYSTEM",
        offer_id=None,
        old_state=old_status,
        new_state="PUBLISHED",
        context={
            "tender_id": tender.id,
            "title": tender.title,
            "deadline": tender.deadline.isoformat(),
        },
    )
    await db.commit()

    return TenderResponse.model_validate(tender)


@router.get(
    "/",
    response_model=TenderListResponse,
    summary="List all tenders",
)
async def list_tenders(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: TenderStatus | None = None,
    db: AsyncSession = Depends(get_db),
) -> TenderListResponse:
    """
    List tenders with optional filtering.

    ## Query Parameters:
        - skip: Number of records to skip (pagination)
        - limit: Maximum records to return (1-100, default 20)
        - status: Filter by status (DRAFT, PUBLISHED, CLOSED, CANCELLED)

    ## Returns:
        Paginated list of tenders.
    """
    query = select(Tender)

    if status:
        query = query.where(Tender.status == status)

    query = query.order_by(Tender.created_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    tenders = result.scalars().all()

    # Get total count for pagination
    count_result = await db.execute(select(Tender))
    total = len(count_result.scalars().all())

    return TenderListResponse(
        items=[TenderResponse.model_validate(t) for t in tenders],
        total=total,
        page=skip // limit + 1 if limit > 0 else 1,
        page_size=limit,
    )


@router.get(
    "/{tender_id}",
    response_model=TenderResponse,
    summary="Get a specific tender by ID",
    responses={
        404: {"description": "Tender not found"},
    },
)
async def get_tender(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """Retrieve a specific tender by its ID."""
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    return TenderResponse.model_validate(tender)


@router.post(
    "/{tender_id}/close",
    response_model=TenderResponse,
    summary="Close a tender (stop accepting submissions)",
    responses={
        200: {"description": "Tender closed successfully"},
        404: {"description": "Tender not found"},
        409: {"description": "Tender is not in PUBLISHED status"},
    },
)
async def close_tender(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> TenderResponse:
    """
    Manually close a tender, stopping acceptance of new submissions.

    This can be used to close a tender before its deadline.
    Tenders also automatically close when the deadline passes (enforced in Phase 1).

    ## Preconditions:
        - Tender must be in PUBLISHED status

    ## Effect:
        - status changes from PUBLISHED → CLOSED
        - New submissions will be rejected with HTTP 403
    """
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    if tender.status != TenderStatus.PUBLISHED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot close a tender in {tender.status} status",
        )

    old_status = tender.status
    tender.status = TenderStatus.CLOSED

    await db.commit()
    await db.refresh(tender)

    await log_event(
        db_session=db,
        action=ActionType("TENDER_CLOSED"),
        actor="SYSTEM",
        offer_id=None,
        old_state=old_status,
        new_state="CLOSED",
        context={
            "tender_id": tender.id,
            "title": tender.title,
        },
    )
    await db.commit()

    return TenderResponse.model_validate(tender)


@router.get(
    "/{tender_id}/offers",
    response_model=OfferListResponse,
    summary="List all offers for a tender",
)
async def list_tender_offers(
    tender_id: int,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    status: OfferStatus | None = None,
    db: AsyncSession = Depends(get_db),
) -> OfferListResponse:
    """
    List offers for a specific tender with optional filtering.

    ## Query Parameters:
        - skip: Number of records to skip
        - limit: Maximum records to return (1-100, default 20)
        - status: Filter by status (e.g. RECEIVED, EVALUATED)
    """
    # First verify tender exists
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    if tender_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=404, detail=f"Tender {tender_id} not found"
        )

    query = select(Offer).where(Offer.tender_id == tender_id)

    if status:
        query = query.where(Offer.status == status)

    query = query.order_by(Offer.submitted_at.desc()).offset(skip).limit(limit)

    result = await db.execute(query)
    offers = result.scalars().all()

    # Get total count for pagination
    count_query = select(Offer).where(Offer.tender_id == tender_id)
    if status:
        count_query = count_query.where(Offer.status == status)
        
    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    # Map offers to OfferResponse format
    response_items = []
    for o in offers:
        file_info = OfferFileInfo(
            original_filename=o.original_filename,
            hash_algorithm=FileHashAlgorithm.SHA256,
            hash_hex=o.file_hash_sha256,
            size_bytes=None,  # We don't store size currently
        )
        response_items.append(
            OfferResponse(
                id=o.id,
                tender_id=o.tender_id,
                bidder_name=o.bidder_name,
                bidder_email=o.bidder_email,
                status=o.status,
                submitted_at=o.submitted_at,
                file_info=file_info,
            )
        )

    return OfferListResponse(
        items=response_items,
        total=total,
        page=skip // limit + 1 if limit > 0 else 1,
        page_size=limit,
    )
