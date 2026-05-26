"""Daemon lifecycle — PID file, fork, status detection.

Split into two surfaces so each is testable on its own:

  - :class:`LifecyclePaths` — a tiny dataclass that says *where* the
    PID file, socket, and log live. One ``run_dir`` and everything else
    derives from it; ``rm -rf <instance>/run`` is a clean reset.
  - :class:`Lifecycle` — start / stop / status / clean_stale. Methods
    take an injectable ``forker`` / ``killer`` so tests don't have to
    spawn real processes; production calls pass the real ``os.fork`` +
    ``os.kill``.

Why single fork, not double-fork
--------------------------------
Classic UNIX double-fork detaches from the controlling terminal so a
SIGHUP from terminal close doesn't kill the daemon. ``os.setsid()`` in
the child handles that for us, and a single fork keeps the parent's
exit path simple (return the child PID up the chain so ``jaeger start``
can print it).

Why no model loading here
-------------------------
Phase 1 deliberately keeps the daemon empty — just the socket server
plus its three builtin ops. Phase 2 wires ``boot_for_daemon`` into the
child branch of the fork. Doing that here would couple the lifecycle to
the agent and we'd have to redo all of these tests.
"""

from __future__ import annotations

import errno
import os
import signal
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ── path bundle ────────────────────────────────────────────────────


@dataclass(frozen=True)
class LifecyclePaths:
    """Where the lifecycle's files live. ``run_dir`` is the only knob;
    everything else is fixed inside it so ops can use stable names."""
    run_dir: Path

    @property
    def pid_file(self) -> Path:
        return self.run_dir / "jaeger.pid"

    @property
    def socket_path(self) -> Path:
        return self.run_dir / "jaeger.sock"

    @property
    def log_file(self) -> Path:
        return self.run_dir / "jaeger.log"


# ── result types ───────────────────────────────────────────────────


@dataclass(frozen=True)
class StartResult:
    ok: bool
    pid: int | None
    message: str


@dataclass(frozen=True)
class StopResult:
    ok: bool
    message: str


# ── helpers ────────────────────────────────────────────────────────


def _process_is_alive(pid: int) -> bool:
    """``kill(pid, 0)`` — sends no signal but returns success iff the
    process exists. The portable "is this PID alive?" check on UNIX."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        # ESRCH — no such process. EPERM — process exists but we lack
        # permission to signal it. EPERM still means alive.
        return exc.errno == errno.EPERM
    return True


def _read_pid_file(path: Path) -> int | None:
    """Returns the PID integer, or None if the file is missing or
    contains garbage. Both 'missing' and 'corrupt' are recoverable; the
    caller decides what to do."""
    if not path.exists():
        return None
    try:
        text = path.read_text().strip()
    except OSError:
        return None
    if not text or not text.lstrip("-+").isdigit():
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


# ── main class ─────────────────────────────────────────────────────


class Lifecycle:
    """Owns the daemon's on-disk state (PID file, socket) + transitions."""

    def __init__(self, *, paths: LifecyclePaths) -> None:
        self.paths = paths

    # ── status ────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Best-effort snapshot of "is the daemon up?" Always cheap —
        the tray calls this every couple of seconds, so it must not
        block on anything network-y. We look at PID liveness and socket
        existence only; *connecting* and pinging is a richer call the
        caller can layer on top."""
        pid = _read_pid_file(self.paths.pid_file)
        if pid is None:
            if self.paths.pid_file.exists():
                # File exists but didn't parse → garbage.
                return {"running": False, "pid": None,
                        "reason": "pid file is garbage"}
            return {"running": False, "pid": None, "reason": "no pid file"}
        if not _process_is_alive(pid):
            return {"running": False, "pid": pid,
                    "reason": f"stale pid file (pid {pid} not alive)"}
        if not self.paths.socket_path.exists():
            return {"running": False, "pid": pid,
                    "reason": "process alive but socket missing (starting or broken)"}
        return {"running": True, "pid": pid, "reason": "ok"}

    # ── stale cleanup ─────────────────────────────────────────────

    def clean_stale(self) -> bool:
        """Remove PID + socket files IFF they belong to a dead process.
        Returns True if a cleanup happened, False if the PID was alive
        (and we left the files alone)."""
        pid = _read_pid_file(self.paths.pid_file)
        if pid is not None and _process_is_alive(pid):
            return False
        # Either no PID, garbage PID, or dead PID — safe to nuke.
        for p in (self.paths.pid_file, self.paths.socket_path):
            try:
                if p.exists() or p.is_symlink():
                    p.unlink()
            except OSError:
                pass
        return True

    # ── start ──────────────────────────────────────────────────────

    def start(
        self,
        *,
        forker: Callable[[Callable[[int], None]], int],
        socket_wait_s: float = 5.0,
    ) -> StartResult:
        """Bring the daemon up.

        ``forker`` is the spawning callable — production passes a real
        fork+exec; tests pass a thread-based stub. Its contract: launch
        the daemon, call ``pid_callback(pid)`` once the child process
        exists, then return that same PID. The PID is what we record
        on disk.

        The lifecycle layer owns: stale-file cleanup, "already running?"
        check, PID-file write, and the post-spawn wait for the socket
        to appear. The forker owns the actual server-startup and any
        platform-specific setup (setsid, stdio redirect, etc.)."""
        # If a healthy daemon is already up, refuse — replacing a
        # running daemon should be an explicit ``stop`` + ``start``.
        s = self.status()
        if s["running"]:
            return StartResult(
                ok=False, pid=s["pid"],
                message=f"daemon already running (pid={s['pid']})",
            )

        # Otherwise clear stale files so the new daemon's socket bind
        # doesn't fail.
        self.clean_stale()

        # Make sure the run dir exists before the forker tries to drop
        # files into it.
        self.paths.run_dir.mkdir(parents=True, exist_ok=True)

        recorded_pid: list[int] = []

        def record_pid(pid: int) -> None:
            recorded_pid.append(pid)
            try:
                self.paths.pid_file.write_text(str(pid))
            except OSError:
                pass

        try:
            forker(record_pid)
        except Exception as exc:  # noqa: BLE001 — surface every spawn error
            return StartResult(
                ok=False, pid=None,
                message=f"forker failed: {type(exc).__name__}: {exc}",
            )

        # Wait for the socket file to appear *and* accept a connection.
        # The forker may have started the server in a thread that hasn't
        # bound yet; we poll until the socket is responsive or we run
        # out of time.
        deadline = time.monotonic() + socket_wait_s
        while time.monotonic() < deadline:
            if self.paths.socket_path.exists() and self._socket_responsive():
                pid = recorded_pid[0] if recorded_pid else None
                return StartResult(
                    ok=True, pid=pid,
                    message=f"daemon started (pid={pid})",
                )
            time.sleep(0.02)

        return StartResult(
            ok=False, pid=recorded_pid[0] if recorded_pid else None,
            message=f"daemon did not bind socket within {socket_wait_s}s",
        )

    def _socket_responsive(self) -> bool:
        """A bound, accepting Unix socket answers ``connect()`` even
        before any data is exchanged. Cheap reachability probe."""
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(str(self.paths.socket_path))
            return True
        except OSError:
            return False

    # ── stop ───────────────────────────────────────────────────────

    def stop(
        self,
        *,
        killer: Callable[[int, int], None] | None = None,
        wait_s: float = 5.0,
    ) -> StopResult:
        """Bring the daemon down.

        ``killer(pid, sig)`` defaults to ``os.kill``; tests pass a stub.
        We send SIGTERM, wait for the socket to disappear, then clean
        up both files. A second-stage SIGKILL would be reasonable but
        we hold off until Phase 5 — the daemon's shutdown path is small
        enough today that SIGTERM should always suffice."""
        send = killer if killer is not None else os.kill
        pid = _read_pid_file(self.paths.pid_file)
        if pid is None or not _process_is_alive(pid):
            # Already down — tidy up any leftover files and return ok.
            self.clean_stale()
            return StopResult(ok=True, message="daemon not running")

        try:
            send(pid, signal.SIGTERM)
        except ProcessLookupError:
            # Race: died between liveness check and signal. Treat as ok.
            self.clean_stale()
            return StopResult(ok=True, message="daemon not running")
        except PermissionError as exc:
            return StopResult(
                ok=False,
                message=f"cannot signal pid {pid}: {exc} "
                        f"(was the daemon started by a different user?)",
            )

        # Wait for the socket file to disappear (daemon cleanup) — that's
        # our signal that the daemon exited rather than hanging on its
        # in-flight turn.
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            if not self.paths.socket_path.exists():
                break
            time.sleep(0.02)

        # Final tidy: remove any leftovers regardless.
        try:
            if self.paths.pid_file.exists():
                self.paths.pid_file.unlink()
        except OSError:
            pass
        try:
            if self.paths.socket_path.exists():
                self.paths.socket_path.unlink()
        except OSError:
            pass

        return StopResult(ok=True, message=f"daemon stopped (was pid {pid})")


# ── production forker (single fork + setsid + stdio redirect) ──────


def real_forker(
    *,
    paths: LifecyclePaths,
    instance_name: str | None = None,
) -> Callable[[Callable[[int], None]], int]:
    """Build a spawner that launches the daemon as a NEW Python
    interpreter (``subprocess.Popen``) rather than forking.

    Why subprocess instead of ``os.fork()``
    ---------------------------------------
    macOS's Objective-C runtime aborts a forked child the first time
    it touches a class the parent initialized. Python's stdlib
    (``ssl``, ``locale``, the ``keyring`` package on first transitive
    import, …) drags Obj-C in during ``jaeger`` startup, so by the
    time we'd ``os.fork()`` from this code, the parent has already
    poisoned the well — llama-cpp-python's Metal backend then dies
    silently inside ``ggml_metal_device_init`` in the forked child.
    Setting ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` *in the child*
    after fork is too late; Apple's guard latches on first use, not
    on first init.

    Subprocess sidesteps the whole problem: the daemon is a fresh
    Python interpreter that starts with the env var already in place
    (we pass it via ``env=...``), Obj-C never registers the fork
    guard, and Metal initializes cleanly. This is the same pattern
    every major macOS daemon uses (Postgres, Redis, Hermes Agent,
    Werkzeug, Celery, Gunicorn) — the function keeps the
    ``real_forker`` name for compatibility with the existing
    ``Lifecycle.start(forker=…)`` contract, but it's a spawner.

    The child entry point — ``jaeger_os.daemon._child_entry`` — does
    the ``setsid`` + ``dup2`` to the log file + ``serve()`` dance
    that used to live inside ``real_forker``'s child branch.
    """
    import subprocess
    import sys

    def forker(pid_callback: Callable[[int], None]) -> int:
        paths.run_dir.mkdir(parents=True, exist_ok=True)

        env = dict(os.environ)
        # Pre-set BEFORE the new interpreter starts so Python's
        # stdlib loads with Obj-C fork-safety disabled from the
        # very first Obj-C touch.
        env.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

        cmd = [
            sys.executable,
            "-m", "jaeger_os.daemon._child_entry",
            "--run-dir", str(paths.run_dir),
        ]
        if instance_name:
            cmd.extend(["--instance", instance_name])

        # ``start_new_session=True`` is the subprocess-equivalent of
        # ``os.setsid()`` — the daemon becomes its own process group
        # leader so a Ctrl-C in the operator's shell doesn't cascade
        # into it. The child also calls setsid again on its own as
        # belt-and-suspenders (different parent shells deliver SIGHUP
        # to background processes differently).
        # Route stdout/stderr to the log file so import errors or
        # pre-``serve`` crashes don't vanish into the void. The child
        # itself reopens these fds after ``setsid`` (see
        # ``_child_entry._redirect_stdio_to_log``) — that's idempotent.
        log_path = paths.log_file
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(log_path, "ab", buffering=0)

        try:
            proc = subprocess.Popen(
                cmd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_fh,
                stderr=log_fh,
                close_fds=True,
                start_new_session=True,
            )
        finally:
            log_fh.close()
        pid_callback(proc.pid)
        return proc.pid

    return forker


__all__ = [
    "Lifecycle",
    "LifecyclePaths",
    "StartResult",
    "StopResult",
    "real_forker",
]
