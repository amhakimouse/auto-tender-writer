"""
app/api/v1/enterprise.py

Enterprise (Bidder/Tender Writer) API Router

This router provides tooling for enterprises to:
    1. Perform Go/No-Go analysis on tender opportunities
    2. Format CVs/resumes for specific tenders
    3. Extract requirements from tender documents
    4. Manage employee profiles

Separation of Concerns:
    - These endpoints serve the ENTERPRISE (bidder) side
    - They do NOT overlap with procurement evaluation endpoints
    - Authentication will be enterprise-focused (Milestone 4)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.db.models import Tender
from app.schemas.enterprise_schemas import (
    EmployeeProfile,
    FormattedCVResponse,
    GoNoGoDecision,
    TenderTriageRequest,
    TenderTriageResponse,
)
from app.services.cv_formatter import format_cv_for_tender
from app.utils.audit_logger import ActionType, log_event
from app.utils.file_parser import extract_text_from_pdf

router = APIRouter()


# =============================================================================
# Pydantic Schemas for API
# =============================================================================


class TriageUploadRequest(BaseModel):
    """Request body for tender triage with uploaded PDF."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enterprise_capabilities": "We specialize in cloud migration, AWS/Azure...",
                "bid_budget": "$50,000",
                "strategic_priority": "HIGH",
            }
        }
    )

    enterprise_capabilities: str = Field(
        ...,
        min_length=50,
        description="Description of enterprise capabilities and expertise",
    )
    bid_budget: str | None = Field(
        default=None,
        description="Available budget for bid preparation",
    )
    strategic_priority: str = Field(
        default="MEDIUM",
        description="Strategic importance: LOW, MEDIUM, HIGH, CRITICAL",
    )


class CVFormatRequest(BaseModel):
    """Request to format a CV for a tender."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "employee_id": 1,
                "tender_id": 2,
                "max_pages": 2,
                "focus_areas": ["cloud migration", "security"],
            }
        }
    )

    employee_id: int = Field(..., gt=0, description="Employee profile ID")
    tender_id: int = Field(..., gt=0, description="Tender ID to tailor CV for")
    max_pages: int = Field(default=2, ge=1, le=10, description="Maximum page count")
    focus_areas: list[str] = Field(
        default_factory=list,
        description="Specific areas to emphasize",
    )
    excluded_experience: list[str] = Field(
        default_factory=list,
        description="Experience categories to exclude",
    )


# =============================================================================
# Helper Functions
# =============================================================================


async def perform_triage_analysis(
    tender_text: str,
    enterprise_capabilities: str,
    bid_budget: str | None,
    strategic_priority: str,
) -> GoNoGoDecision:
    """
    Perform Go/No-Go analysis using LLM.

    Args:
        tender_text: Extracted text from tender document
        enterprise_capabilities: Enterprise capability description
        bid_budget: Available budget
        strategic_priority: Priority level

    Returns:
        GoNoGoDecision with analysis results
    """
    from app.llm.client import call_llm
    from app.llm.prompts.enterprise import (
        ENTERPRISE_TRIAGE_SYSTEM,
        ENTERPRISE_TRIAGE_USER,
    )
    import json
    from pydantic import ValidationError

    # Format user prompt
    user_prompt = ENTERPRISE_TRIAGE_USER.format(
        enterprise_capabilities=enterprise_capabilities,
        tender_text=tender_text[:20000],  # Limit to avoid token limits
        strategic_priority=strategic_priority,
        bid_budget=bid_budget or "Not specified",
    )

    # Call LLM
    raw_response = await call_llm(
        system_prompt=ENTERPRISE_TRIAGE_SYSTEM,
        user_message=user_prompt,
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=3000,
    )

    # Parse and validate
    try:
        data = json.loads(raw_response)
        decision = GoNoGoDecision(**data)
        return decision
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"Failed to parse LLM response: {exc}") from exc


# =============================================================================
# API Endpoints
# =============================================================================


@router.post(
    "/triage",
    response_model=TenderTriageResponse,
    status_code=status.HTTP_200_OK,
    summary="Perform Go/No-Go analysis on a tender opportunity",
    responses={
        200: {"description": "Triage analysis completed"},
        400: {"description": "Invalid input or PDF extraction failed"},
        413: {"description": "File too large"},
    },
)
async def triage_tender_opportunity(
    enterprise_capabilities: str = Form(
        ...,
        min_length=50,
        description="Description of enterprise capabilities (50+ chars)",
    ),
    bid_budget: str | None = Form(
        default=None,
        description="Available budget for bid preparation",
    ),
    strategic_priority: str = Form(
        default="MEDIUM",
        description="Strategic priority: LOW, MEDIUM, HIGH, CRITICAL",
    ),
    tender_file: UploadFile = File(
        ...,
        description="Tender PDF document to analyze",
    ),
    db: AsyncSession = Depends(get_db),
) -> TenderTriageResponse:
    """
    Perform Go/No-Go analysis on a tender opportunity.

    ## Process:

    1. **Upload**: Submit the tender PDF and your enterprise capabilities
    2. **Extract**: System extracts text from the tender PDF
    3. **Analyze**: LLM compares tender requirements against your capabilities
    4. **Decide**: Returns Go/No-Go with detailed scoring and risk analysis

    ## The Analysis Includes:

    - **Eligibility Score** (0-100): How well you match the requirements
    - **Go/No-Go Decision**: Boolean recommendation
    - **Key Risks**: Specific risks that could prevent winning
    - **Capability Matches**: Detailed assessment of each requirement
    - **Win Probability**: Estimated chance of success

    ## Example Response:

    ```json
    {
      "is_eligible": true,
      "eligibility_score": 85,
      "key_risks": ["Limited past experience in healthcare sector"],
      "recommendation": "Strong Go recommendation...",
      "capability_matches": [...]
    }
    ```
    """
    start_time = time.time()

    # Validate file type
    if tender_file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files accepted. Got: {tender_file.content_type}",
        )

    # Read and validate file
    file_content = await tender_file.read()
    MAX_SIZE = 50 * 1024 * 1024  # 50MB
    if len(file_content) > MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large. Maximum size is 50MB",
        )

    if len(file_content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # Extract text from PDF
    try:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_content)
            tmp_path = Path(tmp.name)

        tender_text = extract_text_from_pdf(tmp_path)
        tmp_path.unlink(missing_ok=True)

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to extract text from PDF: {str(exc)}",
        )

    if len(tender_text.strip()) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF contains insufficient text for analysis",
        )

    # Perform analysis
    try:
        decision = await perform_triage_analysis(
            tender_text=tender_text,
            enterprise_capabilities=enterprise_capabilities,
            bid_budget=bid_budget,
            strategic_priority=strategic_priority,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"LLM analysis failed — could not parse response: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Triage analysis error: {exc}",
        ) from exc

    processing_time_ms = int((time.time() - start_time) * 1000)
    # Extract tender title from first non-empty line (max 100 chars)
    tender_title = next(
        (line.strip() for line in tender_text.splitlines() if line.strip()), "Untitled"
    )[:100]

    return TenderTriageResponse(
        success=True,
        decision=decision,
        tender_title=tender_title,
        processing_time_ms=processing_time_ms,
        error_message=None,
    )


@router.post(
    "/triage-by-id/{tender_id}",
    response_model=TenderTriageResponse,
    summary="Triage a tender already in the system",
)
async def triage_existing_tender(
    tender_id: int,
    request: TriageUploadRequest,
    db: AsyncSession = Depends(get_db),
) -> TenderTriageResponse:
    """
    Perform Go/No-Go analysis on a tender already in the system.

    This is useful when a tender has been published and you want to
    assess it without re-uploading the PDF.
    """
    start_time = time.time()

    # Get tender from database
    result = await db.execute(select(Tender).where(Tender.id == tender_id))
    tender = result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {tender_id} not found",
        )

    # For existing tenders, we might not have the PDF stored
    # In a real implementation, you'd fetch the tender document
    # For now, use the description
    tender_text = f"""
Title: {tender.title}
Reference: {tender.reference_number or "N/A"}
Description: {tender.description or "No description available"}
Status: {tender.status}
Deadline: {tender.deadline.isoformat()}
"""

    try:
        decision = await perform_triage_analysis(
            tender_text=tender_text,
            enterprise_capabilities=request.enterprise_capabilities,
            bid_budget=request.bid_budget,
            strategic_priority=request.strategic_priority,
        )

        processing_time_ms = int((time.time() - start_time) * 1000)

        return TenderTriageResponse(
            success=True,
            decision=decision,
            tender_title=tender.title,
            processing_time_ms=processing_time_ms,
            error_message=None,
        )

    except Exception as exc:
        processing_time_ms = int((time.time() - start_time) * 1000)
        return TenderTriageResponse(
            success=False,
            decision=None,
            tender_title=tender.title,
            processing_time_ms=processing_time_ms,
            error_message=str(exc),
        )


@router.post(
    "/format-cv",
    response_model=FormattedCVResponse,
    status_code=status.HTTP_200_OK,
    summary="Format an employee's CV for a specific tender",
    responses={
        200: {"description": "CV formatted successfully"},
        404: {"description": "Employee or tender not found"},
        400: {"description": "Invalid input"},
    },
)
async def format_cv(
    request: CVFormatRequest,
    db: AsyncSession = Depends(get_db),
) -> FormattedCVResponse:
    """
    Format an employee's CV to highlight experience relevant to a tender.

    ## Process:

    1. **Fetch**: System retrieves the employee's master profile and tender details
    2. **Analyze**: LLM identifies which experience is most relevant to tender requirements
    3. **Tailor**: CV is rewritten to emphasize relevant skills and projects
    4. **Cut**: Irrelevant or outdated experience is removed to meet page limits
    5. **Output**: Returns the tailored CV with metadata

    ## The Result:

    - **Executive Summary**: Rewritten to match tender language
    - **Relevant Skills**: Subset of skills that match requirements
    - **Experience**: Rewritten bullet points emphasizing relevant achievements
    - **Page Count**: Estimated page count (enforced to be ≤ max_pages)

    ## Example Use Cases:

    - Tailoring senior consultant CV for cloud migration tender
    - Emphasizing security experience for cybersecurity RFP
    - Cutting 10-page master resume to 2-page focused CV
    """
    # Fetch tender
    tender_result = await db.execute(
        select(Tender).where(Tender.id == request.tender_id)
    )
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tender with ID {request.tender_id} not found",
        )

    # TODO: In real implementation, fetch employee from database
    # For now, we'll use a placeholder employee profile
    # This would be replaced with actual employee DB lookup
    employee = EmployeeProfile(
        id=request.employee_id,
        full_name=f"Employee {request.employee_id}",  # Placeholder
        current_role="Senior Consultant",
        years_total_experience=10.0,
        executive_summary="Experienced consultant with diverse skills.",
        skills=[
            {
                "skill_name": "Cloud Migration",
                "years_experience": 5,
                "proficiency_level": "EXPERT",
            },
            {
                "skill_name": "AWS",
                "years_experience": 4,
                "proficiency_level": "ADVANCED",
            },
            {
                "skill_name": "Project Management",
                "years_experience": 8,
                "proficiency_level": "EXPERT",
            },
        ],
        work_experience=[
            {
                "company": "TechCorp",
                "role_title": "Senior Cloud Architect",
                "start_date": datetime(2019, 1, 1).date(),
                "description": "Led enterprise cloud migrations for Fortune 500 clients.",
                "key_projects": ["BankCloud Migration", "RetailCorp AWS Setup"],
                "skills_used": ["AWS", "Azure", "Kubernetes"],
            }
        ],
        education=[
            {
                "institution": "State University",
                "degree": "Bachelor of Science",
                "field_of_study": "Computer Science",
                "graduation_year": 2014,
            }
        ],
    )

    try:
        # Call CV formatter service
        tailored_cv = await format_cv_for_tender(
            employee=employee,
            tender=tender,
            max_pages=request.max_pages,
            focus_areas=request.focus_areas,
            excluded_experience=request.excluded_experience,
        )
    except ValueError as exc:
        # LLM returned invalid output — surface as 422 so the caller knows
        # to retry or adjust the request, not treat it as a server bug.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"CV formatting failed — LLM returned invalid data: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CV formatting error: {exc}",
        ) from exc

    return FormattedCVResponse(
        success=True,
        employee_id=request.employee_id,
        tender_id=request.tender_id,
        formatted_cv=tailored_cv,
        output_path=None,
        error_message=None,
    )


@router.get(
    "/",
    summary="List enterprise endpoints",
)
async def list_enterprise_endpoints():
    """List available enterprise tooling endpoints."""
    return {
        "enterprise_endpoints": [
            {
                "path": "/enterprise/triage",
                "method": "POST",
                "description": "Upload tender PDF and perform Go/No-Go analysis",
            },
            {
                "path": "/enterprise/triage-by-id/{tender_id}",
                "method": "POST",
                "description": "Triage a tender already in the system",
            },
            {
                "path": "/enterprise/format-cv",
                "method": "POST",
                "description": "Format employee CV for a specific tender",
            },
        ]
    }
