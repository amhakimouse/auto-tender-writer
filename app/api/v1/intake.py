"""
app/api/v1/intake.py

Final reconciled version after merging Phase 1 (Upload) and Phase 10 (Analysis).
- Handles legacy offer uploads (Phase 1).
- Handles automated tender analysis & dossier generation (Phase 10).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

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
from app.schemas.api_schemas import AnalyzeResponse, DossierResult
from app.services import evaluation_service
from app.llm import orchestrator
from app.utils.file_parser import extract_text_from_pdf_bytes
from app.utils.audit_logger import ActionType, log_event

if TYPE_CHECKING:
    pass

router = APIRouter()

# Maximum file size: 50MB
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf"}

def compute_sha256(file_content: bytes) -> str:
    """Compute the SHA-256 hex digest of file content."""
    return hashlib.sha256(file_content).hexdigest()

def get_effective_deadline(tender_deadline: datetime) -> datetime:
    """Calculate the effective deadline including the grace period."""
    grace_period = timedelta(seconds=settings.LATE_SUBMISSION_TOLERANCE_SECONDS)
    return tender_deadline + grace_period

def save_upload_to_vault(
    file_content: bytes,
    tender_id: int,
    offer_id: int,
    original_filename: str,
) -> Path:
    """Save uploaded file to the secure file vault."""
    content_hash = compute_sha256(file_content)[:16]
    safe_filename = Path(original_filename).name.replace("..", "_")
    vault_dir = settings.DATA_DIR / "tenders" / str(tender_id) / "offers" / str(offer_id)
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_filename = f"{content_hash}_{safe_filename}"
    vault_path = vault_dir / vault_filename
    with open(vault_path, "wb") as f:
        f.write(file_content)
    return vault_path

@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    summary="End-to-End Tender Analysis & Dossier Generation",
)
async def analyze_tender(
    file: UploadFile = File(...),
    company_profile: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 6: Complete Pipeline Integration with Persistence.
    Receives a Tender PDF and a Company Profile, extracts requirements, 
    generates a compliant dossier, and validates/refines it via Person 2 logic.
    Persistence: Saves the extracted data, generated dossier, and evaluation to the DB.
    """
    try:
        # 1. Read and Extract PDF Text
        logger.info("Received analyze request for file: {}", file.filename)
        pdf_content = await file.read()
        document_text = extract_text_from_pdf_bytes(pdf_content)
        
        if not document_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the provided PDF.")
        
        # Compute hash for integrity/de-duplication
        file_hash = compute_sha256(pdf_content)

        # 2. Extract Requirements (Person 1A Logic)
        requirements = await orchestrator.extract_requirements(document_text)
        
        # 3. Parse Company Profile
        try:
            profile_dict = json.loads(company_profile)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format for company_profile.")
        
        # 4. Generate Initial Dossier Draft (Person 1B Logic)
        dossier_draft = await orchestrator.generate_dossier(requirements, profile_dict)
        
        # 5. Validate & Refine (Person 2 Logic)
        validation_report, final_dossier = await evaluation_service.validate_and_refine(
            requirements=requirements,
            dossier=dossier_draft
        )
        
        # 6. PERSISTENCE (Phase 7)
        # ----------------------------------------------------------------------
        # Create Tender record
        tender = Tender(
            title=requirements.get("tender_title", "Untitled Tender"),
            reference_number=requirements.get("tender_reference", f"REF-{file_hash[:8]}"),
            deadline=datetime.utcnow() + timedelta(days=30), # Dummy deadline from requirements extraction if needed
            status=TenderStatus.PUBLISHED,
            description=f"Automated extraction from {file.filename}",
            technical_requirements=requirements.get("technical_requirements", []),
            administrative_documents=requirements.get("administrative_documents", []),
            selection_criteria=requirements.get("selection_criteria", [])
        )
        db.add(tender)
        await db.flush() # Get tender.id

        # Create Offer record
        offer = Offer(
            tender_id=tender.id,
            bidder_name=profile_dict.get("company_name", "Prospective Bidder"),
            bidder_email=profile_dict.get("contact_email", ""),
            file_hash_sha256=file_hash,
            submitted_at=datetime.utcnow(),
            original_filename=file.filename,
            status=OfferStatus.TECHNICAL_SCORED,
            # Store the generated dossier in committee_notes for now or technical_score
            committee_notes=json.dumps(final_dossier)
        )
        db.add(offer)
        await db.flush() # Get offer.id

        # Save file to vault
        vault_path = save_upload_to_vault(pdf_content, tender.id, offer.id, file.filename)
        offer.storage_path = str(vault_path)

        # Create Evaluation record (Person 2 Results)
        from app.db.models.evaluation import Evaluation, EvaluationStatus
        eval_record = Evaluation(
            offer_id=offer.id,
            status=EvaluationStatus.COMPLETED,
            compliance_score=validation_report.compliance_score,
            verdict=validation_report.verdict,
            report_data=validation_report.model_dump(),
            completed_at=datetime.utcnow()
        )
        db.add(eval_record)
        
        await db.commit()
        # ----------------------------------------------------------------------

        # 7. Build and return response
        return AnalyzeResponse(
            tender_ref=tender.reference_number,
            status="success",
            requirements=requirements,
            dossier=DossierResult(**final_dossier),
            validation=validation_report
        )

    except Exception as e:
        await db.rollback()
        logger.exception("Analysis and persistence failed")
        raise HTTPException(status_code=500, detail=str(e))

@router.post(
    "/upload/{tender_id}",
    response_model=OfferUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload an offer PDF for a tender",
)
async def upload_offer(
    tender_id: int,
    bidder_name: str = Form(..., min_length=1, max_length=255),
    bidder_email: str | None = Form(default=None, max_length=255),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> OfferUploadResponse:
    """Legacy endpoint for direct offer submission."""
    server_timestamp = datetime.now(timezone.utc)
    
    tender_result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tender {tender_id} not found")

    if tender.status != TenderStatus.PUBLISHED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tender not published")

    effective_deadline = get_effective_deadline(tender.deadline)
    if server_timestamp > effective_deadline:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Deadline passed")

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")

    file_content = await file.read()
    file_hash = compute_sha256(file_content)

    offer = Offer(
        tender_id=tender_id,
        bidder_name=bidder_name,
        bidder_email=bidder_email,
        file_hash_sha256=file_hash,
        submitted_at=server_timestamp,
        original_filename=file.filename or "unnamed.pdf",
        status=OfferStatus.RECEIVED,
    )

    db.add(offer)
    await db.flush()

    vault_path = save_upload_to_vault(file_content, tender_id, offer.id, offer.original_filename)
    offer.storage_path = str(vault_path)

    await db.commit()
    await db.refresh(offer)

    return OfferUploadResponse(
        id=offer.id,
        tender_id=offer.tender_id,
        bidder_name=offer.bidder_name,
        status=offer.status,
        submitted_at=offer.submitted_at,
        file_info=OfferFileInfo(original_filename=offer.original_filename, hash_hex=offer.file_hash_sha256, size_bytes=len(file_content)),
        message="Offer received"
    )

@router.get("/tenders/{tender_id}/offers", response_model=list[OfferResponse])
async def list_offers(tender_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Offer).where(Offer.tender_id == tender_id).order_by(Offer.submitted_at.desc()))
    return result.scalars().all()

@router.get("/offers/{offer_id}", response_model=OfferResponse)
async def get_offer(offer_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Offer).where(Offer.id == offer_id))
    offer = result.scalar_one_or_none()
    if not offer: raise HTTPException(status_code=404)
    return offer
