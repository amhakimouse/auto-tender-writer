import json
from loguru import logger
from app.llm.client import call_llm
from app.llm.prompts import (
    TENDER_GENERATION_SYSTEM,
    TENDER_GENERATION_USER,
    TENDER_REFINEMENT_SYSTEM,
    TENDER_REFINEMENT_USER
)
from app.schemas.tender_writer import ExtractionResult, CompanyProfile, TenderDossier, ValidationResult
from app.core.config import settings

async def generate_dossier(
    requirements: ExtractionResult, 
    profile: CompanyProfile
) -> TenderDossier:
    """
    Generates a full tender response dossier using Gemini.
    """
    logger.info("Generating tender dossier for {company}...", company=profile.name)
    
    user_message = TENDER_GENERATION_USER.format(
        requirements_json=requirements.model_dump_json(indent=2),
        profile_json=profile.model_dump_json(indent=2)
    )
    
    # Call Gemini (Flash)
    raw_response = await call_llm(
        system_prompt=TENDER_GENERATION_SYSTEM,
        user_message=user_message,
        model=settings.GEMINI_MODEL,
        temperature=0.7 # Slight temperature for better narrative generation
    )
    
    # Extract JSON content
    try:
        # litellm might return markdown blocks, we should strip them if present
        if "```json" in raw_response:
            raw_response = raw_response.split("```json")[-1].split("```")[0].strip()
        elif "```" in raw_response:
            raw_response = raw_response.split("```")[-1].split("```")[0].strip()
            
        data = json.loads(raw_response)
        return TenderDossier(**data)
    except Exception as e:
        logger.error("Failed to parse generation response: {error}", error=str(e))
        logger.debug("Raw response: {resp}", resp=raw_response)
        raise

async def refine_dossier(
    original_dossier: TenderDossier,
    validation_feedback: ValidationResult
) -> TenderDossier:
    """
    Refines the dossier based on validation feedback using Gemini.
    """
    logger.info("Refining tender dossier based on feedback (Score: {score})...", score=validation_feedback.score)
    
    user_message = TENDER_REFINEMENT_USER.format(
        dossier_json=original_dossier.model_dump_json(indent=2),
        feedback_json=validation_feedback.model_dump_json(indent=2)
    )
    
    # Call Gemini
    raw_response = await call_llm(
        system_prompt=TENDER_REFINEMENT_SYSTEM,
        user_message=user_message,
        model=settings.GEMINI_MODEL,
        temperature=0.3 # Lower temperature for refinement
    )
    
    try:
        if "```json" in raw_response:
            raw_response = raw_response.split("```json")[-1].split("```")[0].strip()
        data = json.loads(raw_response)
        return TenderDossier(**data)
    except Exception as e:
        logger.error("Failed to parse refinement response: {error}", error=str(e))
        raise
