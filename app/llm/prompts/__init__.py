"""
app/llm/prompts/__init__.py

Prompts package — makes the prompts/ directory a proper Python package.

Submodules:
  enterprise.py  → Prompts for Go/No-Go triage and CV formatting (Enterprise side)

The flat prompts.py in app/llm/ holds the Procurement Committee-side prompts
(Phase 2-7). Enterprise-side prompts live here in their own subpackage to
enforce separation of concerns.
"""
