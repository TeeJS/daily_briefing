"""HTML rendering. Pure: data in, HTML out.

Renders both the per-day briefing and the archive index page that lists all
past briefings grouped by year and month.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from briefing.config import ARCHIVE_BASE_URL, TIMEZONE

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

# Link hygiene. Feed-supplied links (news RSS, the events JSON) reach the page
# verbatim — feedparser does not drop javascript:/data: links, and autoescaping
# doesn't neutralize a URL scheme — so every dynamic href goes through
# sanitize_url, which allows only http(s) and relative links.
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})
# RFC 3986 scheme: a letter, then letters / digits / + - . — then a colon.
_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")
# Browsers strip leading/trailing C0 controls and spaces and delete tabs and
# newlines anywhere before parsing, so "java\tscript:" is still javascript:.
_URL_STRIP = "".join(chr(c) for c in range(0x21))
_URL_DELETE_RE = re.compile(r"[\t\n\r]")


def sanitize_url(url: object) -> str:
    """Jinja filter: return `url` if it's http(s) or relative, else "#"."""
    if not url:
        return ""
    text = str(url)
    m = _SCHEME_RE.match(_URL_DELETE_RE.sub("", text.strip(_URL_STRIP)))
    if m and m.group(1).lower() not in _ALLOWED_URL_SCHEMES:
        log.warning("dropped link with disallowed scheme %r: %.100r", m.group(1), text)
        return "#"
    return text


# The one script the pages run (the theme toggle), inlined and allowed by hash.
# Every other inline script — including a javascript: URL that got past
# sanitize_url — is blocked. The hash covers the exact text between the tags,
# so the <script> element is built here rather than in the templates.
_THEME_JS = (TEMPLATE_DIR / "theme.js").read_text(encoding="utf-8")
_THEME_JS_HASH = base64.b64encode(hashlib.sha256(_THEME_JS.encode("utf-8")).digest()).decode()
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        f"script-src 'sha256-{_THEME_JS_HASH}'",
        "style-src 'unsafe-inline'",
        "img-src 'self'",
        "base-uri 'none'",
        "form-action 'none'",
    )
)

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["sanitize_url"] = sanitize_url
_env.globals["csp"] = CONTENT_SECURITY_POLICY
_env.globals["theme_script"] = Markup(f"<script>{_THEME_JS}</script>")


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
        meeting_prep=sections.get("meeting_prep", {"status": "stub"}),
        email=sections.get("email", {"status": "stub"}),
        claude_usage=sections.get("claude_usage", {"status": "stub"}),
        codex_usage=sections.get("codex_usage", {"status": "stub"}),
        etsy=sections.get("etsy", {"status": "stub"}),
        freshservice=sections.get("freshservice", {"status": "stub"}),
        news=sections.get("news", {"status": "stub"}),
        events=sections.get("events", {"status": "stub"}),
        outlook=sections.get("outlook", {"status": "stub"}),
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
