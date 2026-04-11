from datetime import datetime
from sqlalchemy import Column, Integer, String, JSON, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import relationship
import enum

from app.db.base import Base

class EvaluationStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Evaluation(Base):
    """
    Persistence for LLM-based tender evaluations.
    Stores the score, verdict, and detailed report for a specific Offer.
    """
    __tablename__ = "evaluations"

    id = Column(Integer, primary_key=True, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=False)
    
    status = Column(SQLEnum(EvaluationStatus), default=EvaluationStatus.PENDING)
    
    # Summary Metrics
    compliance_score = Column(Integer, nullable=False, default=0)
    verdict = Column(String, nullable=False)
    
    # Detailed Reports (JSONB)
    report_data = Column(JSON, nullable=False)  # Full ValidationReportLLM object
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    # Relationships
    offer = relationship("Offer", back_populates="evaluations")

    def __repr__(self):
        return f"<Evaluation(id={self.id}, score={self.compliance_score}, verdict={self.verdict})>"
