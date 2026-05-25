"""Generic per-process singleton slot.

The TUI and the tray both need "is one already running?" gates and
the pattern is small enough to share. This file pins:

  * the helper is reusable with different slot names in the same
    run/ directory (TUI and tray don't clobber each other)
  * stale PID files are auto-cleaned
  * cleanup respects ownership (a reclaimed slot isn't clobbered
    by the old owner's atexit)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jaeger_os.core.runtime.process_slot import (
    acquire_slot, existing_slot_pid,
)


def _slot_file(run_dir: Path, name: str) -> Path:
    return run_dir / f"{name}.pid"


def test_acquire_writes_named_pid_file(tmp_path):
    """The slot name controls the filename so multiple kinds of
    singletons can share the same run_dir without colliding."""
    cleanup = acquire_slot(tmp_path, "myslot")
    try:
        assert _slot_file(tmp_path, "myslot").is_file()
        assert int(_slot_file(tmp_path, "myslot").read_text()) == os.getpid()
    finally:
        cleanup()


def test_two_slots_in_same_run_dir_dont_collide(tmp_path):
    """The TUI and tray both live under ``<instance>/run/`` —
    different slot names must produce different files."""
    c1 = acquire_slot(tmp_path, "tui")
    c2 = acquire_slot(tmp_path, "tray")
    try:
        assert _slot_file(tmp_path, "tui").is_file()
        assert _slot_file(tmp_path, "tray").is_file()
        # Independent removal — one cleanup must not touch the other.
        c1()
        assert not _slot_file(tmp_path, "tui").is_file()
        assert _slot_file(tmp_path, "tray").is_file()
    finally:
        c2()


def test_existing_slot_pid_finds_live_holder(tmp_path):
    """Init/launchd (PID 1) is always alive on every Unix host —
    use it as a stand-in for 'some other live process holds the
    slot'."""
    _slot_file(tmp_path, "tray").write_text("1")
    assert existing_slot_pid(tmp_path, "tray") == 1


def test_existing_slot_pid_cleans_up_stale_file(tmp_path):
    """A PID file pointing at a dead process must not block a new
    owner — the lookup deletes the stale file as a side effect."""
    _slot_file(tmp_path, "tray").write_text("999999")
    assert existing_slot_pid(tmp_path, "tray") is None
    assert not _slot_file(tmp_path, "tray").is_file()


def test_existing_slot_pid_returns_none_for_empty_slot(tmp_path):
    assert existing_slot_pid(tmp_path, "anything") is None


def test_cleanup_does_not_clobber_a_reclaimed_slot(tmp_path):
    """If another process reclaimed the slot before we exited, our
    atexit must NOT remove their PID file — only delete it when the
    recorded PID is still ours."""
    cleanup = acquire_slot(tmp_path, "tray")
    # Simulate a takeover.
    _slot_file(tmp_path, "tray").write_text("12345")
    cleanup()
    assert _slot_file(tmp_path, "tray").is_file()
    # Clean up so other tests don't see this file.
    _slot_file(tmp_path, "tray").unlink()
