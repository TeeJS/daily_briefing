"""Send the briefing via Gmail API users.messages.send."""

from __future__ import annotations

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from briefing.config import RECIPIENT_EMAIL, SENDER_EMAIL
from briefing.secrets import load_google_credentials


def send_briefing(subject: str, html_body: str) -> str:
    """Send the briefing email. Returns the Gmail message id."""
    creds = load_google_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    msg = MIMEMultipart("alternative")
    msg["To"] = RECIPIENT_EMAIL
    msg["From"] = SENDER_EMAIL
    msg["Subject"] = subject

    # Plain-text fallback. Very short — most clients render the HTML version anyway.
    msg.attach(
        MIMEText(
            "This briefing is HTML-only; view it in a client that renders HTML email.",
            "plain",
            "utf-8",
        )
    )
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return result["id"]
