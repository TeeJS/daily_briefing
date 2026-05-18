"""News digest — 7 subsections.

Each section is a NewsSection with one or more feed URLs. Multi-feed sections
get dedup'd by URL, optionally time-filtered, sorted newest-first, and capped.

Sections still as sub-stubs (no feeds yet):
- NWPX — needs stock API + SEC EDGAR + press release scraping
- ERP/SAP/Muka/Titan — SAP RSS easy, Muka/Titan needs web search
- AI — Anthropic news feed discovery + tech news RSS
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser

from briefing.sources import SectionResult

log = logging.getLogger(__name__)

DEFAULT_MAX_ITEMS = 4


@dataclass(frozen=True)
class NewsSection:
    """One subsection of the news digest.

    feeds             tuple of RSS/Atom URLs. Empty = the section is a stub.
    max_items         cap after merge+dedup+filter. Defaults to 4.
    max_age_days      if set, drop entries older than this many days (uses the
                      entry's published_parsed / updated_parsed). None = no filter.
    blocked_sources   case-insensitive substring matches against the entry's
                      Google-News-style <source> title (e.g. "GuruFocus",
                      "TradingKey"). Useful for filtering out stock-pump farms
                      and off-topic outlets that Google News surfaces because
                      the section keyword appears in arena/team names etc.
    sort_by_date      if True, merge all feeds and sort newest-first by
                      pubDate. If False (default), preserve the feed's own
                      order — useful for Google News feeds where the feed is
                      already in relevance order and our chronological re-sort
                      would push curated picks down in favor of high-frequency
                      low-quality auto-published items.
    """

    key: str
    title: str
    feeds: tuple[str, ...] = field(default_factory=tuple)
    max_items: int = DEFAULT_MAX_ITEMS
    max_age_days: int | None = None
    blocked_sources: tuple[str, ...] = field(default_factory=tuple)
    sort_by_date: bool = False


SECTIONS: tuple[NewsSection, ...] = (
    NewsSection(
        key="world",
        title="World",
        # Google News deprecated the lowercase short codes (?topic=w / ?topic=n) —
        # both silently fall back to a generic "Top stories" feed and returned
        # identical content. /rss/topics/<encoded-id> is the working form.
        # Verified 2026-05-17.
        feeds=(
            "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
        ),
    ),
    NewsSection(
        key="us",
        title="United States",
        feeds=(
            "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNRGxqTjNjd0VnSmxiaWdBUAE?hl=en-US&gl=US&ceid=US:en",
        ),
    ),
    NewsSection(
        key="nwpx",
        title="NWPX Infrastructure",
        # Two feeds: the investor site (real press releases — earnings,
        # acquisitions, material events) and the marketing site (employee
        # spotlights, awards, blog posts). The nwpx.com/newsroom/ page is a
        # landing page that links out to investor.nwpx.com; only the latter
        # carries actual news. Combined, deduped by URL.
        # Verified 2026-05-18: investor.nwpx.com uses an HTML landing page at
        # /press-releases — the RSS variant requires the ?pagetemplate=rss
        # query string (discovered via the site's own RSS landing page at
        # /index.php?s=95&rsspage=43).
        feeds=(
            "https://investor.nwpx.com/press-releases?pagetemplate=rss",
            "https://nwpx.com/feed/",
        ),
        # Light feed (monthly-ish cadence), so widen the window and uncap items —
        # whatever shows up in the last 15 days, show it all.
        max_items=30,
        max_age_days=15,
        # Multi-feed; interleave the two sources chronologically.
        sort_by_date=True,
    ),
    NewsSection(
        key="erp",
        title="SAP",
        # Google News search for SAP, bridged through html2rss on noraid. The
        # section was originally going to cover "ERP / Precast Software" (SAP +
        # Muka Development + Titan 3000), but Muka and Titan are silent across
        # all RSS-able channels — see project_briefing_news memory. Section
        # renamed to just SAP to reflect what's actually fed.
        feeds=("http://192.168.1.25:8180/feed/google-news-sap.xml",),
        max_items=10,
        # The Google News SAP search is polluted by two failure modes:
        #   1) Stock-pump farms (GuruFocus, TradingKey, Simply Wall St, etc.)
        #      that auto-publish multiple times a day, swamping the
        #      newest-first sort with low-quality "SAP rallied X% today" posts.
        #   2) Off-topic outlets that match "SAP" in arena/team names like
        #      "SAP Center" (Field Level Media's PWHL article showed up here).
        # Substring match against the entry's <source> title is case-insensitive.
        blocked_sources=(
            "GuruFocus",
            "TradingKey",
            "Simply Wall St",
            "Defense World",
            "Insider Monkey",
            "Field Level Media",
        ),
    ),
    # The template splits SECTIONS in half across two columns: indices 0-3 go
    # left, 4-6 go right. Placing `regional` at index 4 puts the heavy local
    # feed (10 items) at the top of the right column to balance the visual
    # weight of the long left side.
    NewsSection(
        key="regional",
        title="Utah / Local",
        # heraldextra.com and ksl.com don't expose working RSS feeds directly
        # (heraldextra's WordPress feed templates 404, ksl serves empty bodies).
        # Both are bridged via the self-hosted html2rss instance on noraid.
        feeds=(
            "http://192.168.1.25:8180/feed/heraldextra-com.xml",
            "http://192.168.1.25:8180/feed/utah-county-breaking-news-local-stories-ksl.xml",
        ),
        max_items=10,
        max_age_days=7,
        # Multi-feed; interleave the two sources chronologically.
        sort_by_date=True,
    ),
    NewsSection(key="ai", title="AI"),  # stub
    NewsSection(
        key="church",
        title="LDS Church Newsroom",
        # Reverse-discovered: WordPress-style feed. Confirm in production; if 404, swap.
        feeds=("https://newsroom.churchofjesuschrist.org/rss",),
    ),
)


def fetch() -> SectionResult:
    out_sections: list[dict[str, Any]] = []
    for section in SECTIONS:
        if not section.feeds:
            out_sections.append(
                {"key": section.key, "title": section.title, "status": "stub", "entries": []}
            )
            continue
        try:
            items = _pull_section(section)
            out_sections.append(
                {
                    "key": section.key,
                    "title": section.title,
                    "status": "ready",
                    "entries": items,
                }
            )
            log.info(
                "news.%s: %d items from %d feed(s)", section.key, len(items), len(section.feeds)
            )
        except Exception as exc:
            log.exception("news.%s failed", section.key)
            out_sections.append(
                {
                    "key": section.key,
                    "title": section.title,
                    "status": "error",
                    "error": str(exc),
                    "entries": [],
                }
            )

    return {"status": "ready", "sections": out_sections}


def _pull_section(section: NewsSection) -> list[dict[str, Any]]:
    """Pull from every feed in the section, dedupe by URL, time-filter, sort, cap.

    Sort is newest-first by entry pub date. Items without a parseable date sort
    to the end (they still appear unless filtered out by max_age_days).
    """
    cutoff: datetime | None = None
    if section.max_age_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=section.max_age_days)

    seen_links: set[str] = set()
    candidates: list[dict[str, Any]] = []
    blocked_lower = tuple(s.lower() for s in section.blocked_sources)

    for feed_url in section.feeds:
        parsed = feedparser.parse(feed_url)
        for entry in parsed.entries:
            link = getattr(entry, "link", "") or ""
            if link and link in seen_links:
                continue

            pub = _entry_dt(entry)
            if cutoff is not None and (pub is None or pub < cutoff):
                continue

            source = _extract_source(entry)
            if blocked_lower and any(b in source.lower() for b in blocked_lower):
                continue

            if link:
                seen_links.add(link)

            candidates.append(
                {
                    "title": (getattr(entry, "title", "(no title)") or "(no title)").strip(),
                    "link": link or "#",
                    "source": source,
                    "_dt": pub,
                }
            )

    if section.sort_by_date:
        # Newest first. Items without a date sort last via datetime.min fallback.
        candidates.sort(
            key=lambda x: x.get("_dt") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    # Strip the private sort key and cap.
    return [
        {k: v for k, v in item.items() if not k.startswith("_")}
        for item in candidates[: section.max_items]
    ]


def _entry_dt(entry: Any) -> datetime | None:
    """Best-effort parse of an entry's pub date as UTC."""
    for field_name in ("published_parsed", "updated_parsed"):
        val = getattr(entry, field_name, None)
        if val:
            try:
                return datetime(*val[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _extract_source(entry: Any) -> str:
    """Get a short publisher label from a feed entry. Google News puts it in entry.source.title."""
    src = getattr(entry, "source", None)
    if src is not None:
        title = getattr(src, "title", None) or (src.get("title") if isinstance(src, dict) else None)
        if title:
            return title
    return ""
