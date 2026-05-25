"""Tray singleton — one menu-bar icon per host at a time.

The bug we're guarding against: every ``jaeger start`` /
``jaeger restart`` previously fire-and-forgot a new tray process,
adding a fresh ○ icon to the menu bar without checking whether one
was already up. After a few restarts the menu bar fills with stale,
unresponsive icons (the user's screenshot showed eight of them).

Thin wrapper over :mod:`jaeger_os.core.runtime.process_slot` with
the slot name fixed at ``"tray"`` so the tray and the TUI don't
clobber each other's PID files in the same ``run/`` directory.

  * :func:`acquire_tray_slot` — called at rumps startup. Records
    this process's PID at ``<instance>/run/tray.pid``.
  * :func:`existing_tray_pid` — read by ``_spawn_tray`` before
    launching a new tray. Returns the live PID if a tray is already
    in the menu bar, or ``None`` if the slot is free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from jaeger_os.core.runtime.process_slot import acquire_slot, existing_slot_pid


_SLOT = "tray"


def existing_tray_pid(run_dir: Path) -> int | None:
    """Return the live PID of an existing tray for this instance, or
    ``None`` when the slot is free."""
    return existing_slot_pid(run_dir, _SLOT)


def acquire_tray_slot(run_dir: Path) -> Callable[[], None]:
    """Claim the tray slot for this process. See
    :func:`jaeger_os.core.runtime.process_slot.acquire_slot` for the
    full contract."""
    return acquire_slot(run_dir, _SLOT)


__all__ = ["acquire_tray_slot", "existing_tray_pid"]
