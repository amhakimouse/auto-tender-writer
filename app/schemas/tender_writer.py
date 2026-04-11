from typing import List, Optional, Dict
from pydantic import BaseModel, Field

# --- Input / Extraction Schemas ---

class ExtractionResult(BaseModel):
    """Result of parsing the tender specifications (Cahier des Charges)."""
    market_title: str = Field(..., description="Titre du marché")
    contracting_authority: str = Field(..., description="Maître d'ouvrage")
    mandatory_documents: List[str] = Field(default_factory=list, description="Pièces obligatoires")
    evaluation_criteria: List[str] = Field(default_factory=list, description="Critères d'évaluation")
    technical_requirements: List[str] = Field(default_factory=list, description="Exigences techniques")
    elimination_conditions: List[str] = Field(default_factory=list, description="Conditions d'élimination")

class CompanyProfile(BaseModel):
    """User-provided company profile to tailor the response."""
    name: str = Field(..., description="Nom de l'entreprise")
    sector: str = Field(..., description="Secteur d'activité")
    references: List[str] = Field(default_factory=list, description="Références projets similaires")
    certifications: List[str] = Field(default_factory=list, description="Certifications / Qualifications")
    revenue: Optional[str] = Field(None, description="Chiffre d'affaires")
    workforce: Optional[str] = Field(None, description="Effectif / Moyens humains")

# --- Output / Generation Schemas ---

class TenderDossier(BaseModel):
    """The complete generated tender response package."""
    presentation_note: str = Field(..., description="Note de présentation de l'entreprise")
    similar_references_note: str = Field(..., description="Note sur les références similaires")
    execution_methodology: str = Field(..., description="Méthodologie d'exécution")
    preliminary_schedule: str = Field(..., description="Planning prévisionnel")
    technical_offer_details: str = Field(..., description="Offre technique détaillée")
    financial_offer_structure: Optional[str] = Field(None, description="Structure suggestive de l'offre financière")

# --- Validation Schemas ---

class ValidationResult(BaseModel):
    """Compliance scoring and feedback from the validation layer."""
    score: int = Field(..., ge=0, le=100, description="Score de conformité de 0 à 100")
    compliant_sections: List[str] = Field(default_factory=list)
    missing_sections: List[str] = Field(default_factory=list)
    weak_points: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    verdict: str = Field(..., description="CONFORME / NON_CONFORME / A_CORRIGER")

# --- Final Orchestration Schema ---

class AnalyzeResponse(BaseModel):
    """Final output returned by the /api/analyze endpoint."""
    requirements: ExtractionResult
    dossier: TenderDossier
    validation: ValidationResult
    improved: bool = Field(default=False, description="True if a refinement loop was triggered")
