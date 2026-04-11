"""
app/llm/orchestrator.py

The LLM Orchestration Layer — The Enforcer of the Golden Rules.

Responsibilities:
  1. Compose prompts from prompts.py templates.
  2. Call client.call_llm() to get raw text.
  3. Parse the raw text into the correct Pydantic schema (llm_schemas.py).
  4. Catch ALL validation errors here — NEVER let them bubble to routers.
  5. Return a typed Pydantic model to the calling service.

The service layer then reads the Pydantic model and makes all decisions
(DB writes, status updates, flags). The orchestrator only returns data.

Exception Handling Strategy:
  - ValidationError: LLM returned JSON that doesn't match schema (hallucination)
  - json.JSONDecodeError: LLM returned non-JSON (rare with response_format)
  - litellm errors: Network/timeout issues
  - All exceptions are caught, logged, and re-raised as ValueError with context
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import ValidationError

from app.llm import client
from app.llm import prompts
from app.schemas.llm_schemas import (
    ComplianceChecklist,
    TechnicalScore,
    FinancialData,
    create_empty_compliance_result,
    create_empty_technical_score,
)


# =============================================================================
# Phase 2: Compliance Evaluation
# =============================================================================


async def evaluate_compliance(pdf_text: str) -> ComplianceChecklist:
    """
    Phase 2: Extract compliance checklist from offer PDF text.

    Args:
        pdf_text: The extracted text content of the PDF

    Returns:
        Validated ComplianceChecklist Pydantic model

    Raises:
        ValueError: If LLM call fails or returns invalid JSON
        ValidationError: If LLM output doesn't match schema (caught and re-raised)
    """
    system_prompt = """\
You are a document compliance analyst for a public-sector procurement system.
Your ONLY job is to read the provided text and determine which required documents
and certifications are present or absent.

You MUST analyze the document carefully and return a JSON object with the following structure:

{
  "has_tax_document": boolean,
  "has_company_registration": boolean,
  "has_bid_bond": boolean,
  "has_audited_financials": boolean,
  "has_signature": boolean,
  "has_methodology": boolean,
  "documents_found": ["list of document titles found"],
  "missing_documents": ["list of required documents not found"],
  "compliance_notes": "optional string explaining findings",
  "extraction_confidence": "HIGH | MEDIUM | LOW"
}

Be STRICT and CONSERVATIVE. Only mark a document as present if you have clear
evidence in the text. If unsure, mark as false.

Respond ONLY with valid JSON. No markdown, no explanations outside the JSON.
"""

    user_prompt = f"""\
---BEGIN DOCUMENT TEXT---
{pdf_text[:15000]}  # Limit text to avoid token limits
---END DOCUMENT TEXT---

Analyze the document above and return the compliance checklist as JSON.
"""

    logger.debug(
        "Calling LLM for compliance evaluation (text length: {chars} chars)",
        chars=len(pdf_text),
    )

    try:
        raw_response = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,  # Deterministic for extraction
        )

    except Exception as exc:
        logger.error(
            "LLM compliance call failed: {error}",
            error=str(exc),
        )
        raise ValueError(f"LLM compliance call failed: {exc}") from exc

    # Parse JSON response
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        logger.error(
            "LLM returned invalid JSON for compliance: {raw}",
            raw=raw_response[:500],
        )
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Validate against Pydantic schema (catches hallucinations)
    try:
        checklist = ComplianceChecklist(**data)
        logger.debug(
            "Compliance extraction successful: {found} documents found",
            found=len(checklist.documents_found),
        )
        return checklist

    except ValidationError as exc:
        logger.error(
            "Compliance checklist validation failed: {errors}\nRaw data: {data}",
            errors=exc.errors(),
            data=data,
        )
        raise ValidationError(
            f"LLM compliance output failed validation: {exc}",
            model=ComplianceChecklist,
        ) from exc


# =============================================================================
# Phase 3: Technical Scoring
# =============================================================================


async def score_technical_section(pdf_text: str, rubric: str) -> TechnicalScore:
    """
    Phase 3: Score the technical section of an offer against a rubric.

    Args:
        pdf_text: The extracted text content of the PDF
        rubric: The evaluation rubric (JSON or structured text describing criteria)

    Returns:
        Validated TechnicalScore Pydantic model

    Raises:
        ValueError: If LLM call fails or returns invalid JSON
        ValidationError: If LLM output doesn't match schema
    """
    system_prompt = """\
You are a technical evaluation expert for a public-sector tender committee.
You will be given a scoring rubric and an offer document.

Your task is to evaluate the technical proposal against the rubric criteria.

For EACH criterion in the rubric, you must:
1. Read the proposal section covering that criterion
2. Assign a score from 0 to the criterion's maximum
3. Provide a detailed justification explaining why that score was awarded

You MUST return a JSON object with this structure:

{
  "criteria_scores": [
    {
      "criterion": "exact criterion name from rubric",
      "max_score": integer,
      "raw_score": integer (0 to max_score),
      "justification": "detailed explanation of the score"
    }
  ],
  "total_raw_score": integer (sum of all raw_scores, 0-100),
  "overall_summary": "comprehensive assessment of technical quality",
  "key_strengths": ["strength 1", "strength 2", ...],
  "key_weaknesses": ["weakness 1", "weakness 2", ...],
  "scoring_confidence": "HIGH | MEDIUM | LOW",
  "scoring_notes": "optional notes on scoring rationale"
}

IMPORTANT RULES:
- raw_score MUST be between 0 and max_score inclusive
- Justifications must be specific and cite evidence from the document
- Be objective and consistent across criteria
- If information is missing, score 0 and explain why

Respond ONLY with valid JSON. No markdown, no explanations outside the JSON.
"""

    user_prompt = f"""\
---EVALUATION RUBRIC---
{rubric}
---END RUBRIC---

---PROPOSAL DOCUMENT---
{pdf_text[:20000]}  # Allow more text for technical evaluation
---END DOCUMENT---

Score this proposal against the rubric above. Return the JSON result.
"""

    logger.debug(
        "Calling LLM for technical scoring (text: {chars} chars, rubric: {rubric_len} chars)",
        chars=len(pdf_text),
        rubric_len=len(rubric),
    )

    try:
        raw_response = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.1,  # Slightly higher for nuanced scoring
        )

    except Exception as exc:
        logger.error(
            "LLM technical scoring call failed: {error}",
            error=str(exc),
        )
        raise ValueError(f"LLM technical scoring call failed: {exc}") from exc

    # Parse JSON
    try:
        data = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        logger.error(
            "LLM returned invalid JSON for technical scoring: {raw}",
            raw=raw_response[:500],
        )
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

    # Validate against schema
    try:
        score_result = TechnicalScore(**data)
        logger.debug(
            "Technical scoring successful: {score}/100",
            score=score_result.calculate_total(),
        )
        return score_result

    except ValidationError as exc:
        logger.error(
            "Technical score validation failed: {errors}\nRaw data: {data}",
            errors=exc.errors(),
            data=data,
        )
        raise ValidationError(
            f"LLM technical scoring output failed validation: {exc}",
            model=TechnicalScore,
        ) from exc


# =============================================================================
# Phase 4: Financial Extraction
# =============================================================================


async def extract_financial_data(pdf_text: str) -> FinancialData:
    """
    Phase 4: Extract financial data from offer PDF.

    Args:
        pdf_text: The extracted text content of the PDF

    Returns:
        Validated FinancialData Pydantic model
    """
    system_prompt = """\
You are a financial data extraction specialist for procurement evaluation.
Your ONLY job is to extract numeric bid values from the provided document.

DO NOT perform calculations or comparisons. Extract only.

You MUST return a JSON object with this structure:

{
  "total_bid_price": number (the total bid amount),
  "currency": "USD" or "EUR" or "GBP" or "NGN" or "OTHER",
  "price_breakdown": {
    "labour": number or null,
    "materials": number or null,
    "overhead": number or null,
    "profit_margin_pct": number or null,
    "other": number or null
  },
  "bid_validity_days": integer or null,
  "payment_terms": "string describing payment terms" or null,
  "extraction_confidence": "HIGH | MEDIUM | LOW",
  "extraction_notes": "optional notes on extraction challenges"
}

Extract the exact values as stated in the document. Use null for missing data.
"""

    user_prompt = f"""\
---FINANCIAL DOCUMENT---
{pdf_text[:10000]}
---END DOCUMENT---

Extract the financial data and return as JSON.
"""

    logger.debug(
        "Calling LLM for financial extraction ({chars} chars)",
        chars=len(pdf_text),
    )

    try:
        raw_response = await client.call_llm(
            system_prompt=system_prompt,
            user_message=user_prompt,
            response_format={"type": "json_object"},
            temperature=0.0,
        )

    except Exception as exc:
        logger.error(
            "LLM financial extraction call failed: {error}",
            error=str(exc),
        )
        raise ValueError(f"LLM financial extraction call failed: {exc}") from exc

    try:
        data = json.loads(raw_response)
        financial_data = FinancialData(**data)
        logger.debug(
            "Financial extraction successful: {price} {currency}",
            price=financial_data.total_bid_price,
            currency=financial_data.currency,
        )
        return financial_data

    except json.JSONDecodeError as exc:
        logger.error(
            "Invalid JSON from LLM: {raw}",
            raw=raw_response[:500],
        )
        raise ValueError(f"Invalid JSON: {exc}") from exc

    except ValidationError as exc:
        logger.error(
            "Financial data validation failed: {errors}",
            errors=exc.errors(),
        )
        raise ValidationError(
            f"Financial data validation failed: {exc}",
            model=FinancialData,
        ) from exc


# =============================================================================
# Legacy/Stub Functions (for backward compatibility)
# =============================================================================


async def extract_compliance_checklist(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """
    Legacy wrapper for compliance extraction.
    Returns raw dict for backward compatibility.
    """
    try:
        result = await evaluate_compliance(document_text)
        return result.model_dump()
    except Exception as exc:
        logger.error("Compliance extraction failed: {error}", error=str(exc))
        raise


async def extract_technical_scores(
    tender_ref: str,
    enterprise_name: str,
    rubric_json: str,
    document_text: str,
) -> dict:
    """
    Legacy wrapper for technical scoring.
    Returns raw dict for backward compatibility.
    """
    try:
        result = await score_technical_section(document_text, rubric_json)
        return result.model_dump()
    except Exception as exc:
        logger.error("Technical scoring failed: {error}", error=str(exc))
        raise


async def extract_financial_data_legacy(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """
    Legacy wrapper for financial extraction.
    Returns raw dict for backward compatibility.
    """
    try:
        result = await extract_financial_data(document_text)
        return result.model_dump()
    except Exception as exc:
        logger.error("Financial extraction failed: {error}", error=str(exc))
        raise
