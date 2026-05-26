"""Local events — weekly feed from temples.schmitzplex.com/events.json.

JSON shape:
  {
    "updated": "2026-05-26T16:45:30-06:00",
    "week_of": "2026-05-25",
    "events": [
      {
        "venue": "Cargo",
        "title": "Jaws",
        "days": ["Fri", "Sat"],
        "time": "8 PM",
        "type": "movie",
        "cost": "$4",          # optional
        "url": "https://..."   # optional
      }
    ],
    "skipped": [],
    "sources_failed": ["Venue - reason", ...]
  }
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections import defaultdict
from typing import Any

from briefing.config import EVENTS_URL
from briefing.sources import SectionResult

log = logging.getLogger(__name__)


def fetch() -> SectionResult:
    if not EVENTS_URL:
        return {"status": "stub"}

    data = _fetch_json()
    raw_events = data.get("events") or []
    log.info("events: %d event(s) from feed", len(raw_events))

    # Group events by venue, preserving order of first appearance
    by_venue: dict[str, list[dict]] = defaultdict(list)
    for e in raw_events:
        venue = (e.get("venue") or "Unknown").strip()
        by_venue[venue].append(_normalize(e))

    venues = [{"name": name, "events": evts} for name, evts in by_venue.items()]

    return {
        "status": "ready",
        "week_of": data.get("week_of", ""),
        "venues": venues,
        "total": len(raw_events),
        "sources_failed": data.get("sources_failed") or [],
    }


def _fetch_json() -> dict[str, Any]:
    req = urllib.request.Request(
        EVENTS_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; daily-briefing/1.0)",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _normalize(e: dict[str, Any]) -> dict[str, Any]:
    # days is a plain string — e.g. "Fri Sat", "6/4", "6/11-6/27"
    days = (e.get("days") or "").strip()

    return {
        "title": (e.get("title") or "").strip(),
        "days_str": days,
        "time": (e.get("time") or "").strip(),
        "type": (e.get("type") or "").strip(),
        "cost": (e.get("cost") or "").strip(),
        "url": (e.get("url") or "").strip(),
    }
