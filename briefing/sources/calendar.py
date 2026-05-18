"""Today's events from the included Google calendars.

Returns events from the 6 calendars in `config.INCLUDED_CALENDARS`. All-day events
come first, then timed events sorted by start. Times are rendered in `config.TIMEZONE`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from googleapiclient.discovery import build

from briefing.config import INCLUDED_CALENDARS, TIMEZONE
from briefing.secrets import load_google_credentials
from briefing.sources import SectionResult


def fetch(today: date | None = None) -> SectionResult:
    today = today or datetime.now(TIMEZONE).date()
    start = datetime.combine(today, time.min, tzinfo=TIMEZONE)
    end = start + timedelta(days=1)

    creds = load_google_credentials()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    all_events: list[dict] = []
    for cal in INCLUDED_CALENDARS:
        try:
            resp = (
                service.events()
                .list(
                    calendarId=cal.id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )
        except Exception as exc:
            # One bad calendar shouldn't kill the whole section.
            all_events.append(
                {
                    "is_error": True,
                    "calendar": cal.label,
                    "error": str(exc),
                }
            )
            continue

        for item in resp.get("items", []):
            all_events.append(_normalize(item, cal.label))

    all_events.sort(key=_sort_key)

    return {"status": "ready", "events": all_events, "date": today}


def _normalize(item: dict, calendar_label: str) -> dict:
    start = item.get("start", {})
    end = item.get("end", {})

    # Google returns `htmlLink` on every event — the canonical web URL for opening
    # this event in Google Calendar.
    link = item.get("htmlLink", "")

    if "date" in start:
        # All-day event. `end.date` is exclusive in Google's API.
        return {
            "is_error": False,
            "is_all_day": True,
            "time_str": "all day",
            "summary": item.get("summary", "(no title)"),
            "location": item.get("location"),
            "calendar": calendar_label,
            "link": link,
        }

    start_dt = datetime.fromisoformat(start["dateTime"]).astimezone(TIMEZONE)
    end_dt = (
        datetime.fromisoformat(end["dateTime"]).astimezone(TIMEZONE) if "dateTime" in end else None
    )
    # Windows-safe formatting (no %-I on Windows; lstrip the leading zero ourselves).
    time_str = start_dt.strftime("%I:%M %p").lstrip("0").lower()
    if end_dt:
        end_str = end_dt.strftime("%I:%M %p").lstrip("0").lower()
        time_str = f"{time_str} – {end_str}"

    return {
        "is_error": False,
        "is_all_day": False,
        "time_str": time_str,
        "summary": item.get("summary", "(no title)"),
        "location": item.get("location"),
        "calendar": calendar_label,
        "link": link,
        "_start_dt": start_dt,
    }


def _sort_key(ev: dict) -> tuple:
    # Errors last, then all-day, then timed events by start.
    if ev.get("is_error"):
        return (2, "")
    if ev.get("is_all_day"):
        return (0, ev.get("summary", ""))
    return (1, ev.get("_start_dt") or datetime.min)
