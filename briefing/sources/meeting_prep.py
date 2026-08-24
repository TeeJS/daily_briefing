"""Meeting prep — daily briefs produced by an external process.

Architecture
------------
Another job writes self-contained HTML meeting-prep files into
  /mnt/user/data/media/meetings/meeting_prep/YYYY/MM/DD/*.html
(that's M:\\media\\meetings\\meeting_prep on Windows — the same \\\\192.168.1.25\\data
share, under media/ rather than websites/).  That tree is mounted read-only into
the container at MEETING_PREP_DIR (default /app/meeting_prep).

The container can *read* those files but nginx can't *serve* them — they live
outside the served briefings volume.  So fetch() copies today's prep files into
BRIEFINGS_DIR/meeting_prep/YYYY/MM/DD/ (which nginx serves) and returns
root-relative links.  This mirrors the outlook bridge pattern.

If today's folder is missing or empty, returns status="stub" and the section
renders nothing (no header) — the user only wants links when prep exists.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import date
from pathlib import Path

from briefing.config import BRIEFINGS_DIR, MEETING_PREP_DIR
from briefing.sources import SectionResult

log = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def fetch(today: date) -> SectionResult:
    """Copy today's meeting-prep HTML into the served tree; return link list."""
    rel = f"{today.year:04d}/{today.month:02d}/{today.day:02d}"
    src_dir = MEETING_PREP_DIR / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    if not src_dir.is_dir():
        log.info("meeting_prep: no folder for today at %s — stub", src_dir)
        return {"status": "stub"}

    files = sorted(p for p in src_dir.glob("*.html") if p.is_file())
    if not files:
        log.info("meeting_prep: %s has no .html files — stub", src_dir)
        return {"status": "stub"}

    dest_dir = BRIEFINGS_DIR / "meeting_prep" / f"{today.year:04d}" / f"{today.month:02d}" / f"{today.day:02d}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Key is "entries" not "items": obj.items on a dict passed to Jinja resolves
    # to the dict method, not the value (documented gotcha in CLAUDE.md).
    entries: list[dict] = []
    for f in files:
        try:
            shutil.copy2(f, dest_dir / f.name)
        except Exception as exc:
            log.warning("meeting_prep: failed to copy %s: %s", f.name, exc)
            continue
        entries.append({"title": _title_for(f), "url": f"/meeting_prep/{rel}/{f.name}"})

    if not entries:
        return {"status": "stub"}
    log.info("meeting_prep: %d brief(s) for today", len(entries))
    return {"status": "ready", "entries": entries}


def _title_for(path: Path) -> str:
    """Prefer the HTML <title>; fall back to a cleaned filename."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8192]
        m = _TITLE_RE.search(head)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            if title:
                return title
    except Exception as exc:
        log.debug("meeting_prep: title parse failed for %s: %s", path.name, exc)
    # Fallback: strip a leading YYYY-MM-DD- prefix, then prettify the stem.
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", path.stem)
    return stem.replace("-", " ").replace("_", " ").strip() or path.name
