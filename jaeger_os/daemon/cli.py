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
  - menu-bar tray: removed in 0.2.6, replaced by the Swift desktop
    app in 0.3.0 (Ollama Desktop-style native app — one process owns
    the tray icon + chat window + voice surface, talks to this daemon
    over the same Unix socket).
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
# ``rich-tui`` is a daemon-attached client — distinct from the 0.1.0
# ``jaeger tui`` which boots in-process and stays untouched.
#
# INST-2 (0.2.0) adds the instance-lifecycle verbs alongside daemon
# lifecycle: ``setup``, ``instance``, ``migrate`` (and the
# upcoming ``backup``, ``restore``, ``update``).
SUBCOMMANDS: frozenset[str] = frozenset({
    "start", "stop", "status", "restart", "bench",
    "attach", "rich-tui",
    "setup", "instance", "migrate",
    "backup", "restore", "update",
    "skill", "memory", "kill", "health",
})


def is_daemon_subcommand(argv: Sequence[str]) -> bool:
    """``main.py`` calls this on ``sys.argv[1:]`` — True if the first
    word is one of our subcommands. ``--instance`` and the like are
    parsed AFTER the dispatch, so a flag-first argv falls through to
    the legacy path (we never had ``--start`` etc. before this).

    Also returns True for the removed-but-still-recognized ``tray``
    name so :func:`dispatch` can print a removal notice instead of
    letting the word slip through to the legacy ``prompt`` parser
    (where it would silently become a one-shot prompt of "tray")."""
    return len(argv) >= 1 and (argv[0] in SUBCOMMANDS or argv[0] == "tray")


def dispatch(argv: Sequence[str]) -> int:
    """Run the daemon subcommand named by ``argv[0]``. Returns the exit
    code the CLI should hand back to the OS."""
    if not argv:
        _print_usage()
        return 2
    # 0.2.6: the menu-bar tray was removed (the Swift desktop app
    # replaces it in 0.3.0). Print a clear notice instead of letting
    # the bare word slip through to the legacy parser.
    if argv[0] == "tray":
        print(
            "jaeger tray was removed in 0.2.6. The Swift desktop app\n"
            "(in 0.3.0) replaces it with a single-process native UI:\n"
            "tray icon + chat window + voice surface in one app.\n"
            "\n"
            "Until then, use the TUI directly:\n"
            "    ./run.sh --instance NAME            (standalone)\n"
            "    ./run.sh attach --instance NAME      (daemon-attached)\n"
            "    ./run.sh rich-tui --instance NAME    (daemon-attached, rich UI)\n",
            file=sys.stderr,
        )
        return 2
    # Peel off ``bench`` BEFORE the lifecycle argparse — bench has its
    # own sub-verbs (``run`` / ``timing``) and its own flags
    # (``--tags`` / ``--limit`` / ``--ids``) that don't belong in the
    # lifecycle parser.
    if argv[0] == "bench":
        return _cmd_bench(list(argv[1:]))
    # ``attach`` is a streaming client — peel it off here so its
    # ``--instance`` / ``--session`` flags don't have to be re-declared
    # in the lifecycle parser below.
    if argv[0] == "attach":
        from jaeger_os.daemon.attach import _cmd_attach_argv
        return _cmd_attach_argv(list(argv[1:]))
    # ``rich-tui`` — daemon-attached Rich UI. Its own argparse lives
    # in ``interfaces.rich_tui.__main__`` so this dispatcher doesn't
    # have to know about its flags. The existing ``jaeger tui`` (the
    # 0.1.0 in-process surface) is NOT in SUBCOMMANDS — it falls
    # through to ``main.py``'s legacy path, unchanged.
    if argv[0] == "rich-tui":
        from jaeger_os.interfaces.rich_tui.__main__ import main as _rich_main
        return _rich_main(list(argv[1:]))
    # INST-2 verbs — instance lifecycle. Each has its own argparse
    # in ``daemon.instance_verbs`` so flags don't fight the
    # lifecycle parser.
    if argv[0] == "setup":
        from jaeger_os.daemon.instance_verbs import _cmd_setup_argv
        return _cmd_setup_argv(list(argv[1:]))
    if argv[0] == "instance":
        from jaeger_os.daemon.instance_verbs import _cmd_instance_argv
        return _cmd_instance_argv(list(argv[1:]))
    if argv[0] == "migrate":
        from jaeger_os.daemon.instance_verbs import _cmd_migrate_argv
        return _cmd_migrate_argv(list(argv[1:]))
    if argv[0] == "backup":
        from jaeger_os.daemon.backup_restore import _cmd_backup_argv
        return _cmd_backup_argv(list(argv[1:]))
    if argv[0] == "restore":
        from jaeger_os.daemon.backup_restore import _cmd_restore_argv
        return _cmd_restore_argv(list(argv[1:]))
    if argv[0] == "update":
        from jaeger_os.daemon.update_verb import _cmd_update_argv
        return _cmd_update_argv(list(argv[1:]))
    if argv[0] == "skill":
        from jaeger_os.daemon.skill_verbs import _cmd_skill_argv
        return _cmd_skill_argv(list(argv[1:]))
    if argv[0] == "memory":
        from jaeger_os.daemon.memory_verbs import _cmd_memory_argv
        return _cmd_memory_argv(list(argv[1:]))
    if argv[0] == "kill":
        from jaeger_os.daemon.kill_verb import _cmd_kill_argv
        return _cmd_kill_argv(list(argv[1:]))
    if argv[0] == "health":
        from jaeger_os.daemon.health_verb import _cmd_health_argv
        return _cmd_health_argv(list(argv[1:]))
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
        return _cmd_start(lifecycle, instance=args.instance)
    if args.subcommand == "stop":
        return _cmd_stop(lifecycle)
    if args.subcommand == "status":
        return _cmd_status(lifecycle)
    if args.subcommand == "restart":
        return _cmd_restart(lifecycle, instance=args.instance)
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
        script = repo / "dev_benchmark" / "run_flat_bench.py"
        if not script.is_file():
            print(f"bench script missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    if verb == "timing":
        import subprocess
        script = repo / "dev_benchmark" / "timing" / "bench.py"
        if not script.is_file():
            print(f"timing bench missing at {script}", file=sys.stderr)
            return 1
        return subprocess.call([sys.executable, str(script), *rest])

    if verb == "compare":
        from jaeger_os.daemon.bench_compare_verb import _cmd_bench_compare_argv
        return _cmd_bench_compare_argv(rest)

    if verb == "history":
        from jaeger_os.daemon.bench_history_verb import _cmd_bench_history_argv
        return _cmd_bench_history_argv(rest)

    print(f"unknown bench verb: {verb!r}", file=sys.stderr)
    _print_bench_usage()
    return 2


def _print_bench_usage() -> None:
    print(
        "usage: jaeger bench {run | timing | compare | history} "
        "[bench-specific args]\n"
        "\n"
        "  run     — flat routing/multistep/multiturn/recovery corpus\n"
        "  timing  — wall-clock per-prompt timing suite\n"
        "  compare — pick multiple models from a list, bench each,\n"
        "            write a comparison report (operator-driven)\n"
        "  history — rolling leaderboard across every model ever\n"
        "            benched on this machine (sweep + flat artifacts)\n"
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
        if (parent / "dev_benchmark").is_dir():
            return parent
    # Fall back to the package's package-root sibling — useful for
    # editable installs where ``__file__`` lives under ``src/``.
    return here.parents[3]


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
               instance: str | None = None) -> int:
    """``jaeger start`` — fork the daemon into the background.

    The daemon's child branch loads the model + builds the agent
    (``boot_for_daemon``) before the socket starts accepting. From
    that point ``chat.send`` / ``chat.history`` / ``status.snapshot``
    are live and any client (TUI / attach / GUI) can drive the agent
    that just booted.

    0.2.6: the menu-bar tray was removed in this release; the Swift
    desktop app that replaces it in 0.3.0 owns its own lifecycle.
    """
    forker = real_forker(paths=lifecycle.paths, instance_name=instance)
    result = lifecycle.start(forker=forker)
    if not result.ok:
        print(result.message, file=sys.stderr)
        return 1
    print(result.message)
    return 0


def _agent_serve_factory(paths: LifecyclePaths, *, instance_name: str | None = None):
    """Build the ``serve`` callable the forker hands to the child.

    Wrapped in a factory so the closure captures ``paths`` +
    ``instance_name`` without us having to keep references to mutable
    state. The serve callable blocks forever — ``serve_forever`` inside
    the Server's accept thread, with the main thread waiting on a
    SIGTERM-driven event.

    Child branch sequence:
      1. Bind the NDJSON socket immediately (with stub chat ops that
         answer "still booting"). This lets ``jaeger start`` return
         within its 5s readiness window even for slow model loads.
      2. Boot the agent on a background thread — ``boot_for_daemon``
         takes the instance lock, binds tools, loads the model,
         builds the agent.
      3. Once boot finishes, swap the stubs for the production
         chat / history / snapshot handlers.
      4. Block on SIGTERM/SIGINT; on shutdown stop the server and
         release the instance lock + extension subsystems.

    If boot raises (model file missing, instance corrupt, etc.), the
    failure is logged AND surfaced via ``status.snapshot``'s
    ``boot_error`` field so clients can read what happened. The daemon
    keeps the socket up so ``jaeger stop`` works cleanly.
    """
    def serve() -> None:
        import faulthandler
        import signal as _signal
        import sys as _sys
        import threading
        import time as _time
        import traceback

        # Native-level crash dumps go to the log instead of dying
        # silently. Catches the llama-cpp/Metal ``ggml_abort`` paths
        # and friends that bypass Python's exception machinery.
        faulthandler.enable(file=_sys.stderr, all_threads=True)

        # Imports inside the closure so the import cost is paid by the
        # child branch only.
        from jaeger_os.daemon.chat_ops import (
            register_booting_stubs,
            register_chat_ops,
        )

        progress: dict[str, Any] = {
            "started_at": _time.time(),
            "ready": False,
            "error": None,
        }

        server = Server(socket_path=paths.socket_path)
        register_booting_stubs(server, progress)
        # ``Server.start()`` spawns its own accept thread for the socket
        # — it does NOT block the caller — so we can do the model load
        # right here on the main thread. That matters on macOS: llama-
        # cpp-python's Metal backend can only safely initialize from
        # the main thread of the process. Booting on a worker thread
        # (what we tried first) dies inside ``ggml_metal_device_init``
        # with no Python traceback. ``register_booting_stubs`` keeps
        # the socket usable for ``status.snapshot`` / ``ping`` during
        # the boot window so clients see "still booting", not a refused
        # connection.
        server.start()
        print(f"[jaeger-daemon] listening on {paths.socket_path}; "
              "loading agent on main thread…", flush=True)

        boot: Any = None
        try:
            from jaeger_os.main import boot_for_daemon
            print(f"[jaeger-daemon] booting agent for instance "
                  f"{instance_name or 'default'}…", flush=True)
            boot = boot_for_daemon(
                instance_name=instance_name,
                with_memory=True,
                warmup=True,
            )
            register_chat_ops(server, boot)
            progress["ready"] = True
            print(f"[jaeger-daemon] agent ready (instance "
                  f"{boot.layout.root}).", flush=True)
        except Exception as exc:  # noqa: BLE001
            progress["error"] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            print(f"[jaeger-daemon] BOOT FAILED: {exc}", flush=True)
            # Don't return — keep the socket alive so a client can
            # call ``status.snapshot`` and read ``boot_error``, and so
            # ``jaeger stop`` works cleanly to clean up. The stubs
            # still answer "agent is still booting" for chat.send.
            # Don't return — keep the socket alive so a client can
            # call ``status.snapshot`` and read ``boot_error``, and so
            # ``jaeger stop`` works cleanly to clean up. The stubs
            # still answer "agent is still booting" for chat.send.

        shutdown = threading.Event()

        def _on_signal(signum, _frame):  # noqa: ANN001 — signal handler shape
            print(f"[jaeger-daemon] signal {signum} — shutting down…",
                  flush=True)
            shutdown.set()

        _signal.signal(_signal.SIGTERM, _on_signal)
        _signal.signal(_signal.SIGINT, _on_signal)

        try:
            shutdown.wait()
        finally:
            try:
                server.stop()
            finally:
                if boot is not None:
                    try:
                        boot.cleanup()
                    except Exception:  # noqa: BLE001
                        pass
            print("[jaeger-daemon] stopped.", flush=True)
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
                 instance: str | None = None) -> int:
    """Convenience verb — stop, then start. We don't do anything clever
    about handing the new daemon the old daemon's state; ``stop`` cleans
    up and ``start`` runs fresh."""
    stop_rc = _cmd_stop(lifecycle)
    if stop_rc != 0:
        return stop_rc
    return _cmd_start(lifecycle, instance=instance)


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
        "Usage: jaeger {start|stop|status|restart|kill|health|bench} "
        "[--instance NAME]\n"
        "\n"
        "  start    Bring the daemon up in the background.\n"
        "  stop     Send SIGTERM to the running daemon and clean up.\n"
        "  kill     Force-stop every jaeger process + sweep stale\n"
        "           lock files. Use when the TUI is hung on a Metal\n"
        "           stall and Ctrl-C won't break out. Idempotent.\n"
        "  status   Show whether the daemon is running.\n"
        "  restart  Stop the running daemon and start a fresh one.\n"
        "  health   Runtime substrate probe (post-boot diagnostics).\n"
        "           Pairs with ``--doctor`` which checks deps BEFORE\n"
        "           boot. ``--deep`` adds live agent-loop turns.\n"
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
