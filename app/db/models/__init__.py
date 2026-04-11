"""
app/db/models/__init__.py

Central export point for all SQLAlchemy ORM models.

Import order matters for dependency resolution (ForeignKey relationships).
Models with no dependencies come first; models referencing them come later.
"""

# Base first (no dependencies)
from app.db.base import Base

# Independent entities (no FKs)
from app.db.models.user import User, UserRole

# Entities referencing User
from app.db.models.tender import Tender, TenderStatus

# Entities referencing Tender
from app.db.models.offer import Offer, OfferStatus

# Audit log (references Offer)
from app.db.models.audit_log import AuditLog

# Evaluation (references Offer)
from app.db.models.evaluation import Evaluation, EvaluationStatus

# Appeal (references Tender and Offer)
from app.db.models.appeal import Appeal, AppealStatus


__all__ = [
    # Base
    "Base",
    # User
    "User",
    "UserRole",
    # Tender
    "Tender",
    "TenderStatus",
    # Offer
    "Offer",
    "OfferStatus",
    # Audit
    "AuditLog",
    # Evaluation
    "Evaluation",
    "EvaluationStatus",
    # Appeal
    "Appeal",
    "AppealStatus",
]
