"""
app/api/v1/evaluation.py

Phase 3 — Technical Evaluation
Phase 4 — Financial Evaluation
Phase 5 — Combined Scoring & Ranking

Blueprint rules enforced here by Python (The Enforcer):
  - Python validates LLM scores fit within the defined rubric max range.
  - Python runs the lowest-price scoring formula (Phase 4 math).
  - Python applies weights (DEFAULT_TECHNICAL_WEIGHT from settings).
  - Python flags close ties (< CLOSE_TIE_THRESHOLD_PCT difference).
  - Python flags abnormally low bids (< ABNORMALLY_LOW_PRICE_THRESHOLD_PCT).
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", summary="[STUB] List evaluation scores")
async def list_evaluations():
    """Placeholder — implemented in Milestone 3."""
    return {"message": "Evaluation router online. Implementation: Milestone 3."}
