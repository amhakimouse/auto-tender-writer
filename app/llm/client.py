"""
app/llm/client.py

Provider-aware async LLM client.

Dispatches to the correct backend based on the model requested:
  1. Google Gemini (via native AsyncClient)
  2. Featherless/OpenAI (via LiteLLM)
  3. Ollama/Local (via LiteLLM)

Golden Rule: This module ONLY makes HTTP calls and returns raw text strings.
All JSON parsing and Pydantic validation happen in orchestrator.py, never here.
"""

from __future__ import annotations

import json
from typing import Any

import litellm
from loguru import logger

from app.core.config import settings

# ── Gemini client (lazy singleton) ────────────────────────────────────────────
_gemini_client: Any = None

def _get_gemini_client():
    """
    Returns a lazy-initialised google-genai AsyncClient.
    """
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is missing from environment.")

    try:
        from google import genai
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return _gemini_client
    except ImportError as exc:
        raise RuntimeError("google-genai SDK not installed.") from exc


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
    response_format: str | dict | None = None,
) -> str:
    """
    Send a system + user prompt to the appropriate LLM provider.
    
    Routing Logic:
      - If model is 'gemini-...' or None (and provider is gemini) -> Gemini SDK
      - If model is 'Qwen/...' or is settings.FEATHERLESS_MODEL -> Featherless API (LiteLLM)
      - Otherwise -> Default LiteLLM (Ollama/OpenAI) 
    """
    # 1. Determine target model and provider
    target_model = model or settings.GEMINI_MODEL # Default to Gemini for now
    
    _temp = temperature if temperature is not None else settings.LLM_TEMPERATURE
    _max_tok = max_tokens or settings.LLM_MAX_TOKENS

    logger.debug(
        "LLM call → model={m} temp={t}",
        m=target_model,
        t=_temp
    )

    # 2. Route to the correct backend
    if "gemini" in target_model.lower():
        return await _call_gemini(
            system_prompt=system_prompt,
            user_message=user_message,
            model=target_model,
            temperature=_temp,
            max_tokens=_max_tok,
        )
    elif target_model == settings.FEATHERLESS_MODEL or "qwen" in target_model.lower():
        return await _call_featherless(
            system_prompt=system_prompt,
            user_message=user_message,
            model=target_model,
            temperature=_temp,
            max_tokens=_max_tok,
            response_format=response_format
        )
    else:
        # Fallback to general LiteLLM (e.g. Ollama)
        return await _call_litellm_default(
            system_prompt=system_prompt,
            user_message=user_message,
            model=target_model,
            temperature=_temp,
            max_tokens=_max_tok,
            response_format=response_format,
        )


# =============================================================================
# Internal backends
# =============================================================================

async def _call_gemini(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str:
    from google.genai import types
    client = _get_gemini_client()
    
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_tokens,
        response_mime_type="application/json",
    )

    try:
        response = await client.aio.models.generate_content(
            model=model,
            contents=user_message,
            config=config,
        )
        return response.text or ""
    except Exception as exc:
        logger.error("Gemini API call failed: {err}", err=str(exc))
        raise

async def _call_featherless(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Any = None
) -> str:
    """
    Call the Featherless API using the provided keys.
    """
    if not settings.FEATHERLESS_API_KEY:
        logger.warning("FEATHERLESS_API_KEY is missing. Falling back to default LiteLLM config.")
        return await _call_litellm_default(system_prompt, user_message, model, temperature, max_tokens, response_format)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    try:
        response = await litellm.acompletion(
            model=f"openai/{model}", # Force openai prefix for custom endpoints
            messages=messages,
            api_base=str(settings.FEATHERLESS_BASE_URL),
            api_key=settings.FEATHERLESS_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            response_format=response_format if isinstance(response_format, dict) else None
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("Featherless/LiteLLM call failed: {err}", err=str(exc))
        raise

async def _call_litellm_default(
    system_prompt: str,
    user_message: str,
    model: str,
    temperature: float,
    max_tokens: int,
    response_format: Any = None
) -> str:
    """
    Fallback for local Ollama or default OpenAI config.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    
    try:
        response = await litellm.acompletion(
            model=model,
            messages=messages,
            api_base=str(settings.LLM_BASE_URL),
            api_key=settings.LLM_API_KEY,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.LLM_REQUEST_TIMEOUT,
            response_format=response_format if isinstance(response_format, dict) else None
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        logger.error("Default LiteLLM call failed: {err}", err=str(exc))
        raise
