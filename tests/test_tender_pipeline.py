import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch
from app.schemas.tender_writer import CompanyProfile, ExtractionResult, TenderDossier, ValidationResult
from app.services.generation_service import generate_dossier
from app.services.validation_service import validate_dossier

@pytest.mark.asyncio
async def test_generation_service_mock():
    # Setup mocks
    requirements = ExtractionResult(
        market_title="Test Tender",
        contracting_authority="Test Auth",
        mandatory_documents=["Doc A"],
        evaluation_criteria=["Crit X"],
        technical_requirements=["Req Y"],
        elimination_conditions=["Cond Z"]
    )
    profile = CompanyProfile(
        name="Test Company",
        sector="IT",
        references=["Ref 1"],
        certifications=["Cert A"]
    )
    
    # Mock call_llm response
    mock_response = json.dumps({
        "presentation_note": "Mocked Note",
        "similar_references_note": "Mocked Refs",
        "execution_methodology": "Mocked Method",
        "preliminary_schedule": "Mocked Schedule",
        "technical_offer_details": "Mocked Tech",
        "financial_offer_structure": "Mocked Finance"
    })
    
    with patch("app.services.generation_service.call_llm", new_callable=AsyncMock) as mocked_call:
        mocked_call.return_value = mock_response
        
        result = await generate_dossier(requirements, profile)
        
        assert isinstance(result, TenderDossier)
        assert result.presentation_note == "Mocked Note"
        mocked_call.assert_called_once()

@pytest.mark.asyncio
async def test_validation_service_mock():
    requirements = ExtractionResult(market_title="Test", contracting_authority="Auth")
    dossier = TenderDossier(
        presentation_note="Note",
        similar_references_note="Refs",
        execution_methodology="Method",
        preliminary_schedule="Schedule",
        technical_offer_details="Tech"
    )
    
    mock_validation = json.dumps({
        "score": 85,
        "compliant_sections": ["Section A"],
        "missing_sections": ["Detail B"],
        "weak_points": ["Point C"],
        "recommendations": ["Fix D"],
        "verdict": "CONFORME"
    })
    
    with patch("app.services.validation_service.call_llm", new_callable=AsyncMock) as mocked_call:
        mocked_call.return_value = mock_validation
        
        result = await validate_dossier(requirements, dossier)
        
        assert isinstance(result, ValidationResult)
        assert result.score == 85
        assert result.verdict == "CONFORME"

if __name__ == "__main__":
    asyncio.run(test_generation_service_mock())
    asyncio.run(test_validation_service_mock())
    print("Mocks verification passed!")
