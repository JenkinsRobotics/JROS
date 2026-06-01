"""``jaeger rich-tui`` — daemon-attached UI tests.

The Rich rendering itself is exercised by piping a ``Console`` to a
capture buffer; the prompt loop is driven by monkeypatching
``read_prompt`` to return canned input lines. No real daemon, no
real terminal — these tests stay fast and deterministic.
"""

from __future__ import annotations

import io
import socket as _socket
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from jaeger_os.daemon import chat_ops
from jaeger_os.daemon.server import Server
from jaeger_os.interfaces.rich_tui import app as rich_app


# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def short_tmp():
    d = Path(tempfile.mkdtemp(prefix="jrt-", dir="/tmp"))
    try:
        yield d
    finally:
        for p in sorted(d.rglob("*"), reverse=True):
            try:
                p.unlink() if p.is_file() or p.is_symlink() else p.rmdir()
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
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def audit_log_path(self) -> Path:
        return self.logs_dir / "audit.log"

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
    """Stub ``jaeger_os.main`` so chat.send doesn't load a real model."""
    from jaeger_os import main as m
    state: dict[str, Any] = {
        "turn_calls": [],
        "next_result": {
            "text": "agent replies here",
            "error": None,
            "tool_activity": [],
            "elapsed_s": 0.42,
            "skipped_final": False,
        },
        "agents_by_session": {},
        "pipeline": {"config": None},
    }

    def fake_run_turn(client, user_text, *, session_key):
        state["turn_calls"].append({"text": user_text, "session_key": session_key})
        bus = state["pipeline"].get("daemon_event_bus")
        if bus is not None:
            bus.publish("tool.progress", name="echo", phase="start")
            bus.publish("tool.progress", name="echo", phase="done", elapsed_s=0.01)
        return dict(state["next_result"])

    monkeypatch.setattr(m, "_run_turn", fake_run_turn, raising=True)
    monkeypatch.setattr(m, "_jaeger_agents_by_session", state["agents_by_session"], raising=True)
    monkeypatch.setattr(m, "_pipeline", state["pipeline"], raising=True)
    return state


@pytest.fixture
def daemon(short_tmp, patched_main):
    sock_path = short_tmp / "jaeger.sock"
    (short_tmp / "logs").mkdir(parents=True, exist_ok=True)
    boot = _FakeBoot(client=object(), layout=_FakeLayout(root=short_tmp))
    server = Server(socket_path=sock_path)
    chat_ops.register_chat_ops(server, boot)
    server.start()
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    try:
        yield sock_path, patched_main
    finally:
        server.stop()


# ── _probe_daemon ──────────────────────────────────────────────────


def test_probe_daemon_returns_none_when_socket_missing(short_tmp, capsys):
    from rich.console import Console
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    snap = rich_app._probe_daemon(short_tmp / "nonexistent.sock", console)
    assert snap is None


def test_probe_daemon_returns_snapshot_when_alive(daemon):
    sock_path, _ = daemon
    from rich.console import Console
    console = Console(file=io.StringIO(), force_terminal=False, width=80)
    snap = rich_app._probe_daemon(sock_path, console)
    assert snap is not None
    assert snap["running"] is True
    assert "uptime_s" in snap


# ── run() loop (mocked read_prompt) ────────────────────────────────


class _PromptScript:
    """Tiny driver that hands ``read_prompt`` one line at a time, then
    returns None (EOF) to unwind the loop cleanly."""

    def __init__(self, lines: list[Any]):
        # ``lines`` may include sentinels like ``rich_app.CTRL_C`` to
        # exercise the Ctrl-C branch.
        self._lines = list(lines)

    def __call__(self, session, *, message, placeholder=None):
        if not self._lines:
            return None  # EOF
        return self._lines.pop(0)


def test_run_quits_on_eof_after_one_turn(daemon, monkeypatch, capsys):
    sock_path, state = daemon
    script = _PromptScript(["hi"])
    monkeypatch.setattr(rich_app, "read_prompt", script)
    # ``build_session`` returns a real PromptSession; we don't use it
    # since read_prompt is mocked, but the call has to succeed.
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    code = rich_app.run(sock_path=sock_path, session_key="t1")
    assert code == 0
    # The turn reached the daemon.
    assert state["turn_calls"] == [{"text": "hi", "session_key": "t1"}]
    out = capsys.readouterr().out
    assert "agent replies here" in out


def test_run_handles_slash_quit(daemon, monkeypatch, capsys):
    sock_path, state = daemon
    monkeypatch.setattr(rich_app, "read_prompt",
                        _PromptScript(["/quit"]))
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    code = rich_app.run(sock_path=sock_path, session_key="t2")
    assert code == 0
    # /quit never reaches the daemon as a chat.send.
    assert state["turn_calls"] == []


def test_run_handles_slash_help(daemon, monkeypatch, capsys):
    sock_path, state = daemon
    monkeypatch.setattr(rich_app, "read_prompt",
                        _PromptScript(["/help", "/quit"]))
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    code = rich_app.run(sock_path=sock_path, session_key="t3")
    assert code == 0
    out = capsys.readouterr().out
    assert "rich-tui commands" in out
    assert "/quit" in out
    assert state["turn_calls"] == []


def test_run_ignores_ctrl_c(daemon, monkeypatch, capsys):
    sock_path, _ = daemon
    monkeypatch.setattr(
        rich_app, "read_prompt",
        _PromptScript([rich_app.CTRL_C, "hi", None]),
    )
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    code = rich_app.run(sock_path=sock_path, session_key="t4")
    assert code == 0
    out = capsys.readouterr().out
    assert "Ctrl-C ignored" in out
    assert "agent replies here" in out


def test_run_blank_lines_skipped(daemon, monkeypatch):
    sock_path, state = daemon
    monkeypatch.setattr(
        rich_app, "read_prompt",
        _PromptScript(["", "   ", "real message", None]),
    )
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    rich_app.run(sock_path=sock_path, session_key="t5")
    assert [c["text"] for c in state["turn_calls"]] == ["real message"]


def test_run_returns_1_when_daemon_down(short_tmp):
    code = rich_app.run(sock_path=short_tmp / "nope.sock",
                        session_key="t6")
    assert code == 1


def test_run_surfaces_turn_error(daemon, monkeypatch, capsys):
    sock_path, state = daemon
    state["next_result"] = {
        "text": "",
        "error": "ContextOverflow: too big",
        "tool_activity": [],
        "elapsed_s": 0.0,
        "skipped_final": False,
    }
    monkeypatch.setattr(rich_app, "read_prompt",
                        _PromptScript(["x", None]))
    monkeypatch.setattr(rich_app, "build_session", lambda: object())

    code = rich_app.run(sock_path=sock_path, session_key="t7")
    assert code == 0
    out = capsys.readouterr().out
    assert "ContextOverflow" in out
