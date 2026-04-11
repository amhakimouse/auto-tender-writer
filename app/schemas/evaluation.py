"""
app/schemas/evaluation.py

Pydantic schemas for evaluation API responses.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EvaluationStatus(StrEnum):
    """Status of an evaluation."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CriterionScore(BaseModel):
    """Score for a single criterion."""

    criterion: str
    max_score: int
    raw_score: int
    justification: str


class EvaluationResult(BaseModel):
    """Result of an evaluation run."""

    model_config = ConfigDict(from_attributes=True)

    tender_id: int
    status: EvaluationStatus
    total_offers: int
    processed_offers: int
    compliant_offers: int
    disqualified_offers: int
    scored_offers: int
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
