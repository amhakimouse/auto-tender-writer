from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from app.schemas.evaluation import ValidationReportResponse

class DossierResult(BaseModel):
    # Mapping the LLM output keys to the API result
    # The LLM generates these specific sections
    presentation_note: str
    similar_references_note: str
    execution_methodology: str
    preliminary_schedule: str
    technical_offer_details: str
    financial_offer_structure: str

class AnalyzeResponse(BaseModel):
    tender_ref: str
    status: str = "success"
    requirements: Dict
    dossier: DossierResult
    validation: ValidationReportResponse
