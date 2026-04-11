"""
app/llm/orchestrator.py

The LLM Orchestration Layer — The Enforcer of the Golden Rules.

Responsibilities:
  1. Compose prompts (inline for procurement phases; enterprise prompts from
     app/llm/prompts/enterprise.py for the bidder-side tooling).
  2. Call client.call_llm() to get raw text.
  3. Strip markdown fences (handled by client) then parse JSON.
  4. Validate output against the correct Pydantic schema.
  5. Re-raise all errors as ValueError with clear context — NEVER let
     bare ValidationError or JSONDecodeError propagate to routers.

Calling convention:
  - All functions are async and return a typed Pydantic model.
  - The service layer reads the model and makes ALL decisions (DB writes,
    status flags, disqualification). The orchestrator only extracts data.
  - Temperature 0.0 for all extraction tasks (deterministic JSON).
    Raise only for narrative drafts (letters, acknowledgements).
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import ValidationError

from app.llm import client
from app.llm.prompts import enterprise as enterprise_prompts
from app.schemas.llm_schemas import (
    ComplianceChecklist,
    FinancialData,
    TechnicalScore,
    create_empty_compliance_result,
    create_empty_technical_score,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_and_validate(raw: str, model_cls, context: str) -> Any:
    """
    Parse raw LLM text as JSON, then validate against a Pydantic model.

    Args:
        raw:       Raw string returned by call_llm (fences already stripped).
        model_cls: The Pydantic BaseModel subclass to validate against.
        context:   Human-readable description for error messages.

    Returns:
        A validated instance of model_cls.

    Raises:
        ValueError: On JSONDecodeError or ValidationError — always with context.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(
            "[Orchestrator] {ctx} — invalid JSON from LLM: {preview}",
            ctx=context,
            preview=raw[:400],
        )
        raise ValueError(
            f"{context}: LLM returned invalid JSON — {exc}. "
            f"Raw preview: {raw[:200]}"
        ) from exc

    try:
        return model_cls(**data)
    except ValidationError as exc:
        logger.error(
            "[Orchestrator] {ctx} — Pydantic validation failed: {errors}",
            ctx=context,
            errors=exc.errors(),
        )
        # Pydantic v2: re-raise as ValueError so callers get a simple except clause
        raise ValueError(
            f"{context}: LLM output failed schema validation — {exc.errors()}"
        ) from exc


# =============================================================================
# Phase 2: Compliance Evaluation
# =============================================================================


async def evaluate_compliance(pdf_text: str) -> ComplianceChecklist:
    """
    Phase 2: Extract compliance checklist from offer PDF text.

    The LLM reads the document and reports which required documents are present.
    Python (The Enforcer) in evaluation_service.py then decides disqualification.

    Args:
        pdf_text: Extracted text from the offer PDF.

    Returns:
        Validated ComplianceChecklist.

    Raises:
        ValueError: If the LLM call fails or its output fails validation.
    """
    system_prompt = """\
You are a document compliance analyst for a public-sector procurement system.
Your ONLY job is to read the provided text and determine which required documents
and certifications are present or absent.

You MUST return a JSON object with EXACTLY this structure — no extra fields:

{
  "has_tax_document": boolean,
  "has_company_registration": boolean,
  "has_bid_bond": boolean,
  "has_audited_financials": boolean,
  "has_signature": boolean,
  "has_methodology": boolean,
  "documents_found": ["list of document titles found"],
  "missing_documents": ["list of required documents not found"],
  "compliance_notes": "optional string explaining findings or null",
  "extraction_confidence": "HIGH" | "MEDIUM" | "LOW"
}

RULES:
- Be STRICT and CONSERVATIVE. Only mark a document as present if you have
  clear, explicit evidence in the text. If unsure → false.
- "has_audited_financials" = true only if financial statements dated within 3 years found.
- Respond ONLY with valid JSON. No markdown, no explanations outside the JSON.
"""

    user_prompt = (
        f"---BEGIN DOCUMENT TEXT---\n"
        f"{pdf_text[:15000]}\n"
        f"---END DOCUMENT TEXT---\n\n"
        "Analyze the document and return the compliance checklist as JSON."
    )

    logger.debug(
        "Compliance evaluation → {chars} chars of PDF text",
        chars=len(pdf_text),
    )

    try:
        raw = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
    except Exception as exc:
        raise ValueError(f"Compliance LLM call failed: {exc}") from exc

    return _parse_and_validate(raw, ComplianceChecklist, "Phase 2 Compliance")


# =============================================================================
# Phase 3: Technical Scoring
# =============================================================================


async def score_technical_section(pdf_text: str, rubric: str) -> TechnicalScore:
    """
    Phase 3: Score the technical proposal against a rubric.

    The LLM evaluates each rubric criterion and returns a score with
    justification. Python validates bounds and normalises the final score.

    Args:
        pdf_text: Extracted text from the offer PDF.
        rubric:   Evaluation rubric (JSON or plain-text criteria list).

    Returns:
        Validated TechnicalScore.

    Raises:
        ValueError: If the LLM call fails or its output fails validation.
    """
    system_prompt = """\
You are a technical evaluation expert for a public-sector tender committee.
Evaluate the given proposal against each criterion in the rubric.

For EACH criterion you must:
1. Read the relevant section of the proposal.
2. Assign a score from 0 to the criterion's maximum.
3. Write a specific justification citing evidence from the document.

Return EXACTLY this JSON structure — no extra fields:

{
  "criteria_scores": [
    {
      "criterion": "exact criterion name from rubric",
      "max_score": integer,
      "raw_score": integer (0 to max_score inclusive),
      "justification": "detailed explanation citing evidence (min 10 chars)"
    }
  ],
  "total_raw_score": integer (sum of raw_scores, 0-100),
  "overall_summary": "comprehensive assessment of technical quality (min 20 chars)",
  "key_strengths": ["strength 1", "strength 2"],
  "key_weaknesses": ["weakness 1", "weakness 2"],
  "scoring_confidence": "HIGH" | "MEDIUM" | "LOW",
  "scoring_notes": "optional notes or null"
}

RULES:
- raw_score MUST be >= 0 and <= max_score.
- Cite specific evidence from the document for every score.
- If a section is missing entirely, score 0 and explain.
- Respond ONLY with valid JSON.
"""

    user_prompt = (
        f"---EVALUATION RUBRIC---\n"
        f"{rubric}\n"
        f"---END RUBRIC---\n\n"
        f"---PROPOSAL DOCUMENT---\n"
        f"{pdf_text[:20000]}\n"
        f"---END DOCUMENT---\n\n"
        "Score this proposal against the rubric and return JSON."
    )

    logger.debug(
        "Technical scoring → {chars} chars PDF, {rlen} chars rubric",
        chars=len(pdf_text),
        rlen=len(rubric),
    )

    try:
        raw = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.1,
        )
    except Exception as exc:
        raise ValueError(f"Technical scoring LLM call failed: {exc}") from exc

    return _parse_and_validate(raw, TechnicalScore, "Phase 3 Technical Scoring")


# =============================================================================
# Phase 4: Financial Data Extraction
# =============================================================================


async def extract_financial_data(pdf_text: str) -> FinancialData:
    """
    Phase 4: Extract bid price and financial details from an offer PDF.

    The LLM ONLY extracts values — it never calculates scores.
    Python applies the lowest-price formula in evaluation_service.py.

    Args:
        pdf_text: Extracted text from the offer PDF.

    Returns:
        Validated FinancialData.

    Raises:
        ValueError: If the LLM call fails or its output fails validation.
    """
    system_prompt = """\
You are a financial data extraction specialist for procurement evaluation.
Your ONLY job is to extract numeric bid values from the provided document.

DO NOT calculate, compare, or score anything. Extract only.

Return EXACTLY this JSON structure — no extra fields:

{
  "total_bid_price": number (the total bid amount as a float),
  "currency": "USD" | "EUR" | "GBP" | "NGN" | "JPY" | "CAD" | "AUD" | "CHF" | "CNY" | "OTHER",
  "price_breakdown": {
    "labour": number or null,
    "materials": number or null,
    "overhead": number or null,
    "profit_margin_pct": number or null,
    "other": number or null
  },
  "bid_validity_days": integer or null,
  "payment_terms": "string describing payment terms" or null,
  "extraction_confidence": "HIGH" | "MEDIUM" | "LOW",
  "extraction_notes": "notes on extraction challenges or null"
}

RULES:
- Extract the TOTAL bid price exactly as stated — no rounding.
- Use null for any field not mentioned in the document.
- Respond ONLY with valid JSON.
"""

    user_prompt = (
        f"---FINANCIAL DOCUMENT---\n"
        f"{pdf_text[:12000]}\n"
        f"---END DOCUMENT---\n\n"
        "Extract the financial data and return as JSON."
    )

    logger.debug(
        "Financial extraction → {chars} chars of PDF text",
        chars=len(pdf_text),
    )

    try:
        raw = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
    except Exception as exc:
        raise ValueError(f"Financial extraction LLM call failed: {exc}") from exc

    return _parse_and_validate(raw, FinancialData, "Phase 4 Financial Extraction")


# =============================================================================
# Enterprise (Bidder-Side) — Tender Triage
# =============================================================================


async def run_enterprise_triage(
    tender_text: str,
    enterprise_capabilities: str,
    bid_budget: str = "Not specified",
    strategic_priority: str = "Standard",
) -> dict:
    """
    Enterprise Phase: Go/No-Go triage analysis.

    Uses the versioned prompts from app/llm/prompts/enterprise.py.
    Returns a raw dict (validated by the enterprise router against GoNoGoDecision).

    Args:
        tender_text:              Full text of the tender document.
        enterprise_capabilities:  The enterprise's profile / capability statement.
        bid_budget:               Available budget to pursue this bid.
        strategic_priority:       "High" | "Standard" | "Low" priority rating.

    Returns:
        dict matching the GoNoGoDecision schema (validated by caller).

    Raises:
        ValueError: LLM call failure or JSON/validation error.
    """
    user_prompt = enterprise_prompts.ENTERPRISE_TRIAGE_USER.format(
        enterprise_capabilities=enterprise_capabilities,
        tender_text=tender_text[:18000],
        strategic_priority=strategic_priority,
        bid_budget=bid_budget,
    )

    logger.debug(
        "Enterprise triage → {chars} tender chars, {cap_chars} capability chars",
        chars=len(tender_text),
        cap_chars=len(enterprise_capabilities),
    )

    try:
        raw = await client.call_llm(
            system_prompt=enterprise_prompts.ENTERPRISE_TRIAGE_SYSTEM,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
    except Exception as exc:
        raise ValueError(f"Enterprise triage LLM call failed: {exc}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Enterprise triage: LLM returned invalid JSON — {exc}"
        ) from exc


# =============================================================================
# Enterprise (Bidder-Side) — CV Tailoring
# =============================================================================


async def format_cv_for_tender_llm(
    employee_profile: dict,
    tender_requirements: str,
    max_pages: int = 2,
    focus_areas: list[str] | None = None,
    excluded_experience: list[str] | None = None,
) -> dict:
    """
    Enterprise Phase: Tailor an employee CV for a specific tender.

    Uses the versioned prompts from app/llm/prompts/enterprise.py.
    Returns a raw dict (validated by cv_formatter.py against TailoredCVOutput).

    Args:
        employee_profile:    Dict with employee details (name, role, skills, etc.).
        tender_requirements: Concatenated tender requirements text.
        max_pages:           Hard page limit for the output CV.
        focus_areas:         List of skills/areas to emphasise.
        excluded_experience: Experience items to exclude entirely.

    Returns:
        dict matching TailoredCVOutput schema (validated by caller).

    Raises:
        ValueError: LLM call failure or JSON error.
    """
    import json as _json

    # Format skills and experience for the prompt
    skills_list = "\n".join(
        f"- {s}" for s in employee_profile.get("skills", [])
    ) or "Not specified"

    experience_items = employee_profile.get("work_experience", [])
    work_exp_text = "\n\n".join(
        f"Company: {e.get('company', 'N/A')}\n"
        f"Role: {e.get('role_title', 'N/A')}\n"
        f"Period: {e.get('start_date', '')} – {e.get('end_date', 'Present')}\n"
        f"Description: {e.get('description', '')}\n"
        f"Key Achievements: {', '.join(e.get('key_achievements', []))}"
        for e in experience_items
    ) or "Not specified"

    education = "\n".join(
        f"- {e.get('degree', '')} from {e.get('institution', '')} ({e.get('year', '')})"
        for e in employee_profile.get("education", [])
    ) or "Not specified"

    user_prompt = enterprise_prompts.ENTERPRISE_CV_FORMATTER_USER.format(
        employee_name=employee_profile.get("full_name", "Unknown"),
        current_role=employee_profile.get("current_role", "N/A"),
        years_experience=employee_profile.get("years_of_experience", 0),
        executive_summary=employee_profile.get("executive_summary", ""),
        skills_list=skills_list,
        work_experience=work_exp_text,
        education=education,
        tender_requirements=tender_requirements[:8000],
        max_pages=max_pages,
        focus_areas=", ".join(focus_areas) if focus_areas else "None specified",
        excluded_experience=", ".join(excluded_experience) if excluded_experience else "None",
    )

    logger.debug(
        "CV formatting → employee={name}, max_pages={mp}",
        name=employee_profile.get("full_name", "?"),
        mp=max_pages,
    )

    try:
        raw = await client.call_llm(
            system_prompt=enterprise_prompts.ENTERPRISE_CV_FORMATTER_SYSTEM,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.2,  # Slight creativity for rewriting bullet points
        )
    except Exception as exc:
        raise ValueError(f"CV formatting LLM call failed: {exc}") from exc

    try:
        return _json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"CV formatter: LLM returned invalid JSON — {exc}"
        ) from exc


# =============================================================================
# Enterprise — Requirements Extraction
# =============================================================================


async def extract_tender_requirements(tender_text: str) -> dict:
    """
    Enterprise: Extract structured requirements from a tender document.

    Used as a pre-processing step before CV tailoring or triage to give
    the enterprise a machine-readable breakdown of what the buyer wants.

    Returns:
        dict with 'requirements' list and tender metadata.

    Raises:
        ValueError: LLM call failure or JSON error.
    """
    user_prompt = enterprise_prompts.ENTERPRISE_REQUIREMENTS_EXTRACTION_USER.format(
        tender_text=tender_text[:18000],
    )

    try:
        raw = await client.call_llm(
            system_prompt=enterprise_prompts.ENTERPRISE_REQUIREMENTS_EXTRACTION_SYSTEM,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,
        )
    except Exception as exc:
        raise ValueError(f"Requirements extraction LLM call failed: {exc}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Requirements extraction: LLM returned invalid JSON — {exc}"
        ) from exc


# =============================================================================
# Narrative Drafting (Phase 7 Letters + Phase 8 Acknowledgements)
# =============================================================================


async def draft_narrative(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 600,
) -> str:
    """
    General-purpose narrative text generation (NOT JSON extraction).

    Used for:
    - Phase 7 award / rejection letters (committee.py)
    - Phase 8 appeal acknowledgement letters (intake.py)
    - Any other free-text LLM output where Pydantic validation is not needed

    Returns:
        Plain text string (no JSON parsing, no Pydantic validation).

    Raises:
        ValueError: If the LLM call fails.
    """
    try:
        return await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        raise ValueError(f"Narrative drafting LLM call failed: {exc}") from exc


# =============================================================================
# Legacy wrappers (kept for backward compatibility — routers may still use these)
# =============================================================================


async def extract_compliance_checklist(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """Legacy wrapper — routes to evaluate_compliance()."""
    result = await evaluate_compliance(document_text)
    return result.model_dump()


async def extract_technical_scores(
    tender_ref: str,
    enterprise_name: str,
    rubric_json: str,
    document_text: str,
) -> dict:
    """Legacy wrapper — routes to score_technical_section()."""
    result = await score_technical_section(document_text, rubric_json)
    return result.model_dump()


async def extract_financial_data_legacy(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """Legacy wrapper — routes to extract_financial_data()."""
    result = await extract_financial_data(document_text)
    return result.model_dump()
