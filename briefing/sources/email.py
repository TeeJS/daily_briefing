"""Important emails — broad Gmail pre-filter + LLM triage.

Pipeline (per project_briefing_email_filter memory):
1. Two Gmail searches: broad candidate set + starred override.
2. Dedupe by thread id.
3. LLM triage into "Action today" and "FYI" buckets, with duplicate-notification collapsing.
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

# Broad pre-filter — see memory: `-category:updates` filters out the actual signal
# (flight check-ins, claims, payment reminders), so we don't add it here.
CANDIDATE_QUERY = "in:inbox newer_than:24h -category:promotions -category:social -category:forums"
STARRED_QUERY = "in:inbox newer_than:24h is:starred"

MAX_CANDIDATES = 30
TRIAGE_MAX_ACTION = 7
TRIAGE_MAX_FYI = 7

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
    log.info("gmail: %d candidate threads (after dedupe)", len(candidates))

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

    action = (result.get("action_today") or [])[:TRIAGE_MAX_ACTION]
    fyi = (result.get("fyi") or [])[:TRIAGE_MAX_FYI]

    return {"status": "ready", "action_today": action, "fyi": fyi}


def _gather_candidates(service) -> list[dict[str, Any]]:
    """Run both Gmail searches, dedupe by thread id, cap at MAX_CANDIDATES."""
    threads = _search(service, CANDIDATE_QUERY, max_results=MAX_CANDIDATES)
    starred = _search(service, STARRED_QUERY, max_results=10)

    seen: dict[str, dict] = {}
    for batch in (threads, starred):
        for t in batch:
            tid = t["id"]
            if tid not in seen:
                seen[tid] = t
    return list(seen.values())[:MAX_CANDIDATES]


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
    }
