import json
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from loguru import logger

from app.services import pdf_service
from app.llm import orchestrator
from app.schemas.api_schemas import AnalyzeResponse

router = APIRouter()

@router.post("/analyze", response_model=AnalyzeResponse, summary="Analyze AO and Generate Tender Dossier")
async def analyze_tender(
    file: UploadFile = File(...),
    company_profile: str = Form(...) # Expecting a JSON string in form field
):
    """
    Step 6: Complete Pipeline Integration.
    Receives a Tender PDF and a Company Profile, extracts requirements, 
    generates a compliant dossier, and validates it.
    """
    try:
        # 1. Read and Extract PDF Text
        logger.info("Received analyze request for file: {}", file.filename)
        pdf_content = await file.read()
        document_text = pdf_service.extract_text(pdf_content)
        
        if not document_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the provided PDF.")
        
        # 2. Extract Requirements (Person 1A Logic)
        requirements = await orchestrator.extract_requirements(document_text)
        
        # 3. Parse Company Profile
        try:
            profile_dict = json.loads(company_profile)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format for company_profile.")
        
        # 4. Generate & Refine Dossier (Roadmap Step 4 & 5)
        result = await orchestrator.generate_dossier(requirements, profile_dict)
        
        # 5. Build and return response
        return AnalyzeResponse(
            tender_ref=requirements.get("tender_reference", "UNKNOWN"),
            requirements=requirements,
            dossier=result["dossier"],
            validation=result["validation"]
        )
        
    except Exception as e:
        logger.exception("Pipeline failed: {}", str(e))
        raise HTTPException(status_code=500, detail=f"Pipeline error: {str(e)}")
