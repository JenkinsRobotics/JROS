"""Connect/disconnect audit hooks — DAEMON-E.

The Server gains ``on_connect`` / ``on_disconnect`` callbacks; chat_ops
wires them to append JSON lines to ``<instance>/logs/audit.log``. These
tests prove the wiring works end-to-end against a real socket; the
chat_ops integration test checks the file format and content.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jaeger_os.daemon import chat_ops
from jaeger_os.daemon.client import Client
from jaeger_os.daemon.server import Server


@pytest.fixture
def short_tmp():
    d = Path(tempfile.mkdtemp(prefix="ju-", dir="/tmp"))
    try:
        yield d
    finally:
        for p in d.rglob("*"):
            try:
                p.unlink()
            except (OSError, IsADirectoryError):
                pass
        for p in sorted(d.rglob("*"), reverse=True):
            try:
                p.rmdir()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


# ── server-level callbacks ──────────────────────────────────────────


def test_server_invokes_connect_and_disconnect_callbacks(short_tmp):
    """Bare-server smoke test: open a connection, send one ping, close
    it. Both callbacks should fire with consistent ``client_id``s and
    the disconnect carries ``ops_called=['ping']``."""
    sock_path = short_tmp / "jaeger.sock"

    connects: list[dict[str, Any]] = []
    disconnects: list[dict[str, Any]] = []
    done = threading.Event()

    def on_connect(meta):
        connects.append(dict(meta))

    def on_disconnect(meta):
        disconnects.append(dict(meta))
        done.set()

    server = Server(socket_path=sock_path,
                    on_connect=on_connect, on_disconnect=on_disconnect)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    try:
        with Client(socket_path=sock_path) as c:
            resp = c.call("ping")
            assert resp.ok
    finally:
        # The handler's finally block fires on socket close, which the
        # Client's __exit__ triggered. Give it a beat to actually run.
        assert done.wait(1.0), "disconnect callback never fired"
        server.stop()

    assert len(connects) == 1
    assert len(disconnects) == 1
    assert connects[0]["client_id"] == disconnects[0]["client_id"]
    assert disconnects[0]["ops_called"] == ["ping"]
    assert disconnects[0]["duration_s"] >= 0


def test_client_ids_are_monotonic_per_server(short_tmp):
    """Three sequential clients get ids 1, 2, 3 — proves the counter
    is shared across connection handlers."""
    sock_path = short_tmp / "jaeger.sock"
    ids: list[int] = []
    events = threading.Event()
    lock = threading.Lock()

    def on_disconnect(meta):
        with lock:
            ids.append(meta["client_id"])
            if len(ids) == 3:
                events.set()

    server = Server(socket_path=sock_path, on_disconnect=on_disconnect)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    try:
        for _ in range(3):
            with Client(socket_path=sock_path) as c:
                c.call("ping")
        assert events.wait(1.0)
    finally:
        server.stop()

    assert ids == [1, 2, 3]


def test_set_lifecycle_hooks_can_be_called_after_construction(short_tmp):
    """``chat_ops.register_chat_ops`` calls ``set_lifecycle_hooks``
    AFTER ``Server(...)``, so this code path must work."""
    sock_path = short_tmp / "jaeger.sock"
    captured: list[str] = []

    server = Server(socket_path=sock_path)
    server.set_lifecycle_hooks(
        on_connect=lambda m: captured.append("c"),
        on_disconnect=lambda m: captured.append("d"),
    )
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    try:
        with Client(socket_path=sock_path) as c:
            c.call("ping")
    finally:
        # Wait for handler to finish.
        for _ in range(50):
            if "d" in captured:
                break
            time.sleep(0.01)
        server.stop()

    assert "c" in captured and "d" in captured


def test_callback_exception_doesnt_break_handler(short_tmp):
    """A buggy audit callback must not poison the connection or
    prevent other handlers from running."""
    sock_path = short_tmp / "jaeger.sock"

    def bad_connect(meta):
        raise RuntimeError("audit went sideways")

    server = Server(socket_path=sock_path, on_connect=bad_connect)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    try:
        with Client(socket_path=sock_path) as c:
            resp = c.call("ping")
            assert resp.ok, "ping should succeed despite buggy on_connect"
    finally:
        server.stop()


# ── chat_ops audit-log integration ──────────────────────────────────


@dataclass
class _AuditLayout:
    root: Path

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def audit_log_path(self) -> Path:
        return self.logs_dir / "audit.log"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"


@dataclass
class _AuditBoot:
    client: Any
    layout: _AuditLayout

    def cleanup(self) -> None:
        pass


@pytest.fixture
def patched_main(monkeypatch):
    from jaeger_os import main as m
    state = {"pipeline": {"config": None}, "agents_by_session": {}}

    def fake_run_turn(client, user_text, *, session_key):
        return {"text": "ok", "error": None, "tool_activity": [],
                "elapsed_s": 0.0, "skipped_final": False}

    monkeypatch.setattr(m, "_run_turn", fake_run_turn, raising=True)
    monkeypatch.setattr(m, "_jaeger_agents_by_session", state["agents_by_session"], raising=True)
    monkeypatch.setattr(m, "_pipeline", state["pipeline"], raising=True)
    return state


def test_register_chat_ops_writes_audit_lines(short_tmp, patched_main):
    sock_path = short_tmp / "jaeger.sock"
    layout = _AuditLayout(root=short_tmp)
    boot = _AuditBoot(client=object(), layout=layout)
    server = Server(socket_path=sock_path)
    chat_ops.register_chat_ops(server, boot)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)

    try:
        with Client(socket_path=sock_path) as c:
            c.call("status.snapshot")
            c.call("chat.send", text="hi")
    finally:
        # Wait for the disconnect to flush before reading the file.
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if layout.audit_log_path.exists() and layout.audit_log_path.stat().st_size > 0:
                break
            time.sleep(0.02)
        server.stop()

    assert layout.audit_log_path.exists(), "audit log was never written"
    lines = layout.audit_log_path.read_text().splitlines()
    entries = [json.loads(ln) for ln in lines]
    events = [e["event"] for e in entries]
    assert "daemon.client.connect" in events
    assert "daemon.client.disconnect" in events
    disconnect = next(e for e in entries if e["event"] == "daemon.client.disconnect")
    assert disconnect["ops_called"] == ["status.snapshot", "chat.send"]
    assert disconnect["client_id"] == 1
