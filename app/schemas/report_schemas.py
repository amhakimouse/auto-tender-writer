"""
app/schemas/report_schemas.py

Pydantic schemas for Phase 9: Audit Trail and Archive Closure Reports.

These schemas define:
    - Tender statistics aggregation (Python-computed)
    - LLM-generated executive summaries for auditors
    - Closure report structured output

Design Principles:
    - Python computes all deterministic statistics (mathematical aggregation)
    - LLM generates narrative summaries and insights
    - Strict Pydantic validation for LLM outputs
    - All data structured for government auditor consumption
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Phase 9 — Tender Statistics (Python Computed)
# =============================================================================


class TenderStatistics(BaseModel):
    """
    Aggregated statistics for a tender.

    ALL values computed by Python (The Enforcer) — never by the LLM.
    These are deterministic mathematical aggregations.
    """

    model_config = ConfigDict(extra="forbid")

    tender_id: int = Field(..., description="ID of the tender")
    tender_title: str = Field(..., description="Title of the tender")
    tender_reference: str | None = Field(default=None, description="Reference number")

    # --- Offer Counts ---
    total_offers_received: int = Field(
        default=0, ge=0, description="Total bids submitted"
    )
    offers_compliant: int = Field(
        default=0, ge=0, description="Offers passing Phase 2 compliance"
    )
    offers_incompliant: int = Field(
        default=0, ge=0, description="Offers failing Phase 2 compliance"
    )
    offers_technically_scored: int = Field(
        default=0, ge=0, description="Offers receiving Phase 3 technical scores"
    )
    offers_financially_scored: int = Field(
        default=0, ge=0, description="Offers receiving Phase 4 financial scores"
    )
    offers_combined_scored: int = Field(
        default=0, ge=0, description="Offers with Phase 5 combined scores"
    )

    # --- Financial Statistics ---
    average_bid_price: float | None = Field(
        default=None, ge=0, description="Average bid price among compliant offers"
    )
    lowest_bid_price: float | None = Field(
        default=None, ge=0, description="Lowest bid price"
    )
    highest_bid_price: float | None = Field(
        default=None, ge=0, description="Highest bid price"
    )
    price_currency: str | None = Field(default=None, description="Currency code")

    # --- Scoring Statistics ---
    average_technical_score: float | None = Field(
        default=None, ge=0, le=100, description="Average technical score"
    )
    average_financial_score: float | None = Field(
        default=None, ge=0, le=100, description="Average financial score"
    )
    average_combined_score: float | None = Field(
        default=None, ge=0, le=100, description="Average combined score"
    )

    # --- Winner Information ---
    winner_offer_id: int | None = Field(default=None, description="ID of winning offer")
    winner_bidder_name: str | None = Field(
        default=None, description="Winning bidder name"
    )
    winner_technical_score: float | None = Field(
        default=None, ge=0, le=100, description="Winner's technical score"
    )
    winner_financial_score: float | None = Field(
        default=None, ge=0, le=100, description="Winner's financial score"
    )
    winner_combined_score: float | None = Field(
        default=None, ge=0, le=100, description="Winner's combined score"
    )
    winner_bid_price: float | None = Field(
        default=None, ge=0, description="Winner's bid price"
    )

    # --- Committee Actions ---
    total_score_overrides: int = Field(
        default=0, ge=0, description="Number of committee score overrides (Phase 6)"
    )
    close_tie_detected: bool = Field(
        default=False, description="Whether a close tie was flagged"
    )

    # --- Appeals ---
    total_appeals: int = Field(default=0, ge=0, description="Total appeals filed")
    appeals_upheld: int = Field(
        default=0, ge=0, description="Appeals where original decision stood"
    )
    appeals_overturned: int = Field(default=0, ge=0, description="Appeals granted")
    appeals_pending: int = Field(
        default=0, ge=0, description="Appeals awaiting resolution"
    )

    # --- Timing ---
    tender_deadline: datetime = Field(..., description="Original tender deadline")
    tender_closed_at: datetime | None = Field(
        default=None, description="When tender was marked CLOSED"
    )
    days_open_for_bids: int = Field(
        default=0, ge=0, description="Days between publish and deadline"
    )
    report_generated_at: datetime = Field(
        default_factory=lambda: datetime.now(datetime.now().astimezone().tzinfo),
        description="When this report was generated",
    )

    @field_validator("offers_compliant", "offers_incompliant")
    @classmethod
    def validate_compliant_sums(cls, v: int, info) -> int:
        """Ensure compliant + incompliant doesn't exceed total."""
        total = info.data.get("total_offers_received", 0)
        if v > total:
            return total
        return v


# =============================================================================
# Phase 9 — LLM Executive Summary (The Reasoner)
# =============================================================================


class ExecutiveSummary(BaseModel):
    """
    LLM output schema for Phase 9 executive summary.

    The LLM reads the aggregated statistics and generates a
    plain-English narrative suitable for government auditors.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": "Executive summary for government auditors"},
    )

    # --- Header ---
    report_title: str = Field(
        default="Procurement Closure Report",
        max_length=100,
        description="Title of the closure report",
    )
    tender_reference: str = Field(
        ...,
        max_length=100,
        description="Tender reference number",
    )

    # --- Executive Overview ---
    executive_overview: str = Field(
        ...,
        min_length=200,
        max_length=2000,
        description="High-level summary of the entire procurement process",
    )

    # --- Process Summary ---
    process_summary: str = Field(
        ...,
        min_length=200,
        max_length=2000,
        description="Summary of the evaluation process and methodology",
    )

    # --- Participation Summary ---
    participation_summary: str = Field(
        ...,
        min_length=100,
        max_length=1500,
        description="Summary of bidder participation and competition",
    )

    # --- Evaluation Summary ---
    evaluation_summary: str = Field(
        ...,
        min_length=200,
        max_length=2000,
        description="Summary of technical and financial evaluation results",
    )

    # --- Winner Justification ---
    winner_justification: str = Field(
        ...,
        min_length=100,
        max_length=1500,
        description="Explanation of why the winner was selected",
    )

    # --- Compliance and Appeals Summary ---
    compliance_summary: str = Field(
        ...,
        min_length=100,
        max_length=1500,
        description="Summary of compliance checks and any appeals",
    )

    # --- Audit Trail Statement ---
    audit_trail_statement: str = Field(
        ...,
        min_length=100,
        max_length=1000,
        description="Statement on audit trail completeness and integrity",
    )

    # --- Key Findings ---
    key_findings: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key findings from the procurement process",
    )

    # --- Recommendations ---
    recommendations: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Recommendations for future procurements",
    )

    # --- Anomalies or Concerns ---
    anomalies_or_concerns: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Any anomalies or concerns flagged during the process",
    )

    # --- Final Statement ---
    final_statement: str = Field(
        ...,
        min_length=100,
        max_length=1000,
        description="Final closure statement for auditors",
    )

    # --- LLM Confidence ---
    generation_confidence: str = Field(
        default="HIGH",
        description="LLM confidence in the summary: HIGH, MEDIUM, or LOW",
    )
    generation_notes: str | None = Field(
        default=None,
        max_length=1000,
        description="Notes on summary generation",
    )


# =============================================================================
# Phase 9 — Closure Report (Complete Output)
# =============================================================================


class ClosureReport(BaseModel):
    """
    Complete Phase 9 closure report.

    Combines Python-computed statistics with LLM-generated narrative.
    """

    model_config = ConfigDict(from_attributes=True)

    # --- Metadata ---
    tender_id: int
    report_id: str = Field(..., description="Unique report identifier")
    generated_at: datetime
    generated_by: str = Field(default="SYSTEM", description="Report generator")

    # --- Statistics Section (Python) ---
    statistics: TenderStatistics

    # --- Narrative Section (LLM) ---
    executive_summary: ExecutiveSummary

    # --- Audit Trail Summary ---
    total_audit_events: int = Field(
        default=0, ge=0, description="Total audit log events for this tender"
    )
    audit_trail_hash: str | None = Field(
        default=None, description="Hash of audit trail for integrity verification"
    )

    # --- Status ---
    status: str = Field(
        default="DRAFT",
        description="Report status: DRAFT, FINALIZED, ARCHIVED",
    )

    # --- File Outputs ---
    report_pdf_path: str | None = None
    audit_export_path: str | None = None

    class Config:
        json_schema_extra = {
            "example": {
                "tender_id": 1,
                "report_id": "CR-2024-001",
                "generated_at": "2024-01-15T10:30:00Z",
                "statistics": {
                    "tender_id": 1,
                    "tender_title": "IT Infrastructure Upgrade",
                    "total_offers_received": 8,
                    "offers_compliant": 6,
                    "average_bid_price": 125000.0,
                    "winner_combined_score": 92.5,
                },
                "executive_summary": {
                    "report_title": "Procurement Closure Report",
                    "executive_overview": "This report summarizes...",
                },
            }
        }


# =============================================================================
# API Schemas
# =============================================================================


class ClosureReportRequest(BaseModel):
    """Request to generate a closure report."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tender_id": 1,
                "include_full_audit_trail": True,
                "generate_pdf": False,
            }
        }
    )

    tender_id: int = Field(..., gt=0, description="Tender ID to generate report for")
    include_full_audit_trail: bool = Field(
        default=True,
        description="Include full audit trail export",
    )
    generate_pdf: bool = Field(
        default=False,
        description="Generate PDF version of report",
    )
    requested_by: str = Field(
        default="SYSTEM",
        description="User or system requesting the report",
    )


class ClosureReportResponse(BaseModel):
    """Response containing the closure report."""

    success: bool
    report: ClosureReport | None = None
    message: str
    error_code: str | None = None


class AuditTrailExportRequest(BaseModel):
    """Request to export audit trail for a tender."""

    tender_id: int = Field(..., gt=0)
    format: str = Field(default="JSON", description="Export format: JSON, CSV, PDF")
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None


class AuditTrailExportResponse(BaseModel):
    """Response containing audit trail export."""

    success: bool
    tender_id: int
    total_events: int
    export_format: str
    export_path: str | None = None
    download_url: str | None = None
    generated_at: datetime
    error_message: str | None = None


# =============================================================================
# Factory Functions
# =============================================================================


def create_empty_executive_summary(
    tender_reference: str = "UNKNOWN",
) -> ExecutiveSummary:
    """Factory for empty executive summary (error fallback)."""
    return ExecutiveSummary(
        report_title="Procurement Closure Report - Generation Failed",
        tender_reference=tender_reference,
        executive_overview="Executive summary generation failed. Please review the raw statistics below.",
        process_summary="Process summary generation failed.",
        participation_summary="Participation summary generation failed.",
        evaluation_summary="Evaluation summary generation failed.",
        winner_justification="Winner justification generation failed.",
        compliance_summary="Compliance summary generation failed.",
        audit_trail_statement="Audit trail statement generation failed.",
        final_statement="Report generation encountered errors. Manual review required.",
        generation_confidence="LOW",
        generation_notes="An error occurred during LLM summary generation. This is a safe fallback.",
    )
