"""Important emails — narrow Gmail pre-filter + LLM triage.

Pipeline (per project_briefing_email_filter memory, revised 2026-05-17):
1. One Gmail search: unread Primary-tab threads from the last 7 days.
2. LLM triage into "Action today" and "FYI" buckets, with duplicate-notification collapsing.
3. Each item carries a `link` to the underlying Gmail thread so the briefing reader can act.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from googleapiclient.discovery import build

from briefing.config import PROMPTS_DIR, TIMEZONE
from briefing.llm import chat_json
from briefing.secrets import load_google_credentials
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

# Tight pre-filter: only the Primary tab, only unread, only the last 7 days. This is
# narrow on purpose — promotional/social/forums/updates are explicitly excluded by the
# `category:primary` qualifier. (An earlier design used a broader 24h candidate set with
# a starred override; the user wanted simplicity instead.)
CANDIDATE_QUERY = "in:inbox category:primary is:unread newer_than:7d"

MAX_CANDIDATES = 30
TRIAGE_MAX_ACTION = 7
TRIAGE_MAX_FYI = 7

# Gmail's web URL for opening a thread. Works with the API-returned thread IDs.
GMAIL_THREAD_URL = "https://mail.google.com/mail/u/0/#inbox/{thread_id}"


def _thread_link(thread_id: str) -> str:
    return GMAIL_THREAD_URL.format(thread_id=thread_id)


# Prompt for the LLM triage. The default below is embedded so the container always works,
# but if /app/prompts/email_triage.txt exists at runtime (volume-mounted from the host),
# the file's contents override the default. This lets the user iterate on the prompt
# without rebuilding the image: edit the file, re-run `docker run`, see new behavior.
TRIAGE_PROMPT_FILE = PROMPTS_DIR / "email_triage.txt"

DEFAULT_TRIAGE_SYSTEM = """Please act as a personal assistant triaging emails for a daily morning briefing.

Pick threads from the candidate list and place them in one of two buckets:

- "action_today": time-sensitive things occuring, due or expiring today or in the near future
- "fyi": informational but worth knowing.

Drop entirely:
- Receipts for completed purchases unless they reflect something the user needs to act on.  Upcoming/pending/failed purchases should be included.
- Saved-search digests from real estate, jobs, etc.
- Things that happened in the past (ie: invitations, events, lessons, reservations, etc.) that occured before today
- Weekly WPForms Summary
- Messages that are obviously SPAM

Return ONLY valid JSON in this exact shape:
{
  "action_today": [
    {"sender": "<display name or domain>", "summary": "<one short sentence>", "thread_ids": ["<id>", ...]}
  ],
  "fyi": [
    {"sender": "<display name or domain>", "summary": "<one short sentence>", "thread_ids": ["<id>", ...]}
  ]
}

The thread_ids array must include every candidate thread id you're representing. Always include at least one id per entry."""


def _load_triage_system() -> str:
    """Return the email-triage system prompt.

    Reads /app/prompts/email_triage.txt if present (so the user can edit the prompt
    on noraid without a container rebuild). Falls back to DEFAULT_TRIAGE_SYSTEM if
    the file is missing or unreadable.
    """
    if TRIAGE_PROMPT_FILE.exists():
        try:
            text = TRIAGE_PROMPT_FILE.read_text(encoding="utf-8")
            log.info("email triage prompt: using override from %s (%d chars)",
                     TRIAGE_PROMPT_FILE, len(text))
            return text
        except Exception as exc:
            log.warning("email triage prompt: failed to read %s (%s); using embedded default",
                        TRIAGE_PROMPT_FILE, exc)
    else:
        log.info("email triage prompt: %s not found; using embedded default",
                 TRIAGE_PROMPT_FILE)
    return DEFAULT_TRIAGE_SYSTEM


def fetch() -> SectionResult:
    creds = load_google_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    candidates = _gather_candidates(service)
    log.info("gmail: %d candidate threads (query=%r)", len(candidates), CANDIDATE_QUERY)
    # Trace-log each candidate so we can see exactly what the LLM was asked to triage.
    for c in candidates:
        log.info(
            "  candidate id=%s sender=%r subject=%r",
            c.get("id"),
            (c.get("sender") or "")[:80],
            (c.get("subject") or "")[:120],
        )

    if not candidates:
        return {"status": "ready", "action_today": [], "fyi": []}

    triage_input = _format_for_llm(candidates)
    triage_system = _load_triage_system()
    try:
        result = chat_json(triage_system, triage_input)
    except Exception as exc:
        log.exception("LLM triage failed; falling back to top-5-as-FYI")
        return {
            "status": "ready",
            "triage_failed": True,
            "triage_error": str(exc),
            "action_today": [],
            "fyi": [_simple_fallback(c) for c in candidates[:5]],
        }

    action = _attach_links((result.get("action_today") or [])[:TRIAGE_MAX_ACTION])
    fyi = _attach_links((result.get("fyi") or [])[:TRIAGE_MAX_FYI])

    return {"status": "ready", "action_today": action, "fyi": fyi}


def _gather_candidates(service) -> list[dict[str, Any]]:
    """Run the single Gmail search and cap at MAX_CANDIDATES."""
    return _search(service, CANDIDATE_QUERY, max_results=MAX_CANDIDATES)[:MAX_CANDIDATES]


def _attach_links(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add a `link` field to each item using its first thread_id."""
    for item in items:
        tids = item.get("thread_ids") or []
        item["link"] = _thread_link(tids[0]) if tids else "https://mail.google.com/mail/u/0/#inbox"
    return items


def _search(service, query: str, max_results: int) -> list[dict[str, Any]]:
    """Return a list of {id, sender, subject, snippet} for matching threads."""
    resp = (
        service.users()
        .threads()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )
    thread_summaries = resp.get("threads", [])

    out: list[dict[str, Any]] = []
    for t in thread_summaries:
        # The list endpoint returns thread metadata but not the per-message headers
        # we need; fetch the first message.
        detail = (
            service.users()
            .threads()
            .get(userId="me", id=t["id"], format="metadata", metadataHeaders=["From", "Subject"])
            .execute()
        )
        messages = detail.get("messages", [])
        if not messages:
            continue
        first = messages[0]
        headers = {h["name"]: h["value"] for h in first.get("payload", {}).get("headers", [])}
        out.append(
            {
                "id": t["id"],
                "sender": headers.get("From", "(unknown)"),
                "subject": headers.get("Subject", "(no subject)"),
                "snippet": first.get("snippet", ""),
            }
        )
    return out


def _format_for_llm(candidates: list[dict[str, Any]]) -> str:
    """Format the candidate list as compact JSON for the LLM prompt.

    Prepends today's date in the user's timezone so the LLM can reason about
    "today", "in the near future", and "events that occurred before today"
    without having to guess what the current date is.
    """
    now = datetime.now(TIMEZONE)
    today_str = now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    time_str = now.strftime("%I:%M %p %Z").lstrip("0").lower()

    compact = [
        {
            "id": c["id"],
            "sender": c["sender"],
            "subject": c["subject"],
            "snippet": c["snippet"][:300],
        }
        for c in candidates
    ]
    return (
        f"Today is {today_str}. Current time: {time_str}.\n\n"
        "Candidate threads to triage:\n\n" + json.dumps(compact, indent=2)
    )


def _simple_fallback(c: dict[str, Any]) -> dict[str, Any]:
    """Used if LLM triage fails entirely — just show raw sender/subject."""
    return {
        "sender": c["sender"],
        "summary": c["subject"],
        "thread_ids": [c["id"]],
        "link": _thread_link(c["id"]),
    }
