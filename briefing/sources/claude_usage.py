"""Claude account usage from the undocumented OAuth endpoint.

See project_briefing_claude_usage memory for the API shape and rate-limit caveat
(don't poll faster than 300s — backoff is ~24h and locks /usage in Claude Code too).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime

from briefing.anthropic_auth import get_access_token
from briefing.config import ANTHROPIC_API_BETA_HEADER, ANTHROPIC_USAGE_URL, TIMEZONE
from briefing.sources import SectionResult

log = logging.getLogger(__name__)


def fetch() -> SectionResult:
    token = get_access_token()
    req = urllib.request.Request(
        ANTHROPIC_USAGE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": ANTHROPIC_API_BETA_HEADER,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = json.loads(resp.read())

    return {"status": "ready", **_parse(raw)}


def _parse(raw: dict) -> dict:
    """Convert the API response into a flat dict the template can render directly."""
    out: dict = {}

    five_hour = raw.get("five_hour") or {}
    out["session_pct"] = five_hour.get("utilization")
    out["session_resets"] = _fmt_reset(five_hour.get("resets_at"))

    seven_day = raw.get("seven_day") or {}
    out["week_pct"] = seven_day.get("utilization")
    out["week_resets"] = _fmt_reset(seven_day.get("resets_at"))

    seven_day_sonnet = raw.get("seven_day_sonnet") or {}
    out["week_sonnet_pct"] = seven_day_sonnet.get("utilization")
    out["week_sonnet_resets"] = _fmt_reset(seven_day_sonnet.get("resets_at"))

    extra = raw.get("extra_usage") or {}
    out["extra_enabled"] = bool(extra.get("is_enabled"))
    if out["extra_enabled"]:
        out["extra_pct"] = extra.get("utilization")
        used = extra.get("used_credits")
        limit = extra.get("monthly_limit")
        # The API returns credits in cents.
        out["extra_used_dollars"] = used / 100 if used is not None else None
        out["extra_limit_dollars"] = limit / 100 if limit is not None else None

    return out


def _fmt_reset(iso: str | None) -> str | None:
    """Render an ISO-8601 reset time as a short local-time string like 'today 11pm'."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TIMEZONE)
    except ValueError:
        return iso
    now = datetime.now(TIMEZONE)
    time_str = dt.strftime("%I:%M %p").lstrip("0").lower()
    if dt.date() == now.date():
        return f"today {time_str}"
    if (dt.date() - now.date()).days == 1:
        return f"tomorrow {time_str}"
    return dt.strftime("%a %b %d, ").replace(" 0", " ") + time_str
