"""
app/llm/orchestrator.py

The Orchestrator — combines raw LLM calls with Pydantic validation.
"""

import json
import re
from loguru import logger
from pydantic import ValidationError

from app.llm import client, prompts
from app.schemas.llm_output import ValidationReportLLM
from app.schemas.llm_schemas import ComplianceChecklist, TechnicalScore
from app.core.config import settings

# ── Person 1 — Generation Logic ──────────────────────────────────────────────

async def extract_requirements(document_text: str) -> dict:
    """Person 1A: Extract requirements from tender text."""
    raw = await client.call_llm(
        system_prompt=prompts.REQUIREMENTS_EXTRACTION_SYSTEM,
        user_message=prompts.REQUIREMENTS_EXTRACTION_USER.format(document_text=document_text),
        model=settings.GEMINI_MODEL,
        response_format="json"
    )
    return _safe_parse_json(raw)

async def generate_dossier(requirements: dict, profile: dict) -> dict:
    """Person 1B: Generate a tender response dossier."""
    user_message = prompts.TENDER_GENERATION_USER.format(
        requirements_json=json.dumps(requirements),
        profile_json=json.dumps(profile)
    )
    raw = await client.call_llm(
        system_prompt=prompts.TENDER_GENERATION_SYSTEM,
        user_message=user_message,
        model=settings.GEMINI_MODEL,
        response_format="json"
    )
    return _safe_parse_json(raw)


# ── Person 2 — Validation (Writer Journey) ───────────────────────────────────

async def validate_dossier(requirements: dict, dossier: dict) -> ValidationReportLLM:
    """Person 2: Validate live dossier."""
    system = prompts.VALIDATION_SYSTEM
    user = prompts.VALIDATION_USER.format(
        requirements=json.dumps(requirements),
        dossier=json.dumps(dossier)
    )
    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        model=settings.FEATHERLESS_MODEL,
        response_format="json"
    )
    data = _safe_parse_json(raw)
    return ValidationReportLLM(**data)

async def refine_dossier_specialized(dossier: dict, report: ValidationReportLLM, requirements: dict) -> dict:
    """Person 2: Refine dossier based on auditor feedback."""
    user = prompts.REFINEMENT_USER.format(
        dossier=json.dumps(dossier),
        score=report.score,
        sections_manquantes=", ".join(report.sections_manquantes),
        clauses_eliminatoires=", ".join(report.clauses_eliminatoires),
        points_faibles=", ".join(report.points_faibles),
        recommandations=", ".join(report.recommandations),
        requirements=json.dumps(requirements)
    )
    raw = await client.call_llm(
        system_prompt=prompts.REFINEMENT_SYSTEM,
        user_message=user,
        model=settings.FEATHERLESS_MODEL,
        response_format="json"
    )
    return _safe_parse_json(raw)


# ── Phases 2-3 — Batch Evaluation (Auditor Journey) ──────────────────────────

async def evaluate_compliance(pdf_text: str) -> ComplianceChecklist:
    """Phase 2: Administrative check."""
    raw = await client.call_llm(
        system_prompt=prompts.COMPLIANCE_EXTRACTION_SYSTEM,
        user_message=prompts.COMPLIANCE_EXTRACTION_USER.format(
            document_text=pdf_text,
            tender_ref="UNKNOWN", 
            enterprise_name="UNKNOWN"
        ),
        model=settings.FEATHERLESS_MODEL,
        response_format="json"
    )
    data = _safe_parse_json(raw)
    return ComplianceChecklist(**data)

async def score_technical_section(pdf_text: str, rubric: str) -> TechnicalScore:
    """Phase 3: Technical scoring."""
    raw = await client.call_llm(
        system_prompt=prompts.TECHNICAL_SCORING_SYSTEM,
        user_message=prompts.TECHNICAL_SCORING_USER.format(
            document_text=pdf_text,
            rubric_json=rubric,
            tender_ref="UNKNOWN",
            enterprise_name="UNKNOWN"
        ),
        model=settings.GEMINI_MODEL,
        response_format="json"
    )
    data = _safe_parse_json(raw)
    # The teammate's schema has 'criteria_scores', but the prompt might return 'scores'.
    # Manual mapping if necessary
    if "scores" in data and "criteria_scores" not in data:
        data["criteria_scores"] = data.pop("scores")
    return TechnicalScore(**data)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_parse_json(content: str) -> dict:
    """Extract and parse JSON from LLM response."""
    try:
        return json.loads(content)
    except:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
        if match: return json.loads(match.group(1))
        match = re.search(r"\{[\s\S]*\}", content)
        if match: return json.loads(match.group(0))
    raise ValueError(f"Could not parse JSON: {content[:100]}")
