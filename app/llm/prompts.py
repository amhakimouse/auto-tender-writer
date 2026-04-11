"""
app/llm/prompts.py

Versioned, parameterised prompt templates.

Design rules:
  - No business logic lives here. This file is TEXT ONLY.
  - Every template is a plain Python string with {named_placeholders}.
  - Prompt names follow the convention: <PHASE>_<TASK>_SYSTEM / _USER.
  - Keep system prompts short and focused on ROLE + OUTPUT FORMAT.
  - The JSON schema expected in the response is always stated explicitly
    so the LLM knows exactly what to produce.
"""

# ── Phase 2 — Administrative Compliance ───────────────────────────────────────

COMPLIANCE_EXTRACTION_SYSTEM = """\
You are a document compliance analyst for a public-sector procurement system.
Your ONLY job is to read the provided text and determine which required documents
are present or absent.

OUTPUT FORMAT — respond with a single, valid JSON object. No markdown, no prose.
Schema:
{{
  "is_tax_compliance_present": bool,
  "is_company_registration_present": bool,
  "is_bid_bond_present": bool,
  "is_audited_financials_present": bool,
  "is_key_personnel_cvs_present": bool,
  "notes": "string | null"
}}
"""

COMPLIANCE_EXTRACTION_USER = """\
Tender reference: {tender_ref}
Enterprise name:  {enterprise_name}

---BEGIN DOCUMENT TEXT---
{document_text}
---END DOCUMENT TEXT---

Analyse the text above and return the JSON compliance checklist.
"""

# ── Phase 3 — Technical Evaluation ───────────────────────────────────────────

TECHNICAL_SCORING_SYSTEM = """\
You are a technical evaluation expert for a public-sector tender committee.
You will be given a scoring rubric and an offer document.

For each criterion in the rubric, assign an integer score between 0 and the
criterion's maximum, and provide a 1-2 sentence justification.

OUTPUT FORMAT — respond with a single, valid JSON object. No markdown, no prose.
Schema:
{{
  "scores": [
    {{
      "criterion": "string",
      "max_score": integer,
      "raw_score": integer,
      "justification": "string"
    }}
  ]
}}

IMPORTANT: raw_score MUST NOT exceed max_score. Never invent criteria.
"""

TECHNICAL_SCORING_USER = """\
Tender reference: {tender_ref}
Enterprise name:  {enterprise_name}

RUBRIC:
{rubric_json}

---BEGIN OFFER TEXT---
{document_text}
---END OFFER TEXT---

Score the offer against EVERY criterion in the rubric and return the JSON array.
"""

# ── Phase 4 — Financial Evaluation ────────────────────────────────────────────

FINANCIAL_EXTRACTION_SYSTEM = """\
You are a financial data extraction specialist.
Your ONLY job is to extract numeric bid values from the provided document.
Do NOT perform calculations. Do NOT compare prices. Extract only.

OUTPUT FORMAT — respond with a single, valid JSON object. No markdown, no prose.
Schema:
{{
  "total_bid_price": number,
  "currency": "string (ISO 4217, e.g. USD, GBP, EUR, NGN)",
  "price_breakdown": {{
    "labour": number | null,
    "materials": number | null,
    "overhead": number | null,
    "profit_margin_pct": number | null,
    "other": number | null
  }},
  "bid_validity_days": integer | null,
  "extraction_confidence": "HIGH | MEDIUM | LOW",
  "notes": "string | null"
}}
"""

FINANCIAL_EXTRACTION_USER = """\
Tender reference: {tender_ref}
Enterprise name:  {enterprise_name}

---BEGIN FINANCIAL DOCUMENT TEXT---
{document_text}
---END FINANCIAL DOCUMENT TEXT---

Extract the financial data and return the JSON object.
"""

# ── Phase 6/7 — Notification Narrative ───────────────────────────────────────

AWARD_NOTIFICATION_SYSTEM = """\
You are a formal correspondence writer for a public procurement authority.
Write a professional, concise award notification letter body.
Do not invent facts — use only the data provided in the variables below.
Return plain text only (no markdown).
"""

AWARD_NOTIFICATION_USER = """\
Tender reference: {tender_ref}
Tender title:     {tender_title}
Awarded to:       {enterprise_name}
Combined score:   {combined_score} / 100
Technical score:  {technical_score}
Financial score:  {financial_score}
Award date:       {award_date}

Draft the body of the official award notification letter.
"""

REJECTION_NOTIFICATION_USER = """\
Tender reference:  {tender_ref}
Tender title:      {tender_title}
Enterprise name:   {enterprise_name}
Rejection reason:  {rejection_reason}
Combined score:    {combined_score} / 100

Draft the body of the official rejection notification letter.
"""
