"""Unread / starred emails — two Gmail queries, deduped, sorted chronologically.

No LLM triage, no classification. Pipeline:
  1. Q1: unread Primary-tab threads from the last 7 days.
  2. Q2: starred threads (still in inbox = not archived) from the last 30 days.
  3. Merge by thread_id (Q2 wins on metadata if a thread appears in both).
  4. Sort by the thread's latest internal date, oldest-first.
  5. Each item carries a `link` to the Gmail thread.

The previous design used a single narrow query + LLM triage into Action/FYI buckets.
That was abandoned 2026-05-17 because the local LLM (glm-4.7-flash) was unreliable
at the categorization. See project_briefing_email_filter memory for history.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build

from briefing.config import TIMEZONE
from briefing.secrets import load_google_credentials
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

# Two queries — each result deduped by thread id, then merged into a single list.
# `is:important` was dropped 2026-05-18 — Gmail's algorithmic importance flag was
# too noisy. User-applied stars are the only secondary signal we trust.
UNREAD_PRIMARY_QUERY = "in:inbox category:primary is:unread newer_than:7d"
STARRED_QUERY = "in:inbox is:starred newer_than:30d"

# Per-query cap (the result count after dedupe is typically much smaller).
MAX_PER_QUERY = 50

# Gmail's web URL for opening a thread. Works with the API-returned thread IDs.
GMAIL_THREAD_URL = "https://mail.google.com/mail/u/0/#inbox/{thread_id}"


def _thread_link(thread_id: str) -> str:
    return GMAIL_THREAD_URL.format(thread_id=thread_id)


def fetch() -> SectionResult:
    creds = load_google_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    threads_a = _search(service, UNREAD_PRIMARY_QUERY, max_results=MAX_PER_QUERY)
    threads_b = _search(service, STARRED_QUERY, max_results=MAX_PER_QUERY)
    log.info(
        "gmail: %d threads from unread-primary-7d, %d from starred-30d",
        len(threads_a),
        len(threads_b),
    )

    # Dedupe by thread id. Iterate B first so A overwrites with its (typically newer) data.
    by_id: dict[str, dict[str, Any]] = {}
    for t in threads_b + threads_a:
        by_id[t["id"]] = t

    # Sort by latest internal date, oldest first.
    items = sorted(by_id.values(), key=lambda t: t.get("date_ms") or 0)

    rendered = [_render_item(t) for t in items]
    log.info("gmail: %d total unique items (after dedupe)", len(rendered))
    # Key is `messages` not `items` — Jinja2 resolves `.items` on a dict to the
    # built-in dict.items() method, not a key lookup. See CLAUDE.md gotcha note.
    return {"status": "ready", "messages": rendered}


def _render_item(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "sender": _short_sender(t.get("sender") or "(unknown)"),
        "subject": t.get("subject") or "(no subject)",
        "date_str": _fmt_date(t.get("date_ms")),
        "link": _thread_link(t["id"]),
    }


def _short_sender(raw: str) -> str:
    """Trim a "Name <addr@host>" header to just the name (or the address if no name)."""
    if "<" in raw:
        # "Name <addr@host>" -> "Name"
        name, _, _rest = raw.partition("<")
        name = name.strip().strip('"')
        if name:
            return name
        # Bare "<addr@host>" -> "addr@host"
        addr = _rest.rstrip(">").strip()
        return addr or raw
    return raw.strip()


def _fmt_date(date_ms: int | None) -> str:
    """Format the thread's latest internalDate as a short relative-ish label."""
    if not date_ms:
        return ""
    try:
        dt = datetime.fromtimestamp(date_ms / 1000, tz=TIMEZONE)
    except (ValueError, OSError):
        return ""
    today = datetime.now(TIMEZONE).date()
    days_ago = (today - dt.date()).days
    if days_ago == 0:
        return "today " + dt.strftime("%I:%M %p").lstrip("0").lower()
    if days_ago == 1:
        return "yesterday"
    if days_ago < 7:
        return dt.strftime("%a")  # Mon, Tue, ...
    return dt.strftime("%b %d").replace(" 0", " ")  # May 13


def _search(service, query: str, max_results: int) -> list[dict[str, Any]]:
    """Return a list of {id, sender, subject, date_ms} for matching threads."""
    resp = (
        service.users()
        .threads()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    thread_summaries = resp.get("threads", [])

    out: list[dict[str, Any]] = []
    for t in thread_summaries:
        # Fetch the latest message in the thread for headers + internalDate.
        detail = (
            service.users()
            .threads()
            .get(
                userId="me",
                id=t["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )
        messages = detail.get("messages", [])
        if not messages:
            continue
        # Use the most recent message in the thread for sender/subject/date.
        latest = messages[-1]
        headers = {h["name"]: h["value"] for h in latest.get("payload", {}).get("headers", [])}
        date_ms_raw = latest.get("internalDate")
        try:
            date_ms = int(date_ms_raw) if date_ms_raw is not None else None
        except (TypeError, ValueError):
            date_ms = None
        out.append(
            {
                "id": t["id"],
                "sender": headers.get("From", "(unknown)"),
                "subject": headers.get("Subject", "(no subject)"),
                "date_ms": date_ms,
            }
        )
    return out
