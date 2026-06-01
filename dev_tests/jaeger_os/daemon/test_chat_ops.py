"""Chat-ops verbs over the daemon socket — DAEMON-A / DAEMON-B.

The daemon-side wiring is exercised with a fake ``boot_result`` so
these tests don't have to load a real GGUF model. We stub the
``jaeger_os.main`` symbols the chat-ops module reaches into
(``_run_turn``, ``_pipeline``, ``_jaeger_agents_by_session``) so a
``chat.send`` round-trip just runs through the dispatcher and into
our fake turn function.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jaeger_os.daemon import chat_ops
from jaeger_os.daemon.client import Client
from jaeger_os.daemon.server import Server


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def short_tmp():
    """Match the existing daemon-test fixture — Unix-socket paths are
    short. pytest's tmp_path is too long on macOS."""
    d = Path(tempfile.mkdtemp(prefix="jc-", dir="/tmp"))
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
class _FakeAgent:
    """Stand-in for JaegerAgent — just exposes the attributes chat_ops
    reads (``messages``, ``last_halt_reason``)."""
    messages: list[dict[str, Any]]
    last_halt_reason: str | None = None


@dataclass
class _FakeBoot:
    client: Any
    layout: _FakeLayout

    def cleanup(self) -> None:
        pass


@pytest.fixture
def patched_main(monkeypatch):
    """Patch the ``jaeger_os.main`` surface ``register_chat_ops``
    touches: ``_run_turn`` (the turn driver), ``_pipeline`` (for
    config / model_path lookups), ``_jaeger_agents_by_session`` (for
    history). Returns a small handle so tests can inject behaviour."""
    from jaeger_os import main as m

    state: dict[str, Any] = {
        "turn_calls": [],
        "next_result": {
            "text": "ok",
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
        return dict(state["next_result"])

    monkeypatch.setattr(m, "_run_turn", fake_run_turn, raising=True)
    monkeypatch.setattr(m, "_jaeger_agents_by_session", state["agents_by_session"], raising=True)
    monkeypatch.setattr(m, "_pipeline", state["pipeline"], raising=True)
    return state


@pytest.fixture
def chat_server(short_tmp, patched_main):
    """Stand up a Server with a fake boot already registered. Yields
    (server, client_factory, patched_main_state)."""
    sock_path = short_tmp / "jaeger.sock"
    boot = _FakeBoot(client=object(), layout=_FakeLayout(root=short_tmp))
    server = Server(socket_path=sock_path)
    chat_ops.register_chat_ops(server, boot)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        yield server, (lambda: Client(socket_path=sock_path)), patched_main
    finally:
        server.stop()


# ── chat.send ───────────────────────────────────────────────────────


def test_chat_send_returns_text_and_metadata(chat_server):
    server, make_client, state = chat_server
    with make_client() as c:
        resp = c.call("chat.send", text="hi there")
    assert resp.ok is True
    assert resp.result["text"] == "ok"
    assert resp.result["error"] is None
    assert resp.result["session_key"] == "daemon"
    assert resp.result["elapsed_s"] == 0.001
    assert resp.result["skipped_final"] is False
    # Turn was actually called through to _run_turn with the right shape.
    assert state["turn_calls"] == [{"text": "hi there", "session_key": "daemon"}]


def test_chat_send_uses_explicit_session_key(chat_server):
    server, make_client, state = chat_server
    with make_client() as c:
        resp = c.call("chat.send", text="hello", session_key="my-window")
    assert resp.ok is True
    assert resp.result["session_key"] == "my-window"
    assert state["turn_calls"][-1]["session_key"] == "my-window"


def test_chat_send_surfaces_turn_error(chat_server):
    server, make_client, state = chat_server
    state["next_result"] = {
        "text": "",
        "error": "ContextOverflow: prompt too long",
        "tool_activity": [],
        "elapsed_s": 0.0,
        "skipped_final": False,
    }
    with make_client() as c:
        resp = c.call("chat.send", text="x")
    # The OP succeeded (we got a response); the TURN's error is inside
    # the result payload so the client can distinguish transport
    # failure from turn failure.
    assert resp.ok is True
    assert resp.result["error"] == "ContextOverflow: prompt too long"


# ── chat.history ────────────────────────────────────────────────────


def test_chat_history_empty_when_no_turns_yet(chat_server):
    server, make_client, state = chat_server
    with make_client() as c:
        resp = c.call("chat.history")
    assert resp.ok is True
    assert resp.result["count"] == 0
    assert resp.result["messages"] == []
    assert resp.result["session_key"] == "daemon"


def test_chat_history_reflects_cached_agent_messages(chat_server):
    server, make_client, state = chat_server
    state["agents_by_session"]["daemon"] = _FakeAgent(
        messages=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hi back"},
        ],
    )
    with make_client() as c:
        resp = c.call("chat.history")
    assert resp.ok is True
    assert resp.result["count"] == 2
    assert resp.result["messages"][0]["content"] == "hi"
    assert resp.result["messages"][1]["role"] == "assistant"


def test_chat_history_respects_limit(chat_server):
    server, make_client, state = chat_server
    state["agents_by_session"]["daemon"] = _FakeAgent(
        messages=[{"i": i} for i in range(10)],
    )
    with make_client() as c:
        resp = c.call("chat.history", limit=3)
    assert [m["i"] for m in resp.result["messages"]] == [7, 8, 9]


# ── status.snapshot ─────────────────────────────────────────────────


def test_status_snapshot_includes_uptime_and_instance(chat_server):
    server, make_client, state = chat_server
    with make_client() as c:
        resp = c.call("status.snapshot")
    assert resp.ok is True
    snap = resp.result
    assert snap["running"] is True
    assert snap["uptime_s"] >= 0
    assert "instance" in snap
    assert snap["turns_completed"] == 0
    assert snap["last_user_text"] is None


def test_status_snapshot_updates_after_turn(chat_server):
    server, make_client, state = chat_server
    state["next_result"] = {
        "text": "response",
        "error": None,
        "tool_activity": ["▸ tool(x)"],
        "elapsed_s": 0.05,
        "skipped_final": False,
    }
    with make_client() as c:
        c.call("chat.send", text="ping")
        resp = c.call("status.snapshot")
    snap = resp.result
    assert snap["turns_completed"] == 1
    assert snap["last_user_text"] == "ping"
    assert snap["last_answer_text"] == "response"
    assert snap["last_elapsed_s"] == 0.05


# ── booting stubs ───────────────────────────────────────────────────


def test_booting_stubs_report_not_ready(short_tmp):
    """Before the boot worker calls register_chat_ops, the stubs
    should answer with a clear "still booting" signal so a client
    isn't left guessing."""
    sock_path = short_tmp / "jaeger.sock"
    server = Server(socket_path=sock_path)
    progress: dict[str, Any] = {"started_at": time.time(), "ready": False, "error": None}
    chat_ops.register_booting_stubs(server, progress)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        with Client(socket_path=sock_path) as c:
            snap = c.call("status.snapshot")
            assert snap.ok is True
            assert snap.result["agent_ready"] is False
            assert snap.result["boot_error"] is None

            send = c.call("chat.send", text="hi")
            assert send.ok is True
            assert "booting" in send.result["error"].lower()
    finally:
        server.stop()


def test_booting_stubs_surface_boot_error(short_tmp):
    sock_path = short_tmp / "jaeger.sock"
    server = Server(socket_path=sock_path)
    progress: dict[str, Any] = {
        "started_at": time.time(),
        "ready": False,
        "error": "ModelLoadError: not found",
    }
    chat_ops.register_booting_stubs(server, progress)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        with Client(socket_path=sock_path) as c:
            snap = c.call("status.snapshot")
            assert snap.result["boot_error"] == "ModelLoadError: not found"
            send = c.call("chat.send", text="x")
            assert "ModelLoadError" in send.result["error"]
    finally:
        server.stop()


def test_register_chat_ops_replaces_booting_stubs(short_tmp, patched_main):
    """The boot worker should be able to swap stubs for production
    handlers without colliding on op-already-registered."""
    sock_path = short_tmp / "jaeger.sock"
    server = Server(socket_path=sock_path)
    progress: dict[str, Any] = {"started_at": time.time(), "ready": False, "error": None}
    chat_ops.register_booting_stubs(server, progress)
    # No `replace=True` collision should occur — chat_ops does it.
    boot = _FakeBoot(client=object(), layout=_FakeLayout(root=short_tmp))
    chat_ops.register_chat_ops(server, boot)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        with Client(socket_path=sock_path) as c:
            resp = c.call("chat.send", text="real-turn")
            assert resp.result["text"] == "ok"   # production stub answers
            assert resp.result["session_key"] == "daemon"
    finally:
        server.stop()
