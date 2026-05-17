"""Google OAuth credential load/persist. Refresh tokens rotate; the file is RW."""

from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from briefing.config import GOOGLE_SCOPES, GOOGLE_TOKENS_FILE


def load_google_credentials() -> Credentials:
    """Load Google OAuth credentials, refreshing the access token if needed.

    The bootstrap script (`scripts/bootstrap_google_oauth.py`) must have run once
    to create the tokens file.
    """
    if not GOOGLE_TOKENS_FILE.exists():
        raise FileNotFoundError(
            f"Google tokens not found at {GOOGLE_TOKENS_FILE}. "
            "Run scripts/bootstrap_google_oauth.py once to bootstrap."
        )

    creds = Credentials.from_authorized_user_file(
        str(GOOGLE_TOKENS_FILE), scopes=list(GOOGLE_SCOPES)
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_google_credentials(creds)

    if not creds.valid:
        raise RuntimeError(
            "Google credentials are not valid and could not be refreshed. "
            "Re-run scripts/bootstrap_google_oauth.py."
        )

    return creds


def save_google_credentials(creds: Credentials) -> None:
    """Persist Google credentials to disk. Refresh tokens may have rotated."""
    GOOGLE_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOOGLE_TOKENS_FILE.write_text(creds.to_json())
