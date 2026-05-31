"""End-to-end streaming — ``chat.subscribe`` over a real socket.

The handler is registered on a Server, a client connects + calls
``chat.subscribe``, we publish events to the bus from the test, and
assert they land on the client. Then we publish a synthetic
``chat.send`` round-trip and confirm ``turn.start`` / ``turn.complete``
events flow through.

Uses the same fake-boot pattern as ``test_chat_ops.py`` so the real
LLM never loads.
"""

from __future__ import annotations

import socket as _socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jaeger_os.daemon import chat_ops
from jaeger_os.daemon import protocol as P
from jaeger_os.daemon.client import Client
from jaeger_os.daemon.server import Server


@pytest.fixture
def short_tmp():
    d = Path(tempfile.mkdtemp(prefix="js-", dir="/tmp"))
    try:
        yield d
    finally:
        for p in d.iterdir():
            try:
                p.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


@dataclass
class _FakeLayout:
    root: Path

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"


@dataclass
class _FakeBoot:
    client: Any
    layout: _FakeLayout

    def cleanup(self) -> None:
        pass


@pytest.fixture
def patched_main(monkeypatch):
    from jaeger_os import main as m
    state: dict[str, Any] = {
        "turn_calls": [],
        "next_result": {
            "text": "answer",
            "error": None,
            "tool_activity": [],
            "elapsed_s": 0.001,
            "skipped_final": False,
        },
        "agents_by_session": {},
        "pipeline": {"config": None},
    }

    def fake_run_turn(client, user_text, *, session_key):
        state["turn_calls"].append({"text": user_text, "session_key": session_key})
        # The real turn would publish through ``bus`` via the
        # tool_progress callback; emulate one publish so the test
        # exercises the path.
        bus = state["pipeline"].get("daemon_event_bus")
        if bus is not None:
            bus.publish("tool.progress", name="echo", phase="start")
            bus.publish("tool.progress", name="echo", phase="done", elapsed_s=0.0001)
        return dict(state["next_result"])

    monkeypatch.setattr(m, "_run_turn", fake_run_turn, raising=True)
    monkeypatch.setattr(m, "_jaeger_agents_by_session", state["agents_by_session"], raising=True)
    monkeypatch.setattr(m, "_pipeline", state["pipeline"], raising=True)
    return state


def _wait_for_socket(path: Path, timeout: float = 1.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise TimeoutError(f"socket {path} never appeared")


@pytest.fixture
def daemon(short_tmp, patched_main):
    sock_path = short_tmp / "jaeger.sock"
    boot = _FakeBoot(client=object(), layout=_FakeLayout(root=short_tmp))
    server = Server(socket_path=sock_path)
    chat_ops.register_chat_ops(server, boot)
    server.start()
    _wait_for_socket(sock_path)
    try:
        yield server, sock_path, patched_main
    finally:
        server.stop()


# ── basic subscribe ────────────────────────────────────────────────


def test_subscribe_receives_subscribed_marker_immediately(daemon):
    """The handler emits a ``subscribed`` event right after the bus
    subscription is in place, so the client can confirm liveness
    before any agent activity happens."""
    server, sock_path, state = daemon
    # Open a raw socket so we can read Events between Requests/Responses.
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.connect(str(sock_path))
    sock.sendall(P.encode(P.Request(id=1, op="chat.subscribe")))

    framer = P.Framer()
    sock.settimeout(1.0)
    try:
        framer.feed(sock.recv(4096))
        msgs = list(framer.drain())
    finally:
        sock.close()
    assert msgs, "expected at least the 'subscribed' event"
    first = msgs[0]
    assert isinstance(first, P.Event)
    assert first.name == "subscribed"
    assert "subscription_id" in first.payload


def test_subscribe_streams_turn_events_from_chat_send(daemon):
    """Two connections: one subscribes, the other sends. The
    subscriber receives turn.start / tool.progress / turn.complete."""
    server, sock_path, state = daemon

    received: list[P.Event] = []
    sub_done = threading.Event()
    sub_ready = threading.Event()

    def _subscriber():
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall(P.encode(P.Request(id=99, op="chat.subscribe")))
        framer = P.Framer()
        s.settimeout(2.0)
        try:
            while not sub_done.is_set():
                try:
                    chunk = s.recv(4096)
                except _socket.timeout:
                    break
                if not chunk:
                    break
                framer.feed(chunk)
                for msg in framer.drain():
                    if isinstance(msg, P.Event):
                        received.append(msg)
                        if msg.name == "subscribed":
                            sub_ready.set()
                        if msg.name == "turn.complete":
                            sub_done.set()
                            return
                    elif isinstance(msg, P.Response):
                        return
        finally:
            s.close()

    t = threading.Thread(target=_subscriber, daemon=True)
    t.start()
    assert sub_ready.wait(1.0), "subscriber never got 'subscribed' marker"

    # Now drive a turn through the sender connection.
    with Client(socket_path=sock_path) as c:
        resp = c.call("chat.send", text="hello daemon")
    assert resp.ok and resp.result["text"] == "answer"

    t.join(timeout=2.0)
    assert not t.is_alive(), "subscriber thread didn't see turn.complete"

    names = [e.name for e in received]
    assert "subscribed" in names
    assert "turn.start" in names
    assert "tool.progress" in names
    assert "turn.complete" in names
    # turn.start carries the user's text + session_key.
    start_evt = next(e for e in received if e.name == "turn.start")
    assert start_evt.payload["text"] == "hello daemon"
    assert start_evt.payload["session_key"] == "daemon"


def test_multiple_subscribers_all_get_events(daemon):
    """Two subscribers, one chat.send — both subscribers see all
    events (pub/sub, not load-balanced)."""
    server, sock_path, state = daemon
    counts = {"a": 0, "b": 0}

    def _sub(label: str, ready: threading.Event, done: threading.Event):
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.connect(str(sock_path))
        s.sendall(P.encode(P.Request(id=1, op="chat.subscribe")))
        framer = P.Framer()
        s.settimeout(2.0)
        try:
            while not done.is_set():
                try:
                    chunk = s.recv(4096)
                except _socket.timeout:
                    break
                if not chunk:
                    break
                framer.feed(chunk)
                for msg in framer.drain():
                    if isinstance(msg, P.Event):
                        counts[label] += 1
                        if msg.name == "subscribed":
                            ready.set()
                        if msg.name == "turn.complete":
                            done.set()
                            return
        finally:
            s.close()

    ra, rb = threading.Event(), threading.Event()
    da, db = threading.Event(), threading.Event()
    ta = threading.Thread(target=_sub, args=("a", ra, da), daemon=True)
    tb = threading.Thread(target=_sub, args=("b", rb, db), daemon=True)
    ta.start()
    tb.start()
    assert ra.wait(1.0) and rb.wait(1.0)

    with Client(socket_path=sock_path) as c:
        c.call("chat.send", text="x")

    ta.join(timeout=2.0)
    tb.join(timeout=2.0)
    # Both saw the same number of events (subscribed + turn.start + 2*tool.progress + turn.complete = 5)
    assert counts["a"] == counts["b"]
    assert counts["a"] >= 5
