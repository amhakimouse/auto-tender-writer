"""
app/schemas/llm_output.py

Pydantic schemas for LLM outputs related to the Tender Writer journey.
Standardized on the teammate's preferred keys.
"""

from __future__ import annotations
from pydantic import BaseModel, Field

class ValidationReportLLM(BaseModel):
    """
    Compliance report for the live dossier writer loop.
    Matches the schema expected in prompts.VALIDATION_SYSTEM.
    """
    score: int = Field(..., ge=0, le=100)
    verdict: str = Field(..., description="CONFORME | A_CORRIGER | NON_CONFORME")
    sections_conformes: list[str] = Field(default_factory=list)
    sections_manquantes: list[str] = Field(default_factory=list)
    clauses_eliminatoires: list[str] = Field(default_factory=list)
    points_faibles: list[str] = Field(default_factory=list)
    recommandations: list[str] = Field(default_factory=list)
