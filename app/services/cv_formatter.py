"""
app/services/cv_formatter.py

CV Formatter Service for Enterprise Profiles.

This service takes an employee's master profile and a tender's requirements,
then uses the LLM to generate a tailored CV that:
    - Highlights only relevant experience
    - Cuts fluff and outdated entries
    - Meets strict page limits
    - Uses tender-specific keywords

Architecture:
    - Service receives EmployeeProfile and Tender requirements
    - Formats data for LLM prompt
    - Calls LLM orchestrator
    - Validates output against Pydantic schema
    - Returns TailoredCVOutput or error
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import ValidationError

from app.llm.prompts.enterprise import (
    ENTERPRISE_CV_FORMATTER_SYSTEM,
    ENTERPRISE_CV_FORMATTER_USER,
)
from app.schemas.enterprise_schemas import (
    EmployeeProfile,
    Skill,
    TailoredCVOutput,
    WorkExperience,
)

if TYPE_CHECKING:
    from app.db.models import Tender


class CVFormatterService:
    """
    Service for formatting/tailoring employee CVs for specific tenders.
    """

    def __init__(self):
        self.logger = logger.bind(service="CVFormatter")

    def _format_skills(self, skills: list[Skill]) -> str:
        """Format skills for LLM prompt."""
        lines = []
        for skill in skills:
            cert_str = (
                f" [{', '.join(skill.certifications)}]" if skill.certifications else ""
            )
            lines.append(
                f"- {skill.skill_name}: {skill.proficiency_level} "
                f"({skill.years_experience} years){cert_str}"
            )
        return "\n".join(lines) if lines else "No skills listed"

    def _format_work_experience(self, experiences: list[WorkExperience]) -> str:
        """Format work experience for LLM prompt."""
        lines = []
        for exp in experiences:
            duration = f"{exp.start_date.strftime('%Y-%m')} to {exp.end_date.strftime('%Y-%m') if exp.end_date else 'Present'}"
            lines.append(f"\n** {exp.role_title} at {exp.company} ({duration}) **")
            lines.append(f"Description: {exp.description}")
            if exp.key_projects:
                lines.append(f"Key Projects: {', '.join(exp.key_projects)}")
            if exp.skills_used:
                lines.append(f"Skills Used: {', '.join(exp.skills_used)}")
        return "\n".join(lines) if lines else "No work experience listed"

    def _format_education(self, education: list) -> str:
        """Format education for LLM prompt."""
        lines = []
        for edu in education:
            year_str = f" ({edu.graduation_year})" if edu.graduation_year else ""
            field_str = f" in {edu.field_of_study}" if edu.field_of_study else ""
            lines.append(f"- {edu.degree}{field_str} from {edu.institution}{year_str}")
        return "\n".join(lines) if lines else "No education listed"

    async def _call_llm_for_formatting(
        self,
        employee: EmployeeProfile,
        tender_requirements: str,
        max_pages: int,
        focus_areas: list[str],
        excluded_experience: list[str],
    ) -> TailoredCVOutput:
        """
        Call LLM to format the CV.

        Args:
            employee: Employee profile data
            tender_requirements: Tender requirements text
            max_pages: Maximum page limit
            focus_areas: Areas to emphasize
            excluded_experience: Experience to exclude

        Returns:
            TailoredCVOutput with formatted CV content

        Raises:
            ValueError: If LLM call or validation fails
        """
        # Import here to avoid circular imports
        from app.llm.client import call_llm

        # Prepare prompt data
        skills_formatted = self._format_skills(employee.skills)
        experience_formatted = self._format_work_experience(employee.work_experience)
        education_formatted = self._format_education(employee.education)

        # Format user prompt
        user_prompt = ENTERPRISE_CV_FORMATTER_USER.format(
            employee_name=employee.full_name,
            current_role=employee.current_role or "Not specified",
            years_experience=employee.years_total_experience,
            executive_summary=employee.executive_summary or "Not provided",
            skills_list=skills_formatted,
            work_experience=experience_formatted,
            education=education_formatted,
            tender_requirements=tender_requirements,
            max_pages=max_pages,
            focus_areas=", ".join(focus_areas) if focus_areas else "None specified",
            excluded_experience=", ".join(excluded_experience)
            if excluded_experience
            else "None",
        )

        self.logger.debug(
            "Calling LLM for CV formatting: employee={name}, pages={pages}",
            name=employee.full_name,
            pages=max_pages,
        )

        # Call LLM
        try:
            raw_response = await call_llm(
                system_prompt=ENTERPRISE_CV_FORMATTER_SYSTEM,
                user_message=user_prompt,
                response_format={"type": "json_object"},
                temperature=0.2,  # Slightly creative for rewrites
                max_tokens=4000,
            )
        except Exception as exc:
            self.logger.error("LLM CV formatting call failed: {error}", error=str(exc))
            raise ValueError(f"LLM call failed: {exc}") from exc

        # Parse JSON
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError as exc:
            self.logger.error(
                "LLM returned invalid JSON for CV: {raw}",
                raw=raw_response[:500],
            )
            raise ValueError(f"Invalid JSON from LLM: {exc}") from exc

        # Validate against schema
        try:
            tailored_cv = TailoredCVOutput(**data)
            self.logger.info(
                "CV formatting successful: {pages:.1f} pages, relevance {score}%",
                pages=tailored_cv.estimated_page_count,
                score=tailored_cv.relevance_score,
            )
            return tailored_cv

        except ValidationError as exc:
            self.logger.error(
                "CV output validation failed: {errors}\nData: {data}",
                errors=exc.errors(),
                data=data,
            )
            raise ValueError(f"CV validation failed: {exc}") from exc

    async def format_cv_for_tender(
        self,
        employee: EmployeeProfile,
        tender: Tender,
        max_pages: int = 2,
        focus_areas: list[str] | None = None,
        excluded_experience: list[str] | None = None,
    ) -> TailoredCVOutput:
        """
        Format an employee's CV for a specific tender.

        Args:
            employee: Employee profile to format
            tender: Tender to tailor CV for
            max_pages: Maximum page count (default 2)
            focus_areas: Specific areas to emphasize
            excluded_experience: Experience to exclude

        Returns:
            TailoredCVOutput with formatted content
        """
        self.logger.info(
            "Formatting CV for employee {employee_id} against tender {tender_id}",
            employee_id=employee.id,
            tender_id=tender.id,
        )

        # Extract tender requirements as text
        tender_requirements = self._extract_tender_requirements(tender)

        # Call LLM for formatting
        result = await self._call_llm_for_formatting(
            employee=employee,
            tender_requirements=tender_requirements,
            max_pages=max_pages,
            focus_areas=focus_areas or [],
            excluded_experience=excluded_experience or [],
        )

        return result

    def _extract_tender_requirements(self, tender: Tender) -> str:
        """Extract requirements from tender as formatted text."""
        requirements = []

        requirements.append(f"Tender: {tender.title}")
        requirements.append(f"Reference: {tender.reference_number or 'N/A'}")
        requirements.append(f"Description: {tender.description or 'N/A'}")
        requirements.append(f"Deadline: {tender.deadline.isoformat()}")

        return "\n\n".join(requirements)


# Singleton instance
_cv_formatter_service: CVFormatterService | None = None


def get_cv_formatter_service() -> CVFormatterService:
    """Get or create CV formatter service singleton."""
    global _cv_formatter_service
    if _cv_formatter_service is None:
        _cv_formatter_service = CVFormatterService()
    return _cv_formatter_service


# Convenience function
async def format_cv_for_tender(
    employee: EmployeeProfile,
    tender: Tender,
    max_pages: int = 2,
    focus_areas: list[str] | None = None,
    excluded_experience: list[str] | None = None,
) -> TailoredCVOutput:
    """
    Convenience function to format CV without managing service instance.

    Args:
        employee: Employee profile
        tender: Tender to tailor for
        max_pages: Page limit
        focus_areas: Areas to emphasize
        excluded_experience: Experience to exclude

    Returns:
        TailoredCVOutput
    """
    service = get_cv_formatter_service()
    return await service.format_cv_for_tender(
        employee=employee,
        tender=tender,
        max_pages=max_pages,
        focus_areas=focus_areas,
        excluded_experience=excluded_experience,
    )
