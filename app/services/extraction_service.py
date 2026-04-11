from loguru import logger
from app.schemas.tender_writer import ExtractionResult

async def extract_requirements(pdf_content: bytes) -> ExtractionResult:
    """
    STUB: Extract requirements from PDF content.
    This will be fully implemented by Person 1A.
    """
    logger.info("Extracting requirements from PDF (STUB)...")
    
    # Mock data based on a typical Moroccan IT tender
    return ExtractionResult(
        market_title="Développement et mise en place d'une plateforme de gestion des archives numériques",
        contracting_authority="Ministère du Numérique",
        mandatory_documents=[
            "Note de présentation",
            "Attestation fiscale",
            "Certificat d'immatriculation au registre de commerce",
            "Moyens humains et techniques"
        ],
        evaluation_criteria=[
            "Qualité de la méthodologie (40 points)",
            "Qualifications de l'équipe (30 points)",
            "Planning d'exécution (30 points)"
        ],
        technical_requirements=[
            "Hébergement souverain (Maroc)",
            "Conformité avec la loi 09-08",
            "Architecture micro-services"
        ],
        elimination_conditions=[
            "Absence de note de présentation",
            "Non-respect des délais de livraison",
            "Moyens humains insuffisants"
        ]
    )
