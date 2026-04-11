"""
app/llm/client.py

Provider-aware async LLM client.

Dispatches to the correct backend based on LLM_PROVIDER in settings:

  Provider  │ SDK                        │ Config used
  ──────────┼────────────────────────────┼─────────────────────────────────────
  gemini    │ google-genai (native)      │ GEMINI_API_KEY, GEMINI_MODEL
  openai    │ litellm (OpenAI protocol)  │ LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  ollama    │ litellm (OpenAI protocol)  │ LLM_BASE_URL = host:11434/v1

Golden Rule: This module ONLY makes HTTP calls and returns raw text strings.
All JSON parsing and Pydantic validation happen in orchestrator.py, never here.

Switching providers requires ONLY an environment variable change — no code edits.
"""

from __future__ import annotations

import re
from typing import Any

import litellm
from loguru import logger

from app.core.config import settings


# ── Gemini lazy singleton ─────────────────────────────────────────────────────
_gemini_client: Any = None


def _get_gemini_client() -> Any:
    """
    Returns a lazy-initialised google-genai Client.
    Fails fast with a clear message if the key is missing or SDK not installed.
    """
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "LLM_PROVIDER='gemini' but GEMINI_API_KEY is empty. "
            "Add it to your .env or docker-compose.yml environment block."
        )

    try:
        from google import genai  # pip install google-genai
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        logger.info(
            "Gemini client initialised → model={model}",
            model=settings.GEMINI_MODEL,
        )
        return _gemini_client
    except ImportError as exc:
        raise RuntimeError(
            "google-genai SDK not installed. "
            "Ensure 'google-genai>=1.5.0' is in requirements.txt and rebuild Docker image."
        ) from exc


def _strip_json_fences(text: str) -> str:
    """
    Gemini occasionally wraps JSON in markdown code-fences even when
    response_mime_type='application/json' is set.  Strip them out so that
    json.loads() in the orchestrator doesn't fail.

    Handles:
      ```json\\n{...}\\n```
      ```\\n{...}\\n```
      Plain JSON (returned unchanged)
    """
    text = text.strip()
    # Remove leading/trailing markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# =============================================================================
# Public API — single entry point used by the entire application
# =============================================================================


async def call_llm(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> str:
    """
    Send a system + user prompt to the configured LLM and return raw text.

    Args:
        system_prompt:   Role + task instructions for the model.
        user_message:    The document text / data payload.
        model:           Override the default model name (provider-specific).
        temperature:     Override temperature. Keep 0.0 for extraction tasks.
        max_tokens:      Hard cap on output tokens.
        response_format: {"type": "json_object"} for OpenAI/Ollama JSON mode
                         (Gemini uses response_mime_type="application/json" instead).

    Returns:
        Raw string content from the model, with markdown fences stripped.

    Raises:
        RuntimeError:  Gemini key missing or SDK not installed.
        Exception:     Network, quota, or auth errors (propagated to orchestrator).
    """
    provider = settings.LLM_PROVIDER
    _temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    _max_tok = max_tokens or settings.LLM_MAX_TOKENS

    _model_label = (
        settings.GEMINI_MODEL if provider == "gemini" else settings.LLM_MODEL
    )
    logger.debug(
        "LLM call → provider={p} model={m} temp={t} max_tok={mt}",
        p=provider,
        m=model or _model_label,
        t=_temp,
        mt=_max_tok,
    )

    if provider == "gemini":
        raw = await _call_gemini(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=_temp,
            max_tokens=_max_tok,
        )
    else:
        raw = await _call_litellm(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=_temp,
            max_tokens=_max_tok,
            response_format=response_format,
        )

    # Always strip markdown fences — cost is ~0, safety is high
    content = _strip_json_fences(raw)

    logger.debug("LLM call ← {chars} chars returned.", chars=len(content))
    return content


# =============================================================================
# Internal backends
# =============================================================================


async def _call_gemini(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None,
    temperature: float,
    max_tokens: int,
) -> str:
    """
    Call Google Gemini 2.0 Flash via the native google-genai async SDK.

    Key design decisions:
    - `system_instruction` keeps the role prompt separate from the document payload
    - `response_mime_type="application/json"` instructs Gemini to output valid JSON
      without markdown wrapping (though _strip_json_fences handles edge cases)
    - Temperature is always passed — 0.0 for extraction, 0.3 for narrative drafts
    """
    from google.genai import types  # type: ignore[import]

    client = _get_gemini_client()
    _model = model or settings.GEMINI_MODEL

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
    )

    try:
        response = await client.aio.models.generate_content(
            model=_model,
            contents=user_message,
            config=config,
        )
        return response.text or ""
    except Exception as exc:
        logger.error(
            "Gemini API call failed [model={m}]: {err}",
            m=_model,
            err=str(exc),
        )
        raise


async def _call_litellm(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict | None,
) -> str:
    """
    Call any OpenAI-compatible endpoint (Ollama, OpenAI, Anthropic) via litellm.
    Only used when LLM_PROVIDER is 'ollama' or 'openai'.
    """
    # litellm reads api_base / api_key from env or the module-level attributes
    # We set them here each call in case settings changed (e.g. tests)
    litellm.api_base = str(settings.LLM_BASE_URL)
    litellm.api_key = settings.LLM_API_KEY

    _model = model or settings.LLM_MODEL

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]

    kwargs: dict = {
        "model":       _model,
        "messages":    messages,
        "temperature": temperature,
        "max_tokens":  max_tokens,
        "timeout":     settings.LLM_REQUEST_TIMEOUT,
    }
    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = await litellm.acompletion(**kwargs)
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error(
            "litellm call failed [model={m}]: {err}",
            m=_model,
            err=str(exc),
        )
        raise
