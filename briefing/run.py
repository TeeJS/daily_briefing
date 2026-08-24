"""Daily briefing orchestrator. Entry point: `python -m briefing.run`.

Generates the daily briefing as an HTML file on disk. No email is sent — the
briefing has zero send/modify authority on the user's accounts. The archive
directory is served as the user's distribution channel (briefing.schmitzplex.com).
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from briefing.config import BRIEFINGS_DIR, LOGS_DIR, TIMEZONE
from briefing.render import render, render_index
from briefing.sources import (
    calendar as calendar_source,
    claude_usage as claude_usage_source,
    email as email_source,
    etsy as etsy_source,
    events as events_source,
    freshservice as freshservice_source,
    meeting_prep as meeting_prep_source,
    news as news_source,
    outlook as outlook_source,
)

# Robots.txt content — block all search engines from indexing the briefing.
# Briefings contain personal data (calendar entries, customer names, email
# senders/subjects). Authentication on the proxy is the real gate; this is
# defense-in-depth against well-behaved crawlers.
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


def _setup_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(TIMEZONE).date()
    log_path = LOGS_DIR / f"briefing-{today.strftime('%Y-%m')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _archive_path(today: date) -> Path:
    return BRIEFINGS_DIR / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}.html"


def _gather_sections(today: date, log: logging.Logger) -> dict[str, dict]:
    """Run each source's fetch, isolating failures so one bad section doesn't kill the briefing."""
    sources = {
        "calendar": lambda: calendar_source.fetch(today=today),
        "meeting_prep": lambda: meeting_prep_source.fetch(today=today),
        "email": email_source.fetch,
        "claude_usage": claude_usage_source.fetch,
        "etsy": etsy_source.fetch,
        "freshservice": freshservice_source.fetch,
        "news": news_source.fetch,
        "events": events_source.fetch,
        "outlook": outlook_source.fetch,
    }
    out: dict[str, dict] = {}
    for name, fetch in sources.items():
        try:
            out[name] = fetch()
            log.info("source %s -> status=%s", name, out[name].get("status"))
        except Exception as exc:
            log.exception("source %s failed", name)
            out[name] = {"status": "error", "error": str(exc)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the daily briefing as an HTML file on disk."
    )
    parser.add_argument(
        "--date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        help="Override the briefing date (YYYY-MM-DD). Defaults to today in TZ.",
    )
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("briefing")

    today = args.date or datetime.now(TIMEZONE).date()
    log.info("=== Briefing for %s ===", today.isoformat())

    sections = _gather_sections(today, log)
    # The renderer returns (subject, html). Subject is embedded in the HTML
    # <title> tag; nothing outside the renderer needs it anymore.
    _, html = render(sections, today)

    # Write the dated archive copy at /YYYY/MM/DD.html — the permanent address.
    archive = _archive_path(today)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(html, encoding="utf-8")
    log.info("wrote briefing to %s", archive)

    # Write today.html — the "latest" pointer at the root of the served site.
    # Same content, overwritten each morning.
    today_path = BRIEFINGS_DIR / "today.html"
    today_path.write_text(html, encoding="utf-8")
    log.info("wrote today pointer to %s", today_path)

    # Regenerate the archive index (year → month → days, newest first) so
    # the new briefing shows up in the listing.
    index_html = render_index(BRIEFINGS_DIR)
    index_path = BRIEFINGS_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    log.info("wrote archive index to %s", index_path)

    # Idempotent — same content every run. Cheaper to overwrite than to check.
    robots_path = BRIEFINGS_DIR / "robots.txt"
    robots_path.write_text(ROBOTS_TXT, encoding="utf-8")
    log.info("wrote robots.txt to %s", robots_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
