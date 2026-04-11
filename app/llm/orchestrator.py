import json
import re
from loguru import logger
from pydantic import ValidationError

from app.llm import client, prompts
from app.schemas.llm_output import ValidationReportLLM
from app.core.config import settings

# ── Person 1 — Generation Logic ──────────────────────────────────────────────

async def extract_requirements(document_text: str) -> dict:
    """
    Person 1A: Extract structured requirements from tender PDF text.
    Uses Gemini for high-accuracy extraction.
    """
    logger.info("Extracting requirements from document text...")
    
    raw_response = await client.call_llm(
        system_prompt=prompts.REQUIREMENTS_EXTRACTION_SYSTEM,
        user_message=prompts.REQUIREMENTS_EXTRACTION_USER.format(document_text=document_text),
        model=settings.GEMINI_MODEL,
        response_format="json"
    )
    
    try:
        return _safe_parse_json(raw_response)
    except Exception as e:
        logger.error("Failed to parse requirements JSON: {error}", error=str(e))
        return {"error": "Failed to parse requirements", "raw": raw_response}

async def generate_dossier(requirements: dict, profile: dict) -> dict:
    """
    Person 1B: Generate a compliant tender response dossier.
    Uses Gemini for high-quality administrative French generation.
    """
    logger.info("Generating tender dossier draft...")
    
    user_message = prompts.TENDER_GENERATION_USER.format(
        requirements_json=json.dumps(requirements, indent=2),
        profile_json=json.dumps(profile, indent=2)
    )
    
    raw_response = await client.call_llm(
        system_prompt=prompts.TENDER_GENERATION_SYSTEM,
        user_message=user_message,
        model=settings.GEMINI_MODEL,
        response_format="json"
    )
    
    try:
        return _safe_parse_json(raw_response)
    except Exception as e:
        logger.error("Failed to parse dossier JSON: {error}", error=str(e))
        raise RuntimeError(f"Dossier generation failed: {str(e)}")


# ── Person 2 — Dossier Validation & Refinement ───────────────────────────────

async def validate_dossier(
    requirements: dict,
    dossier: dict,
) -> ValidationReportLLM:
    """
    Person 2 — Phase: Dossier Compliance Validation.
    Uses the specialized Featherless/Qwen/Mistral backend for strict audit.
    """
    system = prompts.VALIDATION_SYSTEM
    user = prompts.VALIDATION_USER.format(
        requirements=json.dumps(requirements, ensure_ascii=False, indent=2),
        dossier=json.dumps(dossier, ensure_ascii=False, indent=2),
    )

    logger.debug("LLM validation call triggered → model={m}", m=settings.FEATHERLESS_MODEL)

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        model=settings.FEATHERLESS_MODEL,
        temperature=0.0,   # deterministic for validation
        response_format="json",
    )

    try:
        data = _safe_parse_json(raw)
        report = ValidationReportLLM(**data)
        return report
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.error("LLM validation output failed check: {err}", err=str(exc))
        raise ValueError(f"LLM returned invalid validation JSON: {exc}") from exc

async def refine_dossier_specialized(
    dossier: dict,
    validation_report: ValidationReportLLM,
    requirements: dict,
) -> dict:
    """
    Person 2 — Refinement pass (triggered when score is low).
    Uses the Featherless backend to fix specific compliance issues.
    """
    system = prompts.REFINEMENT_SYSTEM
    user = prompts.REFINEMENT_USER.format(
        dossier=json.dumps(dossier, ensure_ascii=False, indent=2),
        score=validation_report.score,
        sections_manquantes=", ".join(validation_report.sections_manquantes) or "Aucune",
        clauses_eliminatoires=", ".join(validation_report.clauses_eliminatoires) or "Aucune",
        points_faibles="\n- ".join(validation_report.points_faibles) or "Aucun",
        recommandations="\n- ".join(validation_report.recommandations) or "Aucune",
        requirements=json.dumps(requirements, ensure_ascii=False, indent=2),
    )

    logger.info("LLM refinement call triggered → model={m}", m=settings.FEATHERLESS_MODEL)

    raw = await client.call_llm(
        system_prompt=system,
        user_message=user,
        model=settings.FEATHERLESS_MODEL,
        temperature=0.3,
        response_format="json",
    )

    try:
        return _safe_parse_json(raw)
    except Exception as exc:
        logger.error("LLM refinement returned non-JSON: {err}", err=str(exc))
        raise ValueError(f"LLM refinement returned invalid JSON: {exc}") from exc


# ── JSON parse helper (shared) ───────────────────────────────────────────────

def _safe_parse_json(content: str) -> dict:
    """
    Try multiple strategies to extract valid JSON from an LLM response.
    """
    # 1. Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Extract from ```json block
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find first top-level {...}
    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise json.JSONDecodeError(
        f"Could not extract JSON from LLM response (first 100 chars): {content[:100]}",
        content,
        0,
    )
