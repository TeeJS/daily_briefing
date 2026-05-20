"""Freshservice unassigned tickets — mirrors the Kanban board's UNASSIGNED column.

Uses the same query as fetchUnassignedTickets() in github.com/TeeJS/golang-kanban:
  (status:2 OR status:3 OR status:6 OR status:7)
  AND (group_id:33000158516 OR group_id:33000158515)
  AND agent_id:null
  AND created_at:>'<6 months ago>'

Group IDs:
  33000158516 = T (Titan Admins)
  33000158515 = S (SAP Basis Admins)
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from briefing.config import FRESHSERVICE_APIKEY, FRESHSERVICE_DOMAIN, TIMEZONE
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

# Group IDs / labels — must match golang-kanban exactly
TITAN_GROUP_ID = 33000158516   # T = Titan Admins
SAP_GROUP_ID = 33000158515     # S = SAP Basis Admins
GROUP_LABELS: dict[int, str] = {
    TITAN_GROUP_ID: "T",
    SAP_GROUP_ID: "S",
}

PRIORITY_LABELS: dict[int, str] = {
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Urgent",
}

STATUS_LABELS: dict[int, str] = {
    2: "Open",
    3: "Pending",
    6: "Waiting on 3rd Party",
    7: "Resolved",
}


def fetch() -> SectionResult:
    if not FRESHSERVICE_APIKEY or not FRESHSERVICE_DOMAIN:
        return {"status": "stub"}

    tickets = _fetch_unassigned_tickets()
    log.info("freshservice: %d unassigned tickets", len(tickets))

    normalized = [_normalize_ticket(t) for t in tickets]
    # Sort by priority descending (Urgent=4 first), then oldest created first
    normalized.sort(
        key=lambda t: (
            -(t["priority"] or 2),
            t["created_at"] or datetime.min.replace(tzinfo=TIMEZONE),
        )
    )

    return {
        "status": "ready",
        "tickets": normalized,
        "total": len(normalized),
    }


def _auth_header() -> str:
    """Basic auth with API key as username and 'X' as password (Freshservice convention)."""
    raw = f"{FRESHSERVICE_APIKEY}:X".encode()
    return f"Basic {base64.b64encode(raw).decode()}"


def _fetch_unassigned_tickets() -> list[dict[str, Any]]:
    """Query Freshservice filter API for unassigned tickets in the two admin groups."""
    # 6-month lookback, matching golang-kanban behaviour
    cutoff = (datetime.now(TIMEZONE) - timedelta(days=180)).strftime("%Y-%m-%d")

    query = (
        f"(status:2 OR status:3 OR status:6 OR status:7) AND "
        f"(group_id:{TITAN_GROUP_ID} OR group_id:{SAP_GROUP_ID}) AND "
        f"agent_id:null AND created_at:>'{cutoff}'"
    )
    # Freshservice expects the query wrapped in double-quotes, then URL-encoded
    params = urllib.parse.urlencode({"query": f'"{query}"', "per_page": 100})
    url = f"https://{FRESHSERVICE_DOMAIN}/api/v2/tickets/filter?{params}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": _auth_header(),
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    return body.get("tickets", [])


def _normalize_ticket(t: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Freshservice ticket into the shape the template uses."""
    ticket_id = t.get("id")
    group_id = t.get("group_id")

    created_raw = t.get("created_at")
    created_dt: datetime | None = None
    if created_raw:
        try:
            # Freshservice returns ISO 8601; Python 3.12 fromisoformat handles Z suffix
            created_dt = datetime.fromisoformat(
                created_raw.replace("Z", "+00:00")
            ).astimezone(TIMEZONE)
        except (ValueError, AttributeError):
            pass

    priority = t.get("priority") or 2

    return {
        "id": ticket_id,
        "url": f"https://{FRESHSERVICE_DOMAIN}/a/tickets/{ticket_id}",
        "subject": (t.get("subject") or "").strip(),
        "priority": priority,
        "priority_str": PRIORITY_LABELS.get(priority, "?"),
        "group_id": group_id,
        "group_label": GROUP_LABELS.get(group_id, "?"),
        "created_at": created_dt,
        "created_str": _fmt_date(created_dt),
        "status": t.get("status") or 2,
        "status_str": STATUS_LABELS.get(t.get("status") or 2, "?"),
    }


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    # Avoid %-d on Windows; strip leading zero with replace
    return dt.strftime("%b %d").replace(" 0", " ")
