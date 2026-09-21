"""Codex (ChatGPT) account usage from the ChatGPT rate-limit endpoint.

Mirrors the community "ai-usage" Bedrock Panel app's ``codexLiveLimits()``: GET
``chatgpt.com/backend-api/wham/usage`` with the Codex CLI login token. The data is
account-global (identical on every machine), so a synced copy of the token works.

Credential model (option B): a scheduled task on a machine where the Codex CLI
runs copies ``~/.codex/auth.json`` into ``SECRETS_DIR`` as ``codex_auth.json``
before the daily run. The Codex CLI keeps that token fresh; the briefing only
reads it (never refreshes or writes), so a stale token degrades to a friendly
error rather than corrupting anything.

The endpoint returns ``rate_limit.primary_window`` / ``secondary_window``; which
slot is the ~5h vs the weekly window is not fixed, so we classify by
``limit_window_seconds`` and label each row from that, rather than assuming.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime

from briefing.config import CODEX_AUTH_FILE, CODEX_USAGE_URL, TIMEZONE
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

_DAY_SECONDS = 86400


def fetch() -> SectionResult:
    if not CODEX_AUTH_FILE.exists():
        return {
            "status": "error",
            "error": (
                f"Codex auth not found at {CODEX_AUTH_FILE}. Sync ~/.codex/auth.json "
                "from a machine where the Codex CLI runs into the secrets dir as "
                "codex_auth.json."
            ),
        }
    try:
        auth = json.loads(CODEX_AUTH_FILE.read_text())
    except (ValueError, OSError) as exc:
        return {"status": "error", "error": f"Codex auth unreadable: {exc}"}

    tokens = auth.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        return {"status": "error", "error": "codex_auth.json has no tokens.access_token"}

    req = urllib.request.Request(
        CODEX_USAGE_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "ChatGPT-Account-Id": tokens.get("account_id") or "",
            "User-Agent": "codex-cli",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {
                "status": "error",
                "error": "Codex token stale (401) — sync a fresh ~/.codex/auth.json",
            }
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        return {
            "status": "error",
            "error": f"Codex usage HTTP {exc.code} {exc.reason} — {detail}",
        }

    return {"status": "ready", **_parse(raw)}


def _parse(raw: dict) -> dict:
    """Convert the API response into a flat dict the template can render directly."""
    # Always set every key (None when absent) so the template can test
    # `pct is not none` rather than tripping on a missing attribute.
    out: dict = {
        "plan": _clean_plan(raw.get("plan_type")),
        "session_pct": None, "session_resets": None, "session_label": None,
        "week_pct": None, "week_resets": None, "week_label": None,
    }

    rl = raw.get("rate_limit") or {}
    windows: list[tuple[int, float, object]] = []
    for w in (rl.get("primary_window"), rl.get("secondary_window")):
        if not w:
            continue
        pct = w.get("used_percent")
        secs = w.get("limit_window_seconds")
        if pct is None or secs is None:
            continue
        windows.append((int(secs), pct, w.get("reset_at")))
    windows.sort(key=lambda t: t[0])

    # A "short" window is anything under a day (~5h in practice); "weekly" is the
    # longest window a day or over. Either may be absent — the template omits
    # rows with no data.
    short = next((w for w in windows if w[0] < _DAY_SECONDS), None)
    weekly = next((w for w in reversed(windows) if w[0] >= _DAY_SECONDS), None)
    if short:
        out["session_pct"] = short[1]
        out["session_resets"] = _fmt_reset(short[2])
        out["session_label"] = _window_label(short[0])
    if weekly:
        out["week_pct"] = weekly[1]
        out["week_resets"] = _fmt_reset(weekly[2])
        out["week_label"] = _window_label(weekly[0])
    return out


def _window_label(seconds: int) -> str:
    """A row label derived from the window size: 18000 -> '5-hour', 604800 -> '7-day'."""
    if seconds < _DAY_SECONDS:
        hours = round(seconds / 3600)
        return f"{hours}-hour"
    days = round(seconds / _DAY_SECONDS)
    return f"{days}-day"


def _clean_plan(plan: str | None) -> str | None:
    """Prettify a raw plan_type like 'self_serve_business_prolite' -> 'Business Prolite'."""
    if not plan:
        return None
    text = str(plan)
    for prefix in ("self_serve_", "chatgpt_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.replace("_", " ").strip().title() or None


def _fmt_reset(val: object) -> str | None:
    """Render a reset time (epoch seconds or ISO-8601) as a short local string."""
    if val is None:
        return None
    try:
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val, tz=TIMEZONE)
        else:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00")).astimezone(TIMEZONE)
    except (ValueError, OverflowError, OSError):
        return str(val)
    now = datetime.now(TIMEZONE)
    time_str = dt.strftime("%I:%M %p").lstrip("0").lower()
    if dt.date() == now.date():
        return f"today {time_str}"
    if (dt.date() - now.date()).days == 1:
        return f"tomorrow {time_str}"
    return dt.strftime("%a %b %d, ").replace(" 0", " ") + time_str
