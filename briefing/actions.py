"""'Mark complete' service for meeting-prep briefs.

A tiny HTTP service reached at briefing.schmitzplex.com/api/ (NPM Plus forwards
that path here, behind the same Authelia login as the rest of the site). It is the
only writer of ``done.json`` and the only holder of the kanban API key; the
brief's page script (``templates/done.js``, served from here) just calls it.

Routes
  GET    /api/done.js        the page script
  GET    /api/done           {"items": {<id>: <entry>, ...}}
  POST   /api/done           mark one item complete   {id, text, owner, brief}
  DELETE /api/done/<id>      undo

``done.json`` lives in STATE_DIR (the meeting_prep share, so the meeting-prep
skill reads it next to the analysis files). Shape:

  {"version": 1, "items": {"<id>": {
      "id", "text", "owner", "brief", "completed_at" (UTC ISO-8601),
      "kanban": null | {"card": N, "state": "moved"|"already_done"|..., "prev_status": "todo"}}}}

Item ids are ``card-<N>`` when the row has a kanban card, otherwise a slug the
skill builds. Completing a ``card-<N>`` item also moves that card to Done
(kanban ``PATCH /api/cards/<N>``); the done list is recorded even if kanban
can't be reached, and the response says so. Undo moves the card back only if
this service moved it.

Stdlib only on purpose: the container needs no pip install.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import signal
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import error, request
from urllib.parse import unquote, urlsplit

log = logging.getLogger("briefing.actions")

JS_PATH = Path(__file__).parent / "templates" / "done.js"
DONE_STATUS = "done"  # kanban status slug for the Done column
GUARD_HEADER = "X-Briefing-Action"
MAX_BODY = 8192

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
CARD_RE = re.compile(r"^card-(\d{1,9})$")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


class KanbanError(Exception):
    """A kanban call failed; the message is safe to show (never contains the key)."""


class Kanban:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = request.Request(  # noqa: S310 - URL comes from operator config
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                raw = resp.read()
        except error.HTTPError as exc:
            detail = ""
            try:
                parsed = json.loads(exc.read() or b"{}")
                detail = str(parsed.get("error", "")) if isinstance(parsed, dict) else ""
            except (ValueError, OSError):
                pass
            suffix = f": {detail}" if detail else ""
            raise KanbanError(f"kanban answered {exc.code}{suffix}") from exc
        except (error.URLError, TimeoutError, OSError) as exc:
            raise KanbanError(f"kanban unreachable ({getattr(exc, 'reason', exc)})") from exc
        try:
            return json.loads(raw) if raw else None
        except ValueError as exc:
            raise KanbanError("kanban sent a response that is not JSON") from exc

    def card_status(self, card_id: int) -> str | None:
        """Current status slug of a card, or None if it isn't on the board.

        The kanban API has no single-card GET, so this reads the list. Its Go
        struct has no json tags, so keys arrive capitalised ("ID", "Status").
        """
        cards = self._call("GET", "/api/cards")
        if not isinstance(cards, list):
            raise KanbanError("kanban card list was not a list")
        for card in cards:
            if not isinstance(card, dict):
                continue
            lowered = {str(k).lower(): v for k, v in card.items()}
            if lowered.get("id") == card_id:
                status = lowered.get("status")
                return str(status) if status else None
        return None

    def set_status(self, card_id: int, status: str) -> None:
        self._call("PATCH", f"/api/cards/{card_id}", {"status": status})


class DoneStore:
    """done.json with atomic writes and a one-deep .bak of the previous version."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {"version": 1, "items": {}}
        # A corrupt file raises here on purpose: never overwrite what we can't read.
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
            raise ValueError(f"{self.path} is not a done list")
        return data

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:  # copy, not move: done.json must never be absent mid-save
                shutil.copyfile(self.path, self.path.with_name(self.path.name + ".bak"))
            except OSError:
                log.warning("could not write %s.bak", self.path.name)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)


def _clean(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", _CTRL_RE.sub(" ", value)).strip()[:limit]


class Service:
    """The done list plus kanban sync. Handlers call this; tests call it directly."""

    def __init__(self, state_dir: Path, kanban: Kanban) -> None:
        self.store = DoneStore(state_dir / "done.json")
        self.kanban = kanban
        self._lock = threading.Lock()

    def list_items(self) -> dict:
        with self._lock:
            return self.store.load()["items"]

    def complete(
        self, item_id: str, text: str, owner: str, brief: str
    ) -> tuple[dict, dict | None, bool]:
        """Returns (entry, kanban_result, already_done)."""
        with self._lock:
            data = self.store.load()
            existing = data["items"].get(item_id)
            if existing is not None:
                return existing, None, True
            card = CARD_RE.match(item_id)
            kanban_result = self._move_card(int(card.group(1))) if card else None
            entry = {
                "id": item_id,
                "text": text,
                "owner": owner,
                "brief": brief,
                "completed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "kanban": kanban_result,
            }
            data["items"][item_id] = entry
            self.store.save(data)
            log.info("completed %s (%s)", item_id, (kanban_result or {}).get("state", "no card"))
            return entry, kanban_result, False

    def undo(self, item_id: str) -> tuple[dict | None, dict | None]:
        """Returns (removed_entry or None, kanban_result or None)."""
        with self._lock:
            data = self.store.load()
            entry = data["items"].pop(item_id, None)
            if entry is None:
                return None, None
            kanban_result = self._restore_card(entry.get("kanban"))
            self.store.save(data)
            log.info("undid %s", item_id)
            return entry, kanban_result

    def _move_card(self, card_id: int) -> dict:
        if not self.kanban.configured:
            return {"card": card_id, "state": "unconfigured"}
        try:
            prev = self.kanban.card_status(card_id)
            if prev is None:
                return {"card": card_id, "state": "not_found"}
            if prev == DONE_STATUS:
                return {"card": card_id, "state": "already_done", "prev_status": prev}
            self.kanban.set_status(card_id, DONE_STATUS)
            return {"card": card_id, "state": "moved", "prev_status": prev}
        except KanbanError as exc:
            return {"card": card_id, "state": "failed", "error": str(exc)}

    def _restore_card(self, recorded: object) -> dict | None:
        if not isinstance(recorded, dict) or recorded.get("state") != "moved":
            return None  # we never moved it, so we don't move it back
        card_id, prev = recorded.get("card"), recorded.get("prev_status")
        if not isinstance(card_id, int) or not prev:
            return None
        if not self.kanban.configured:
            return {"card": card_id, "state": "restore_failed", "error": "kanban not configured"}
        try:
            self.kanban.set_status(card_id, str(prev))
            return {"card": card_id, "state": "restored", "status": str(prev)}
        except KanbanError as exc:
            return {"card": card_id, "state": "restore_failed", "error": str(exc)}


def make_server(service: Service, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "briefing-actions"
        sys_version = ""

        def log_message(self, fmt: str, *args) -> None:
            log.info("%s %s", self.address_string(), fmt % args)

        # ---- plumbing ----
        def _send(self, status: int, payload: object | None = None, *, body: bytes | None = None,
                  ctype: str = "application/json; charset=utf-8", cache: str = "no-store") -> None:
            if body is None:
                body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, status: int, message: str) -> None:
            self._send(status, {"ok": False, "error": message})

        def _path(self) -> str:
            return urlsplit(self.path).path

        def _guard(self) -> bool:
            """CSRF guard for state changes. Browsers send basic-auth credentials on
            cross-site requests, so require a custom header (forces a CORS preflight
            this service never approves) and, when present, a same-host Origin."""
            if self.headers.get(GUARD_HEADER) != "1":
                self._fail(403, f"missing {GUARD_HEADER} header")
                return False
            origin = self.headers.get("Origin")
            if origin:
                host = self.headers.get("X-Forwarded-Host") or self.headers.get("Host") or ""
                if urlsplit(origin).netloc != host:
                    self._fail(403, "cross-origin request refused")
                    return False
            return True

        def _json_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._fail(411, "Content-Length required")
                return None
            if length < 0 or length > MAX_BODY:
                self._fail(413, "body too large")
                return None
            try:
                body = json.loads(self.rfile.read(length) or b"null")
            except ValueError:
                self._fail(400, "body is not JSON")
                return None
            if not isinstance(body, dict):
                self._fail(400, "body must be a JSON object")
                return None
            return body

        # ---- routes ----
        def do_GET(self) -> None:
            path = self._path()
            if path == "/api/done.js":
                try:
                    self._send(200, body=JS_PATH.read_bytes(),
                               ctype="text/javascript; charset=utf-8", cache="no-cache")
                except OSError:
                    self._fail(500, "done.js missing from the image")
            elif path == "/api/done":
                try:
                    self._send(200, {"ok": True, "items": service.list_items()})
                except (OSError, ValueError) as exc:
                    log.error("reading done list failed: %s", exc)
                    self._fail(500, "could not read the done list")
            else:
                self._fail(404, "not found")

        def do_POST(self) -> None:
            if self._path() != "/api/done":
                self._fail(404, "not found")
                return
            if not self._guard():
                return
            body = self._json_body()
            if body is None:
                return
            item_id = body.get("id")
            if not isinstance(item_id, str) or not ID_RE.match(item_id):
                self._fail(400, "invalid id")
                return
            try:
                entry, kanban, already = service.complete(
                    item_id,
                    _clean(body.get("text"), 200),
                    _clean(body.get("owner"), 100),
                    _clean(body.get("brief"), 300),
                )
            except (OSError, ValueError) as exc:
                log.error("saving done list failed: %s", exc)
                self._fail(500, "could not save the done list")
                return
            self._send(200, {"ok": True, "already": already, "item": entry, "kanban": kanban})

        def do_DELETE(self) -> None:
            prefix = "/api/done/"
            path = self._path()
            if not path.startswith(prefix):
                self._fail(404, "not found")
                return
            if not self._guard():
                return
            item_id = unquote(path[len(prefix):])
            if not ID_RE.match(item_id):
                self._fail(400, "invalid id")
                return
            try:
                entry, kanban = service.undo(item_id)
            except (OSError, ValueError) as exc:
                log.error("saving done list failed: %s", exc)
                self._fail(500, "could not save the done list")
                return
            self._send(200, {"ok": True, "removed": entry is not None, "kanban": kanban})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    state_dir = Path(os.environ.get("BRIEFING_STATE_DIR", "/app/state"))
    port = int(os.environ.get("BRIEFING_ACTIONS_PORT", "8183"))
    kanban = Kanban(os.environ.get("KANBAN_URL", ""), os.environ.get("KANBAN_API_KEY", ""))

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        probe = state_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(f"state dir {state_dir} is not writable: {exc}") from exc

    server = make_server(Service(state_dir, kanban), "0.0.0.0", port)  # noqa: S104 - container
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    log.info("listening on :%d, state in %s, kanban %s", port, state_dir,
             "connected" if kanban.configured else "NOT configured (cards will not be updated)")
    server.serve_forever()


if __name__ == "__main__":
    main()
