"""Daily briefing orchestrator. Entry point: `python -m briefing.run`."""

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
    parser = argparse.ArgumentParser(description="Generate and send the daily briefing.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and archive but do not send the email.",
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
    subject, html = render(sections, today)

    archive = _archive_path(today)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_text(html, encoding="utf-8")
    log.info("archived to %s", archive)

    if args.dry_run:
        log.info("--dry-run: skipping email send")
        return 0

    # Import lazily so --dry-run works without google credentials.
    from briefing.send import send_briefing

    message_id = send_briefing(subject, html)
    log.info("sent email; gmail message id=%s", message_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
