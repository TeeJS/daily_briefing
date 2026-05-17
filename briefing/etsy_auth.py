"""Etsy OAuth token management. Refresh tokens rotate (90-day functional lifetime)."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any

from briefing.config import ETSY_CLIENT_ID, ETSY_TOKEN_URL, ETSY_TOKENS_FILE

log = logging.getLogger(__name__)

REFRESH_LEAD_SECONDS = 60


def load_tokens() -> dict[str, Any]:
    if not ETSY_TOKENS_FILE.exists():
        raise FileNotFoundError(
            f"Etsy tokens not found at {ETSY_TOKENS_FILE}. "
            "Run scripts/bootstrap_etsy_oauth.py once to bootstrap."
        )
    return json.loads(ETSY_TOKENS_FILE.read_text())


def save_tokens(tokens: dict[str, Any]) -> None:
    ETSY_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    ETSY_TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


def get_credentials() -> tuple[str, int]:
    """Return (access_token, shop_id), refreshing the access token if necessary."""
    tokens = load_tokens()
    expires_at = tokens.get("expires_at", 0)
    if time.time() >= expires_at - REFRESH_LEAD_SECONDS:
        tokens = _refresh(tokens)
        save_tokens(tokens)
    return tokens["access_token"], tokens["shop_id"]


def _refresh(tokens: dict[str, Any]) -> dict[str, Any]:
    if not ETSY_CLIENT_ID:
        raise RuntimeError("ETSY_CLIENT_ID env var must be set to refresh Etsy tokens.")

    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": ETSY_CLIENT_ID,
            "refresh_token": tokens["refresh_token"],
        }
    ).encode("ascii")
    req = urllib.request.Request(
        ETSY_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if "access_token" not in data:
        raise RuntimeError(f"Etsy refresh response missing access_token: {data}")
    return {
        **tokens,  # preserve shop_id, user_id
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", tokens["refresh_token"]),
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
