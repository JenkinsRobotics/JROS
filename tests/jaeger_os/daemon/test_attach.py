"""``jaeger attach`` — streaming client end-to-end.

Stands up a Server with the fake-boot chat ops (so no model loads),
runs ``run_attach`` with an in-memory stdin / stdout, and asserts on
what the client printed.
"""

from __future__ import annotations

import io
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jaeger_os.daemon import chat_ops
from jaeger_os.daemon.attach import run_attach
from jaeger_os.daemon.server import Server


@pytest.fixture
def short_tmp():
    d = Path(tempfile.mkdtemp(prefix="ja-", dir="/tmp"))
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
        "agents_by_session": {},
        "pipeline": {"config": None},
        "next_result": {
            "text": "agent replies",
            "error": None,
            "tool_activity": [],
            "elapsed_s": 0.05,
            "skipped_final": False,
        },
    }

    def fake_run_turn(client, user_text, *, session_key):
        state["turn_calls"].append({"text": user_text, "session_key": session_key})
        bus = state["pipeline"].get("daemon_event_bus")
        if bus is not None:
            bus.publish("tool.progress", name="echo", phase="start")
            bus.publish("tool.progress", name="echo", phase="done", elapsed_s=0.001)
        return dict(state["next_result"])

    monkeypatch.setattr(m, "_run_turn", fake_run_turn, raising=True)
    monkeypatch.setattr(m, "_jaeger_agents_by_session", state["agents_by_session"], raising=True)
    monkeypatch.setattr(m, "_pipeline", state["pipeline"], raising=True)
    return state


@pytest.fixture
def daemon(short_tmp, patched_main):
    sock_path = short_tmp / "jaeger.sock"
    boot = _FakeBoot(client=object(), layout=_FakeLayout(root=short_tmp))
    server = Server(socket_path=sock_path)
    chat_ops.register_chat_ops(server, boot)
    server.start()
    # Wait for socket.
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        yield sock_path, patched_main
    finally:
        server.stop()


# ── attach core flow ───────────────────────────────────────────────


def test_attach_sends_lines_and_prints_responses(daemon):
    sock_path, state = daemon
    stdin = io.StringIO("hello world\nsecond turn\n")
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = run_attach(
        sock_path=sock_path,
        session_key="my-attach",
        subscribe_events=False,  # keep it deterministic for this case
        stdin=stdin, stdout=stdout, stderr=stderr,
    )
    assert code == 0
    out = stdout.getvalue()
    # The answer text appears for each turn.
    assert out.count("agent replies") == 2
    # The elapsed-time line follows each answer.
    assert "0.05s" in out
    # Both lines reached the daemon with the right session key.
    assert state["turn_calls"] == [
        {"text": "hello world", "session_key": "my-attach"},
        {"text": "second turn", "session_key": "my-attach"},
    ]


def test_attach_blank_lines_are_skipped(daemon):
    sock_path, state = daemon
    stdin = io.StringIO("\n\nhi\n\n")
    code = run_attach(
        sock_path=sock_path, session_key="attach", subscribe_events=False,
        stdin=stdin, stdout=io.StringIO(), stderr=io.StringIO(),
    )
    assert code == 0
    # Only one real turn fired.
    assert [c["text"] for c in state["turn_calls"]] == ["hi"]


def test_attach_returns_1_when_daemon_not_running(short_tmp):
    code = run_attach(
        sock_path=short_tmp / "nonexistent.sock",
        session_key="x", subscribe_events=False,
        stdin=io.StringIO(""), stdout=io.StringIO(), stderr=io.StringIO(),
    )
    assert code == 1


def test_attach_surfaces_turn_error(daemon):
    sock_path, state = daemon
    state["next_result"] = {
        "text": "",
        "error": "ContextOverflow: too big",
        "tool_activity": [],
        "elapsed_s": 0.0,
        "skipped_final": False,
    }
    stderr = io.StringIO()
    code = run_attach(
        sock_path=sock_path, session_key="x", subscribe_events=False,
        stdin=io.StringIO("x\n"), stdout=io.StringIO(), stderr=stderr,
    )
    assert code == 0
    assert "ContextOverflow" in stderr.getvalue()


def test_attach_streams_tool_events_when_subscribed(daemon):
    """With --no-events OFF (the default), the subscriber thread
    prints tool-progress lines for each tool call as it happens."""
    sock_path, state = daemon
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_attach(
        sock_path=sock_path, session_key="attach",
        subscribe_events=True,
        stdin=io.StringIO("hi\n"), stdout=stdout, stderr=stderr,
    )
    assert code == 0
    out = stdout.getvalue()
    # The subscribed marker + at least one tool-progress line.
    assert "event stream live" in out
    assert "echo start" in out
    assert "echo done" in out
    # The final answer also lands (printed by the sender).
    assert "agent replies" in out
