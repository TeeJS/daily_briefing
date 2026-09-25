"""Link sanitizing and the Content-Security-Policy on rendered pages.

Both fail silently when they regress: a hostile feed link renders as a working
javascript: href, or a CSP hash mismatch quietly kills the theme toggle.
"""

from __future__ import annotations

import base64
import hashlib
import re
from datetime import date

import pytest

from briefing.render import render, render_index, sanitize_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/a?b=c&d=e",
        "http://192.168.1.25:8180/feed/x.xml",
        "HTTPS://EXAMPLE.COM",
        "/meeting_prep/2026/09/25/prep.html",
        "#",
        "relative/page.html",
    ],
)
def test_sanitize_url_keeps_http_and_relative(url):
    assert sanitize_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)",
        "\x01javascript:alert(1)",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
    ],
)
def test_sanitize_url_drops_other_schemes(url):
    assert sanitize_url(url) == "#"


@pytest.mark.parametrize("url", [None, ""])
def test_sanitize_url_empty(url):
    assert sanitize_url(url) == ""


def _hostile_sections() -> dict:
    return {
        "news": {
            "status": "ready",
            "sections": [
                {
                    "key": "world",
                    "title": "World",
                    "status": "ready",
                    "entries": [
                        {"title": "evil", "link": "javascript:alert(1)", "source": "x"},
                        {"title": "fine", "link": "https://example.com/story", "source": "y"},
                    ],
                }
            ],
        },
        "events": {
            "status": "ready",
            "week_of": "2026-09-21",
            "venues": [
                {
                    "name": "Venue",
                    "events": [
                        {
                            "title": "Show",
                            "days_str": "Fri",
                            "time": "8 PM",
                            "type": "movie",
                            "cost": "",
                            "url": "data:text/html,hi",
                        }
                    ],
                }
            ],
            "total": 1,
            "sources_failed": [],
        },
    }


def _hrefs(html: str) -> list[str]:
    return re.findall(r'href="([^"]*)"', html)


def test_briefing_drops_hostile_feed_links():
    _, html = render(_hostile_sections(), date(2026, 9, 25))
    hrefs = _hrefs(html)
    assert "https://example.com/story" in hrefs
    assert not any(h.lower().startswith(("javascript:", "data:")) for h in hrefs)


def _assert_csp_allows_only_page_script(html: str) -> None:
    csp = re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html)
    assert csp, "missing CSP meta tag"
    policy = csp.group(1).replace("&#39;", "'")
    assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]

    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) == 1, "only the hashed theme script may be inline"
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
    assert f"script-src 'sha256-{digest}'" in policy
    assert not re.search(r"\son[a-z]+=", html), "inline event handlers are blocked by the CSP"


def test_briefing_csp_matches_its_script():
    _, html = render(_hostile_sections(), date(2026, 9, 25))
    _assert_csp_allows_only_page_script(html)


def test_index_csp_matches_its_script(tmp_path):
    (tmp_path / "2026" / "09").mkdir(parents=True)
    (tmp_path / "2026" / "09" / "25.html").write_text("x")
    _assert_csp_allows_only_page_script(render_index(tmp_path))
