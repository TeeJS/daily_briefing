"""HTML rendering. Pure: data in, HTML out. Same artifact is emailed and archived."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from briefing.config import ARCHIVE_BASE_URL, TIMEZONE

TEMPLATE_DIR = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(sections: dict[str, dict], today: date) -> tuple[str, str]:
    """Render the briefing. Returns (subject, html_body)."""
    # Windows-safe formatting (no %-d on Windows; strip the leading zero ourselves).
    weekday = today.strftime("%a")
    date_short = today.strftime("%b %d").replace(" 0", " ")
    date_long = today.strftime("%A, %B %d, %Y").replace(" 0", " ")

    subject = f"Daily Briefing — {weekday}, {date_short}"

    now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M %Z")

    template = _env.get_template("briefing.html.j2")
    html = template.render(
        subject=subject,
        date_long=date_long,
        generated_at=now_str,
        archive_url=ARCHIVE_BASE_URL,
        calendar=sections.get("calendar", {"status": "stub"}),
        email=sections.get("email", {"status": "stub"}),
        claude_usage=sections.get("claude_usage", {"status": "stub"}),
        etsy=sections.get("etsy", {"status": "stub"}),
        news=sections.get("news", {"status": "stub"}),
    )
    return subject, html
