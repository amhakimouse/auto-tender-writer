"""
app/api/v1/files.py

Secure File Serving Router

Enables the frontend PDF viewer to display offer PDFs in-browser.

Security Rules (Python The Enforcer):
  1. Request MUST carry a valid JWT (get_current_user dependency).
  2. Requesting user MUST have REVIEWER, COMMITTEE_MEMBER, COMMITTEE_CHAIR,
     or ADMIN role — bidders (READONLY) cannot view each other's PDFs.
  3. Python verifies the file exists on disk before returning it.
  4. Response uses Content-Disposition: inline so the browser renders
     the PDF instead of forcing a download.
  5. The actual file path is NEVER exposed in any API response — only
     the offer_id + tender_id URL parameters are accepted.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_user, require_role
from app.db.models import Offer, Tender
from app.db.models.user import UserRole

router = APIRouter()

# Roles that may view offer PDFs
_VIEWER_ROLES = [
    UserRole.ADMIN,
    UserRole.COMMITTEE_CHAIR,
    UserRole.COMMITTEE_MEMBER,
    UserRole.REVIEWER,
]


@router.get(
    "/tenders/{tender_id}/offers/{offer_id}/download",
    summary="Secure PDF download — opens inline in browser",
    response_class=FileResponse,
    responses={
        200: {"description": "PDF file returned (inline)"},
        403: {"description": "Insufficient role to view this file"},
        404: {"description": "Offer or file not found"},
    },
)
async def download_offer_pdf(
    tender_id: int,
    offer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(*_VIEWER_ROLES)),
) -> FileResponse:
    """
    Serve the uploaded offer PDF for in-browser viewing.

    The frontend PDF viewer (e.g. react-pdf, PDF.js) fetches this endpoint
    with the Bearer token in the Authorization header.

    ## Security Checks (all enforced by Python before any file I/O):
      1. JWT must be valid (handled by `require_role` dependency chain).
      2. Role must be REVIEWER or above.
      3. The offer must belong to the given tender (prevents ID-guessing).
      4. The file must exist on disk (prevents path-not-found crashes).

    ## Returns:
      The PDF file with `Content-Disposition: inline` — renders in browser.
    """
    # 1. Fetch offer and verify it belongs to this tender
    result = await db.execute(
        select(Offer).where(Offer.id == offer_id, Offer.tender_id == tender_id)
    )
    offer = result.scalar_one_or_none()

    if offer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Offer {offer_id} not found under tender {tender_id}.",
        )

    # 2. Verify storage path is set
    if not offer.storage_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No file stored for this offer.",
        )

    # 3. Verify file exists on disk
    pdf_path = Path(offer.storage_path)
    if not pdf_path.exists() or not pdf_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk. It may have been deleted.",
        )

    # 4. Serve inline (browser renders; no forced download)
    safe_filename = f"offer_{offer_id}_{offer.bidder_name.replace(' ', '_')}.pdf"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=safe_filename,
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"',
            "X-Offer-Id": str(offer_id),
            "X-Tender-Id": str(tender_id),
        },
    )
