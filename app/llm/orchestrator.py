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

from app.schemas.llm_output import ValidationReportLLM

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


# ── Person 2 — Dossier Validation ────────────────────────────────────────────

async def validate_dossier(
    requirements: dict,
    dossier: dict,
) -> ValidationReportLLM:
    """
    Person 2 — Phase: Dossier Compliance Validation

    Sends the generated dossier + extracted requirements to the LLM for
    strict Moroccan public procurement compliance analysis.

    Returns a fully validated ValidationReportLLM Pydantic model.
    The service layer reads this model to decide whether refinement is needed.

    Args:
        requirements : extracted tender requirements (from Person 1A)
        dossier      : generated response dossier (from Person 1B)

    Raises:
        ValueError : if the LLM returns malformed JSON or fails Pydantic validation
    """
    import json as _json

    system = prompts.VALIDATION_SYSTEM
    user = prompts.VALIDATION_USER.format(
        requirements=_json.dumps(requirements, ensure_ascii=False, indent=2),
        dossier=_json.dumps(dossier, ensure_ascii=False, indent=2),
    )

    logger.info("LLM validation call — requirements keys: {k}", k=list(requirements.keys()))

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        temperature=0.0,   # deterministic — never raise for validation
        response_format={"type": "json_object"},
    )

    try:
        data = _safe_parse_json(raw)
        report = ValidationReportLLM(**data)
        logger.info(
            "Validation done — score={score} verdict={verdict}",
            score=report.score,
            verdict=report.verdict,
        )
        return report
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("LLM validation output failed Pydantic check: {err}", err=str(exc))
        raise ValueError(f"LLM returned invalid validation JSON: {exc}") from exc


# ── Person 2 — Dossier Refinement ────────────────────────────────────────────

async def refine_dossier(
    dossier: dict,
    validation_report: ValidationReportLLM,
    requirements: dict,
) -> dict:
    """
    Person 2 — Refinement pass (triggered when score < 60).

    Sends the original dossier + validation feedback back to the LLM
    with targeted instructions to fix only the failing sections.

    Returns the corrected dossier as a plain dict (same keys as input dossier).
    The orchestrator does NOT re-run Pydantic on this — the service layer
    will re-call validate_dossier() to score the improved version.

    Args:
        dossier           : original generated dossier dict
        validation_report : ValidationReportLLM from the first validation pass
        requirements      : extracted tender requirements

    Raises:
        ValueError : if the LLM returns malformed JSON
    """
    import json as _json

    system = prompts.REFINEMENT_SYSTEM
    user = prompts.REFINEMENT_USER.format(
        dossier=_json.dumps(dossier, ensure_ascii=False, indent=2),
        score=validation_report.score,
        sections_manquantes=", ".join(validation_report.sections_manquantes) or "Aucune",
        clauses_eliminatoires=", ".join(validation_report.clauses_eliminatoires) or "Aucune",
        points_faibles="\n- ".join(validation_report.points_faibles) or "Aucun",
        recommandations="\n- ".join(validation_report.recommandations) or "Aucune",
        requirements=_json.dumps(requirements, ensure_ascii=False, indent=2),
    )

    logger.info(
        "LLM refinement call — initial score={score}, missing={n} sections",
        score=validation_report.score,
        n=len(validation_report.sections_manquantes),
    )

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        temperature=0.3,   # slight creativity allowed for writing improvement
        max_tokens=8192,   # refinement output can be long
        response_format={"type": "json_object"},
    )

    try:
        refined = _safe_parse_json(raw)
        logger.info("Refinement pass complete — {keys} sections returned", keys=list(refined.keys()))
        return refined
    except json.JSONDecodeError as exc:
        logger.error("LLM refinement returned non-JSON: {err}", err=str(exc))
        raise ValueError(f"LLM refinement returned invalid JSON: {exc}") from exc


# ── JSON parse helper (shared) ────────────────────────────────────────────────

def _safe_parse_json(content: str) -> dict:
    """
    Try multiple strategies to extract valid JSON from an LLM response.
    Handles markdown code-fenced output and stray text around JSON objects.
    """
    import re

    # 1. Direct parse (ideal path)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Extract from ```json … ``` block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find the first top-level {...} object in the string
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response (first 300 chars): {content[:300]}",
        content,
        0,
    )
