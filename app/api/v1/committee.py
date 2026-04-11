"""
app/api/v1/committee.py

Phase 6 — Human Score Overrides
Phase 7 — Award Decision & Notification

Blueprint rules enforced here by Python (The Enforcer):
  - Role-based access: only committee_member / committee_chair may POST here.
  - Override payloads MUST include a non-empty justification string.
  - Every override is written to the AuditLog (old state → new state).
  - Python triggers notification templates; LLM only fills in the prose.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", summary="[STUB] Committee dashboard")
async def committee_dashboard():
    """Placeholder — implemented in Milestone 4."""
    return {"message": "Committee router online. Implementation: Milestone 4."}
