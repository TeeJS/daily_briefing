"""Work Outlook inbox — unread messages pre-fetched by scripts/prefetch_outlook.py.

Architecture
------------
The briefing container runs on Unraid (Linux/Docker) and has no access to the
Windows COM interface that Outlook exposes.  Instead, a Windows Task Scheduler
job at 5:45 AM runs scripts/prefetch_outlook.py on the Windows machine.  That
script connects to the running Outlook.exe via COM, pulls unread inbox items,
and writes outlook_cache.json to the briefings SMB share.

This module reads that cache file.  If the file is missing or older than 24 h
(e.g. the Windows machine was off) it returns status="stub" so the briefing
still ships with a placeholder rather than an error block.

Cache file path inside the container: /app/briefings/outlook/outlook_cache.json
Windows UNC path (same share):        \\\\192.168.1.25\\data\\websites\\briefing\\outlook\\outlook_cache.json
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from briefing.config import BRIEFINGS_DIR
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

# Cache lives in a subdirectory of the briefings share so it doesn't pollute
# the root alongside the dated HTML archives.
CACHE_FILE: Path = BRIEFINGS_DIR / "outlook" / "outlook_cache.json"

# If the cache is older than this, treat it as stale and return stub.
MAX_CACHE_AGE = timedelta(hours=24)


def fetch() -> SectionResult:
    """Read the pre-fetched Outlook cache and return messages for the renderer."""
    if not CACHE_FILE.exists():
        log.info("outlook: cache file not found at %s — returning stub", CACHE_FILE)
        return {"status": "stub"}

    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("outlook: failed to read cache: %s", exc)
        return {"status": "error", "error": f"Cache read failed: {exc}"}

    # Staleness check — if the Windows machine missed its 5:45 AM window the
    # cache might be from the previous day.  Return stub rather than stale data.
    fetched_at_str = data.get("fetched_at", "")
    if fetched_at_str:
        try:
            fetched_at = datetime.fromisoformat(fetched_at_str)
            # Ensure both sides are timezone-aware before comparing.
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - fetched_at
            if age > MAX_CACHE_AGE:
                log.warning(
                    "outlook: cache is %.1f h old (max %s h) — returning stub",
                    age.total_seconds() / 3600,
                    MAX_CACHE_AGE.total_seconds() / 3600,
                )
                return {"status": "stub"}
        except ValueError:
            log.debug("outlook: could not parse fetched_at %r — skipping age check", fetched_at_str)

    messages = data.get("messages", [])
    log.info("outlook: %d unread message(s) from cache (age check passed)", len(messages))
    return {"status": "ready", "messages": messages}
