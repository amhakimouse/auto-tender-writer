"""
app/api/v1/compliance.py

Phase 2 — Administrative & Compliance Checklist

Blueprint rules enforced here by Python (The Enforcer):
  - Python reads the Pydantic ComplianceChecklist output from the LLM.
  - Python alone decides DISQUALIFIED status based on boolean flags.
  - LLM just returns JSON — it never sets offer status.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", summary="[STUB] List compliance results")
async def list_compliance():
    """Placeholder — implemented in Milestone 2."""
    return {"message": "Compliance router online. Implementation: Milestone 2."}
