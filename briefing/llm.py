"""Thin client for the local LiteLLM proxy (OpenAI-compatible)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from openai import OpenAI

from briefing.config import LLM_API_KEY, LLM_BASE_URL

log = logging.getLogger(__name__)

# Model name as configured in LiteLLM. Override per-deployment via env.
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "local-default")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)
    return _client


def chat_json(
    system: str,
    user: str,
    *,
    model: str | None = None,
    temperature: float = 0.2,
) -> dict[str, Any]:
    """Ask the LLM for a JSON response. Returns the parsed dict.

    Uses chat completions with `response_format={"type": "json_object"}`. Most local
    backends served via LiteLLM honor this; if not, the model is instructed via the
    system prompt to return raw JSON and we'll parse from the message content.
    """
    client = _get_client()
    model = model or DEFAULT_MODEL

    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or "{}"
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        log.warning("LLM returned non-JSON content; raw=%r", content[:500])
        raise ValueError(f"LLM did not return valid JSON: {exc}") from exc
