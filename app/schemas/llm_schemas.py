"""
app/schemas/llm_schemas.py

Pydantic v2 schemas for LLM-structured outputs.

These schemas are the CONTRACT between the LLM and Python.
They enforce strict validation to catch hallucinations and malformed JSON.

Design Principles:
    - Every field has type annotations and validation constraints
    - Required fields (no default) force the LLM to provide values
    - Optional fields use `| None` with Field(default=None)
    - String enums constrain values to expected vocabulary
    - Scores have min/max bounds to catch out-of-range hallucinations
    - Descriptions help LLMs understand field semantics
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


# =============================================================================
# Phase 2 — Administrative Compliance
# =============================================================================


class ComplianceConfidence(StrEnum):
    """Confidence level in the compliance extraction."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ComplianceChecklist(BaseModel):
    """
    LLM output schema for administrative compliance checking (Phase 2).

    The LLM must examine the document and determine which mandatory
    documents and certifications are present.

    Python (The Enforcer) will disqualify the offer if any mandatory
    item is False. The LLM only provides observations.
    """

    model_config = ConfigDict(
        extra="forbid",  # Reject any unexpected fields (prevents hallucinations)
        json_schema_extra={
            "description": "Administrative compliance checklist extraction result"
        },
    )

    # --- Mandatory Document Checks (all required) ---
    has_tax_document: bool = Field(
        ...,
        description="Whether tax compliance certificate/document is present",
    )
    has_company_registration: bool = Field(
        ...,
        description="Whether company registration/business license is present",
    )
    has_bid_bond: bool = Field(
        ...,
        description="Whether bid bond/guarantee is present",
    )
    has_audited_financials: bool = Field(
        ...,
        description="Whether audited financial statements are present",
    )
    has_signature: bool = Field(
        ...,
        description="Whether the document has authorized signature(s)",
    )
    has_methodology: bool = Field(
        ...,
        description="Whether technical methodology/approach is described",
    )

    # --- Document List (what was actually found) ---
    documents_found: list[str] = Field(
        default_factory=list,
        description="List of document titles/types found in the submission",
    )

    # --- Exception Tracking ---
    missing_documents: list[str] = Field(
        default_factory=list,
        description="List of required documents that appear to be missing",
    )
    compliance_notes: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional notes on compliance findings or exceptions",
    )

    # --- LLM Confidence (for monitoring) ---
    extraction_confidence: ComplianceConfidence = Field(
        default=ComplianceConfidence.MEDIUM,
        description="LLM's confidence in this extraction (HIGH/MEDIUM/LOW)",
    )

    @field_validator("documents_found", "missing_documents")
    @classmethod
    def validate_document_list(cls, v: list[str]) -> list[str]:
        """Ensure document names are non-empty and trimmed."""
        return [doc.strip() for doc in v if doc and doc.strip()]


# =============================================================================
# Phase 3 — Technical Scoring
# =============================================================================


class CriterionScore(BaseModel):
    """
    Score for a single technical evaluation criterion.

    This is a sub-model used within TechnicalScore.
    """

    model_config = ConfigDict(extra="forbid")

    criterion: Annotated[str, StringConstraints(min_length=1, max_length=200)] = Field(
        ...,
        description="Name of the evaluation criterion",
    )
    max_score: int = Field(
        ...,
        ge=1,
        le=100,
        description="Maximum possible score for this criterion",
    )
    raw_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Actual score awarded (must be 0 to max_score)",
    )
    justification: Annotated[str, StringConstraints(min_length=10, max_length=1000)] = (
        Field(
            ...,
            description="Written explanation for the score awarded",
        )
    )

    @field_validator("raw_score")
    @classmethod
    def validate_score_bounds(cls, v: int, info) -> int:
        """Ensure raw_score does not exceed max_score."""
        max_score = info.data.get("max_score")
        if max_score is not None and v > max_score:
            raise ValueError(f"raw_score ({v}) cannot exceed max_score ({max_score})")
        return v


class TechnicalScore(BaseModel):
    """
    LLM output schema for technical evaluation scoring (Phase 3).

    The LLM evaluates the offer against a rubric and provides scores
    with written justifications for each criterion.

    Python (The Enforcer) will:
        - Validate all scores are within bounds
        - Calculate the weighted technical score
        - Flag any criteria the LLM may have hallucinated
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": "Technical evaluation scoring result"},
    )

    # --- Individual Criterion Scores ---
    criteria_scores: list[CriterionScore] = Field(
        ...,
        min_length=0,   # 0 allows the empty-fallback factory; real LLM output will have ≥1
        max_length=20,
        description="Scores for each criterion in the evaluation rubric",
    )

    # --- Overall Assessment ---
    total_raw_score: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Sum of all criterion scores (auto-calculated if null)",
    )
    overall_summary: Annotated[
        str, StringConstraints(min_length=20, max_length=2000)
    ] = Field(
        ...,
        description="Overall assessment of the technical offer quality",
    )
    key_strengths: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Top strengths identified in the proposal",
    )
    key_weaknesses: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Key weaknesses or gaps in the proposal",
    )

    # --- Confidence ---
    scoring_confidence: ComplianceConfidence = Field(
        default=ComplianceConfidence.MEDIUM,
        description="LLM's confidence in scoring accuracy",
    )
    scoring_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Additional notes on the scoring rationale",
    )

    @field_validator("total_raw_score")
    @classmethod
    def validate_total(cls, v: int | None) -> int | None:
        """Total must not exceed 100 points."""
        if v is not None and v > 100:
            raise ValueError("Total score cannot exceed 100")
        return v

    def calculate_total(self) -> int:
        """Calculate total from criteria scores."""
        return sum(c.raw_score for c in self.criteria_scores)


# =============================================================================
# Phase 4 — Financial Extraction
# =============================================================================


class Currency(StrEnum):
    """ISO 4217 currency codes."""

    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    NGN = "NGN"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"
    CHF = "CHF"
    CNY = "CNY"
    OTHER = "OTHER"


class PriceBreakdown(BaseModel):
    """Detailed breakdown of the bid price."""

    model_config = ConfigDict(extra="forbid")

    labour: float | None = Field(default=None, ge=0)
    materials: float | None = Field(default=None, ge=0)
    overhead: float | None = Field(default=None, ge=0)
    profit_margin_pct: float | None = Field(default=None, ge=0, le=100)
    other: float | None = Field(default=None, ge=0)


class FinancialData(BaseModel):
    """
    LLM output schema for financial data extraction (Phase 4).

    The LLM extracts numeric bid values. Python applies the scoring formula.
    """

    model_config = ConfigDict(extra="forbid")

    total_bid_price: float = Field(
        ...,
        ge=0,
        description="Total bid price as stated in the document",
    )
    currency: Currency = Field(
        ...,
        description="ISO 4217 currency code",
    )
    price_breakdown: PriceBreakdown = Field(
        default_factory=PriceBreakdown,
        description="Optional breakdown of costs",
    )
    bid_validity_days: int | None = Field(
        default=None,
        ge=1,
        le=365,
        description="Number of days the bid remains valid",
    )
    payment_terms: str | None = Field(
        default=None,
        max_length=500,
        description="Payment terms described in the offer",
    )

    # --- Confidence ---
    extraction_confidence: ComplianceConfidence = Field(
        default=ComplianceConfidence.MEDIUM,
        description="Confidence in the extraction accuracy",
    )
    extraction_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Notes on extraction challenges or assumptions",
    )


# =============================================================================
# Unified Result Types (for internal use)
# =============================================================================


def create_empty_compliance_result() -> ComplianceChecklist:
    """Factory for empty compliance result (all False)."""
    return ComplianceChecklist(
        has_tax_document=False,
        has_company_registration=False,
        has_bid_bond=False,
        has_audited_financials=False,
        has_signature=False,
        has_methodology=False,
        documents_found=[],
        missing_documents=[],
        compliance_notes="Extraction failed - fallback to empty result",
        extraction_confidence=ComplianceConfidence.LOW,
    )


def create_empty_technical_score() -> TechnicalScore:
    """Factory for empty technical score (error fallback — all zeros)."""
    return TechnicalScore(
        criteria_scores=[],          # allowed by min_length=0
        overall_summary="Scoring failed — fallback to empty result (extraction error).",
        key_strengths=[],
        key_weaknesses=[],
        scoring_confidence=ComplianceConfidence.LOW,
        scoring_notes="An error occurred during LLM scoring; this is a safe fallback.",
    )
