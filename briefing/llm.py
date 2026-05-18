"""Thin client for the local LiteLLM proxy (OpenAI-compatible)."""

from __future__ import annotations

import json
import logging
import os
import re
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
        return json.loads(_strip_code_fences(content))
    except json.JSONDecodeError as exc:
        log.warning("LLM returned non-JSON content; raw=%r", content[:500])
        raise ValueError(f"LLM did not return valid JSON: {exc}") from exc


# Matches an opening ``` or ```json (with optional trailing space) and the closing ```.
# llama.cpp (and other local backends) commonly wrap JSON in a markdown code fence even
# when `response_format={"type":"json_object"}` is set, so we strip the fence defensively.
_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$",
    re.DOTALL | re.IGNORECASE,
)


def _strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown ```json ... ``` fence if present.

    No-op when the content is already raw JSON. Defensive only — we still ask the
    backend for json_object, and the JSON-parse path raises if the result is still
    not parseable after stripping.
    """
    m = _CODE_FENCE_RE.match(text)
    return m.group(1) if m else text
