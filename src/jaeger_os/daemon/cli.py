"""``jaeger start`` / ``stop`` / ``status`` — the lifecycle CLI surface.

Pulled out of ``main.py`` so a Phase-1 daemon command doesn't need to
import the full pipeline. ``main.py`` peels ``sys.argv[1]`` and calls
:func:`dispatch` from here if the first word is a daemon subcommand;
otherwise it falls through to the existing argparse + TUI/voice path
so standalone ``jaeger`` keeps working exactly as today.

What this module owns
---------------------
  - argv → subcommand mapping
  - human-readable stdout/stderr output for each verb
  - exit codes (0 success, 1 unhealthy, 2 misuse)
  - plumbing ``Lifecycle`` against an instance-resolved ``run/`` dir

What it deliberately does NOT own
---------------------------------
  - the agent loop (Phase 2)
  - the actual fork target — :func:`real_forker` from ``lifecycle.py``
    does the os-level dance; we just hand it a ``serve`` callable
  - tray UI: that's a separate client (Phase 1.6)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from jaeger_os.daemon.client import Client, DaemonNotRunning
from jaeger_os.daemon.lifecycle import (
    Lifecycle,
    LifecyclePaths,
    real_forker,
)
from jaeger_os.daemon.server import Server


# Subcommands that route to this module instead of the main TUI path.
SUBCOMMANDS: frozenset[str] = frozenset({"start", "stop", "status", "restart"})


def is_daemon_subcommand(argv: Sequence[str]) -> bool:
    """``main.py`` calls this on ``sys.argv[1:]`` — True if the first
    word is one of our subcommands. ``--instance`` and the like are
    parsed AFTER the dispatch, so a flag-first argv falls through to
    the legacy path (we never had ``--start`` etc. before this)."""
    return len(argv) >= 1 and argv[0] in SUBCOMMANDS


def dispatch(argv: Sequence[str]) -> int:
    """Run the daemon subcommand named by ``argv[0]``. Returns the exit
    code the CLI should hand back to the OS."""
    if not argv:
        _print_usage()
        return 2
    parser = argparse.ArgumentParser(
        prog="jaeger", add_help=False,
        description="Jaeger daemon lifecycle commands.",
    )
    parser.add_argument("subcommand", choices=sorted(SUBCOMMANDS))
    parser.add_argument("--instance", default=None,
                        help="Instance name (default: $JAEGER_INSTANCE_NAME or 'default').")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)

    if args.help:
        _print_usage()
        return 0

    paths = _resolve_paths(args.instance)
    lifecycle = Lifecycle(paths=paths)

    if args.subcommand == "start":
        return _cmd_start(lifecycle)
    if args.subcommand == "stop":
        return _cmd_stop(lifecycle)
    if args.subcommand == "status":
        return _cmd_status(lifecycle)
    if args.subcommand == "restart":
        return _cmd_restart(lifecycle)
    _print_usage()
    return 2


# ── path resolution ────────────────────────────────────────────────


def _resolve_paths(instance_name: str | None) -> LifecyclePaths:
    """Return the ``run/`` dir for ``instance_name`` (or the default
    instance). We don't ``InstanceLayout``-resolve here because that
    pulls in the wizard / manifest check, which the lifecycle is
    deliberately decoupled from — ``jaeger status`` must not run a
    setup wizard."""
    from jaeger_os.core.instance.instance import default_instance_name, resolve_instance_dir

    name = instance_name or default_instance_name()
    root = Path(resolve_instance_dir(name))
    return LifecyclePaths(run_dir=root / "run")


# ── subcommand implementations ────────────────────────────────────


def _cmd_start(lifecycle: Lifecycle) -> int:
    """``jaeger start`` — fork the daemon into the background.

    The Phase-1 daemon just runs the server with its three builtin ops.
    Phase 2 swaps in a serve() that calls boot_for_daemon first."""
    forker = real_forker(paths=lifecycle.paths, serve=_phase1_serve_factory(lifecycle.paths))
    result = lifecycle.start(forker=forker)
    if result.ok:
        print(result.message)
        return 0
    print(result.message, file=sys.stderr)
    return 1


def _phase1_serve_factory(paths: LifecyclePaths):
    """Build the ``serve`` callable the forker hands to the child.

    Wrapped in a factory so the closure captures ``paths`` without us
    having to keep references to mutable state. The serve callable
    blocks forever — ``serve_forever`` inside the Server's accept
    thread, with the main thread waiting on a SIGTERM-driven event.
    """
    def serve() -> None:
        import threading
        server = Server(socket_path=paths.socket_path)
        server.start()
        # Block the main thread on a shutdown event; SIGTERM flips it.
        shutdown = threading.Event()

        def _on_signal(signum, _frame):  # noqa: ANN001 — signal handler shape
            shutdown.set()

        import signal as _signal
        _signal.signal(_signal.SIGTERM, _on_signal)
        _signal.signal(_signal.SIGINT, _on_signal)

        try:
            shutdown.wait()
        finally:
            server.stop()
    return serve


def _cmd_stop(lifecycle: Lifecycle) -> int:
    result = lifecycle.stop()
    print(result.message)
    return 0 if result.ok else 1


def _cmd_status(lifecycle: Lifecycle) -> int:
    """Print the daemon status. Exits 0 if running, 1 if not — same
    convention as ``systemctl is-active`` so scripts can chain on it."""
    s = lifecycle.status()
    if s["running"]:
        # Try the live ping so we can show real uptime / agent state,
        # not just the on-disk PID file.
        live = _live_status(lifecycle)
        if live is not None:
            print(f"running (pid={s['pid']}, uptime={live.get('uptime_s', 0):.1f}s)")
        else:
            print(f"running (pid={s['pid']}; socket up but no response)")
        return 0
    print(f"not running ({s['reason']})")
    return 1


def _cmd_restart(lifecycle: Lifecycle) -> int:
    """Convenience verb — stop, then start. Used by the tray's Restart
    menu item. We don't do anything clever about handing the new daemon
    the old daemon's state; ``stop`` cleans up and ``start`` runs fresh."""
    stop_rc = _cmd_stop(lifecycle)
    if stop_rc != 0:
        return stop_rc
    return _cmd_start(lifecycle)


def _live_status(lifecycle: Lifecycle) -> dict | None:
    """Ping the socket for the daemon's self-reported status payload.
    Returns None if the daemon is up on disk but not answering."""
    try:
        with Client(socket_path=lifecycle.paths.socket_path,
                    connect_timeout=0.5, call_timeout=1.0) as c:
            resp = c.call("status")
        if resp.ok and isinstance(resp.result, dict):
            return resp.result
    except (DaemonNotRunning, TimeoutError, OSError):
        return None
    return None


# ── help text ──────────────────────────────────────────────────────


def _print_usage() -> None:
    print(
        "Usage: jaeger {start|stop|status|restart} [--instance NAME]\n"
        "\n"
        "  start    Bring the daemon up in the background.\n"
        "  stop     Send SIGTERM to the running daemon and clean up.\n"
        "  status   Show whether the daemon is running.\n"
        "  restart  Stop the running daemon and start a fresh one.\n"
        "\n"
        "Run ``jaeger`` with no subcommand to launch the in-process TUI"
        " as before.",
        file=sys.stderr,
    )


__all__ = ["SUBCOMMANDS", "dispatch", "is_daemon_subcommand"]


# ``python -m jaeger_os.daemon.cli start`` — direct entry so the
# end-to-end smoke test (and any operator who prefers it) can hit the
# lifecycle without booting ``jaeger_os.main``.
if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(dispatch(sys.argv[1:]))
