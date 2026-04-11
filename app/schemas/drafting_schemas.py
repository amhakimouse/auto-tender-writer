"""
app/schemas/drafting_schemas.py

Pydantic schemas for Enterprise RAG Bid Drafting.

These schemas define:
    - Input: Past winning bids and new tender requirements
    - Output: Drafted proposal sections with citations
    - Gap analysis and quality metrics

Design Principles:
    - Strict validation for LLM outputs
    - Clear citation tracking for audit trail
    - Quality metrics for coverage assessment
    - Support for iterative drafting workflows
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


# =============================================================================
# Input Schemas
# =============================================================================


class PastWinningBid(BaseModel):
    """
    A snippet from a past winning bid to use as RAG source material.
    """

    model_config = ConfigDict(extra="forbid")

    bid_reference: str = Field(
        ...,
        max_length=100,
        description="Reference identifier for the past bid",
    )
    original_tender_title: str | None = Field(
        default=None,
        max_length=500,
        description="Title of the original tender this bid won",
    )
    winning_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Score received (if known)",
    )
    content_snippet: Annotated[
        str, StringConstraints(min_length=100, max_length=10000)
    ] = Field(
        ...,
        description="Relevant content from the past bid",
    )
    key_success_factors: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Why this bid won (strengths identified)",
    )
    date_won: date | None = Field(
        default=None,
        description="When this bid was awarded",
    )


class ProposalDraftRequest(BaseModel):
    """
    Request to draft a proposal using RAG from past winning bids.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tender_id": 123,
                "past_winning_bids": [
                    {
                        "bid_reference": "BID-2023-001",
                        "content_snippet": "Our methodology...",
                        "key_success_factors": [
                            "Innovative approach",
                            "Cost efficiency",
                        ],
                    }
                ],
                "max_pages": 5,
                "tone_requirements": "Formal, technical, detailed",
                "focus_areas": ["cloud migration", "security"],
            }
        }
    )

    tender_id: int = Field(
        ...,
        gt=0,
        description="ID of the tender to draft proposal for",
    )
    past_winning_bids: list[PastWinningBid] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Past winning bid snippets to use as source material",
    )
    max_pages: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum page count for the draft",
    )
    tone_requirements: str | None = Field(
        default=None,
        max_length=500,
        description="Desired tone: formal/casual, technical/business, etc.",
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Specific areas to emphasize in the draft",
    )
    additional_instructions: str | None = Field(
        default=None,
        max_length=2000,
        description="Any additional instructions for the drafter",
    )

    @field_validator("past_winning_bids")
    @classmethod
    def validate_at_least_one_bid(cls, v: list[PastWinningBid]) -> list[PastWinningBid]:
        """Ensure at least one past bid is provided."""
        if len(v) == 0:
            raise ValueError("At least one past winning bid is required")
        return v


# =============================================================================
# Output Schemas (LLM Generated)
# =============================================================================


class ContentSource(BaseModel):
    """
    Citation of source material used in a drafted section.
    """

    model_config = ConfigDict(extra="forbid")

    bid_reference: str = Field(
        ...,
        description="Reference to the past bid used",
    )
    relevance_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="How relevant this source was to the section (0-100)",
    )
    adaptation_notes: str | None = Field(
        default=None,
        max_length=500,
        description="How content was adapted from source",
    )


class SectionDraft(BaseModel):
    """
    A single section of the drafted proposal.
    """

    model_config = ConfigDict(extra="forbid")

    section_title: Annotated[str, StringConstraints(min_length=5, max_length=200)] = (
        Field(
            ...,
            description="Title of this section",
        )
    )
    section_requirement: str = Field(
        ...,
        max_length=1000,
        description="The tender requirement this section addresses",
    )
    drafted_content: Annotated[
        str, StringConstraints(min_length=50, max_length=10000)
    ] = Field(
        ...,
        description="The drafted content for this section",
    )
    word_count: int = Field(
        ...,
        ge=0,
        description="Word count of drafted content",
    )
    sources_used: list[ContentSource] = Field(
        default_factory=list,
        max_length=10,
        description="Past bids used as sources for this section",
    )
    is_new_content: bool = Field(
        default=False,
        description="True if no suitable past content was found",
    )
    quality_assessment: str | None = Field(
        default=None,
        max_length=500,
        description="LLM assessment of section quality",
    )


class GapAnalysis(BaseModel):
    """
    Analysis of gaps between requirements and drafted content.
    """

    model_config = ConfigDict(extra="forbid")

    requirement_text: str = Field(
        ...,
        description="The requirement with a coverage gap",
    )
    gap_type: str = Field(
        ...,
        description="MISSING_CONTENT, NEEDS_EXPANSION, NEEDS_EVIDENCE, etc.",
    )
    severity: str = Field(
        ...,
        description="CRITICAL, HIGH, MEDIUM, or LOW",
    )
    suggested_action: str | None = Field(
        default=None,
        max_length=500,
        description="What to do to address this gap",
    )


class DraftedProposal(BaseModel):
    """
    Complete LLM output schema for RAG-drafted proposal.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": "RAG-drafted proposal with citations and quality metrics"
        },
    )

    # --- Metadata ---
    tender_id: int = Field(
        ...,
        description="ID of the tender this draft is for",
    )
    tender_title: str | None = Field(
        default=None,
        max_length=500,
        description="Title of the tender",
    )
    draft_version: str = Field(
        default="1.0",
        description="Version of this draft",
    )
    generated_at: str = Field(
        ...,
        description="ISO timestamp when draft was generated",
    )

    # --- Drafted Content ---
    sections: list[SectionDraft] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Drafted sections of the proposal",
    )
    executive_summary: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional executive summary",
    )

    # --- Quality Metrics ---
    estimated_page_count: float = Field(
        ...,
        ge=0.5,
        le=100,
        description="Estimated page count based on content",
    )
    total_word_count: int = Field(
        ...,
        ge=0,
        description="Total words across all sections",
    )
    coverage_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="How well requirements are covered (0-100)",
    )

    # --- Gap Analysis ---
    gaps: list[GapAnalysis] = Field(
        default_factory=list,
        max_length=20,
        description="Requirements not well covered by past content",
    )

    # --- Source Statistics ---
    bids_used: list[str] = Field(
        default_factory=list,
        description="References of past bids that contributed content",
    )
    new_content_percentage: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Percentage of content that is new (not from past bids)",
    )

    # --- Confidence ---
    draft_confidence: str = Field(
        default="MEDIUM",
        description="HIGH, MEDIUM, or LOW confidence in the draft",
    )
    drafting_notes: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Notes on drafting decisions and challenges",
    )

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, v: list[SectionDraft]) -> list[SectionDraft]:
        """Ensure sections are valid."""
        if len(v) == 0:
            raise ValueError("At least one section must be drafted")
        return v


# =============================================================================
# API Response Schemas
# =============================================================================


class DraftProposalResponse(BaseModel):
    """Response from proposal drafting request."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    tender_id: int
    draft: DraftedProposal | None = None
    message: str
    processing_time_ms: int | None = None
    error_code: str | None = None


class SectionRefinementRequest(BaseModel):
    """Request to refine a specific section."""

    tender_id: int = Field(..., gt=0)
    section_title: str = Field(..., min_length=1)
    current_content: str = Field(..., min_length=10)
    refinement_instructions: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="How to improve this section",
    )
    additional_sources: list[PastWinningBid] = Field(default_factory=list)


class GapAnalysisResponse(BaseModel):
    """Response from gap analysis."""

    success: bool
    tender_id: int
    coverage_score: int
    total_gaps: int
    critical_gaps: int
    gaps: list[GapAnalysis]
    recommendations: list[str]


# =============================================================================
# Factory Functions
# =============================================================================


def create_empty_draft(tender_id: int) -> DraftedProposal:
    """Factory for empty draft (error fallback)."""
    from datetime import datetime, timezone

    return DraftedProposal(
        tender_id=tender_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sections=[
            SectionDraft(
                section_title="Draft Generation Failed",
                section_requirement="N/A",
                drafted_content="The LLM was unable to draft the proposal. Please try again with different past bids or requirements.",
                word_count=0,
                is_new_content=True,
                quality_assessment="Drafting failed - fallback content",
            )
        ],
        estimated_page_count=0.5,
        total_word_count=0,
        coverage_score=0,
        draft_confidence="LOW",
        drafting_notes=["Drafting failed - fallback to manual process"],
    )


def create_empty_section(title: str = "Untitled") -> SectionDraft:
    """Factory for empty section (error fallback)."""
    return SectionDraft(
        section_title=title,
        section_requirement="N/A",
        drafted_content="Section drafting failed. Manual review required.",
        word_count=0,
        is_new_content=True,
        quality_assessment="Drafting failed",
    )
