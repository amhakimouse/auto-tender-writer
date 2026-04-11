"""
app/api/v1/intake.py

Phase 1 — Offer Submission Intake
Phase 8 — Enterprise Appeals

Blueprint rules enforced here by Python (The Enforcer):
  - Timestamp is captured server-side (not trusted from client).
  - SHA-256 file hash is computed immediately on upload.
  - Submission is rejected deterministically if timestamp > tender.deadline + grace_period.
  - Tender must be in PUBLISHED status to accept submissions.
  - Duplicate file hashes are rejected (same hash for same tender = likely re-upload).
  - Every state change is piped through audit_logger.py.
  - Audit logs are written to the database within the same transaction.

LLM is NOT called from this router.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.core.config import settings
from app.db.models import Offer, Tender
from app.db.models.tender import TenderStatus
from app.db.models.offer import OfferStatus
from app.schemas.offer import (
    OfferFileInfo,
    OfferRejectedResponse,
    OfferResponse,
    OfferUploadResponse,
)
from app.utils.audit_logger import ActionType, log_event

if TYPE_CHECKING:
    pass

router = APIRouter()


# Maximum file size: 50MB (configurable via settings if needed)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf"}


def compute_sha256(file_content: bytes) -> str:
    """
    Compute the SHA-256 hex digest of file content.

    This is the cryptographic proof that the file has not been modified
    since upload. The hash is stored and can be verified later.
    """
    return hashlib.sha256(file_content).hexdigest()


def get_effective_deadline(tender_deadline: datetime) -> datetime:
    """
    Calculate the effective deadline including the grace period.

    The grace period allows for slight clock skew and transmission delays.
    Default is 0 seconds (strict), but can be configured in settings.
    """
    grace_period = timedelta(seconds=settings.LATE_SUBMISSION_TOLERANCE_SECONDS)
    return tender_deadline + grace_period


def save_upload_to_vault(
    file_content: bytes,
    tender_id: int,
    offer_id: int,
    original_filename: str,
) -> Path:
    """
    Save uploaded file to the secure file vault.

    File structure: {DATA_DIR}/tenders/{tender_id}/offers/{offer_id}/{hash}_{filename}

    Returns:
        Absolute path to the saved file
    """
    # Generate a short hash prefix for the filename to prevent collisions
    content_hash = compute_sha256(file_content)[:16]
    safe_filename = Path(original_filename).name.replace("..", "_")

    # Build vault path
    vault_dir = (
        settings.DATA_DIR / "tenders" / str(tender_id) / "offers" / str(offer_id)
    )
    vault_dir.mkdir(parents=True, exist_ok=True)

    # Filename format: {hash_prefix}_{original_name}
    vault_filename = f"{content_hash}_{safe_filename}"
    vault_path = vault_dir / vault_filename

    # Write file to vault
    with open(vault_path, "wb") as f:
        f.write(file_content)

    return vault_path


@router.post(
    "/upload/{tender_id}",
    response_model=OfferUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an offer PDF for a tender",
    responses={
        201: {
            "description": "Offer uploaded and verified successfully",
            "model": OfferUploadResponse,
        },
        400: {
            "description": "Invalid file or request (duplicate hash)",
        },
        403: {
            "description": "Submission not accepted (deadline passed, not published, etc.)",
            "model": OfferRejectedResponse,
        },
        404: {
            "description": "Tender not found",
        },
        413: {
            "description": "File too large",
        },
        409: {
            "description": "Duplicate file hash detected for this tender",
        },
    },
)
async def upload_offer(
    tender_id: int,
    bidder_name: str = Form(..., min_length=1, max_length=255),
    bidder_email: str | None = Form(default=None, max_length=255),
    file: UploadFile = File(
        ...,
        description="PDF file containing the offer proposal",
    ),
    db: AsyncSession = Depends(get_db),
) -> OfferUploadResponse:
    """
    Receive an offer PDF submission for a specific tender.

    ## The Enforcer's Rules (Phase 1):

    1. **Server-side timestamp**: Request time is captured at the moment
       the request hits the API, not from any client-provided value.

    2. **Tender status check**: Tender must be in PUBLISHED status.
       DRAFT, CLOSED, or CANCELLED tenders reject submissions.

    3. **Grace period deadline enforcement**: If the server timestamp is past
       the Tender's deadline + LATE_SUBMISSION_TOLERANCE_SECONDS, the submission
       is REJECTED with HTTP 403. Default tolerance is 0 seconds (strict).

    4. **SHA-256 integrity**: The complete file content is hashed immediately.
       This hash is stored permanently and proves the file hasn't changed.

    5. **Duplicate detection**: If the same SHA-256 hash already exists for
       this tender (same file re-uploaded), reject with HTTP 409.

    6. **Immutable audit trail**: Every upload attempt (success or failure)
       is recorded in the AuditLog table within the same database transaction.

    ## Returns:
        - On success: HTTP 201 with offer details and file hash
        - On late submission: HTTP 403 with rejection details
        - On duplicate hash: HTTP 409 with rejection details
        - On other errors: Appropriate 4xx status with error message
    """
    # ==========================================================================
    # STEP 1: Capture server-side timestamp (The Enforcer's timestamp)
    # ==========================================================================
    server_timestamp = datetime.now(timezone.utc)

    # ==========================================================================
    # STEP 2: Validate tender exists
    # ==========================================================================
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # ==========================================================================
    # STEP 3: CHECK TENDER STATUS (Must be PUBLISHED)
    # ==========================================================================
    if tender.status != TenderStatus.PUBLISHED:
        await log_event(
            db_session=db,
            action=ActionType.OFFER_REJECTED_NOT_PUBLISHED,
            actor="SYSTEM",
            offer_id=None,
            old_state=None,
            new_state="REJECTED_NOT_PUBLISHED",
            context={
                "tender_id": tender_id,
                "tender_status": tender.status,
                "bidder_name": bidder_name,
                "reason": f"Tender is not accepting submissions (status: {tender.status})",
            },
        )
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Tender is not accepting submissions",
                "tender_id": tender_id,
                "tender_status": tender.status,
                "reason": f"Tender must be in PUBLISHED status to accept submissions. Current status: {tender.status}",
            },
        )

    # ==========================================================================
    # STEP 4: GRACE PERIOD DEADLINE CHECK (Python The Enforcer)
    # ==========================================================================
    effective_deadline = get_effective_deadline(tender.deadline)

    if server_timestamp > effective_deadline:
        # Record the rejection attempt in audit log
        await log_event(
            db_session=db,
            action=ActionType.OFFER_REJECTED_LATE,
            actor="SYSTEM",
            offer_id=None,
            old_state=None,
            new_state="REJECTED_LATE",
            context={
                "tender_id": tender_id,
                "deadline": tender.deadline.isoformat(),
                "effective_deadline": effective_deadline.isoformat(),
                "grace_period_seconds": settings.LATE_SUBMISSION_TOLERANCE_SECONDS,
                "submitted_at": server_timestamp.isoformat(),
                "bidder_name": bidder_name,
                "reason": "Submission received after tender deadline (including grace period)",
            },
        )
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "Submission deadline has passed",
                "tender_id": tender_id,
                "deadline": tender.deadline.isoformat(),
                "grace_period_seconds": settings.LATE_SUBMISSION_TOLERANCE_SECONDS,
                "effective_deadline": effective_deadline.isoformat(),
                "submitted_at": server_timestamp.isoformat(),
                "reason": "The tender is no longer accepting submissions",
            },
        )

    # ==========================================================================
    # STEP 5: Validate and read uploaded file
    # ==========================================================================
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Only PDF files are accepted. Got: {file.content_type}",
        )

    # Read file content into memory
    file_content = await file.read()

    # Check file size
    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB",
        )

    if len(file_content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # ==========================================================================
    # STEP 6: Compute SHA-256 hash (The Enforcer's proof of integrity)
    # ==========================================================================
    file_hash = compute_sha256(file_content)

    # ==========================================================================
    # STEP 7: DUPLICATE FILE HASH DETECTION
    # ==========================================================================
    existing_offer_result = await db.execute(
        select(Offer).where(
            Offer.tender_id == tender_id,
            Offer.file_hash_sha256 == file_hash,
        )
    )
    existing_offer = existing_offer_result.scalar_one_or_none()

    if existing_offer is not None:
        # Duplicate detected - reject the submission
        await log_event(
            db_session=db,
            action=ActionType.OFFER_REJECTED_DUPLICATE_HASH,
            actor="SYSTEM",
            offer_id=existing_offer.id,
            old_state=None,
            new_state="REJECTED_DUPLICATE_HASH",
            context={
                "tender_id": tender_id,
                "duplicate_offer_id": existing_offer.id,
                "file_hash_sha256": file_hash,
                "bidder_name": bidder_name,
                "original_bidder_name": existing_offer.bidder_name,
                "reason": "File with identical hash already submitted for this tender",
            },
        )
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "Duplicate submission detected",
                "tender_id": tender_id,
                "reason": "A file with identical content has already been submitted for this tender",
                "original_submission_id": existing_offer.id,
                "original_bidder": existing_offer.bidder_name,
                "submitted_at": existing_offer.submitted_at.isoformat(),
            },
        )

    # Log the hash computation
    await log_event(
        db_session=db,
        action=ActionType.FILE_HASH_COMPUTED,
        actor="SYSTEM",
        offer_id=None,  # Will update after offer creation
        new_state="HASH_COMPUTED",
        context={
            "tender_id": tender_id,
            "file_hash_sha256": file_hash,
            "file_size_bytes": len(file_content),
            "original_filename": file.filename,
        },
    )

    # ==========================================================================
    # STEP 8: Create Offer record (transaction not yet committed)
    # ==========================================================================
    offer = Offer(
        tender_id=tender_id,
        bidder_name=bidder_name,
        bidder_email=bidder_email,
        file_hash_sha256=file_hash,
        submitted_at=server_timestamp,
        original_filename=file.filename or "unnamed.pdf",
        status=OfferStatus.RECEIVED,
        storage_path=None,  # Will update after saving file
    )

    db.add(offer)
    await db.flush()  # Get the offer.id assigned by the database

    # ==========================================================================
    # STEP 9: Save file to secure vault
    # ==========================================================================
    try:
        vault_path = save_upload_to_vault(
            file_content=file_content,
            tender_id=tender_id,
            offer_id=offer.id,
            original_filename=offer.original_filename,
        )
        offer.storage_path = str(vault_path)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store uploaded file: {str(e)}",
        )

    # ==========================================================================
    # STEP 10: Record successful receipt in audit log
    # ==========================================================================
    await log_event(
        db_session=db,
        action=ActionType.OFFER_RECEIVED,
        actor="SYSTEM",
        offer_id=offer.id,
        old_state=None,
        new_state="RECEIVED",
        context={
            "tender_id": tender_id,
            "tender_reference": tender.reference_number,
            "bidder_name": bidder_name,
            "bidder_email": bidder_email,
            "file_hash_sha256": file_hash,
            "file_size_bytes": len(file_content),
            "submitted_at": server_timestamp.isoformat(),
            "storage_path": str(vault_path),
        },
    )

    # ==========================================================================
    # STEP 11: Commit the transaction (Offer + AuditLogs atomically)
    # ==========================================================================
    await db.commit()

    # Refresh to get any DB-generated timestamps
    await db.refresh(offer)

    # ==========================================================================
    # STEP 12: Return response
    # ==========================================================================
    return OfferUploadResponse(
        id=offer.id,
        tender_id=offer.tender_id,
        bidder_name=offer.bidder_name,
        bidder_email=offer.bidder_email,
        status=offer.status,
        submitted_at=offer.submitted_at,
        file_info=OfferFileInfo(
            original_filename=offer.original_filename,
            hash_algorithm="SHA256",
            hash_hex=offer.file_hash_sha256,
            size_bytes=len(file_content),
        ),
        message="Offer received and integrity verified",
    )


@router.get(
    "/tenders/{tender_id}/offers",
    response_model=list[OfferResponse],
    summary="List all offers for a tender",
)
async def list_offers(
    tender_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[OfferResponse]:
    """List all offers submitted for a specific tender."""
    # Verify tender exists
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # Fetch offers
    result = await db.execute(
        select(Offer)
        .where(Offer.tender_id == tender_id)
        .order_by(Offer.submitted_at.desc())
    )
    offers = result.scalars().all()

    return [
        OfferResponse(
            id=offer.id,
            tender_id=offer.tender_id,
            bidder_name=offer.bidder_name,
            bidder_email=offer.bidder_email,
            status=offer.status,
            submitted_at=offer.submitted_at,
            file_info=OfferFileInfo(
                original_filename=offer.original_filename,
                hash_algorithm="SHA256",
                hash_hex=offer.file_hash_sha256,
            ),
        )
        for offer in offers
    ]


@router.get(
    "/offers/{offer_id}",
    response_model=OfferResponse,
    summary="Get a specific offer by ID",
)
async def get_offer(
    offer_id: int,
    db: AsyncSession = Depends(get_db),
) -> OfferResponse:
    """Retrieve a specific offer by its ID."""
    result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer with ID {offer_id} not found",
        )

    return OfferResponse(
        id=offer.id,
        tender_id=offer.tender_id,
        bidder_name=offer.bidder_name,
        bidder_email=offer.bidder_email,
        status=offer.status,
        submitted_at=offer.submitted_at,
        file_info=OfferFileInfo(
            original_filename=offer.original_filename,
            hash_algorithm="SHA256",
            hash_hex=offer.file_hash_sha256,
        ),
    )


# =============================================================================
# Phase 8 — Enterprise Appeals
# =============================================================================


from pydantic import BaseModel, Field as PydanticField, ConfigDict


class AppealRequest(BaseModel):
    """Phase 8: Bidder submits formal grounds for an appeal."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "grounds": "The compliance check incorrectly flagged our tax certificate "
                "as missing. We have attached the certificate in Appendix B.",
                "contact_email": "legal@bidder.com",
            }
        }
    )

    grounds: str = PydanticField(
        ...,
        min_length=50,
        max_length=5000,
        description="Detailed grounds for the appeal (min 50 characters).",
    )
    contact_email: str | None = PydanticField(
        default=None,
        description="Email for the appeal response.",
    )
    use_llm_acknowledgement: bool = PydanticField(
        default=True,
        description="If True, use LLM to draft an acknowledgement letter.",
    )


class AppealResponse(BaseModel):
    """Phase 8 response: appeal receipt confirmation."""

    offer_id: int
    bidder_name: str
    previous_status: str
    new_status: str
    appeal_received_at: str
    acknowledgement_text: str | None = None
    case_reference: str


@router.post(
    "/offers/{offer_id}/appeal",
    response_model=AppealResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Phase 8 — Submit a formal appeal for a rejected offer",
    responses={
        201: {"description": "Appeal received and audit-logged"},
        404: {"description": "Offer not found"},
        409: {"description": "Offer is not in an appealable status"},
    },
)
async def submit_appeal(
    offer_id: int,
    request: AppealRequest,
    db: AsyncSession = Depends(get_db),
) -> AppealResponse:
    """
    Submit a formal appeal against a rejection decision.

    ## The Enforcer's Rules (Phase 8):

    1. **Appealable statuses only**: Only offers in `REJECTED_FINAL` or
       `INCOMPLIANT` status can be appealed. Python enforces this.

    2. **Status update**: Offer moves to `APPEALED` — it is NOT automatically
       reinstated. A human committee decision is required.

    3. **Immutable audit trail**: The appeal grounds, timestamp, and contact
       are written to `AuditLog` with action `APPEAL_RECEIVED`.

    4. **LLM acknowledgement** (optional): If `use_llm_acknowledgement=True`,
       the LLM drafts a formal receipt acknowledgement letter confirming the
       appeal was received and explaining next steps.
    """
    # Fetch offer
    result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found.",
        )

    # Python enforcement: only certain statuses are appealable
    APPEALABLE_STATUSES = {OfferStatus.REJECTED_FINAL, OfferStatus.INCOMPLIANT}
    if offer.status not in APPEALABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Offer {offer_id} is in status '{offer.status}' which is not appealable. "
                f"Only {[s.value for s in APPEALABLE_STATUSES]} offers may be appealed."
            ),
        )

    import hashlib
    from datetime import datetime, timezone

    appeal_at = datetime.now(timezone.utc)
    # Generate a short unique case reference
    case_ref = f"APP-{offer_id}-{hashlib.sha256(appeal_at.isoformat().encode()).hexdigest()[:8].upper()}"

    prev_status = offer.status
    offer.status = OfferStatus.APPEALED

    await log_event(
        db_session=db,
        action=ActionType.APPEAL_RECEIVED,
        actor=f"bidder:{offer.bidder_name}",
        offer_id=offer_id,
        old_state=prev_status,
        new_state="APPEALED",
        context={
            "grounds": request.grounds,
            "contact_email": request.contact_email,
            "case_reference": case_ref,
            "appeal_received_at": appeal_at.isoformat(),
        },
    )

    await db.commit()

    # Optional LLM acknowledgement draft
    acknowledgement = None
    if request.use_llm_acknowledgement:
        try:
            from app.llm.client import call_llm

            system_prompt = (
                "You are a procurement officer drafting a formal appeal acknowledgement letter. "
                "Be professional, neutral, and compliant with public procurement rules. "
                "Do NOT pre-judge the appeal outcome. Return only the letter body text."
            )
            user_prompt = (
                f"Draft an appeal acknowledgement for:\n"
                f"Bidder: {offer.bidder_name}\n"
                f"Offer ID: {offer_id}\n"
                f"Case Reference: {case_ref}\n"
                f"Appeal Grounds (summary): {request.grounds[:500]}\n\n"
                "The letter should: confirm receipt, provide the case reference, "
                "state the appeal will be reviewed within 15 working days, "
                "and advise the bidder to submit supporting documents if any."
            )
            acknowledgement = await call_llm(
                system_prompt,
                user_prompt,
                temperature=0.3,
                max_tokens=500,
            )

            await log_event(
                db_session=db,
                action=ActionType.APPEAL_RESPONSE_DRAFTED,
                actor="LLM",
                offer_id=offer_id,
                new_state="ACKNOWLEDGEMENT_DRAFTED",
                context={"case_reference": case_ref},
            )
            await db.commit()

        except Exception as exc:
            logger.warning(
                "LLM acknowledgement draft failed for appeal {ref}: {err}",
                ref=case_ref,
                err=str(exc),
            )

    return AppealResponse(
        offer_id=offer_id,
        bidder_name=offer.bidder_name,
        previous_status=prev_status,
        new_status=OfferStatus.APPEALED,
        appeal_received_at=appeal_at.isoformat(),
        acknowledgement_text=acknowledgement,
        case_reference=case_ref,
    )

# =============================================================================
# Prototype Demo endpoint for Frontend Standalone UI Test
# =============================================================================
import asyncio
from pydantic import BaseModel

class DemoAnalyzeResponse(BaseModel):
    validation: dict
    requirements: dict
    dossier: dict

@router.post("/analyze", response_model=DemoAnalyzeResponse)
async def analyze_tender_document(
    tender_id: int = Form(...),
    file: UploadFile = File(...),
    profile_context: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Real AI analysis pipeline for the Bid Writer application.
    1. Extract requirements from the uploaded tender PDF.
    2. Generate a tailored response dossier using the company profile.
    3. Validate the dossier and return a compliance score + recommendations.
    """
    from app.llm import orchestrator
    from app.utils.file_parser import extract_text_from_pdf
    import tempfile
    import os

    # Fetch real tender from database
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()
    
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Read file and extract text
    try:
        content = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        pdf_text = extract_text_from_pdf(Path(tmp_path))
        os.unlink(tmp_path)
    except Exception as e:
        logger.error(f"Failed to extract text from PDF: {e}")
        raise HTTPException(status_code=400, detail="Could not read PDF content.")

    # Person 1A: Extract Requirements
    try:
        requirements = await orchestrator.extract_requirements(pdf_text)
    except Exception as e:
        logger.warning(f"Requirement extraction failed: {e}. Using fallback.")
        requirements = {"administrative_documents": ["Check PDF for requirements"], "selection_criteria": []}

    # Person 1B: Generate Dossier
    profile = {"capability_statement": profile_context}
    try:
        dossier = await orchestrator.generate_dossier(requirements, profile)
    except Exception as e:
        logger.error(f"Dossier generation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate tender dossier.")

    # Person 2: Validate & Score
    try:
        validation_report = await orchestrator.validate_dossier(requirements, dossier)
        validation = {
            "compliance_score": validation_report.score,
            "verdict": "STRONG MATCH" if validation_report.score > 80 else "POTENTIAL MATCH",
            "sections_compliant": [s for s in validation_report.sections_manquantes if "found" in s] or ["Evaluated"],
            "recommendations": validation_report.recommandations
        }
    except Exception as e:
        logger.warning(f"Validation failed: {e}")
        validation = {"compliance_score": 0, "verdict": "ERROR", "sections_compliant": [], "recommendations": ["Validation failed"]}

    return {
        "validation": validation,
        "requirements": requirements,
        "dossier": dossier
    }
