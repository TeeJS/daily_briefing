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
from briefing.render import render
from briefing.sources import (
    calendar as calendar_source,
    claude_usage as claude_usage_source,
    email as email_source,
    etsy as etsy_source,
    news as news_source,
)


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
        "email": email_source.fetch,
        "claude_usage": claude_usage_source.fetch,
        "etsy": etsy_source.fetch,
        "news": news_source.fetch,
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

    archive = _archive_path(today)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(html, encoding="utf-8")
    log.info("wrote briefing to %s", archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
