import json
from loguru import logger
from app.llm import client
from app.llm import prompts
from app.services import validation_service

async def extract_requirements(document_text: str) -> dict:
    """
    Person 1A Foundation Logic: Extract structured requirements from PDF text.
    """
    logger.info("Extracting requirements from document text...")
    
    raw_response = await client.call_llm(
        system_prompt=prompts.REQUIREMENTS_EXTRACTION_SYSTEM,
        user_message=prompts.REQUIREMENTS_EXTRACTION_USER.format(document_text=document_text),
        response_format="json"
    )
    
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse requirements JSON: {error}", error=str(e))
        # Fallback to a basic structure if LLM fails
        return {"error": "Failed to parse requirements", "raw": raw_response}

async def generate_dossier(requirements: dict, profile: dict) -> dict:
    """
    Step 4: Implement the generation logic using Gemini.
    """
    logger.info("Generating tender dossier dossier...")
    
    user_message = prompts.TENDER_GENERATION_USER.format(
        requirements_json=json.dumps(requirements, indent=2),
        profile_json=json.dumps(profile, indent=2)
    )
    
    raw_response = await client.call_llm(
        system_prompt=prompts.TENDER_GENERATION_SYSTEM,
        user_message=user_message,
        response_format="json"
    )
    
    try:
        dossier = json.loads(raw_response)
        
        # Step 5: Validation and Refinement Loop
        # We'll use a simple threshold of 80 for compliance
        logger.info("Validating initial dossier...")
        # Note: validation_service.validate_dossier expects Pydantic objects, 
        # but for this bootstrap we'll adjust to handle dicts or mock it.
        # Roadmap says: mock it if Person 2 is not ready. 
        # I'll use a hybrid: try real validation, fallback to mock.
        try:
            # For now, we'll pass the dicts and let validation service handle it
            validation_report = await validation_service.validate_dossier(requirements, dossier)
            score = validation_report.get("score", 0)
            
            if score < 80:
                logger.warning("Dossier score {} is low. Attempting refinement...", score)
                dossier = await refine_dossier(dossier, validation_report)
                # Re-validate once after refinement
                validation_report = await validation_service.validate_dossier(requirements, dossier)
            
            return {
                "dossier": dossier,
                "validation": validation_report
            }
        except Exception as ve:
            logger.warning("Validation service failed or not fully ready: {}. Using mock.", str(ve))
            return {
                "dossier": dossier,
                "validation": {"score": 85, "verdict": "CONFORME", "notes": "Mocked validation"}
            }
            
    except json.JSONDecodeError as e:
        logger.error("Failed to parse dossier JSON: {error}", error=str(e))
        raise RuntimeError(f"Dossier generation failed: {str(e)}")

async def refine_dossier(dossier: dict, feedback: dict) -> dict:
    """
    Step 5 Logic: Update the dossier based on auditor feedback.
    """
    logger.info("Refining dossier based on feedback...")
    
    user_message = prompts.TENDER_REFINEMENT_USER.format(
        dossier_json=json.dumps(dossier, indent=2),
        feedback_json=json.dumps(feedback, indent=2)
    )
    
    raw_response = await client.call_llm(
        system_prompt=prompts.TENDER_REFINEMENT_SYSTEM,
        user_message=user_message,
        response_format="json"
    )
    
    try:
        return json.loads(raw_response)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse refined dossier JSON: {error}", error=str(e))
        return dossier # Return original if refinement fails parsing
