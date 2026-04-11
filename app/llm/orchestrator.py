"""
app/llm/orchestrator.py

The LLM orchestration layer — the enforcer of the Golden Rules.

Responsibilities:
  1. Compose prompts from prompts.py templates.
  2. Call client.call_llm() to get raw text.
  3. Parse the raw text into the correct Pydantic schema (llm_schemas.py).
  4. Catch ALL validation errors here — NEVER let them bubble to routers.
  5. Return a typed Pydantic model to the calling service.

The service layer then reads the Pydantic model and makes all decisions
(DB writes, status updates, flags).  The orchestrator only returns data.
"""

from __future__ import annotations

import json

from loguru import logger
from pydantic import ValidationError

from app.llm import client
from app.llm import prompts

# Schemas will be imported from app.schemas.llm_schemas in Milestone 2+
# from app.schemas.llm_schemas import ComplianceChecklistLLM, TechnicalScoresLLM, ...


async def extract_compliance_checklist(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """
    Phase 2: Extract the compliance checklist from an offer PDF.

    Returns a validated Pydantic model (stub returns raw dict until
    llm_schemas.py is wired in Milestone 2).
    """
    system = prompts.COMPLIANCE_EXTRACTION_SYSTEM
    user = prompts.COMPLIANCE_EXTRACTION_USER.format(
        tender_ref=tender_ref,
        enterprise_name=enterprise_name,
        document_text=document_text,
    )

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
        # TODO (Milestone 2): return ComplianceChecklistLLM(**data)
        return data
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error(
            "LLM compliance extraction failed validation: {err}", err=str(exc)
        )
        raise ValueError(f"LLM returned invalid compliance JSON: {exc}") from exc


async def extract_technical_scores(
    tender_ref: str,
    enterprise_name: str,
    rubric_json: str,
    document_text: str,
) -> dict:
    """
    Phase 3: Score the technical offer against the rubric.
    Python will validate score bounds AFTER this returns.
    """
    system = prompts.TECHNICAL_SCORING_SYSTEM
    user = prompts.TECHNICAL_SCORING_USER.format(
        tender_ref=tender_ref,
        enterprise_name=enterprise_name,
        rubric_json=rubric_json,
        document_text=document_text,
    )

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
        # TODO (Milestone 3): return TechnicalScoresLLM(**data)
        return data
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("LLM technical scoring failed validation: {err}", err=str(exc))
        raise ValueError(f"LLM returned invalid technical scores JSON: {exc}") from exc


async def extract_financial_data(
    tender_ref: str,
    enterprise_name: str,
    document_text: str,
) -> dict:
    """
    Phase 4: Extract raw financial figures from the offer.
    Python applies the lowest-price formula AFTER this returns.
    """
    system = prompts.FINANCIAL_EXTRACTION_SYSTEM
    user = prompts.FINANCIAL_EXTRACTION_USER.format(
        tender_ref=tender_ref,
        enterprise_name=enterprise_name,
        document_text=document_text,
    )

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(raw)
        # TODO (Milestone 3): return FinancialDataLLM(**data)
        return data
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("LLM financial extraction failed validation: {err}", err=str(exc))
        raise ValueError(f"LLM returned invalid financial JSON: {exc}") from exc
