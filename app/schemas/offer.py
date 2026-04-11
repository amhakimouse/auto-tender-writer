"""
app/schemas/offer.py

Pydantic v2 schemas for Offer (Bid/Submission) data validation.

These schemas strictly separate:
    - Input schemas (what clients may submit)
    - Internal schemas (service layer communication)
    - Output schemas (what API returns to clients)

The Enforcer uses these to validate all data before persistence.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfferStatus(StrEnum):
    """Mirror of db.models.offer.OfferStatus for API use."""

    RECEIVED = "RECEIVED"
    REJECTED_LATE = "REJECTED_LATE"
    COMPLIANCE_PENDING = "COMPLIANCE_PENDING"
    COMPLIANT = "COMPLIANT"
    INCOMPLIANT = "INCOMPLIANT"
    TECHNICAL_SCORING = "TECHNICAL_SCORING"
    TECHNICAL_SCORED = "TECHNICAL_SCORED"
    FINANCIAL_EXTRACTED = "FINANCIAL_EXTRACTED"
    COMBINED_SCORED = "COMBINED_SCORED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    AWARDED = "AWARDED"
    REJECTED_FINAL = "REJECTED_FINAL"
    APPEALED = "APPEALED"


class FileHashAlgorithm(StrEnum):
    """Supported file hashing algorithms for integrity verification."""

    SHA256 = "SHA256"


# =============================================================================
# Upload Request Schema
# =============================================================================


class OfferUploadRequest(BaseModel):
    """
    Metadata accompanying an Offer PDF upload.

    Note: The actual PDF file is sent as multipart/form-data (UploadFile),
    not as JSON. This schema validates the accompanying metadata fields.
    """

    bidder_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the submitting organization",
    )
    bidder_email: str | None = Field(
        default=None,
        max_length=255,
        description="Contact email for this submission",
    )


# =============================================================================
# Response Schemas
# =============================================================================


class OfferFileInfo(BaseModel):
    """File integrity information for API responses."""

    original_filename: str
    hash_algorithm: FileHashAlgorithm = FileHashAlgorithm.SHA256
    hash_hex: str = Field(..., pattern=r"^[a-fA-F0-9]{64}$")
    size_bytes: int | None = None


class OfferInDB(BaseModel):
    """Schema representing an Offer as stored in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    bidder_name: str
    bidder_email: str | None
    file_hash_sha256: str
    submitted_at: datetime
    original_filename: str
    storage_path: str | None
    status: OfferStatus
    compliance_passed: bool | None
    technical_score: float | None = Field(default=None, ge=0, le=100)
    financial_score: float | None = Field(default=None, ge=0, le=100)
    total_score: float | None = Field(default=None, ge=0, le=100)
    disqualification_reason: str | None
    committee_notes: str | None
    created_at: datetime
    updated_at: datetime


class OfferResponse(BaseModel):
    """
    API response for Offer operations.

    Excludes internal details like storage_path while including
    the file integrity proof (hash).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: int
    bidder_name: str
    bidder_email: str | None
    status: OfferStatus
    submitted_at: datetime
    file_info: OfferFileInfo


class OfferListResponse(BaseModel):
    """Paginated list of offers."""
    items: list[OfferResponse]
    total: int
    page: int
    page_size: int


class OfferUploadResponse(OfferResponse):
    """
        Response returned after successful offer upload.

    n    Includes the computed file hash and submission confirmation.
    """

    message: str = "Offer received and integrity verified"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "tender_id": 1,
                "bidder_name": "Acme Corp",
                "bidder_email": "bids@acme.com",
                "status": "RECEIVED",
                "submitted_at": "2024-01-15T10:30:00+00:00",
                "file_info": {
                    "original_filename": "acme_proposal.pdf",
                    "hash_algorithm": "SHA256",
                    "hash_hex": "a3f5c2...64chars",
                },
                "message": "Offer received and integrity verified",
            }
        }
    )


class OfferRejectedResponse(BaseModel):
    """Response when an offer is rejected (e.g., late submission)."""

    success: bool = False
    reason: str
    tender_id: int
    deadline: datetime
    submitted_at: datetime


# =============================================================================
# Service Layer Schemas (Internal)
# =============================================================================


class OfferCreateInternal(BaseModel):
    """
    Internal schema for creating an Offer record.

    This is constructed by the intake service after:
        - Computing the file hash
        - Capturing server timestamp
        - Validating deadline
    """

    tender_id: int
    bidder_name: str
    bidder_email: str | None
    file_hash_sha256: str = Field(..., pattern=r"^[a-fA-F0-9]{64}$")
    submitted_at: datetime
    original_filename: str
    storage_path: str | None = None
    status: OfferStatus = OfferStatus.RECEIVED
