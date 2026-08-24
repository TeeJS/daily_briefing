"""One-time Anthropic OAuth bootstrap (PKCE against claude.ai).

Run this once from a machine with a browser. It:
  1. Builds the authorize URL with a fresh PKCE verifier + state.
  2. Opens the URL in your default browser.
  3. After you authorize, the redirect lands at console.anthropic.com showing an
     authorization code (paste it back here).
  4. Exchanges the code for tokens and writes them to ANTHROPIC_TOKENS_FILE.

After this, the briefing job refreshes the access token silently each run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

# Make `briefing` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from briefing.anthropic_auth import save_tokens
from briefing.config import (
    ANTHROPIC_AUTHORIZE_URL,
    ANTHROPIC_OAUTH_CLIENT_ID,
    ANTHROPIC_OAUTH_SCOPES,
    ANTHROPIC_REDIRECT_URI,
    ANTHROPIC_TOKEN_URL,
)


def _gen_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _exchange_code(code: str, state_in_code: str, verifier: str) -> dict:
    # This endpoint requires a JSON body — form-urlencoded 400s. Matches the
    # trickv/hass-claude-usage config_flow, which POSTs json=payload.
    body = json.dumps(
        {
            "grant_type": "authorization_code",
            "code": code,
            "state": state_in_code,
            "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
            "redirect_uri": ANTHROPIC_REDIRECT_URI,
            "code_verifier": verifier,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_TOKEN_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            # Anthropic's token endpoint 403s the default urllib User-Agent.
            # Mimic the HA integration's client. (Verified 2026-05-17.)
            "User-Agent": "daily_briefing-bootstrap/0.1",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # Read and surface the response body so we can debug the underlying reason.
        body_text = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Anthropic token exchange failed: HTTP {e.code} {e.reason}\n"
            f"Response body: {body_text}"
        ) from e


def main() -> int:
    verifier, challenge = _gen_pkce()
    state = secrets.token_urlsafe(32)

    authorize_url = ANTHROPIC_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "code": "true",
            "client_id": ANTHROPIC_OAUTH_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": ANTHROPIC_REDIRECT_URI,
            "scope": ANTHROPIC_OAUTH_SCOPES,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )

    print("Opening browser for Anthropic OAuth authorization...")
    print(f"If it doesn't open, visit:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    # The callback URL includes the code on the visible page; the user pastes it here.
    # Format from the callback is typically: <code>#<state>
    raw = input("\nPaste the authorization code shown after authorizing: ").strip()
    if not raw:
        print("No code entered.", file=sys.stderr)
        return 1

    parts = raw.split("#", 1)
    code = parts[0]
    returned_state = parts[1] if len(parts) > 1 else ""
    if returned_state and returned_state != state:
        print("OAuth state mismatch — possible CSRF. Aborting.", file=sys.stderr)
        return 1

    token_data = _exchange_code(code, returned_state, verifier)
    if "access_token" not in token_data:
        print(f"Token exchange failed: {token_data}", file=sys.stderr)
        return 1

    save_tokens(
        {
            "access_token": token_data["access_token"],
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": time.time() + token_data.get("expires_in", 3600),
        }
    )
    print("Wrote anthropic tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
