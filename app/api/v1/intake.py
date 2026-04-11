"""
app/api/v1/intake.py

Phase 1 — Offer Submission Intake
Phase 8 — Enterprise Appeals

Blueprint rules enforced here by Python (The Enforcer):
  - Timestamp is captured server-side (not trusted from client).
  - SHA-256 file hash is computed immediately on upload.
  - Submission is rejected deterministically if timestamp > tender.deadline.
  - Every state change is piped through audit_logger.py.

LLM is NOT called from this router.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", summary="[STUB] List all offers")
async def list_offers():
    """Placeholder — implemented in Milestone 1."""
    return {"message": "Intake router online. Implementation: Milestone 1."}
