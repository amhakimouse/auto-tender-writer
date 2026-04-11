#!/usr/bin/env python3
"""
scripts/seed_db.py

Database seeding script for development and testing.

This script:
    1. Initializes the database tables (async SQLAlchemy)
    2. Creates sample tenders for testing Milestone 1

Usage:
    python scripts/seed_db.py

Sample Tenders Created:
    1. "IT Infrastructure Modernization" (PUBLISHED, active)
       - Deadline: 30 days from now
       - Status: PUBLISHED (accepts submissions)

    2. "Legacy System Migration" (CLOSED, past deadline)
       - Deadline: 7 days ago
       - Status: CLOSED (rejects submissions)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.init_db import init_db
from app.db.models import Tender
from app.db.models.tender import TenderStatus
from app.db.session import AsyncSessionLocal, engine


async def create_sample_tenders(db: AsyncSession) -> list[Tender]:
    """Create sample tenders for testing."""

    now = datetime.now(timezone.utc)

    # Tender 1: PUBLISHED and accepting submissions
    tender_1 = Tender(
        title="IT Infrastructure Modernization",
        description="""
RFP for comprehensive IT infrastructure modernization including:
- Cloud migration strategy and implementation
- Network security hardening
- Disaster recovery systems
- Staff training and documentation

This is a critical procurement for the organization. 
Vendors must demonstrate proven experience with enterprise-scale cloud migrations.
""".strip(),
        reference_number="RFP-2024-001-ITMOD",
        status=TenderStatus.PUBLISHED,
        deadline=now + timedelta(days=30),
        created_by=None,
    )

    # Tender 2: CLOSED (deadline passed)
    tender_2 = Tender(
        title="Legacy System Migration (Closed)",
        description="""
RFP for migrating legacy on-premise systems to cloud infrastructure.

NOTE: This tender is now closed and no longer accepting submissions.
The deadline has passed and evaluation is in progress.
""".strip(),
        reference_number="RFP-2024-002-LEGACY",
        status=TenderStatus.CLOSED,
        deadline=now - timedelta(days=7),  # Deadline was 7 days ago
        created_by=None,
    )

    # Tender 3: DRAFT (not yet published)
    tender_3 = Tender(
        title="Data Analytics Platform",
        description="""
RFP for enterprise data analytics platform including:
- Data warehouse implementation
- Business intelligence dashboards
- Machine learning capabilities
- Integration with existing systems

This tender is currently in draft status and will be published after review.
""".strip(),
        reference_number="RFP-2024-003-ANALYTICS",
        status=TenderStatus.DRAFT,
        deadline=now + timedelta(days=60),
        created_by=None,
    )

    db.add_all([tender_1, tender_2, tender_3])
    await db.commit()

    # Refresh to get IDs
    for tender in [tender_1, tender_2, tender_3]:
        await db.refresh(tender)

    return [tender_1, tender_2, tender_3]


async def seed_database() -> None:
    """Main seeding function."""
    print("=" * 60)
    print("Auto Tender Writer - Database Seeding")
    print("=" * 60)
    print()

    # Initialize database tables
    print("🗃️  Initializing database tables...")
    await init_db()
    print("✅ Database tables initialized")
    print()

    async with AsyncSessionLocal() as db:
        # Check if tenders already exist
        result = await db.execute(select(Tender))
        existing_tenders = result.scalars().all()

        if existing_tenders:
            print(f"⚠️  Found {len(existing_tenders)} existing tenders in database.")
            print("   Use 'DELETE FROM tenders;' to clear them before re-seeding.")
            print()
            print("Existing tenders:")
            for t in existing_tenders:
                print(
                    f"   - ID {t.id}: {t.title} ({t.status}, deadline: {t.deadline.isoformat()})"
                )
            print()
            response = input(
                "Do you want to continue and add more sample tenders? (yes/no): "
            )
            if response.lower() not in ("yes", "y"):
                print("   Aborting.")
                return

        # Create sample tenders
        print("📝 Creating sample tenders...")
        tenders = await create_sample_tenders(db)
        print("✅ Sample tenders created")
        print()

        # Display created tenders
        print("-" * 60)
        print("Created Sample Tenders:")
        print("-" * 60)

        for tender in tenders:
            status_icon = {
                TenderStatus.DRAFT: "📝",
                TenderStatus.PUBLISHED: "✅",
                TenderStatus.CLOSED: "🔒",
                TenderStatus.CANCELLED: "❌",
            }.get(tender.status, "❓")

            print()
            print(f"{status_icon} Tender ID: {tender.id}")
            print(f"   Title: {tender.title}")
            print(f"   Reference: {tender.reference_number}")
            print(f"   Status: {tender.status}")
            print(f"   Deadline: {tender.deadline.isoformat()}")

            if tender.status == TenderStatus.PUBLISHED:
                days_remaining = (tender.deadline - datetime.now(timezone.utc)).days
                print(f"   ⏰ Accepting submissions! ({days_remaining} days remaining)")
                print(f"   🧪 Test upload: curl -X POST \\")
                print(f"        -F 'bidder_name=Test Corp' \\")
                print(f"        -F 'bidder_email=test@example.com' \\")
                print(f"        -F 'file=@your_file.pdf' \\")
                print(f"        http://localhost:8000/api/v1/intake/upload/{tender.id}")
            elif tender.status == TenderStatus.CLOSED:
                print(f"   🔒 Submissions REJECTED (deadline passed)")
                print(f"   🧪 Test rejection: Try uploading to this tender ID")

        print()
        print("-" * 60)
        print("Database seeding complete!")
        print("-" * 60)
        print()
        print("Next steps:")
        print("  1. Start the API server: uvicorn app.main:app --reload")
        print("  2. Access Swagger UI: http://localhost:8000/api/v1/docs")
        print("  3. Test tender creation: POST /api/v1/tenders/")
        print("  4. Test offer upload: POST /api/v1/intake/upload/{tender_id}")
        print()
        print(f"Data directory: {settings.DATA_DIR}")
        print(f"Database URL: {settings.DATABASE_URL}")


async def main() -> None:
    """Entry point."""
    try:
        await seed_database()
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # Close the engine
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
