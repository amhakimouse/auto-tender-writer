"""
app/services/drafting_service.py

The RAG Bid Drafting Service — Enterprise Side Phase 8.

This module implements the "RAG Autopilot" that helps enterprises
draft proposals by:
    1. Retrieving relevant content from past winning bids (simulated)
    2. Matching old successful answers to new requirements
    3. Rewriting content to match the new buyer's tone and length requirements

Architecture Rules:
    1. Python handles document management and API routing
    2. LLM performs the semantic matching and rewriting
    3. Pydantic schemas enforce strict output structure
    4. All operations logged for audit trail
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Tender
from app.llm.client import call_llm
from app.schemas.drafting_schemas import (
    DraftedProposal,
    PastWinningBid,
    ProposalDraftRequest,
    SectionDraft,
)
from app.utils.audit_logger import ActionType, log_event


# =============================================================================
# RAG Bid Drafting Service
# =============================================================================


class DraftingResult:
    """Result container for proposal drafting."""

    def __init__(
        self,
        success: bool,
        draft: DraftedProposal | None,
        message: str,
        error_code: str | None = None,
    ):
        self.success = success
        self.draft = draft
        self.message = message
        self.error_code = error_code


async def draft_proposal_from_past_wins(
    db: AsyncSession,
    request: ProposalDraftRequest,
) -> DraftingResult:
    """
    Draft a proposal using RAG (Retrieval-Augmented Generation) from past winning bids.

    ## The Reasoner's Task:

    1. Analyze new tender requirements
    2. Match requirements to past winning bid content
    3. Rewrite content to match new buyer's tone and length
    4. Identify gaps where new content is needed

    ## Process:

    1. Fetch tender requirements
    2. Process past winning bid snippets
    3. LLM maps old content to new requirements
    4. Generate draft sections with citations
    5. Return structured proposal draft
    """
    logger.info(
        "Drafting proposal for tender {tender_id} using {count} past bids",
        tender_id=request.tender_id,
        count=len(request.past_winning_bids),
    )

    # --- Step 1: Fetch Tender Requirements ---
    tender_result = await db.execute(
        select(Tender).where(Tender.id == request.tender_id)
    )
    tender = tender_result.scalar_one_or_none()

    if tender is None:
        return DraftingResult(
            success=False,
            draft=None,
            message=f"Tender {request.tender_id} not found",
            error_code="TENDER_NOT_FOUND",
        )

    tender_requirements = tender.description or "No requirements available"

    # --- Step 2: Validate Past Bids ---
    if not request.past_winning_bids:
        return DraftingResult(
            success=False,
            draft=None,
            message="At least one past winning bid is required for RAG drafting",
            error_code="NO_PAST_BIDS",
        )

    # --- Step 3: Call LLM for Drafting ---
    try:
        draft = await _call_llm_draft_proposal(
            tender_requirements=tender_requirements,
            tender_title=tender.title,
            past_bids=request.past_winning_bids,
            max_pages=request.max_pages,
            tone_requirements=request.tone_requirements,
            focus_areas=request.focus_areas,
        )
    except Exception as exc:
        logger.error(
            "LLM proposal drafting failed for tender {id}: {error}",
            id=request.tender_id,
            error=str(exc),
        )
        return DraftingResult(
            success=False,
            draft=None,
            message=f"Drafting failed: {str(exc)}",
            error_code="DRAFTING_FAILED",
        )

    # --- Step 4: Log Drafting Event ---
    await log_event(
        db_session=db,
        action=ActionType.PROPOSAL_DRAFTED,
        actor="LLM",
        offer_id=None,
        new_state="DRAFT_GENERATED",
        context={
            "tender_id": request.tender_id,
            "tender_title": tender.title,
            "past_bids_used": len(request.past_winning_bids),
            "sections_generated": len(draft.sections),
            "estimated_pages": draft.estimated_page_count,
            "draft_confidence": draft.draft_confidence,
        },
    )
    await db.commit()

    logger.info(
        "Proposal draft generated for tender {tender_id}: "
        "{sections} sections, {pages:.1f} pages estimated",
        tender_id=request.tender_id,
        sections=len(draft.sections),
        pages=draft.estimated_page_count,
    )

    return DraftingResult(
        success=True,
        draft=draft,
        message="Proposal drafted successfully from past winning bids.",
    )


async def _call_llm_draft_proposal(
    tender_requirements: str,
    tender_title: str,
    past_bids: list[PastWinningBid],
    max_pages: int,
    tone_requirements: str | None,
    focus_areas: list[str],
) -> DraftedProposal:
    """
    Call LLM to draft proposal from past winning bids.

    The LLM:
    1. Analyzes the new tender requirements
    2. Matches them to past bid content
    3. Rewrites to match tone and length
    4. Identifies gaps
    """
    system_prompt = """You are an expert bid writer using Retrieval-Augmented Generation (RAG) to draft proposals.

Your task is to:
1. Analyze the new tender requirements
2. Match them to relevant content from past winning bids
3. Rewrite the content to match the new buyer's tone and length requirements
4. Identify gaps where new content must be written from scratch
5. Output structured draft sections with citations

RULES:
1. Match old content to new requirements by theme/topic, not just keyword
2. Adapt tone: formal/casual, technical/business, detailed/summary based on requirements
3. Respect page limits strictly — condense or expand as needed
4. Cite which past bid each section draws from
5. Flag gaps where no suitable past content exists
6. Output ONLY valid JSON matching the DraftedProposal schema
7. Maintain factual accuracy — do not invent capabilities or experience

QUALITY STANDARDS:
- Each section should directly address specific tender requirements
- Language should be persuasive but factual
- Avoid boilerplate — tailor everything to this specific buyer
- Respect any word count or page limits specified"""

    # Format past bids for LLM
    past_bids_text = []
    for i, bid in enumerate(past_bids, 1):
        past_bids_text.append(f"""
--- PAST WINNING BID #{i} ---
Reference: {bid.bid_reference}
Original Tender: {bid.original_tender_title or "N/A"}
Score: {bid.winning_score}/100

Content:
{bid.content_snippet}

Key Success Factors: {", ".join(bid.key_success_factors) if bid.key_success_factors else "N/A"}
--- END BID #{i} ---
""")

    focus_areas_text = ", ".join(focus_areas) if focus_areas else "General proposal"
    tone_text = tone_requirements or "Professional and persuasive"

    user_message = f"""Draft a proposal for the following tender using the past winning bids provided.

--- NEW TENDER REQUIREMENTS ---
Title: {tender_title}

{tender_requirements[:15000]}  # Limit to avoid token limits
--- END REQUIREMENTS ---

--- TONE AND LENGTH REQUIREMENTS ---
Target Length: {max_pages} pages maximum
Tone: {tone_text}
Focus Areas: {focus_areas_text}
--- END REQUIREMENTS ---

--- PAST WINNING BIDS (RAG SOURCE) ---
{chr(10).join(past_bids_text)}
--- END PAST BIDS ---

INSTRUCTIONS:
1. Map each section of the new tender requirements to relevant past bid content
2. Rewrite content to match the new buyer's tone and length requirements
3. Cite which past bid(s) each section references
4. Flag any gaps where no suitable past content exists
5. Provide an overall assessment of how well past bids cover new requirements

Generate the proposal draft as structured JSON matching the DraftedProposal schema."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=8000,
    )

    # Parse and validate
    data = json.loads(raw_response)
    draft = DraftedProposal(**data)

    # -------------------------------------------------------------------------
    # ENFORCER LOGIC: The LLM shouldn't randomly guess the resemblance percentage.
    # Python computes the EXACT string matching ratio to find new vs reused content.
    # -------------------------------------------------------------------------
    import difflib

    total_drafted_text = " ".join([s.drafted_content for s in draft.sections])
    total_source_text = " ".join([b.content_snippet for b in past_bids])

    if total_drafted_text and total_source_text:
        # SequenceMatcher ratio returns a similarity score from 0.0 to 1.0
        matcher = difflib.SequenceMatcher(None, total_drafted_text.lower(), total_source_text.lower())
        resemblance_ratio = matcher.ratio()

        # New content percentage is the exact inverse of resemblance
        exact_new_content_pct = round((1.0 - resemblance_ratio) * 100.0, 2)
        draft.new_content_percentage = exact_new_content_pct
    else:
        draft.new_content_percentage = 100.0 if not total_source_text else 0.0

    return draft


# =============================================================================
# Section-by-Section Drafting
# =============================================================================


async def draft_section_from_past_content(
    section_requirements: str,
    relevant_past_content: list[dict[str, Any]],
    target_length_words: int,
    tone: str,
) -> SectionDraft:
    """
    Draft a single section using relevant past content.

    This is useful for iterative drafting where the user
    wants to draft section by section.
    """
    system_prompt = f"""You are drafting a single section of a proposal.

Requirements:
- Target length: {target_length_words} words
- Tone: {tone}
- Use the provided past content as inspiration
- Do NOT copy verbatim — rewrite and adapt
- Output valid JSON matching SectionDraft schema"""

    past_content_text = "\n\n".join(
        [
            f"--- SOURCE {i + 1} ---\n{p.get('content', '')}"
            for i, p in enumerate(relevant_past_content)
        ]
    )

    user_message = f"""Draft a proposal section for the following requirements:

--- SECTION REQUIREMENTS ---
{section_requirements}
--- END REQUIREMENTS ---

--- REFERENCE CONTENT (from past winning bids) ---
{past_content_text}
--- END REFERENCE ---

Draft this section in approximately {target_length_words} words with a {tone} tone.
Return as structured JSON matching the SectionDraft schema."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=3000,
    )

    data = json.loads(raw_response)
    section = SectionDraft(**data)

    return section


# =============================================================================
# Gap Analysis
# =============================================================================


async def analyze_coverage_gaps(
    tender_requirements: str,
    drafted_sections: list[SectionDraft],
) -> dict[str, Any]:
    """
    Analyze gaps between tender requirements and drafted content.

    Returns a report of which requirements are not well covered.
    """
    system_prompt = """You are a bid quality reviewer analyzing proposal coverage.

Compare the tender requirements to the drafted sections and identify:
1. Requirements not addressed or poorly covered
2. Sections that may need expansion
3. Missing evidence or examples
4. Compliance risks

Output as JSON with:
- coverage_score (0-100)
- gaps (list of uncovered requirements)
- recommendations (list of improvement suggestions)"""

    sections_text = "\n\n".join(
        [
            f"--- SECTION: {s.section_title} ---\n{s.drafted_content[:500]}..."
            for s in drafted_sections
        ]
    )

    user_message = f"""Analyze coverage of the following tender requirements:

--- TENDER REQUIREMENTS ---
{tender_requirements[:8000]}
--- END REQUIREMENTS ---

--- DRAFTED SECTIONS ---
{sections_text}
--- END SECTIONS ---

Analyze gaps in coverage and return structured JSON."""

    raw_response = await call_llm(
        system_prompt=system_prompt,
        user_message=user_message,
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=3000,
    )

    return json.loads(raw_response)
