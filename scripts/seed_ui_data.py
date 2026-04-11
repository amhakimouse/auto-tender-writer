"""
scripts/seed_ui_data.py

UI Developer Mock Seeder.

This script drops existing database tables, recreates them, and inserts
mock data (Tenders, Offers, Users, Audit Logs) to assist UI development
without triggering LLM API costs.

Usage:
    PYTHONPATH=. python scripts/seed_ui_data.py
"""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.session import engine, AsyncSessionLocal
from app.db.models import Tender, Offer, User, AuditLog
from app.db.models.tender import TenderStatus
from app.db.models.offer import OfferStatus
from app.db.models.user import UserRole
from app.core.security import hash_password
from app.utils.audit_logger import ActionType

async def wipe_db():
    print("🧨 Dropping all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    print("🏗️ Recreating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def seed_data(session: AsyncSession):
    now = datetime.now(timezone.utc)
    
    print("👤 Seeding Users...")
    admin = User(
        email="admin@example.com",
        name="Admin User",
        role=UserRole.ADMIN,
        hashed_password=hash_password("admin123"),
        is_active=True
    )
    committee = User(
        email="chair@example.com",
        name="Committee Chair",
        role=UserRole.COMMITTEE_CHAIR,
        hashed_password=hash_password("chair123"),
        is_active=True
    )
    reviewer = User(
        email="reviewer@example.com",
        name="Reviewer User",
        role=UserRole.REVIEWER,
        hashed_password=hash_password("reviewer123"),
        is_active=True
    )
    session.add_all([admin, committee, reviewer])
    await session.commit()

    print("📄 Seeding Tenders...")
    tenders = [
        Tender(
            title="Supply of Office Computers",
            description="Procurement of 500 desktops and laptops for the new HQ.",
            reference_number="PROC-2024-001",
            status=TenderStatus.PUBLISHED,
            deadline=now + timedelta(days=10),
        ),
        Tender(
            title="Cloud Hosting Services",
            description="Provision of cloud infrastructure for public digital platforms.",
            reference_number="PROC-2024-002",
            status=TenderStatus.CLOSED,
            deadline=now - timedelta(days=5),
        ),
        Tender(
            title="Security Audit & Penetration Testing",
            description="Comprehensive security assessment of internal networks.",
            reference_number="PROC-2024-003",
            status=TenderStatus.PUBLISHED,
            deadline=now + timedelta(days=30),
        ),
        Tender(
            title="Office Furniture Supply",
            description="Ergonomic chairs and desks for the regional branches.",
            reference_number="PROC-2023-099",
            status=TenderStatus.CANCELLED,
            deadline=now - timedelta(days=50),
        ),
        Tender(
            title="Legal Consultation Retainer",
            description="Ongoing legal support for international contracts.",
            reference_number="PROC-2024-004",
            status=TenderStatus.DRAFT,
            deadline=now + timedelta(days=60),
        ),
    ]
    session.add_all(tenders)
    await session.commit()
    
    for t in tenders:
        await session.refresh(t)

    print("💼 Seeding Offers...")
    cloud_tender = tenders[1]  # CLOSED tender
    offers = [
        Offer(
            tender_id=cloud_tender.id,
            bidder_name="TechCorp Solutions",
            bidder_email="bids@techcorp.com",
            file_hash_sha256="db43bde81db320f77977461421062bca9ba5c5f242551a148a0f123456789abc",
            submitted_at=now - timedelta(days=6),
            original_filename="techcorp_proposal.pdf",
            status=OfferStatus.AWARDED,
            compliance_passed=True,
            technical_score=85.5,
            financial_score=90.0,
            total_score=88.2,
        ),
        Offer(
            tender_id=cloud_tender.id,
            bidder_name="CloudNet Inc",
            bidder_email="sales@cloudnet.com",
            file_hash_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495123456789abc",
            submitted_at=now - timedelta(days=7),
            original_filename="cloudnet_submission.pdf",
            status=OfferStatus.REJECTED_FINAL,
            compliance_passed=True,
            technical_score=70.0,
            financial_score=88.0,
            total_score=77.2,
        ),
        Offer(
            tender_id=cloud_tender.id,
            bidder_name="LateBidders LLC",
            bidder_email="hello@latebidders.com",
            file_hash_sha256="abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234abcd1234",
            submitted_at=now - timedelta(days=4), # Late
            original_filename="late_bid.pdf",
            status=OfferStatus.REJECTED_LATE,
            disqualification_reason="Submitted past the deadline."
        )
    ]
    
    # Add a bunch of pending offers for the published tenders
    compute_tender = tenders[0]
    for i in range(17):
        offers.append(Offer(
            tender_id=compute_tender.id,
            bidder_name=f"Standard Bidder {i}",
            bidder_email=f"contact{i}@example.com",
            file_hash_sha256=f"a{'b'*61}{i:02d}",
            submitted_at=now - timedelta(hours=i),
            original_filename=f"bid_{i}.pdf",
            status=OfferStatus.RECEIVED
        ))
        
    session.add_all(offers)
    await session.commit()
    
    for o in offers:
        await session.refresh(o)

    print("📜 Seeding Audit Logs...")
    logs = [
        AuditLog(
            action_type=ActionType.TENDER_CREATED,
            actor="SYSTEM",
            new_state="PUBLISHED",
            context={"note": "Initial tender creation", "tender_id": cloud_tender.id}
        ),
        AuditLog(
            action_type=ActionType.SCORE_OVERRIDDEN,
            actor="chair@example.com",
            offer_id=offers[0].id,
            new_state="COMMITTEE_REVIEW",
            context={"reason": "Experience heavily outweighs cost for this project.", "tender_id": cloud_tender.id}
        ),
    ]
    session.add_all(logs)
    await session.commit()
    print("✅ Seeding complete!")

async def main():
    await wipe_db()
    async with AsyncSessionLocal() as session:
        await seed_data(session)

if __name__ == "__main__":
    asyncio.run(main())
