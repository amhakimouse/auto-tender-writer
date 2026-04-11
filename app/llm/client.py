"""
app/llm/client.py

Provider-aware async LLM client.

Dispatches to the correct backend based on LLM_PROVIDER in settings:

  Provider  │ SDK                        │ Config used
  ──────────┼────────────────────────────┼───────────────────────────────────
  gemini    │ google-genai (native)      │ GEMINI_API_KEY, GEMINI_MODEL
  openai    │ litellm (OpenAI protocol)  │ LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  ollama    │ litellm (OpenAI protocol)  │ LLM_BASE_URL = localhost:11434/v1

Golden Rule: This module ONLY makes HTTP calls and returns raw text strings.
All JSON parsing and Pydantic validation happen in orchestrator.py, never here.

Switching providers requires ONLY an environment variable change — no code edits.
"""

from __future__ import annotations

import json
from typing import Any

import litellm
from loguru import logger

from app.core.config import settings

# ── litellm global config (used for ollama + openai providers) ────────────────
litellm.api_base = str(settings.LLM_BASE_URL)
litellm.api_key = settings.LLM_API_KEY


# ── Gemini client (lazy singleton) ────────────────────────────────────────────
_gemini_client: Any = None


def _get_gemini_client():
    """
    Returns a lazy-initialised google-genai AsyncClient.
    Fails fast with a clear error if the SDK isn't installed or the key is missing.
    """
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    if not settings.GEMINI_API_KEY:
        raise RuntimeError(
            "LLM_PROVIDER is set to 'gemini' but GEMINI_API_KEY is empty. "
            "Add GEMINI_API_KEY to your .env or docker-compose environment."
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
            "google-genai SDK not installed. Add 'google-genai' to requirements.txt "
            "and rebuild the Docker image."
        ) from exc


# =============================================================================
# Public API
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
        system_prompt:   Role and task instructions.
        user_message:    The document text / payload.
        model:           Override the default model (provider-specific name).
        temperature:     Override temperature (0.0 = deterministic for extraction).
        max_tokens:      Hard cap on output tokens.
        response_format: {"type": "json_object"} to request JSON output mode
                         (ignored for Gemini — we use system-prompt enforcement instead).

    Returns:
        Raw string content from the model.

    Raises:
        RuntimeError: Gemini API key missing or SDK not installed.
        litellm.*:    Network / quota / auth errors for OpenAI/Ollama providers.
    """
    provider = settings.LLM_PROVIDER
    _temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    _max_tok = max_tokens or settings.LLM_MAX_TOKENS

    logger.debug(
        "LLM call → provider={p} model={m} temp={t} max_tok={mt}",
        p=provider,
        m=model or ("gemini:" + settings.GEMINI_MODEL if provider == "gemini" else settings.LLM_MODEL),
        t=_temp,
        mt=_max_tok,
    )

    if provider == "gemini":
        content = await _call_gemini(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=_temp,
            max_tokens=_max_tok,
        )
    else:
        content = await _call_litellm(
            system_prompt=system_prompt,
            user_message=user_message,
            model=model,
            temperature=_temp,
            max_tokens=_max_tok,
            response_format=response_format,
        )

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
    Call Google Gemini using the native google-genai async SDK.

    Gemini does not have separate system/user roles in the same way —
    we prepend the system prompt into the user content block, which is
    the pattern recommended by the google-genai docs for chat completions.

    JSON enforcement is achieved via the system prompt instruction
    ("Respond ONLY with valid JSON") rather than a response_format flag.
    """
    from google.genai import types  # type: ignore[import]

    client = _get_gemini_client()
    _model = model or settings.GEMINI_MODEL

    # Combine system + user into a single turn (Gemini 2.0 Flash supports
    # system instructions natively via system_instruction parameter)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_tokens,
        # Ask Gemini to return JSON directly — available on gemini-2.0+
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
        logger.error("Gemini API call failed: {err}", err=str(exc))
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
    Call any OpenAI-compatible endpoint (Ollama, OpenAI, Anthropic via litellm).
    """
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
        logger.error("litellm call failed: {err}", err=str(exc))
        raise
