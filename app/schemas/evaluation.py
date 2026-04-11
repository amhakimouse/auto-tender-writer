"""
app/schemas/evaluation.py

API-level Pydantic schemas for the validation & refinement endpoints.
These are what FastAPI serialises to JSON for the frontend (Person 3).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class DossierValidationRequest(BaseModel):
    """
    Payload for POST /api/v1/evaluations/validate

    Person 1 (backend) sends this after generating the dossier.
    Person 3 (frontend) may also call it directly for live validation.
    """

    requirements: dict = Field(
        ...,
        description=(
            "Structured requirements extracted from the tender PDF. "
            "Must contain at minimum: titre_marche, pieces_obligatoires, "
            "criteres_evaluation, conditions_elimination."
        ),
    )
    dossier: dict = Field(
        ...,
        description=(
            "The generated tender response dossier sections. "
            "Expected keys: note_presentation, references_similaires, "
            "methodologie_execution, planning_previsionnel, "
            "offre_technique, offre_financiere."
        ),
    )


class ValidationReportResponse(BaseModel):
    """
    Full API response from POST /api/v1/evaluations/validate
    Includes the validation result + refinement metadata.
    """

    score: int = Field(..., ge=0, le=100)
    verdict: Literal["CONFORME", "A_CORRIGER", "NON_CONFORME"]

    # Populated sections
    sections_conformes: list[str] = Field(default_factory=list)
    sections_manquantes: list[str] = Field(default_factory=list)

    # Moroccan-specific: eliminating clauses
    clauses_eliminatoires: list[str] = Field(
        default_factory=list,
        description="Critical clauses from Décret 2-12-349 that are missing or non-compliant. "
                    "Any item here = automatic elimination risk.",
    )

    points_faibles: list[str] = Field(default_factory=list)
    recommandations: list[str] = Field(default_factory=list)

    # Refinement metadata
    refined: bool = Field(
        default=False,
        description="True if an automatic refinement pass was triggered (score < 60).",
    )
    refinement_attempts: int = Field(
        default=0,
        description="Number of refinement iterations performed.",
    )
