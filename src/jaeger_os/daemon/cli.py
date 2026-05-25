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
SUBCOMMANDS: frozenset[str] = frozenset({
    "start", "stop", "status", "restart", "tray", "bench",
})


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
    # Peel off ``bench`` BEFORE the lifecycle argparse — bench has its
    # own sub-verbs (``run`` / ``timing``) and its own flags
    # (``--tags`` / ``--limit`` / ``--ids``) that don't belong in the
    # lifecycle parser.
    if argv[0] == "bench":
        return _cmd_bench(list(argv[1:]))
    # Same for ``tray`` — the tray module has its own argparse
    # (``--instance`` / ``--poll-s`` / ``--kill-others``) and any
    # flag we add to it later shouldn't have to be re-declared here.
    if argv[0] == "tray":
        return _cmd_tray_argv(list(argv[1:]))
    parser = argparse.ArgumentParser(
        prog="jaeger", add_help=False,
        description="Jaeger daemon lifecycle commands.",
    )
    parser.add_argument("subcommand", choices=sorted(SUBCOMMANDS))
    parser.add_argument("--instance", default=None,
                        help="Instance name (default: $JAEGER_INSTANCE_NAME or 'default').")
    # Tray autolaunch — on by default for `jaeger start` / `restart` on
    # macOS (where rumps works); ``--no-tray`` opts out for headless
    # boxes or scripted starts.
    parser.add_argument("--tray", dest="tray", action="store_true",
                        default=None, help="Autolaunch the menu-bar tray (default on macOS).")
    parser.add_argument("--no-tray", dest="tray", action="store_false",
                        help="Skip the tray (headless / scripted starts).")
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)

    if args.help:
        _print_usage()
        return 0

    paths = _resolve_paths(args.instance)
    lifecycle = Lifecycle(paths=paths)

    if args.subcommand == "start":
        return _cmd_start(lifecycle, instance=args.instance,
                          want_tray=_want_tray(args.tray))
    if args.subcommand == "stop":
        return _cmd_stop(lifecycle)
    if args.subcommand == "status":
        return _cmd_status(lifecycle)
    if args.subcommand == "restart":
        return _cmd_restart(lifecycle, instance=args.instance,
                            want_tray=_want_tray(args.tray))
    if args.subcommand == "tray":
        return _cmd_tray(args.instance)
    _print_usage()
    return 2


def _cmd_bench(argv: list[str]) -> int:
    """``jaeger bench …`` — run the JROS benchmark suites.

    Two verbs today:

      * ``jaeger bench run [--tags …] [--ids …] [--limit N]``
        Runs the flat routing/multistep/multiturn/recovery corpus.
        Boots its own pipeline (cold) so the run reflects a fresh
        process — same shape that ``run_model_sweep.py`` invokes.

      * ``jaeger bench timing``
        Runs the wall-clock-per-prompt timing suite. Appends to the
        committed history file under ``benchmark/timing/``.

    Phase 2 plan: a ``--via-daemon`` flag that re-uses an already-
    booted daemon's model instead of paying the cold-load cost on
    every bench. For now the verb is its own subprocess and the
    daemon is a separate concern.
    """
    if not argv or argv[0] in ("-h", "--help"):
        _print_bench_usage()
        return 0 if argv else 2
    verb = argv[0]
    rest = argv[1:]
    repo = _repo_root()

    if verb == "run":
        # Forward every remaining flag verbatim — ``run_flat_bench.py``
        # owns the argument surface (``--tags`` / ``--ids`` / ``--limit``
        # / ``--no-warmup``); duplicating its argparse here would just
        # mean two places to update on a future flag.
        import subprocess
        script = repo / "benchmark" / "run_flat_bench.py"
        if not script.is_file():
            print(f"bench script missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    if verb == "timing":
        import subprocess
        script = repo / "benchmark" / "timing" / "bench.py"
        if not script.is_file():
            print(f"timing bench missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    print(f"unknown bench verb: {verb!r}", file=sys.stderr)
    _print_bench_usage()
    return 2


def _print_bench_usage() -> None:
    print(
        "usage: jaeger bench {run | timing} [bench-specific args]\n"
        "\n"
        "  run     — flat routing/multistep/multiturn/recovery corpus\n"
        "  timing  — wall-clock per-prompt timing suite\n"
        "\n"
        "  jaeger bench run --tags routing --limit 5\n"
        "  jaeger bench run --ids time_now,calc_sqrt\n"
        "  jaeger bench timing\n",
        file=sys.stderr,
    )


def _repo_root() -> Path:
    """The benchmark scripts live under ``<repo>/benchmark/``. From an
    installed wheel this resolves to wherever the source tree was
    expanded; from a dev checkout it's the working repo. Either way
    we walk up from the package root until we find a ``benchmark``
    sibling."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "benchmark").is_dir():
            return parent
    # Fall back to the package's package-root sibling — useful for
    # editable installs where ``__file__`` lives under ``src/``.
    return here.parents[3]


def _cmd_tray(instance: str | None) -> int:
    """``jaeger tray`` (no extra args) — back-compat helper used by
    the lifecycle argparse path that doesn't peel argv itself. The
    new entry is :func:`_cmd_tray_argv`, which forwards every flag
    to the tray module's own argparse."""
    extra: list[str] = []
    if instance:
        extra = ["--instance", instance]
    return _cmd_tray_argv(extra)


def _cmd_tray_argv(argv: list[str]) -> int:
    """``jaeger tray …`` — hand every remaining flag to the tray
    module's argparse. The tray owns ``--instance`` / ``--poll-s``
    / ``--kill-others``; adding a new flag there should not require
    a duplicate declaration here."""
    if sys.platform != "darwin":
        print("jaeger tray is macOS-only today (rumps).", file=sys.stderr)
        return 2
    try:
        from jaeger_os.interfaces.tray.macos import main as tray_main
    except ImportError as exc:
        print(f"jaeger tray needs rumps — pip install rumps  ({exc})",
              file=sys.stderr)
        return 1
    return tray_main(argv)


def _want_tray(flag: bool | None) -> bool:
    """Resolve the tray autolaunch decision. Explicit ``--tray`` /
    ``--no-tray`` wins; otherwise default to True on macOS (where
    rumps is supported) and False everywhere else."""
    if flag is not None:
        return flag
    return sys.platform == "darwin"


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


def _cmd_start(lifecycle: Lifecycle, *,
               instance: str | None = None,
               want_tray: bool = False) -> int:
    """``jaeger start`` — fork the daemon into the background.

    The Phase-1 daemon just runs the server with its three builtin ops.
    Phase 2 swaps in a serve() that calls boot_for_daemon first.

    When ``want_tray`` is True we also fire-and-forget a menu-bar
    tray process so the user gets a visible 🤖 indicator. The tray
    is dumb — it just polls ``Lifecycle.status()`` and shells out to
    ``jaeger`` for click handlers; a crash there can't take the
    daemon down."""
    forker = real_forker(paths=lifecycle.paths, serve=_phase1_serve_factory(lifecycle.paths))
    result = lifecycle.start(forker=forker)
    if not result.ok:
        print(result.message, file=sys.stderr)
        return 1
    print(result.message)
    if want_tray:
        _spawn_tray(instance)
    return 0


def _spawn_tray(instance: str | None) -> None:
    """Fork the menu-bar tray as a detached process. Best-effort —
    a tray-import failure (no ``rumps`` installed, not on macOS,
    etc.) is logged to stderr but never blocks the daemon start.

    The tray is its OWN process, not a daemon child, so a tray
    crash leaves the daemon untouched and vice versa."""
    import shutil
    import subprocess
    if sys.platform != "darwin":
        # Other platforms have no tray adapter yet — silent skip.
        return
    # Skip if rumps isn't installed; running the tray module would
    # just error and confuse the user.
    try:
        import importlib.util
        if importlib.util.find_spec("rumps") is None:
            print("[jaeger] tray skipped — install rumps to enable: "
                  "pip install rumps", file=sys.stderr)
            return
    except Exception:  # noqa: BLE001
        return
    # Tray singleton — don't spawn a duplicate if one is already in
    # the menu bar. Previously every ``jaeger start`` / ``restart``
    # left a stale icon behind; the slot file gates that.
    try:
        from pathlib import Path as _Path

        from jaeger_os.core.instance.instance import (
            default_instance_name as _default, resolve_instance_dir as _resolve,
        )
        from jaeger_os.interfaces.tray.singleton import existing_tray_pid
        _name = instance or _default()
        _run_dir = _Path(_resolve(_name)) / "run"
        if existing_tray_pid(_run_dir) is not None:
            # Already up — silent skip. The user can see the icon
            # already; no need for a "tray skipped" line.
            return
    except Exception:  # noqa: BLE001 — slot check is advisory
        pass
    # Prefer the installed `jaeger` entry point; fall back to running
    # the tray module via the current interpreter (dev checkout).
    jaeger = shutil.which("jaeger")
    if jaeger:
        cmd = [jaeger, "tray"]
    else:
        cmd = [sys.executable, "-m", "jaeger_os.interfaces.tray.macos"]
    if instance:
        cmd += ["--instance", instance]
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger] tray failed to launch: {exc}", file=sys.stderr)


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


def _cmd_restart(lifecycle: Lifecycle, *,
                 instance: str | None = None,
                 want_tray: bool = False) -> int:
    """Convenience verb — stop, then start. Used by the tray's Restart
    menu item. We don't do anything clever about handing the new daemon
    the old daemon's state; ``stop`` cleans up and ``start`` runs fresh."""
    stop_rc = _cmd_stop(lifecycle)
    if stop_rc != 0:
        return stop_rc
    return _cmd_start(lifecycle, instance=instance, want_tray=want_tray)


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
        "Usage: jaeger {start|stop|status|restart|tray|bench} "
        "[--instance NAME]\n"
        "\n"
        "  start    Bring the daemon up in the background.\n"
        "  stop     Send SIGTERM to the running daemon and clean up.\n"
        "  status   Show whether the daemon is running.\n"
        "  restart  Stop the running daemon and start a fresh one.\n"
        "  tray     Run the macOS menu-bar tray (foreground).\n"
        "  bench    Run a JROS benchmark — `jaeger bench run|timing`.\n"
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
