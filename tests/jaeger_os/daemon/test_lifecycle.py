"""Lifecycle — PID file management, status detection, stale-PID recovery.

We split the lifecycle's job into two surfaces:

  - **Pure logic** — PID file read/write, "is this PID alive?", stale-PID
    cleanup, path resolution. Unit-testable without forking.
  - **The fork** — actually spawning the daemon child. That gets exercised
    by Phase 1.5's end-to-end smoke (subprocess invocation of
    ``jaeger start`` against a tmp instance dir); unit-testing ``os.fork``
    directly is more pain than signal.

This file covers the pure-logic half plus a single in-process integration
test that runs the server via an injected ``forker`` stub — that way we
exercise the orchestration (read PID, wait for socket, ping, succeed)
without committing to a real fork in the test runner.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from jaeger_os.daemon.lifecycle import (
    Lifecycle,
    LifecyclePaths,
    StartResult,
)


@pytest.fixture
def short_tmp():
    """Same short-path tmp dir as the server/client tests — the daemon
    socket lives under here and would blow past AF_UNIX's path limit
    if we used pytest's default ``tmp_path``."""
    d = Path(tempfile.mkdtemp(prefix="jdl-", dir="/tmp"))
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


@pytest.fixture
def lifecycle(short_tmp):
    """A Lifecycle whose run/ dir is under the short tmp path."""
    return Lifecycle(paths=LifecyclePaths(run_dir=short_tmp))


# ── path resolution ────────────────────────────────────────────────


def test_paths_default_under_run_dir(short_tmp):
    """All three lifecycle files (pid, socket, log) sit in ``run/`` so
    ``rm -rf <instance>/run`` is a clean reset."""
    paths = LifecyclePaths(run_dir=short_tmp)
    assert paths.pid_file == short_tmp / "jaeger.pid"
    assert paths.socket_path == short_tmp / "jaeger.sock"
    assert paths.log_file == short_tmp / "jaeger.log"


# ── PID file logic ─────────────────────────────────────────────────


def test_status_when_no_pid_file(lifecycle):
    """No PID file → not running. The simplest baseline; the tray polls
    this every couple of seconds and expects a quick answer."""
    s = lifecycle.status()
    assert s["running"] is False
    assert s["pid"] is None
    assert s["reason"] == "no pid file"


def test_status_when_pid_file_points_at_dead_process(lifecycle):
    """A PID file left behind by a crashed daemon must NOT count as
    running. We write the PID of an obviously-dead process (1 over the
    highest legal PID, or a PID we know we just reaped)."""
    lifecycle.paths.run_dir.mkdir(parents=True, exist_ok=True)
    # Pick a PID we're confident isn't running — fork+exit and use the
    # zombie-then-reaped child's PID.
    dead_pid = os.fork()
    if dead_pid == 0:
        os._exit(0)
    os.waitpid(dead_pid, 0)

    lifecycle.paths.pid_file.write_text(str(dead_pid))
    s = lifecycle.status()
    assert s["running"] is False
    assert s["pid"] == dead_pid
    assert "stale" in s["reason"]


def test_status_when_pid_file_garbage(lifecycle):
    """A PID file with non-numeric content (corrupted fs, partial write)
    is treated the same as a stale file — not running, surface the reason."""
    lifecycle.paths.run_dir.mkdir(parents=True, exist_ok=True)
    lifecycle.paths.pid_file.write_text("not-a-pid")
    s = lifecycle.status()
    assert s["running"] is False
    assert "garbage" in s["reason"] or "stale" in s["reason"]


def test_status_when_pid_alive_but_socket_missing(lifecycle):
    """A live PID with no socket means the daemon is starting up (or
    half-died). We report ``running=False`` so the caller falls back to
    ``jaeger start`` to recover — and we surface the discrepancy."""
    lifecycle.paths.run_dir.mkdir(parents=True, exist_ok=True)
    lifecycle.paths.pid_file.write_text(str(os.getpid()))   # we're alive
    # ... but no socket. Caller sees "starting or broken".
    s = lifecycle.status()
    assert s["running"] is False
    assert "socket" in s["reason"].lower()


# ── stale-PID cleanup ──────────────────────────────────────────────


def test_clean_stale_state_removes_dead_pid_file_and_socket(lifecycle):
    """Before ``start()`` can bind, it must clear leftovers from a
    crashed previous daemon. The cleanup is its own method so the test
    can assert on it directly without firing a fork."""
    lifecycle.paths.run_dir.mkdir(parents=True, exist_ok=True)
    # Stale PID + a leftover socket file (an empty file, not a real
    # listening socket — same byte shape on disk).
    pid_file = lifecycle.paths.pid_file
    sock_path = lifecycle.paths.socket_path
    pid_file.write_text(str(99999999))    # dead PID
    sock_path.write_text("")              # leftover

    cleaned = lifecycle.clean_stale()
    assert cleaned is True
    assert not pid_file.exists()
    assert not sock_path.exists()


def test_clean_stale_state_refuses_when_pid_is_alive(lifecycle):
    """If the PID in the file is a *running* process, we must NOT delete
    its socket out from under it. ``clean_stale`` returns False and
    leaves the files alone; the caller surfaces 'already running'."""
    lifecycle.paths.run_dir.mkdir(parents=True, exist_ok=True)
    lifecycle.paths.pid_file.write_text(str(os.getpid()))   # we're alive
    lifecycle.paths.socket_path.write_text("")              # placeholder

    cleaned = lifecycle.clean_stale()
    assert cleaned is False
    assert lifecycle.paths.pid_file.exists()


# ── start with injected forker ─────────────────────────────────────


def test_start_runs_the_daemon_via_injected_forker(short_tmp):
    """Lifecycle.start() delegates the actual spawn to an injected
    ``forker`` callable — production passes ``os.fork`` + ``run_daemon``;
    tests pass a stub that runs the server in a thread.

    This proves the orchestration (write PID, wait for socket up, ping
    succeeds, return ok) is correct without needing a real fork.
    """
    import threading

    from jaeger_os.daemon.server import Server

    server: list[Server] = []   # captured by closure

    def thread_forker(target_pid_callback):
        """Stand in for fork+exec; runs the daemon "child" in a thread."""
        srv = Server(socket_path=short_tmp / "jaeger.sock")
        srv.start()
        server.append(srv)
        # Report THIS process's PID — the lifecycle assertion checks
        # whether the recorded PID is alive, which it always will be.
        target_pid_callback(os.getpid())
        return os.getpid()

    lc = Lifecycle(paths=LifecyclePaths(run_dir=short_tmp))
    try:
        res: StartResult = lc.start(forker=thread_forker, socket_wait_s=2.0)
        assert res.ok is True, f"start failed: {res.message}"
        assert res.pid == os.getpid()
        # PID file was written.
        assert lc.paths.pid_file.read_text().strip() == str(os.getpid())
        # And status now agrees.
        s = lc.status()
        assert s["running"] is True
        assert s["pid"] == os.getpid()
    finally:
        if server:
            server[0].stop()


def test_start_refuses_when_already_running(short_tmp):
    """Two ``start()`` calls back-to-back: the second must detect the
    first and refuse with a clear message, not blow away the socket."""
    from jaeger_os.daemon.server import Server

    srv = Server(socket_path=short_tmp / "jaeger.sock")
    srv.start()
    try:
        # Pretend a daemon is already running: write our PID + the socket
        # is up because we just started it.
        lc = Lifecycle(paths=LifecyclePaths(run_dir=short_tmp))
        lc.paths.run_dir.mkdir(parents=True, exist_ok=True)
        lc.paths.pid_file.write_text(str(os.getpid()))

        res = lc.start(forker=lambda cb: (_ for _ in ()).throw(
            AssertionError("forker should not be called when already running")
        ))
        assert res.ok is False
        assert "already running" in res.message.lower()
    finally:
        srv.stop()


def test_start_recovers_from_stale_pid_file(short_tmp):
    """A leftover PID file from a crashed daemon doesn't block a fresh
    start — ``clean_stale`` removes it, then the forker proceeds."""
    import threading

    from jaeger_os.daemon.server import Server

    # Write a stale PID file.
    pid_file = short_tmp / "jaeger.pid"
    pid_file.write_text(str(99999999))   # dead PID

    server: list[Server] = []

    def thread_forker(cb):
        srv = Server(socket_path=short_tmp / "jaeger.sock")
        srv.start()
        server.append(srv)
        cb(os.getpid())
        return os.getpid()

    lc = Lifecycle(paths=LifecyclePaths(run_dir=short_tmp))
    try:
        res = lc.start(forker=thread_forker, socket_wait_s=2.0)
        assert res.ok is True, f"start failed: {res.message}"
        assert lc.paths.pid_file.read_text().strip() == str(os.getpid())
    finally:
        if server:
            server[0].stop()


# ── stop ───────────────────────────────────────────────────────────


def test_stop_when_not_running(lifecycle):
    """``stop`` on a not-running daemon is a no-op success — the tray's
    'Stop Daemon' button should never error just because the daemon
    happens to already be down."""
    res = lifecycle.stop()
    assert res.ok is True
    assert "not running" in res.message.lower()


def test_stop_removes_pid_file_and_socket(short_tmp):
    """When the daemon dies, ``stop`` must clean up both files so the
    next ``start`` doesn't trip the 'already running' check."""
    import threading

    from jaeger_os.daemon.server import Server

    srv = Server(socket_path=short_tmp / "jaeger.sock")
    srv.start()

    lc = Lifecycle(paths=LifecyclePaths(run_dir=short_tmp))
    lc.paths.run_dir.mkdir(parents=True, exist_ok=True)
    lc.paths.pid_file.write_text(str(os.getpid()))

    # Inject a stub killer — we don't actually want to SIGTERM ourselves.
    killed: list[int] = []

    def fake_killer(pid: int, sig: int) -> None:
        killed.append(pid)
        # Mimic the real daemon's response: shut down the server so the
        # socket disappears, which is the signal ``stop`` waits on.
        srv.stop()

    res = lc.stop(killer=fake_killer, wait_s=2.0)
    assert res.ok is True
    assert killed == [os.getpid()]
    assert not lc.paths.pid_file.exists()
    assert not lc.paths.socket_path.exists()
