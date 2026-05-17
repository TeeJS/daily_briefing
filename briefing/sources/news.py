"""News digest — 7 subsections.

v1 implementation: pulls RSS feeds and takes top N items per subsection verbatim
(Google News already ranks well). LLM curation across subsections will come later.

Sections still as sub-stubs:
- Regional (Utah / Springville) — needs feed discovery
- NWPX — needs stock API + SEC EDGAR + press release scraping
- ERP/SAP/Muka/Titan — SAP RSS easy, Muka/Titan needs web search
- AI — Anthropic news feed discovery + tech news RSS
"""

from __future__ import annotations

import logging
from typing import Any

import feedparser

from briefing.sources import SectionResult

log = logging.getLogger(__name__)

MAX_ITEMS_PER_SECTION = 4

# Section definitions: (key, title, feed_url) — None feed means the section is still a sub-stub.
SECTIONS: list[tuple[str, str, str | None]] = [
    (
        "world",
        "World",
        "https://news.google.com/rss?topic=w&hl=en-US&gl=US&ceid=US:en",
    ),
    (
        "us",
        "United States",
        "https://news.google.com/rss?topic=n&hl=en-US&gl=US&ceid=US:en",
    ),
    (
        "regional",
        "Utah / Springville",
        None,  # feed discovery TBD — see project_briefing_news memory
    ),
    (
        "nwpx",
        "NWPX Infrastructure",
        None,  # multi-source: stock + SEC EDGAR + press releases
    ),
    (
        "erp",
        "ERP / Precast Software",
        None,  # SAP RSS + web search for Muka/Titan
    ),
    (
        "ai",
        "AI",
        None,  # Anthropic news + TechCrunch AI feed
    ),
    (
        "church",
        "LDS Church Newsroom",
        # Reverse-discovered: WordPress-style feed. Confirm in production; if 404, swap.
        "https://newsroom.churchofjesuschrist.org/rss",
    ),
]


def fetch() -> SectionResult:
    out_sections: list[dict[str, Any]] = []
    for key, title, feed_url in SECTIONS:
        if feed_url is None:
            out_sections.append({"key": key, "title": title, "status": "stub", "entries": []})
            continue
        try:
            items = _pull_feed(feed_url)
            out_sections.append({"key": key, "title": title, "status": "ready", "entries": items})
            log.info("news.%s: %d items from %s", key, len(items), feed_url)
        except Exception as exc:
            log.exception("news.%s failed", key)
            out_sections.append(
                {"key": key, "title": title, "status": "error", "error": str(exc), "entries": []}
            )

    return {"status": "ready", "sections": out_sections}


def _pull_feed(url: str) -> list[dict[str, Any]]:
    """Parse an RSS/Atom feed and return up to MAX_ITEMS_PER_SECTION normalized items."""
    parsed = feedparser.parse(url)
    items = []
    for entry in parsed.entries[:MAX_ITEMS_PER_SECTION]:
        items.append(
            {
                "title": getattr(entry, "title", "(no title)"),
                "link": getattr(entry, "link", "#"),
                "source": _extract_source(entry),
            }
        )
    return items


def _extract_source(entry: Any) -> str:
    """Get a short publisher label from a feed entry. Google News puts it in entry.source.title."""
    src = getattr(entry, "source", None)
    if src is not None:
        title = getattr(src, "title", None) or (src.get("title") if isinstance(src, dict) else None)
        if title:
            return title
    # Fall back to feed-level title if present.
    return ""
