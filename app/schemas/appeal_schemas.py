"""
app/schemas/appeal_schemas.py

Pydantic schemas for Appeal processing (Phase 8).

These schemas define the contract between the LLM and Python for:
    - Extracting grievances from appeal PDFs
    - Drafting counter-explanations for the committee
    - Structured appeal response generation

Design Principles:
    - Every field has type annotations and validation constraints
    - Required fields force the LLM to provide values
    - Optional fields use | None with Field(default=None)
    - String enums constrain values to expected vocabulary
    - All LLM outputs are strictly validated by Pydantic
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


# =============================================================================
# Phase 8 — Appeal Grievance Extraction
# =============================================================================


class GrievanceType(StrEnum):
    """Classification of appeal grievance types."""

    TECHNICAL_SCORING = "TECHNICAL_SCORING"
    FINANCIAL_SCORING = "FINANCIAL_SCORING"
    COMPLIANCE_DECISION = "COMPLIANCE_DECISION"
    PROCEDURAL_IRREGULARITY = "PROCEDURAL_IRREGULARITY"
    CONFLICT_OF_INTEREST = "CONFLICT_OF_INTEREST"
    DOCUMENTATION_ERROR = "DOCUMENTATION_ERROR"
    OTHER = "OTHER"


class Grievance(BaseModel):
    """
    A single grievance extracted from an appeal document.

    The LLM identifies each distinct issue raised by the appellant
    and classifies it for committee review.
    """

    model_config = ConfigDict(extra="forbid")

    grievance_type: GrievanceType = Field(
        ...,
        description="Classification of this grievance",
    )
    summary: Annotated[str, StringConstraints(min_length=20, max_length=500)] = Field(
        ...,
        description="Brief summary of the grievance (20-500 chars)",
    )
    detailed_description: Annotated[
        str, StringConstraints(min_length=50, max_length=2000)
    ] = Field(
        ...,
        description="Full description of the appellant's concern",
    )
    specific_claims: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Specific factual claims made by appellant",
    )
    requested_relief: str | None = Field(
        default=None,
        max_length=500,
        description="What the appellant is asking for",
    )
    relevant_document_refs: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Document references or section numbers cited",
    )


class AppealGrievanceExtraction(BaseModel):
    """
    LLM output schema for extracting grievances from an appeal PDF.

    The LLM reads the appeal document and outputs structured
    grievances for committee review.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": "Structured extraction of appeal grievances"},
    )

    # --- Core Grievances ---
    grievances: list[Grievance] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="List of distinct grievances identified in the appeal",
    )

    # --- Overall Assessment ---
    overall_summary: Annotated[
        str, StringConstraints(min_length=50, max_length=1000)
    ] = Field(
        ...,
        description="Executive summary of all grievances in the appeal",
    )

    # --- Factual Basis ---
    factual_basis: str | None = Field(
        default=None,
        max_length=2000,
        description="Summary of factual basis claimed by appellant",
    )

    # --- Legal/Procedural Grounds ---
    legal_grounds: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Legal or procedural grounds cited by appellant",
    )

    # --- Supporting Evidence ---
    evidence_cited: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Evidence or documents cited in support",
    )

    # --- Confidence ---
    extraction_confidence: str = Field(
        default="MEDIUM",
        description="HIGH, MEDIUM, or LOW confidence in extraction",
    )
    extraction_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Notes on extraction challenges or ambiguities",
    )

    @field_validator("grievances")
    @classmethod
    def validate_at_least_one_grievance(cls, v: list[Grievance]) -> list[Grievance]:
        """Ensure at least one grievance was extracted."""
        if len(v) == 0:
            raise ValueError("At least one grievance must be extracted")
        return v


# =============================================================================
# Phase 8 — Counter-Explanation Drafting
# =============================================================================


class CounterExplanationSection(BaseModel):
    """
    A single section of the counter-explanation addressing one grievance.
    """

    model_config = ConfigDict(extra="forbid")

    grievance_id: int = Field(
        ...,
        ge=1,
        description="Index of the grievance being addressed (1-based)",
    )
    grievance_summary: str = Field(
        ...,
        max_length=500,
        description="Brief restatement of the grievance",
    )
    committee_response: Annotated[
        str, StringConstraints(min_length=100, max_length=2000)
    ] = Field(
        ...,
        description="Detailed response addressing the specific grievance",
    )
    factual_findings: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Factual findings that support the committee's position",
    )
    procedural_references: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Relevant procedure or regulation references",
    )
    conclusion: str = Field(
        ...,
        max_length=500,
        description="Conclusion on this specific grievance",
    )


class AppealCounterExplanation(BaseModel):
    """
    LLM output schema for drafting counter-explanations.

    The LLM combines the extracted grievances with the original
    evaluation audit trail to draft a structured, official
    counter-explanation for the committee.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": "Official counter-explanation for appeal committee"
        },
    )

    # --- Header ---
    appeal_reference: str = Field(
        ...,
        max_length=100,
        description="Reference number for this appeal response",
    )
    tender_title: str = Field(
        ...,
        max_length=500,
        description="Title of the tender being appealed",
    )
    appellant_name: str = Field(
        ...,
        max_length=255,
        description="Name of the appellant organization",
    )

    # --- Executive Summary ---
    executive_summary: Annotated[
        str, StringConstraints(min_length=100, max_length=1500)
    ] = Field(
        ...,
        description="High-level summary of the committee's position",
    )

    # --- Section-by-Section Responses ---
    responses: list[CounterExplanationSection] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Individual responses to each grievance",
    )

    # --- Original Evaluation Context ---
    original_score_summary: str | None = Field(
        default=None,
        max_length=1000,
        description="Summary of original evaluation scores and methodology",
    )

    # --- Committee Position ---
    overall_committee_position: str = Field(
        ...,
        max_length=500,
        description="Overall committee position: UPHELD or OVERTURNED",
    )
    recommended_action: str | None = Field(
        default=None,
        max_length=500,
        description="Recommended action for the committee",
    )

    # --- Quality Indicators ---
    confidence_level: str = Field(
        default="MEDIUM",
        description="Confidence in the counter-explanation: HIGH, MEDIUM, LOW",
    )
    drafting_notes: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Internal notes on drafting decisions",
    )

    @field_validator("responses")
    @classmethod
    def validate_sequential_grievance_ids(
        cls, v: list[CounterExplanationSection]
    ) -> list[CounterExplanationSection]:
        """Ensure grievance IDs are sequential starting from 1."""
        expected_ids = set(range(1, len(v) + 1))
        actual_ids = {section.grievance_id for section in v}
        if actual_ids != expected_ids:
            raise ValueError(
                f"Grievance IDs must be sequential from 1 to {len(v)}. "
                f"Got: {sorted(actual_ids)}"
            )
        return v


# =============================================================================
# API Request/Response Schemas
# =============================================================================


class AppealSubmissionRequest(BaseModel):
    """Request body for submitting a new appeal."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "offer_id": 123,
                "appellant_name": "Acme Corporation",
                "appellant_email": "legal@acme.com",
            }
        }
    )

    offer_id: int = Field(..., gt=0, description="ID of the offer being appealed")
    appellant_name: str = Field(
        ...,
        min_length=2,
        max_length=255,
        description="Name of the organization filing the appeal",
    )
    appellant_email: str | None = Field(
        default=None,
        description="Contact email for appeal correspondence",
    )


class AppealSubmissionResponse(BaseModel):
    """Response after submitting an appeal."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    appeal_id: int | None
    tender_id: int | None
    offer_id: int | None
    status: str | None
    appeal_window_deadline: datetime | None
    message: str
    error_code: str | None = None


class AppealReviewResponse(BaseModel):
    """Response containing the full appeal review data."""

    model_config = ConfigDict(from_attributes=True)

    appeal_id: int
    tender_id: int
    offer_id: int
    appellant_name: str
    status: str
    submitted_at: datetime
    appeal_window_deadline: datetime
    grievances: AppealGrievanceExtraction | None = None
    counter_explanation: AppealCounterExplanation | None = None
    committee_decision: str | None = None
    decision_justification: str | None = None
    resolved_at: datetime | None = None


class AppealResolutionRequest(BaseModel):
    """Request to resolve an appeal with committee decision."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "committee_decision": "UPHELD",
                "justification": "After careful review...",
                "committee_member_id": "user:42",
            }
        }
    )

    committee_decision: str = Field(
        ...,
        pattern="^(UPHELD|OVERTURNED)$",
        description="Final decision: UPHELD or OVERTURNED",
    )
    justification: str = Field(
        ...,
        min_length=50,
        max_length=5000,
        description="Detailed justification for the decision",
    )
    committee_member_id: str = Field(
        ...,
        min_length=2,
        description="ID of the committee member making the decision",
    )


class AppealResolutionResponse(BaseModel):
    """Response after resolving an appeal."""

    appeal_id: int
    tender_id: int
    offer_id: int
    committee_decision: str
    decided_at: datetime
    decided_by: str


# =============================================================================
# Factory Functions
# =============================================================================


def create_empty_grievance_extraction() -> AppealGrievanceExtraction:
    """Factory for empty grievance extraction (error fallback)."""
    return AppealGrievanceExtraction(
        grievances=[
            Grievance(
                grievance_type=GrievanceType.OTHER,
                summary="Extraction failed - grievances could not be parsed",
                detailed_description="The LLM was unable to extract structured grievances from the appeal document. Manual review required.",
                specific_claims=["Extraction failed"],
            )
        ],
        overall_summary="Grievance extraction failed - fallback to manual review",
        extraction_confidence="LOW",
        extraction_notes="An error occurred during LLM extraction; this is a safe fallback",
    )


def create_empty_counter_explanation(
    appeal_reference: str = "UNKNOWN",
    tender_title: str = "UNKNOWN",
    appellant_name: str = "UNKNOWN",
) -> AppealCounterExplanation:
    """Factory for empty counter-explanation (error fallback)."""
    return AppealCounterExplanation(
        appeal_reference=appeal_reference,
        tender_title=tender_title,
        appellant_name=appellant_name,
        executive_summary="Counter-explanation drafting failed. Manual committee review required.",
        responses=[
            CounterExplanationSection(
                grievance_id=1,
                grievance_summary="Drafting failed",
                committee_response="The LLM was unable to draft a counter-explanation. Manual review and drafting required by committee.",
                conclusion="Manual review required",
            )
        ],
        overall_committee_position="MANUAL_REVIEW_REQUIRED",
        confidence_level="LOW",
        drafting_notes=["Drafting failed - fallback to manual process"],
    )
