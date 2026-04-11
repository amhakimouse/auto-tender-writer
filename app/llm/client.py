"""
app/llm/client.py

Thin async wrapper around litellm (which speaks the OpenAI protocol).
Points to the configured LLM_BASE_URL — works with local Ollama (Kimi K2.5),
OpenAI, Anthropic, or any compatible endpoint with zero code changes.

Golden Rule: This module's only job is to make HTTP calls and return raw text.
Validation against Pydantic schemas happens in orchestrator.py, NOT here.
"""

from __future__ import annotations

import litellm
from loguru import logger

from app.core.config import settings

# Configure litellm to use our endpoint globally.
litellm.api_base = str(settings.LLM_BASE_URL)
litellm.api_key = settings.LLM_API_KEY


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
    Send a prompt to the configured LLM and return the raw text content.

    Args:
        system_prompt:   Role and task instructions.
        user_message:    The actual payload (PDF text, rubric, etc.).
        model:           Override the default model from settings.
        temperature:     Override — keep at 0.0 for extraction tasks.
        max_tokens:      Override the default max token cap.
        response_format: Pass {"type": "json_object"} to force JSON mode.

    Returns:
        Raw string content from the model's first message choice.

    Raises:
        litellm.APIConnectionError: Network / endpoint unavailable.
        litellm.RateLimitError:     Quota exceeded.
        litellm.APIStatusError:     Non-2xx response from provider.
    """
    _model = model or settings.LLM_MODEL
    _temperature = temperature if temperature is not None else settings.LLM_TEMPERATURE
    _max_tokens = max_tokens or settings.LLM_MAX_TOKENS

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]

    kwargs: dict = {
        "model":       _model,
        "messages":    messages,
        "temperature": _temperature,
        "max_tokens":  _max_tokens,
        "timeout":     settings.LLM_REQUEST_TIMEOUT,
    }
    if response_format:
        kwargs["response_format"] = response_format

    logger.debug(
        "LLM call → model={model} temp={temp} max_tok={mt}",
        model=_model,
        temp=_temperature,
        mt=_max_tokens,
    )

    response = await litellm.acompletion(**kwargs)
    content: str = response.choices[0].message.content or ""
    logger.debug("LLM call ← {chars} chars returned.", chars=len(content))
    return content
