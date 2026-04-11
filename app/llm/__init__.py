"""
app/llm/__init__.py

LLM Interaction Layer — the boundary between Python and the language model.

Strict rules (Golden Rules from the blueprint):
  1. The LLM NEVER writes to the database.
  2. Every LLM response MUST pass through a Pydantic model before
     any downstream Python code touches it.
  3. If the LLM output fails Pydantic validation, the exception is caught
     HERE — in the service layer — not in the router.
  4. Temperature is 0.0 for all extraction tasks (deterministic JSON).
     It may be raised only for narrative generation.

Modules:
  client.py        → Thin async wrapper around litellm / openai SDK.
  prompts.py       → Versioned prompt templates (no logic here).
  orchestrator.py  → Combines client + prompts + Pydantic validation.
"""
