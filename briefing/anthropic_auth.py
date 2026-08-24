"""Anthropic OAuth token management for the undocumented /api/oauth/usage endpoint.

The flow is reverse-engineered from the trickv/hass-claude-usage HA integration
(see project_briefing_claude_usage memory). Tokens rotate on refresh; this module
persists the rotated tokens back to disk after each refresh.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import urllib.error
import urllib.request

from briefing.config import (
    ANTHROPIC_OAUTH_CLIENT_ID,
    ANTHROPIC_TOKEN_URL,
    ANTHROPIC_TOKENS_FILE,
)

log = logging.getLogger(__name__)

# Refresh ~60s before the access token expires.
REFRESH_LEAD_SECONDS = 60


def load_tokens() -> dict[str, Any]:
    if not ANTHROPIC_TOKENS_FILE.exists():
        raise FileNotFoundError(
            f"Anthropic tokens not found at {ANTHROPIC_TOKENS_FILE}. "
            "Run scripts/bootstrap_anthropic_oauth.py once to bootstrap."
        )
    return json.loads(ANTHROPIC_TOKENS_FILE.read_text())


def save_tokens(tokens: dict[str, Any]) -> None:
    ANTHROPIC_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ANTHROPIC_TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def get_access_token() -> str:
    """Return a valid access token, refreshing if necessary."""
    tokens = load_tokens()
    expires_at = tokens.get("expires_at", 0)
    if time.time() < expires_at - REFRESH_LEAD_SECONDS:
        return tokens["access_token"]

    refreshed = _refresh(tokens["refresh_token"])
    save_tokens(refreshed)
    return refreshed["access_token"]


def _refresh(refresh_token: str) -> dict[str, Any]:
    """Exchange a refresh token for a fresh access token."""
    # The console.anthropic.com/v1/oauth/token endpoint requires a JSON body;
    # form-urlencoded 400s. Matches trickv/hass-claude-usage, which POSTs
    # json=payload for both the code exchange and the refresh. (Verified 2026-08-24.)
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            # Anthropic's token endpoint 403s the default urllib User-Agent.
            "User-Agent": "daily_briefing/0.1",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        # Surface the response body — a bare HTTPError hides why (e.g. an
        # invalid_grant here means the refresh token is dead → re-bootstrap).
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"Anthropic token refresh failed: HTTP {exc.code} {exc.reason} — {detail}"
        ) from exc
    if "access_token" not in data:
        raise RuntimeError(f"Anthropic refresh response missing access_token: {data}")
    return {
        "access_token": data["access_token"],
        # The server usually returns a rotated refresh_token; fall back to the prior one.
        "refresh_token": data.get("refresh_token", refresh_token),
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
