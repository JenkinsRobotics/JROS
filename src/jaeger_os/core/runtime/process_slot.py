"""Generic per-process singleton slot — one TUI, one tray, etc.

The bug we're guarding against: a detached UI process (TUI window,
menu-bar tray) is fire-and-forget by design, so the launcher has no
handle to detect "one is already running" without help from the
process itself. Without a slot file, a user who clicks ``Open TUI``
twice gets two windows; a daemon that auto-launches the tray on
``jaeger start`` adds a new menu-bar icon every restart.

The pattern is small enough that one helper module covers every
singleton in the repo:

  * ``acquire_slot(run_dir, slot_name)`` — claim the slot for THIS
    process; writes ``<slot_name>.pid``, registers ``atexit``
    cleanup, returns the cleanup callable.
  * ``existing_slot_pid(run_dir, slot_name)`` — return the live PID
    of an existing owner, or ``None`` when the slot is free. Stale
    PID files (process gone, garbage contents) are cleaned up here.

Best-effort throughout — a PID-file mishap never blocks the process
it's supposed to gate. The worst case is the gate fails open and a
duplicate window appears; the user notices and closes one. Each
slot is scoped to its ``run_dir`` (typically ``<instance>/run/``),
so two DIFFERENT instances can each hold their own slot of the
same kind concurrently.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import Callable


def _slot_path(run_dir: Path, slot_name: str) -> Path:
    return run_dir / f"{slot_name}.pid"


def _pid_alive(pid: int) -> bool:
    """True when ``pid`` names a live process. ``os.kill(pid, 0)`` is
    a no-op signal that raises if the process is gone."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    return True


def existing_slot_pid(run_dir: Path, slot_name: str) -> int | None:
    """Return the live PID of an existing owner for ``slot_name``, or
    ``None`` when the slot is free. Stale PID files (process gone or
    garbage contents) are deleted as a side effect so the next caller
    can claim the slot."""
    pid_file = _slot_path(run_dir, slot_name)
    if not pid_file.is_file():
        return None
    try:
        recorded = int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        # Corrupted contents — treat as stale, clean up.
        try:
            pid_file.unlink()
        except OSError:
            pass
        return None
    if _pid_alive(recorded) and recorded != os.getpid():
        return recorded
    # Stale — process gone. Drop the file and report the slot free.
    try:
        pid_file.unlink()
    except OSError:
        pass
    return None


def acquire_slot(run_dir: Path, slot_name: str) -> Callable[[], None]:
    """Claim the slot for this process. Writes the PID file and
    registers an ``atexit`` cleanup. Returns the cleanup callable so
    the caller can also wire it into a signal handler if desired.

    Idempotent: re-calling overwrites the PID with this process's
    own PID, which is fine — the slot is ours either way.

    Caller MUST decide what to do when the slot is already taken —
    this function just claims it. Use :func:`existing_slot_pid` to
    check first."""
    run_dir.mkdir(parents=True, exist_ok=True)
    pid_file = _slot_path(run_dir, slot_name)
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        def _noop() -> None:
            pass
        return _noop

    def _cleanup() -> None:
        try:
            # Only remove if we still own it — a concurrent reclaim
            # by another process shouldn't be clobbered by our cleanup.
            if pid_file.is_file():
                recorded = int(pid_file.read_text(encoding="utf-8").strip())
                if recorded == os.getpid():
                    pid_file.unlink()
        except (ValueError, OSError):
            pass

    atexit.register(_cleanup)
    return _cleanup


__all__ = ["acquire_slot", "existing_slot_pid"]
