import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from loguru import logger

from app.schemas.tender_writer import (
    AnalyzeResponse, 
    CompanyProfile, 
    ExtractionResult,
    TenderDossier,
    ValidationResult
)
from app.services.extraction_service import extract_requirements
from app.services.generation_service import generate_dossier, refine_dossier
from app.services.validation_service import validate_dossier

router = APIRouter()

@router.post("/analyze", response_model=AnalyzeResponse, summary="Analyze tender and generate response dossier")
async def analyze_tender(
    tender_pdf: UploadFile = File(...),
    company_profile: str = Form(...)  # Expecting JSON string
):
    """
    Main pipeline:
    1. Extract requirements from PDF (Person 1A)
    2. Generate dossier using Gemini (Person 1B)
    3. Validate dossier using Mistral (Person 2)
    4. Refine if necessary (Person 1B)
    """
    logger.info("Starting analysis for {filename}", filename=tender_pdf.filename)
    
    # 1. Parse Company Profile
    try:
        profile_data = json.loads(company_profile)
        profile = CompanyProfile(**profile_data)
    except Exception as e:
        logger.error("Invalid company profile format: {error}", error=str(e))
        raise HTTPException(status_code=400, detail=f"Invalid company profile JSON: {str(e)}")
    
    # 2. Extract Requirements (Stub/1A)
    pdf_content = await tender_pdf.read()
    requirements = await extract_requirements(pdf_content)
    
    # 3. Generate Initial Dossier
    dossier = await generate_dossier(requirements, profile)
    
    # 4. Validate (Mistral)
    validation = await validate_dossier(requirements, dossier)
    
    # 5. Refinement Loop (H4)
    improved = False
    if validation.score < 70:
        logger.info("Compliance score low ({score}), triggering refinement loop...", score=validation.score)
        dossier = await refine_dossier(dossier, validation)
        # Re-validate to get final score
        validation = await validate_dossier(requirements, dossier)
        improved = True
        
    return AnalyzeResponse(
        requirements=requirements,
        dossier=dossier,
        validation=validation,
        improved=improved
    )
