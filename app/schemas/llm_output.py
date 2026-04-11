"""
app/schemas/llm_output.py

Pydantic models that mirror the exact JSON schemas the LLM must return.
Every LLM output is validated against one of these before any Python code
acts on it — this is the Golden Rule enforcement layer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ValidationReportLLM(BaseModel):
    """
    Schema for the dossier validation report returned by the LLM.
    Maps directly to the JSON format defined in VALIDATION_USER prompt.

    Used by: app/llm/orchestrator.py → validate_dossier()
    """

    score: int = Field(..., ge=0, le=100, description="Conformity score 0-100")
    verdict: Literal["CONFORME", "A_CORRIGER", "NON_CONFORME"]
    sections_conformes: list[str] = Field(default_factory=list)
    sections_manquantes: list[str] = Field(default_factory=list)
    clauses_eliminatoires: list[str] = Field(
        default_factory=list,
        description="Critical eliminating clauses that are missing or non-compliant",
    )
    points_faibles: list[str] = Field(default_factory=list)
    recommandations: list[str] = Field(default_factory=list)
    refined: bool = Field(
        default=False,
        description="True after a refinement pass has been applied",
    )

    @field_validator("verdict", mode="before")
    @classmethod
    def normalise_verdict(cls, v: str) -> str:
        """Accept minor casing variations from the LLM."""
        return v.strip().upper()

    @field_validator("score", mode="before")
    @classmethod
    def clamp_score(cls, v: int | float) -> int:
        """Clamp to [0, 100] in case the LLM hallucinates out-of-range values."""
        return max(0, min(100, int(v)))
