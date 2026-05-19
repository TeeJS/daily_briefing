"""One-time Etsy OAuth bootstrap (PKCE).

Run this once from a machine with a browser. Prerequisites:
  1. Register an app at https://www.etsy.com/developers/your-apps and note:
     - the "API Keystring" (this is the client_id)
     - the redirect URI you registered (must match exactly; HTTPS only)
  2. Set these env vars before running:
     ETSY_CLIENT_ID=<your keystring>
     ETSY_REDIRECT_URI=<your registered redirect URI>

The script opens the Etsy authorize URL in your browser. After authorizing, your
browser redirects to your registered URI with `?code=<code>&state=<state>` in the
URL (the page may 404, that's fine — we just need the URL). Paste the full URL
back into this script.

The script then exchanges the code for tokens and looks up your shop_id, writing
everything to ETSY_TOKENS_FILE.
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

from briefing.config import (
    ETSY_API_BASE,
    ETSY_API_KEY,
    ETSY_AUTHORIZE_URL,
    ETSY_CLIENT_ID,
    ETSY_CLIENT_SECRET,
    ETSY_REDIRECT_URI,
    ETSY_SCOPES,
    ETSY_TOKEN_URL,
)
from briefing.etsy_auth import save_tokens


def _gen_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _exchange_code(code: str, verifier: str) -> dict:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": ETSY_CLIENT_ID,
            "redirect_uri": ETSY_REDIRECT_URI,
            "code": code,
            "code_verifier": verifier,
        }
    ).encode("ascii")
    req = urllib.request.Request(
        ETSY_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _lookup_shop_id(access_token: str, user_id: str) -> int:
    """Etsy's getShopByOwnerUserId — no extra scope required."""
    url = f"{ETSY_API_BASE}/users/{user_id}/shops"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": ETSY_API_KEY,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    # Endpoint returns a single Shop object (not a list).
    shop_id = data.get("shop_id")
    if not shop_id:
        raise RuntimeError(f"Could not extract shop_id from response: {data}")
    return int(shop_id)


def main() -> int:
    if not ETSY_CLIENT_ID or not ETSY_CLIENT_SECRET or not ETSY_REDIRECT_URI:
        print(
            "Set ETSY_CLIENT_ID, ETSY_CLIENT_SECRET, and ETSY_REDIRECT_URI env vars before running.\n"
            "All three are available on your app page at https://www.etsy.com/developers/your-apps.",
            file=sys.stderr,
        )
        return 1

    verifier, challenge = _gen_pkce()
    state = secrets.token_urlsafe(16)

    authorize_url = ETSY_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": ETSY_CLIENT_ID,
            "redirect_uri": ETSY_REDIRECT_URI,
            "scope": ETSY_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    print("Opening browser for Etsy authorization...")
    print(f"If it doesn't open, visit:\n  {authorize_url}\n")
    webbrowser.open(authorize_url)

    pasted = input("\nPaste the FULL URL from your browser after authorizing: ").strip()
    if not pasted:
        print("No URL entered.", file=sys.stderr)
        return 1

    parsed = urllib.parse.urlparse(pasted)
    query = urllib.parse.parse_qs(parsed.query)
    code = (query.get("code") or [""])[0]
    returned_state = (query.get("state") or [""])[0]

    if not code:
        print(f"No `code` parameter in pasted URL.", file=sys.stderr)
        return 1
    if returned_state != state:
        print("OAuth state mismatch — possible CSRF. Aborting.", file=sys.stderr)
        return 1

    token_data = _exchange_code(code, verifier)
    if "access_token" not in token_data:
        print(f"Token exchange failed: {token_data}", file=sys.stderr)
        return 1

    access_token = token_data["access_token"]
    # Etsy access tokens are formatted as "<user_id>.<random>".
    user_id = access_token.split(".", 1)[0]

    print(f"Looking up shop for user_id={user_id}...")
    shop_id = _lookup_shop_id(access_token, user_id)
    print(f"Found shop_id={shop_id}")

    save_tokens(
        {
            "access_token": access_token,
            "refresh_token": token_data.get("refresh_token", ""),
            "expires_at": time.time() + token_data.get("expires_in", 3600),
            "user_id": user_id,
            "shop_id": shop_id,
        }
    )
    print("Wrote Etsy tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
