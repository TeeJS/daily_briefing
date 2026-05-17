"""One-time Google OAuth bootstrap.

Run this once from a machine with a browser. It opens a tab, completes the OAuth
flow, and writes the resulting tokens to GOOGLE_TOKENS_FILE. After this, the
briefing job refreshes silently from those tokens.

Prerequisite: GOOGLE_CLIENT_SECRET_FILE must already exist (downloaded from
Google Cloud Console — Desktop App OAuth credentials).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `briefing` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

from briefing.config import GOOGLE_CLIENT_SECRET_FILE, GOOGLE_SCOPES, GOOGLE_TOKENS_FILE
from briefing.secrets import save_google_credentials


def main() -> int:
    if not GOOGLE_CLIENT_SECRET_FILE.exists():
        print(
            f"Missing {GOOGLE_CLIENT_SECRET_FILE}.\n\n"
            "Download OAuth client credentials (Desktop App type) from "
            "https://console.cloud.google.com/apis/credentials and place the JSON "
            "file at the path above.",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CLIENT_SECRET_FILE), scopes=list(GOOGLE_SCOPES)
    )
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    save_google_credentials(creds)
    print(f"Wrote tokens to {GOOGLE_TOKENS_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
