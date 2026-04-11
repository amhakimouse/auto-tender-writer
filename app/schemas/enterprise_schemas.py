"""
app/schemas/enterprise_schemas.py

Pydantic schemas for Enterprise (Bidder/Tender Writer) tooling.

These schemas support:
    - Go/No-Go decision making (should we bid on this tender?)
    - Employee profile management (master resumes)
    - CV formatting for specific tenders

Design Principles:
    - Strict validation to ensure data quality
    - Clear documentation for LLM context
    - Support for both structured data and text fields
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


# =============================================================================
# Go/No-Go Decision Making
# =============================================================================


class RiskLevel(StrEnum):
    """Risk level classification for tender opportunities."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TenderRequirement(BaseModel):
    """A single requirement extracted from a tender document."""

    model_config = ConfigDict(extra="forbid")

    requirement_text: Annotated[
        str, StringConstraints(min_length=10, max_length=1000)
    ] = Field(
        ...,
        description="The requirement as stated in the tender",
    )
    requirement_type: str = Field(
        ...,
        description="Category: MANDATORY, PREFERRED, TECHNICAL, FINANCIAL, etc.",
    )
    is_mandatory: bool = Field(
        default=False,
        description="Whether this is a mandatory (pass/fail) requirement",
    )


class CapabilityMatch(BaseModel):
    """Assessment of how well enterprise matches a requirement."""

    model_config = ConfigDict(extra="forbid")

    requirement: str = Field(..., description="The tender requirement")
    match_status: str = Field(
        ...,
        description="FULL_MATCH, PARTIAL_MATCH, NO_MATCH, UNKNOWN",
    )
    evidence: str | None = Field(
        default=None,
        description="Evidence from enterprise capabilities supporting this match",
    )
    gap_description: str | None = Field(
        default=None,
        description="Description of any gap if not full match",
    )


class GoNoGoDecision(BaseModel):
    """
    LLM output schema for Go/No-Go tender opportunity assessment.

    This schema captures the decision of whether an enterprise should
    invest resources in bidding on a particular tender.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": "Go/No-Go decision for tender opportunity"},
    )

    # --- Core Decision ---
    is_eligible: bool = Field(
        ...,
        description="Whether the enterprise should proceed with this tender (Go=True, No-Go=False)",
    )
    eligibility_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Overall eligibility score from 0-100 (100 = perfect match)",
    )
    confidence_level: str = Field(
        default="MEDIUM",
        description="Confidence in this assessment: HIGH, MEDIUM, LOW",
    )

    # --- Detailed Assessment ---
    capability_matches: list[CapabilityMatch] = Field(
        default_factory=list,
        description="Detailed assessment of each key requirement vs enterprise capabilities",
    )

    # --- Risk Analysis ---
    key_risks: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key risks that could prevent winning or successful delivery",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.MEDIUM,
        description="Overall risk level of pursuing this tender",
    )

    # --- Recommendation ---
    recommendation: Annotated[
        str, StringConstraints(min_length=50, max_length=2000)
    ] = Field(
        ...,
        description="Detailed recommendation explaining the Go/No-Go decision",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Specific actions to improve eligibility if proceeding",
    )

    # --- Financial Considerations ---
    estimated_bid_cost: str | None = Field(
        default=None,
        description="Estimated cost to prepare and submit this bid",
    )
    win_probability_estimate: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Estimated probability of winning if bid (0-100)",
    )

    @field_validator("eligibility_score")
    @classmethod
    def validate_score_bounds(cls, v: int) -> int:
        """Ensure score is within 0-100 range."""
        if v < 0:
            return 0
        if v > 100:
            return 100
        return v

    @field_validator("key_risks")
    @classmethod
    def validate_risks_not_empty_if_no_go(cls, v: list[str], info) -> list[str]:
        """If No-Go decision, ensure key_risks explains why."""
        is_eligible = info.data.get("is_eligible")
        if is_eligible is False and len(v) == 0:
            raise ValueError("key_risks must not be empty when is_eligible=False")
        return v


# =============================================================================
# Employee Profile Management
# =============================================================================


class SkillLevel(StrEnum):
    """Proficiency level for a skill."""

    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class Skill(BaseModel):
    """A skill with proficiency and years of experience."""

    model_config = ConfigDict(extra="forbid")

    skill_name: Annotated[str, StringConstraints(min_length=2, max_length=100)] = Field(
        ...,
        description="Name of the skill/technology/competency",
    )
    years_experience: float = Field(
        ...,
        ge=0,
        le=50,
        description="Years of experience with this skill",
    )
    proficiency_level: SkillLevel = Field(
        default=SkillLevel.INTERMEDIATE,
        description="Proficiency level from BEGINNER to EXPERT",
    )
    last_used_date: date | None = Field(
        default=None,
        description="When this skill was last used professionally",
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Relevant certifications for this skill",
    )


class WorkExperience(BaseModel):
    """A work experience entry in an employee's career."""

    model_config = ConfigDict(extra="forbid")

    company: Annotated[str, StringConstraints(min_length=2, max_length=200)] = Field(
        ...,
        description="Employer or client organization",
    )
    role_title: Annotated[str, StringConstraints(min_length=2, max_length=200)] = Field(
        ...,
        description="Job title or role",
    )
    start_date: date = Field(..., description="Start date of employment")
    end_date: date | None = Field(
        default=None,
        description="End date (None = current position)",
    )
    description: Annotated[str, StringConstraints(min_length=20, max_length=3000)] = (
        Field(
            ...,
            description="Detailed description of responsibilities and achievements",
        )
    )
    key_projects: list[str] = Field(
        default_factory=list,
        description="Notable projects completed in this role",
    )
    skills_used: list[str] = Field(
        default_factory=list,
        description="Skills and technologies used in this role",
    )


class Education(BaseModel):
    """Educational qualification."""

    institution: Annotated[str, StringConstraints(min_length=2, max_length=200)] = (
        Field(
            ...,
            description="University, college, or institution name",
        )
    )
    degree: Annotated[str, StringConstraints(min_length=2, max_length=200)] = Field(
        ...,
        description="Degree or certification earned",
    )
    field_of_study: str | None = Field(
        default=None,
        description="Major, specialization, or field",
    )
    graduation_year: int | None = Field(
        default=None,
        ge=1950,
        le=2030,
        description="Year of graduation",
    )


class EmployeeProfile(BaseModel):
    """
    Master resume/profile for an enterprise employee.

    This is the canonical record from which tailored CVs are generated
    for specific tender opportunities.
    """

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
    )

    # --- Identity ---
    id: int | None = Field(
        default=None,
        description="Database ID (None for new profiles)",
    )
    full_name: Annotated[str, StringConstraints(min_length=2, max_length=200)] = Field(
        ...,
        description="Employee's full name",
    )
    email: str | None = Field(
        default=None,
        description="Contact email",
    )
    phone: str | None = Field(
        default=None,
        description="Contact phone number",
    )
    current_role: str | None = Field(
        default=None,
        description="Current job title",
    )
    years_total_experience: float = Field(
        default=0,
        ge=0,
        le=60,
        description="Total years of professional experience",
    )

    # --- Professional Summary ---
    executive_summary: Annotated[str, StringConstraints(max_length=1500)] = Field(
        default="",
        description="High-level professional summary (master version)",
    )

    # --- Core Data ---
    skills: list[Skill] = Field(
        default_factory=list,
        description="All skills with proficiency and experience",
        max_length=100,
    )
    work_experience: list[WorkExperience] = Field(
        default_factory=list,
        description="Complete work history",
        max_length=20,
    )
    education: list[Education] = Field(
        default_factory=list,
        description="Educational qualifications",
    )
    certifications: list[str] = Field(
        default_factory=list,
        description="Professional certifications",
    )

    # --- Tender-Specific Metadata ---
    key_strengths: list[str] = Field(
        default_factory=list,
        description="Key professional strengths for marketing",
    )
    industry_expertise: list[str] = Field(
        default_factory=list,
        description="Industries where employee has deep expertise",
    )
    languages: list[str] = Field(
        default_factory=list,
        description="Languages spoken/written",
    )
    security_clearance: str | None = Field(
        default=None,
        description="Security clearance level if applicable",
    )

    # --- Internal ---
    profile_version: int = Field(
        default=1,
        description="Version number for tracking updates",
    )
    last_updated: date | None = Field(
        default=None,
        description="Last update date",
    )


# =============================================================================
# CV Formatting / Generation
# =============================================================================


class CVTailoringRequest(BaseModel):
    """Request to generate a tailored CV for a specific tender."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": 1,
                "tender_id": 2,
                "max_pages": 3,
                "focus_areas": ["cloud migration", "security"],
            }
        }
    )

    employee_id: int = Field(
        ...,
        description="ID of the employee profile to use",
    )
    tender_id: int = Field(
        ...,
        description="ID of the tender to tailor the CV for",
    )
    max_pages: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Maximum page count for the output CV",
    )
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Specific areas to emphasize in the CV",
    )
    excluded_experience: list[str] = Field(
        default_factory=list,
        description="Experience to exclude (e.g., outdated or irrelevant)",
    )


class TailoredCVOutput(BaseModel):
    """
    LLM output schema for tailored CV generation.
    """

    model_config = ConfigDict(extra="forbid")

    # --- Generated Content ---
    executive_summary: Annotated[
        str, StringConstraints(min_length=100, max_length=800)
    ] = Field(
        ...,
        description="Tailored executive summary highlighting relevant experience",
    )
    relevant_skills: list[str] = Field(
        ...,
        description="Skills selected as relevant to this tender",
        max_length=20,
    )
    relevant_experience: list[dict] = Field(
        ...,
        description="Work experience entries tailored for this tender",
    )

    # --- Content Metadata ---
    estimated_page_count: float = Field(
        ...,
        ge=0.5,
        le=10,
        description="Estimated pages based on content length",
    )
    content_cut: bool = Field(
        default=False,
        description="Whether content was cut to meet page limits",
    )
    relevance_score: int = Field(
        ...,
        ge=0,
        le=100,
        description="How well this CV matches the tender (0-100)",
    )

    # --- Quality Indicators ---
    tailoring_notes: list[str] = Field(
        default_factory=list,
        description="Notes on what was emphasized/cut and why",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Potential issues with this CV for the tender",
    )


class FormattedCVResponse(BaseModel):
    """API response for formatted CV generation."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    employee_id: int
    tender_id: int
    formatted_cv: TailoredCVOutput
    output_path: str | None = None
    error_message: str | None = None


# =============================================================================
# Enterprise Tender Triage
# =============================================================================


class TenderTriageRequest(BaseModel):
    """Request to perform Go/No-Go analysis on a tender."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enterprise_capabilities": "We specialize in cloud migration, security audits...",
                "tender_pdf_path": "/uploads/tender_123.pdf",
                "bid_budget": "$50,000",
            }
        }
    )

    enterprise_capabilities: str = Field(
        ...,
        description="Description of enterprise's capabilities and expertise",
    )
    tender_pdf_path: str | None = Field(
        default=None,
        description="Path to uploaded tender PDF (if already uploaded)",
    )
    tender_text: str | None = Field(
        default=None,
        description="Direct tender text (if PDF not provided)",
    )
    bid_budget: str | None = Field(
        default=None,
        description="Available budget for bid preparation",
    )
    strategic_priority: str = Field(
        default="MEDIUM",
        description="Strategic importance: LOW, MEDIUM, HIGH, CRITICAL",
    )


class TenderTriageResponse(BaseModel):
    """Response from Go/No-Go analysis."""

    model_config = ConfigDict(from_attributes=True)

    success: bool
    decision: GoNoGoDecision | None
    tender_title: str | None = None
    processing_time_ms: int | None = None
    error_message: str | None = None
