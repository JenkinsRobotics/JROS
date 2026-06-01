"""Daemon child entry point — runs in the spawned subprocess.

``jaeger start`` spawns a NEW Python process for the daemon (instead
of forking) because Apple's Objective-C runtime aborts a forked child
the first time it touches a class the parent initialized. Python's
stdlib (ssl, locale, …) drags Obj-C in during interpreter startup, so
by the time we'd ``os.fork()`` from ``jaeger start``, the parent has
already poisoned the well — llama-cpp-python's Metal backend dies
silently inside ``ggml_metal_device_init`` in the forked child.

Spawning a fresh interpreter sidesteps the problem: the new process
starts with ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` already in its
environment (we set it via ``subprocess.Popen(env=...)`` in
``lifecycle.spawn_forker``), Obj-C never registers the fork-safety
guard, and Metal initializes cleanly.

This module is intentionally tiny — argparse, setsid, dup2 to the
log file, then call ``serve()`` (the agent boot + chat-ops registry
lives in ``daemon.cli._agent_serve_factory``). Anything heavier here
re-introduces the same fork-state surface we just escaped.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _redirect_stdio_to_log(log_path: Path) -> None:
    """Match ``lifecycle.real_forker``'s child-side stdio redirect so
    every ``print`` lands in ``<instance>/run/jaeger.log``."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fd_null = os.open(os.devnull, os.O_RDONLY)
    fd_log = os.open(
        str(log_path),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600,
    )
    os.dup2(fd_null, 0)
    os.dup2(fd_log, 1)
    os.dup2(fd_log, 2)
    os.close(fd_null)
    os.close(fd_log)
    # Reopen Python's stdout/stderr wrappers with line buffering so
    # ``print(..., flush=True)`` reliably reaches the log file even
    # if a boot step crashes mid-flight.
    sys.stdout = os.fdopen(1, "w", buffering=1)
    sys.stderr = os.fdopen(2, "w", buffering=1)


def main() -> int:
    parser = argparse.ArgumentParser(prog="jaeger-daemon-child")
    parser.add_argument("--instance", default=None,
                        help="instance name; default = JAEGER_INSTANCE_NAME or 'default'")
    parser.add_argument("--run-dir", required=True,
                        help="<instance>/run/ — where pid + socket + log live")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    log_path = run_dir / "jaeger.log"

    # The parent ``subprocess.Popen(start_new_session=True)`` already
    # called ``setsid`` for us, so we don't redo it here — a second
    # ``setsid`` raises ``PermissionError`` because the process is
    # already a session leader.
    _redirect_stdio_to_log(log_path)

    # Imports happen here, in the FRESH interpreter, with
    # OBJC_DISABLE_INITIALIZE_FORK_SAFETY already in env. From this
    # point Metal initializes cleanly during boot_for_daemon.
    #
    # 0.2.6: pre-0.2.0 legacy-layout migration removed (operators on
    # 0.1.0-shape were running prototypes; nothing operational to
    # migrate). Fresh installs go straight to the new
    # <install_root>/.jaeger_os/instances/ layout.

    from jaeger_os.daemon.cli import _agent_serve_factory
    from jaeger_os.daemon.lifecycle import LifecyclePaths

    paths = LifecyclePaths(run_dir=run_dir)
    serve = _agent_serve_factory(paths, instance_name=args.instance)
    try:
        serve()
    except BaseException:  # noqa: BLE001 — must not leak a traceback to no-one
        import traceback as _tb
        _tb.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
