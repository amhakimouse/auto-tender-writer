import json
from loguru import logger
from app.llm.client import call_llm
from app.llm.prompts import (
    TENDER_VALIDATION_SYSTEM,
    TENDER_VALIDATION_USER
)
from app.schemas.tender_writer import ExtractionResult, TenderDossier, ValidationResult
from app.core.config import settings

async def validate_dossier(
    requirements: ExtractionResult,
    dossier: TenderDossier
) -> ValidationResult:
    """
    Validates a generated dossier against requirements using Mistral (via Featherless).
    """
    logger.info("Validating dossier compliance using Mistral...")
    
    # Handle both dicts and Pydantic objects
    req_json = requirements.model_dump_json(indent=2) if hasattr(requirements, 'model_dump_json') else json.dumps(requirements, indent=2)
    dos_json = dossier.model_dump_json(indent=2) if hasattr(dossier, 'model_dump_json') else json.dumps(dossier, indent=2)
    
    user_message = TENDER_VALIDATION_USER.format(
        requirements_json=req_json,
        dossier_json=dos_json
    )
    
    # Call Mistral-7B via Featherless
    raw_response = await call_llm(
        system_prompt=TENDER_VALIDATION_SYSTEM,
        user_message=user_message,
        model=settings.FEATHERLESS_MODEL,
        temperature=0.1 # Very low for compliance tasks
    )
    
    try:
        if "```json" in raw_response:
            raw_response = raw_response.split("```json")[-1].split("```")[0].strip()
        data = json.loads(raw_response)
        return ValidationResult(**data)
    except Exception as e:
        logger.error("Failed to parse validation response: {error}", error=str(e))
        raise
