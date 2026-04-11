from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class DossierResult(BaseModel):
    presentation_note: str
    similar_references_note: str
    execution_methodology: str
    preliminary_schedule: str
    technical_offer_details: str
    financial_offer_structure: str

class ValidationSummary(BaseModel):
    score: int
    compliant_sections: List[str] = []
    missing_sections: List[str] = []
    weak_points: List[str] = []
    recommendations: List[str] = []
    verdict: str

class AnalyzeResponse(BaseModel):
    tender_ref: str
    status: str = "success"
    requirements: Dict
    dossier: DossierResult
    validation: ValidationSummary
