"""
prefetch_outlook.py — Fetch unread Outlook inbox messages via COM and write
outlook_cache.json to the briefings share so the Unraid briefing container
(which runs at 6:00 AM) has fresh data to read.

Run on Windows at 5:45 AM via Task Scheduler. Requires Outlook Desktop
(Classic / OUTLOOK.EXE) to be running. Does NOT use Microsoft Graph API —
only the local COM automation interface.

Requirements (in the daily_briefing venv):
    pip install pywin32

Task Scheduler setup (see HANDOFF.md for full walk-through):
    Program : D:\\Github\\daily_briefing\\.venv\\Scripts\\python.exe
    Arguments: D:\\Github\\daily_briefing\\scripts\\prefetch_outlook.py
    Start in : D:\\Github\\daily_briefing
    Schedule : Daily at 5:45 AM

Write path: \\\\192.168.1.25\\data\\websites\\briefing\\outlook\\outlook_cache.json
Container : /app/briefings/outlook/outlook_cache.json  (same share, different mount)
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# UNC path to the directory on the briefings share.  The Unraid container
# mounts the same share at /app/briefings, so the container reads the file at
# /app/briefings/outlook/outlook_cache.json.
CACHE_FILE = Path(r"\\192.168.1.25\data\websites\briefing\outlook\outlook_cache.json")

OUTLOOK_WEB_SEARCH = "https://outlook.office.com/mail/search/q={}"

# MAPI property tag for the RFC 2822 Internet Message-ID header
# (PR_INTERNET_MESSAGE_ID, PT_STRING8 = 0x001E).
INTERNET_MSGID_PROP = "http://schemas.microsoft.com/mapi/proptag/0x1035001E"

# Outlook item class constants
OL_MAIL_CLASS = 43  # olMail — ignore meeting requests, task requests, etc.

# Default window and cap (match the Gmail section's 7-day window)
DEFAULT_DAYS = 7
DEFAULT_MAX = 50


# ---------------------------------------------------------------------------
# Formatting helpers (same style as briefing/sources/email.py)
# ---------------------------------------------------------------------------

def _to_dt(pywin_dt) -> datetime:
    """Convert a pywintypes.datetime to a plain naive Python datetime (local time)."""
    return datetime(
        pywin_dt.year, pywin_dt.month, pywin_dt.day,
        pywin_dt.hour, pywin_dt.minute, pywin_dt.second,
    )


def _fmt_date(dt: datetime) -> str:
    """Format a received-time as a short label.

    today 9:05 am | yesterday | Mon | Jun 3
    Uses %-free strftime so it works on both Windows and Linux.
    """
    now = datetime.now()
    days_ago = (now.date() - dt.date()).days
    if days_ago == 0:
        # %I gives zero-padded hour; strip the leading zero manually (%-I is
        # Windows-unsafe — see CLAUDE.md gotcha note on Windows time formatting).
        return "today " + dt.strftime("%I:%M %p").lstrip("0").lower()
    if days_ago == 1:
        return "yesterday"
    if days_ago < 7:
        return dt.strftime("%a")  # Mon, Tue, …
    # %d is zero-padded; " 0" → " " removes the zero on single-digit days.
    return dt.strftime("%b %d").replace(" 0", " ")


# ---------------------------------------------------------------------------
# COM fetch
# ---------------------------------------------------------------------------

def fetch_unread(days: int, max_items: int) -> list[dict]:
    """Connect to the running Outlook.exe via COM and return unread inbox items."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        print(
            "ERROR: pywin32 is not installed in this Python environment.\n"
            "Run:  pip install pywin32\n"
            "then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    pythoncom.CoInitialize()
    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        ns = outlook.GetNamespace("MAPI")
        inbox = ns.GetDefaultFolder(6)  # 6 = olFolderInbox

        cutoff = datetime.now() - timedelta(days=days)

        # Sort newest-first before restricting so we can break early on old items.
        items_col = inbox.Items
        items_col.Sort("[ReceivedTime]", True)  # True = Descending

        # Restrict to unread Focused-inbox items only.
        # Exchange Online stamps every inbox item with MAPI property 0x12130003:
        #   0 = Focused,  1 = Other
        # Source: Petri / Office 365 for IT Pros — confirmed via MFCMAPI inspection.
        # Falls back to all-unread if the property is not present on this server.
        FOCUSED_UNREAD = (
            '@SQL="urn:schemas:httpmail:read" = 0 '
            'AND "http://schemas.microsoft.com/mapi/proptag/0x12130003" = 0'
        )
        try:
            restricted = items_col.Restrict(FOCUSED_UNREAD)
            _ = restricted.Count  # force evaluation; throws if property unsupported
            print(f"  Focused inbox filter applied ({restricted.Count} unread focused items).")
        except Exception as exc:
            print(f"  Focused filter unavailable ({exc}), falling back to all unread.")
            restricted = items_col.Restrict("[Unread] = True")

        results: list[dict] = []
        for msg in restricted:
            if len(results) >= max_items:
                break
            try:
                # Skip non-mail items (meeting requests, task requests, etc.)
                if getattr(msg, "Class", None) != OL_MAIL_CLASS:
                    continue

                received_dt = _to_dt(msg.ReceivedTime)
                if received_dt < cutoff:
                    # Items are newest-first; once we're past the window we're done.
                    break

                sender = str(getattr(msg, "SenderName", "") or "(unknown)").strip() or "(unknown)"
                subject = str(getattr(msg, "Subject", "") or "(no subject)").strip() or "(no subject)"

                # Build an Outlook.com search link from the RFC 2822 Message-ID.
                # This opens the message directly in the browser — no Graph API needed.
                link = "https://outlook.office.com/mail/inbox"  # safe fallback
                try:
                    msg_id = msg.PropertyAccessor.GetProperty(INTERNET_MSGID_PROP)
                    if msg_id:
                        link = OUTLOOK_WEB_SEARCH.format(urllib.parse.quote(msg_id))
                except Exception:
                    pass  # Leave link as the inbox fallback

                results.append({
                    "sender": sender,
                    "subject": subject,
                    "date_str": _fmt_date(received_dt),
                    "link": link,
                })

            except Exception as exc:
                print(f"  WARN: skipping a message ({type(exc).__name__}: {exc})", file=sys.stderr)
                continue

        return results

    finally:
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-fetch unread Outlook inbox for the daily briefing.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--days", type=int, default=DEFAULT_DAYS,
        help="How many days back to look for unread messages",
    )
    parser.add_argument(
        "--max", type=int, default=DEFAULT_MAX,
        help="Maximum number of messages to include",
    )
    args = parser.parse_args()

    print(f"Fetching unread Outlook messages - last {args.days} days, max {args.max} ...")

    try:
        messages = fetch_unread(days=args.days, max_items=args.max)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"  Found {len(messages)} unread message(s).")

    # Ensure the output directory exists (creates it on first run).
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "messages": messages,
    }
    CACHE_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Wrote cache -> {CACHE_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
