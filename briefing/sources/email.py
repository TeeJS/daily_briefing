"""Important emails — narrow Gmail pre-filter + LLM triage.

Pipeline (per project_briefing_email_filter memory, revised 2026-05-17):
1. One Gmail search: unread Primary-tab threads from the last 7 days.
2. LLM triage into "Action today" and "FYI" buckets, with duplicate-notification collapsing.
3. Each item carries a `link` to the underlying Gmail thread so the briefing reader can act.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from googleapiclient.discovery import build

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

TRIAGE_SYSTEM = """You are triaging emails for a daily morning briefing.

Pick the most important threads from the candidate list and place them in one of two buckets:

- "action_today": time-sensitive things due, happening, or expiring today (flight check-ins, hotel checkouts, codes the user still needs, things requiring a reply or decision today).
- "fyi": informational but worth knowing (claims processed, payments scheduled for the next few days, notifications the user would want to be aware of).

Drop entirely:
- Marketing, promotions, newsletters (even if they slipped through the pre-filter)
- Receipts for purchases unless they reflect something the user needs to act on
- Already-used or expired auth codes / security alerts the user has already addressed
- Saved-search digests from real estate, jobs, etc.
- Anonymous automated FYIs from systems the user doesn't actively monitor

Collapse near-duplicate notifications into a single line (e.g. "4 HealthEquity claims received" rather than four entries).

Each bucket has a maximum: 7 entries for action_today, 7 for fyi. Be selective — if nothing belongs in a bucket, leave it empty. Quality over quantity.

Return ONLY valid JSON in this exact shape:
{
  "action_today": [
    {"sender": "<display name or domain>", "summary": "<one short sentence>", "thread_ids": ["<id>", ...]}
  ],
  "fyi": [
    {"sender": "<display name or domain>", "summary": "<one short sentence>", "thread_ids": ["<id>", ...]}
  ]
}

The thread_ids array must include every candidate thread id you're representing (used for collapsing duplicates). Always include at least one id per entry."""


def fetch() -> SectionResult:
    creds = load_google_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    candidates = _gather_candidates(service)
    log.info("gmail: %d candidate threads", len(candidates))

    if not candidates:
        return {"status": "ready", "action_today": [], "fyi": []}

    triage_input = _format_for_llm(candidates)
    try:
        result = chat_json(TRIAGE_SYSTEM, triage_input)
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
    """Format the candidate list as compact JSON for the LLM prompt."""
    compact = [
        {
            "id": c["id"],
            "sender": c["sender"],
            "subject": c["subject"],
            "snippet": c["snippet"][:300],
        }
        for c in candidates
    ]
    return "Candidate threads to triage:\n\n" + json.dumps(compact, indent=2)


def _simple_fallback(c: dict[str, Any]) -> dict[str, Any]:
    """Used if LLM triage fails entirely — just show raw sender/subject."""
    return {
        "sender": c["sender"],
        "summary": c["subject"],
        "thread_ids": [c["id"]],
        "link": _thread_link(c["id"]),
    }
