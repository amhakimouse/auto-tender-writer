"""
app/schemas/tender.py

Pydantic v2 schemas for Tender data validation and serialization.

These schemas enforce the contract between the API and the database,
ensuring only valid data reaches the persistence layer.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TenderStatus(StrEnum):
    """Mirror of db.models.tender.TenderStatus for API use."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# =============================================================================
# Base Schemas
# =============================================================================


class TenderBase(BaseModel):
    """Common fields shared across Tender schemas."""

    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    reference_number: str | None = Field(default=None, max_length=100)


# =============================================================================
# Create Schemas (Request bodies)
# =============================================================================


class TenderCreate(TenderBase):
    """Schema for creating a new Tender."""

    deadline: datetime = Field(
        ...,
        description="UTC deadline after which submissions are rejected",
    )
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "title": "IT Infrastructure Modernization",
                "description": "RFP for cloud migration services",
                "reference_number": "RFP-2024-001",
                "deadline": "2024-12-31T23:59:59+00:00",
            }
        }
    )


class TenderPublish(BaseModel):
    """Schema for publishing a draft Tender."""

    pass  # No fields; the action itself changes status


# =============================================================================
# Response Schemas
# =============================================================================


class TenderInDB(TenderBase):
    """Schema representing a Tender as stored in the database."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: TenderStatus
    deadline: datetime
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class TenderResponse(TenderInDB):
    """Schema for Tender API responses."""

    pass


class TenderListResponse(BaseModel):
    """Schema for paginated Tender list responses."""

    items: list[TenderResponse]
    total: int
    page: int
    page_size: int
