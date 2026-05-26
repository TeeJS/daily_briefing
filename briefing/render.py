"""HTML rendering. Pure: data in, HTML out.

Renders both the per-day briefing and the archive index page that lists all
past briefings grouped by year and month.
"""

from __future__ import annotations

from collections import defaultdict
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
        freshservice=sections.get("freshservice", {"status": "stub"}),
        news=sections.get("news", {"status": "stub"}),
        events=sections.get("events", {"status": "stub"}),
    )
    return subject, html


def render_index(briefings_dir: Path) -> str:
    """Render the archive index page by walking the briefings directory.

    Walks `briefings_dir` for files matching the YYYY/MM/DD.html pattern
    (all digits) and groups them by year → month, sorted newest-first.
    Returns the rendered HTML.
    """
    # Walk briefings_dir/YYYY/MM/DD.html — strict digit-only pattern so we
    # don't pick up today.html, robots.txt, index.html, or stray files.
    grouped: dict[int, dict[int, list[tuple[int, str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    pattern = "[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9].html"
    for path in briefings_dir.glob(pattern):
        try:
            year = int(path.parent.parent.name)
            month = int(path.parent.name)
            day = int(path.stem)
            d = date(year, month, day)
        except (ValueError, TypeError):
            # Non-date-shaped filename — skip.
            continue
        weekday = d.strftime("%a")
        rel_url = f"/{year:04d}/{month:02d}/{day:02d}.html"
        grouped[year][month].append((day, weekday, rel_url))

    # Sort: years descending, months within year descending, days within month descending.
    archive: list[tuple[int, list[tuple[int, str, list[tuple[int, str, str]]]]]] = []
    entry_count = 0
    for year in sorted(grouped.keys(), reverse=True):
        months_in_year: list[tuple[int, str, list[tuple[int, str, str]]]] = []
        for month in sorted(grouped[year].keys(), reverse=True):
            days = sorted(grouped[year][month], key=lambda t: t[0], reverse=True)
            month_name = date(year, month, 1).strftime("%B")
            months_in_year.append((month, month_name, days))
            entry_count += len(days)
        archive.append((year, months_in_year))

    now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M %Z")
    template = _env.get_template("index.html.j2")
    return template.render(
        archive=archive,
        entry_count=entry_count,
        generated_at=now_str,
    )
