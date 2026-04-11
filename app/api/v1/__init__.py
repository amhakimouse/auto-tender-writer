"""
app/api/v1/__init__.py

Aggregates all Phase-specific routers into a single top-level v1 APIRouter.
main.py mounts this at the API_V1_PREFIX (e.g. /api/v1).

Blueprint mapping:
  intake.py      → Phase 1 (Offer Submissions) & Phase 8 (Appeals)
  compliance.py  → Phase 2 (Administrative / Compliance Checklists)
  evaluation.py  → Phase 3 (Technical), Phase 4 (Financial), Phase 5 (Combined)
  committee.py   → Phase 6 (Score Overrides) & Phase 7 (Award Decision)
  enterprise.py  → Enterprise tooling (Go/No-Go triage, CV formatter)

Each sub-router is a stub right now — full implementation follows per Milestone.
"""

from fastapi import APIRouter

from app.api.v1.intake import router as intake_router
from app.api.v1.tender import router as tender_router
from app.api.v1.compliance import router as compliance_router
from app.api.v1.evaluation import router as evaluation_router
from app.api.v1.committee import router as committee_router
from app.api.v1.enterprise import router as enterprise_router

router = APIRouter()

router.include_router(
    tender_router, prefix="/tenders", tags=["Phase 0 — Tender Management"]
)
router.include_router(
    intake_router, prefix="/intake", tags=["Phase 1 & 8 — Intake & Appeals"]
)
router.include_router(
    compliance_router, prefix="/compliance", tags=["Phase 2 — Compliance"]
)
router.include_router(
    evaluation_router, prefix="/evaluation", tags=["Phase 3-5 — Evaluation"]
)
router.include_router(
    committee_router, prefix="/committee", tags=["Phase 6 & 7 — Committee"]
)
router.include_router(
    enterprise_router,
    prefix="/enterprise",
    tags=["Enterprise — Bidder Tooling"],
)
