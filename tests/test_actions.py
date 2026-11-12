"""The 'Mark complete' service: done list, kanban sync, and its CSRF guard.

Runs the real HTTP server against a fake kanban, so what's checked is what the
browser script actually hits. These fail quietly in production (an item that
reappears next week, a card left open, a cross-site POST that works), which is
why they're pinned here.
"""

from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from briefing.actions import GUARD_HEADER, Kanban, Service, make_server

KEY = "kanban-secret-key"
HDR = {GUARD_HEADER: "1", "Content-Type": "application/json"}


class FakeKanban:
    """Minimal stand-in for the golang-kanban JSON API."""

    def __init__(self) -> None:
        self.cards = {282: "inprogress", 249: "todo", 7: "done"}
        self.patches: list[tuple[int, str, str]] = []  # (id, status, api key seen)
        self.fail_with: int | None = None
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _reply(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if outer.fail_with:
                    return self._reply(outer.fail_with, {"error": "boom"})
                if self.headers.get("X-API-Key") != KEY:
                    return self._reply(401, {"error": "Unauthorized"})
                # Go struct without json tags => capitalised keys
                self._reply(
                    200, [{"ID": i, "Title": f"t{i}", "Status": s} for i, s in outer.cards.items()]
                )

            def do_PATCH(self):
                card_id = int(self.path.rsplit("/", 1)[1])
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if outer.fail_with:
                    return self._reply(outer.fail_with, {"error": "boom"})
                outer.patches.append((card_id, body["status"], self.headers.get("X-API-Key", "")))
                outer.cards[card_id] = body["status"]
                self._reply(200, {"ID": card_id, "Status": body["status"]})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def kanban():
    fake = FakeKanban()
    yield fake
    fake.close()


def _start(state_dir, kanban_client):
    server = make_server(Service(state_dir, kanban_client), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def app(tmp_path, kanban):
    server = _start(tmp_path, Kanban(kanban.url, KEY))
    yield server, tmp_path
    server.shutdown()
    server.server_close()


def _req(server, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    data = json.dumps(body) if body is not None else None
    conn.request(method, path, body=data, headers=headers or {})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw), resp
    except ValueError:
        return resp.status, raw, resp


def _done_file(state_dir) -> dict:
    return json.loads((state_dir / "done.json").read_text(encoding="utf-8"))


# ---- guard -------------------------------------------------------------------


def test_post_without_guard_header_is_refused(app):
    server, state = app
    no_guard = {"Content-Type": "application/json"}
    status, body, _ = _req(server, "POST", "/api/done", {"id": "x"}, no_guard)
    assert status == 403
    assert not (state / "done.json").exists()


def test_cross_origin_post_is_refused_and_same_origin_allowed(app):
    server, _ = app
    host = f"127.0.0.1:{server.server_address[1]}"
    evil = {**HDR, "Origin": "https://evil.example"}
    assert _req(server, "POST", "/api/done", {"id": "x"}, evil)[0] == 403
    assert _req(server, "DELETE", "/api/done/x", None, evil)[0] == 403
    ok = {**HDR, "Origin": f"http://{host}"}
    assert _req(server, "POST", "/api/done", {"id": "x"}, ok)[0] == 200


@pytest.mark.parametrize("bad", ["", "../x", "a b", "-lead", "x" * 121, "a/b", "a;b"])
def test_bad_ids_rejected(app, bad):
    server, _ = app
    assert _req(server, "POST", "/api/done", {"id": bad}, HDR)[0] == 400


def test_non_json_and_oversized_bodies_rejected(app):
    server, _ = app
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    conn.request("POST", "/api/done", body="not json", headers={**HDR, "Content-Length": "8"})
    assert conn.getresponse().status == 400
    conn.close()
    assert _req(server, "POST", "/api/done", {"id": "x", "text": "y" * 20000}, HDR)[0] == 413


# ---- done list ---------------------------------------------------------------


def test_plain_item_is_recorded_and_listed(app):
    server, state = app
    payload = {
        "id": "20261029-get-titan-admin-panel",
        "text": "Get Titan admin panel working",
        "owner": "T.J. Schmitz",
        "brief": "/meeting_prep/2026/11/12/x.html",
    }
    status, body, _ = _req(server, "POST", "/api/done", payload, HDR)
    assert status == 200 and body["already"] is False and body["kanban"] is None
    entry = _done_file(state)["items"]["20261029-get-titan-admin-panel"]
    assert entry["owner"] == "T.J. Schmitz" and entry["completed_at"].endswith("+00:00")
    status, body, _ = _req(server, "GET", "/api/done")
    assert status == 200 and "20261029-get-titan-admin-panel" in body["items"]


def test_text_is_cleaned_and_capped(app):
    server, state = app
    messy = {"id": "t", "text": "a\x00b\n\n  c" + "z" * 500, "owner": 5}
    _req(server, "POST", "/api/done", messy, HDR)
    entry = _done_file(state)["items"]["t"]
    assert entry["text"].startswith("a b c") and len(entry["text"]) == 200 and entry["owner"] == ""


def test_second_write_keeps_a_backup(app):
    server, state = app
    _req(server, "POST", "/api/done", {"id": "one"}, HDR)
    _req(server, "POST", "/api/done", {"id": "two"}, HDR)
    assert set(json.loads((state / "done.json.bak").read_text())["items"]) == {"one"}


def test_corrupt_done_file_is_never_overwritten(app):
    server, state = app
    (state / "done.json").write_text("{not json", encoding="utf-8")
    assert _req(server, "POST", "/api/done", {"id": "x"}, HDR)[0] == 500
    assert _req(server, "GET", "/api/done")[0] == 500
    assert (state / "done.json").read_text(encoding="utf-8") == "{not json"


# ---- kanban ------------------------------------------------------------------


def test_card_item_moves_card_to_done_with_the_key(app, kanban):
    server, state = app
    payload = {"id": "card-282", "text": "Titan admin"}
    status, body, _ = _req(server, "POST", "/api/done", payload, HDR)
    assert status == 200
    assert body["kanban"] == {"card": 282, "state": "moved", "prev_status": "inprogress"}
    assert kanban.cards[282] == "done"
    assert kanban.patches == [(282, "done", KEY)]
    assert _done_file(state)["items"]["card-282"]["kanban"]["prev_status"] == "inprogress"


def test_completing_twice_does_not_touch_kanban_again(app, kanban):
    server, _ = app
    _req(server, "POST", "/api/done", {"id": "card-282"}, HDR)
    status, body, _ = _req(server, "POST", "/api/done", {"id": "card-282"}, HDR)
    assert body["already"] is True and body["kanban"] is None
    assert len(kanban.patches) == 1


def test_undo_puts_the_card_back_and_removes_the_item(app, kanban):
    server, state = app
    _req(server, "POST", "/api/done", {"id": "card-249"}, HDR)
    status, body, _ = _req(server, "DELETE", "/api/done/card-249", None, HDR)
    assert status == 200 and body["removed"] is True
    assert body["kanban"] == {"card": 249, "state": "restored", "status": "todo"}
    assert kanban.cards[249] == "todo"
    assert "card-249" not in _done_file(state)["items"]
    assert _req(server, "DELETE", "/api/done/card-249", None, HDR)[2].status == 200  # idempotent


def test_card_already_done_is_not_moved_and_undo_leaves_it_done(app, kanban):
    server, _ = app
    _, body, _ = _req(server, "POST", "/api/done", {"id": "card-7"}, HDR)
    assert body["kanban"]["state"] == "already_done" and kanban.patches == []
    _, body, _ = _req(server, "DELETE", "/api/done/card-7", None, HDR)
    assert body["kanban"] is None and kanban.patches == [] and kanban.cards[7] == "done"


def test_card_missing_from_board_is_reported_but_item_still_recorded(app):
    server, state = app
    _, body, _ = _req(server, "POST", "/api/done", {"id": "card-99999"}, HDR)
    assert body["kanban"]["state"] == "not_found"
    assert "card-99999" in _done_file(state)["items"]


def test_kanban_failure_still_records_the_item_and_hides_the_key(app, kanban):
    server, state = app
    kanban.fail_with = 500
    status, body, _ = _req(server, "POST", "/api/done", {"id": "card-282"}, HDR)
    assert status == 200 and body["kanban"]["state"] == "failed"
    assert "500" in body["kanban"]["error"] and KEY not in json.dumps(body)
    assert "card-282" in _done_file(state)["items"]


def test_wrong_key_is_reported_as_failure(tmp_path, kanban):
    server = _start(tmp_path, Kanban(kanban.url, "wrong"))
    try:
        _, body, _ = _req(server, "POST", "/api/done", {"id": "card-282"}, HDR)
        assert body["kanban"]["state"] == "failed" and "401" in body["kanban"]["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_unreachable_kanban_is_reported(tmp_path):
    server = _start(tmp_path, Kanban("http://127.0.0.1:9", KEY, timeout=1))
    try:
        _, body, _ = _req(server, "POST", "/api/done", {"id": "card-1"}, HDR)
        assert body["kanban"]["state"] == "failed" and "unreachable" in body["kanban"]["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_unconfigured_kanban_is_reported(tmp_path):
    server = _start(tmp_path, Kanban("", ""))
    try:
        _, body, _ = _req(server, "POST", "/api/done", {"id": "card-1"}, HDR)
        assert body["kanban"] == {"card": 1, "state": "unconfigured"}
        assert "card-1" in _done_file(tmp_path)["items"]
    finally:
        server.shutdown()
        server.server_close()


# ---- script ------------------------------------------------------------------


def test_script_is_served_as_javascript(app):
    server, _ = app
    status, body, resp = _req(server, "GET", "/api/done.js")
    assert status == 200 and resp.getheader("Content-Type").startswith("text/javascript")
    assert resp.getheader("X-Content-Type-Options") == "nosniff"
    assert b"X-Briefing-Action" in body and b"innerHTML" not in body


def test_unknown_paths_404(app):
    server, _ = app
    assert _req(server, "GET", "/api/nope")[0] == 404
    assert _req(server, "POST", "/api/other", {}, HDR)[0] == 404
