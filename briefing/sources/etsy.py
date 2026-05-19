"""Etsy outstanding orders — unshipped paid receipts grouped by ship-by urgency."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Any

from briefing.config import ETSY_API_BASE, ETSY_API_KEY, ETSY_CLIENT_ID, ETSY_CLIENT_SECRET, TIMEZONE
from briefing.etsy_auth import get_credentials
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

DUE_SOON_DAYS = 3


def fetch() -> SectionResult:
    # Bail out immediately if Etsy isn't configured yet — normal while awaiting
    # API approval or before running the OAuth bootstrap script.
    from briefing.config import ETSY_TOKENS_FILE
    if not ETSY_CLIENT_ID or not ETSY_CLIENT_SECRET:
        return {"status": "stub"}
    if not ETSY_TOKENS_FILE.exists():
        return {"status": "stub"}

    access_token, shop_id = get_credentials()

    receipts = _fetch_unshipped_receipts(access_token, shop_id)
    log.info("etsy: %d unshipped paid receipts", len(receipts))

    now = datetime.now(TIMEZONE)
    soon_cutoff = now + timedelta(days=DUE_SOON_DAYS)

    overdue: list[dict] = []
    due_soon: list[dict] = []
    other: list[dict] = []

    for r in receipts:
        normalized = _normalize_receipt(r)
        ship_by = normalized.get("ship_by_dt")
        if ship_by is None:
            other.append(normalized)
        elif ship_by < now:
            normalized["days_overdue"] = (now - ship_by).days
            overdue.append(normalized)
        elif ship_by <= soon_cutoff:
            normalized["days_until"] = max(0, (ship_by - now).days)
            due_soon.append(normalized)
        else:
            other.append(normalized)

    overdue.sort(key=lambda r: r.get("ship_by_dt") or now)
    due_soon.sort(key=lambda r: r.get("ship_by_dt") or now)

    return {
        "status": "ready",
        "overdue": overdue,
        "due_soon": due_soon,
        "other_count": len(other),
        "other_total_dollars": round(sum(r.get("total_dollars") or 0 for r in other), 2),
    }


def _fetch_unshipped_receipts(access_token: str, shop_id: int) -> list[dict[str, Any]]:
    """GET /v3/application/shops/{shop_id}/receipts with was_shipped=false&was_paid=true."""
    if not ETSY_CLIENT_ID:
        raise RuntimeError("ETSY_CLIENT_ID env var must be set.")

    params = urllib.parse.urlencode(
        {"was_shipped": "false", "was_paid": "true", "limit": 100},
    )
    url = f"{ETSY_API_BASE}/shops/{shop_id}/receipts?{params}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "x-api-key": ETSY_API_KEY,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read())
    return body.get("results", [])


def _normalize_receipt(r: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Receipt into the shape the template uses."""
    transactions = r.get("transactions") or []

    # The receipt-level ship-by is the earliest expected_ship_date across its line items.
    ship_dates = [t.get("expected_ship_date") for t in transactions if t.get("expected_ship_date")]
    ship_by_dt = (
        datetime.fromtimestamp(min(ship_dates), tz=TIMEZONE) if ship_dates else None
    )

    total = _money_to_float(r.get("grandtotal"))
    item_count = sum(t.get("quantity", 0) for t in transactions)
    titles = [t.get("title", "") for t in transactions if t.get("title")]

    return {
        "receipt_id": r.get("receipt_id"),
        "buyer_name": (r.get("name") or "").split()[0] or "(buyer)",
        "item_count": item_count,
        "titles": titles[:3],
        "more_titles": max(0, len(titles) - 3),
        "ship_by_dt": ship_by_dt,
        "ship_by_str": _fmt_ship_by(ship_by_dt),
        "total_dollars": total,
        "currency": (r.get("grandtotal") or {}).get("currency_code", "USD"),
    }


def _money_to_float(m: dict | None) -> float | None:
    if not m:
        return None
    amount = m.get("amount")
    divisor = m.get("divisor") or 100
    if amount is None:
        return None
    return amount / divisor


def _fmt_ship_by(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.strftime("%a %b %d").replace(" 0", " ")
