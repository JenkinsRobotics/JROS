"""End-to-end smoke for the daemon lifecycle.

The earlier ``test_lifecycle.py`` exercises the pure logic with an
injected forker so unit tests don't fork the test runner. *This* file
does the real thing: spawns ``python -m jaeger_os.daemon.cli start`` as
a subprocess, asserts the daemon comes up, pings it, and brings it
back down. If you broke the fork/signal/serve dance, this catches it.

Slow-ish (a real fork + model-free server start takes ~0.5s); marked so
it can be deselected with ``-m 'not slow'`` when iterating.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from jaeger_os.daemon.client import Client


pytestmark = [pytest.mark.slow, pytest.mark.subprocess]


@pytest.fixture
def fake_instance(monkeypatch):
    """Point the daemon CLI at a throwaway instance dir.

    ``jaeger_os.core.instance.resolve_instance_dir`` reads the
    ``JAEGER_INSTANCE_DIR`` env var (or falls back to default), so we
    set it via the env we hand to the subprocess. Using a short prefix
    under /tmp keeps the resulting socket path below AF_UNIX's 104-byte
    cap on macOS."""
    root = Path(tempfile.mkdtemp(prefix="jd-e2e-", dir="/tmp"))
    try:
        yield root
    finally:
        # Best-effort cleanup. If a daemon is still alive (test failed
        # mid-stop), we don't want to leak it.
        pid_file = root / "run" / "jaeger.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                os.kill(pid, 15)        # SIGTERM
            except (ValueError, OSError):
                pass
        # Walk + remove. Avoid shutil.rmtree because the socket inode
        # can resist a naive rm on some platforms.
        for p in sorted(root.rglob("*"), reverse=True):
            try:
                p.unlink() if p.is_file() or p.is_symlink() else p.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass


def _run_cli(args, *, env_extra: dict) -> subprocess.CompletedProcess:
    """Invoke ``python -m jaeger_os.daemon.cli`` with the test's env.

    We bypass ``jaeger_os.main`` so the smoke is purely about lifecycle
    — no risk of model loading or wizard prompts interfering with what
    we're measuring."""
    env = os.environ.copy()
    env.update(env_extra)
    repo_src = str(Path(__file__).resolve().parents[3] / "src")
    env["PYTHONPATH"] = repo_src + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "jaeger_os.daemon.cli", *args],
        env=env, capture_output=True, text=True, timeout=15,
    )


def test_full_lifecycle(fake_instance):
    """``start`` → daemon up; ``status`` says running; client can ping;
    ``stop`` brings it down and removes the files."""
    env = {"JAEGER_INSTANCE_DIR": str(fake_instance)}

    # 1. start
    start = _run_cli(["start"], env_extra=env)
    assert start.returncode == 0, (
        f"start failed: stdout={start.stdout!r} stderr={start.stderr!r}"
    )
    assert "daemon started" in start.stdout

    pid_file = fake_instance / "run" / "jaeger.pid"
    sock_path = fake_instance / "run" / "jaeger.sock"
    assert pid_file.exists()
    assert sock_path.exists()
    pid = int(pid_file.read_text().strip())
    # The recorded PID is alive (kill -0 succeeds).
    os.kill(pid, 0)

    # 2. status
    status = _run_cli(["status"], env_extra=env)
    assert status.returncode == 0
    assert "running" in status.stdout
    assert str(pid) in status.stdout

    # 3. ping over the real socket
    with Client(socket_path=sock_path) as c:
        resp = c.call("ping")
    assert resp.ok and resp.result == {"pong": True}

    # 4. stop
    stop = _run_cli(["stop"], env_extra=env)
    assert stop.returncode == 0
    assert "stopped" in stop.stdout

    # Both files removed. Allow a short grace period: the daemon's
    # SIGTERM handler unlinks the socket; depending on scheduling that
    # can land a tick after ``jaeger stop`` returns.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not pid_file.exists() and not sock_path.exists():
            break
        time.sleep(0.05)
    assert not pid_file.exists()
    assert not sock_path.exists()

    # 5. status after stop → not running, exit code 1
    after = _run_cli(["status"], env_extra=env)
    assert after.returncode == 1
    assert "not running" in after.stdout


def test_start_twice_refuses_the_second(fake_instance):
    """Second ``start`` while the first daemon is up returns exit 1 with
    a clear 'already running' message; the existing daemon is untouched."""
    env = {"JAEGER_INSTANCE_DIR": str(fake_instance)}

    first = _run_cli(["start"], env_extra=env)
    assert first.returncode == 0

    second = _run_cli(["start"], env_extra=env)
    try:
        assert second.returncode == 1
        assert "already running" in (second.stdout + second.stderr).lower()
    finally:
        _run_cli(["stop"], env_extra=env)


def test_stop_when_not_running_is_a_noop_success(fake_instance):
    """The tray's ``Stop Daemon`` button should never error just because
    the daemon happens to already be down."""
    env = {"JAEGER_INSTANCE_DIR": str(fake_instance)}
    result = _run_cli(["stop"], env_extra=env)
    assert result.returncode == 0
    assert "not running" in result.stdout.lower()


def test_restart_replaces_the_daemon(fake_instance):
    """``jaeger restart`` brings the old daemon down and a fresh one
    up. The new PID differs from the old."""
    env = {"JAEGER_INSTANCE_DIR": str(fake_instance)}

    start = _run_cli(["start"], env_extra=env)
    assert start.returncode == 0
    old_pid = int((fake_instance / "run" / "jaeger.pid").read_text().strip())

    restart = _run_cli(["restart"], env_extra=env)
    try:
        assert restart.returncode == 0, restart.stderr
        new_pid = int((fake_instance / "run" / "jaeger.pid").read_text().strip())
        assert new_pid != old_pid
        # The old PID is gone.
        try:
            os.kill(old_pid, 0)
            old_alive = True
        except OSError:
            old_alive = False
        assert old_alive is False
    finally:
        _run_cli(["stop"], env_extra=env)
