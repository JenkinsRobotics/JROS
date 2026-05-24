"""Pytest configuration for the Jaeger-OS framework test suite.

Kept deliberately small — the framework tests are self-contained and do
not need fixtures. ``QT_QPA_PLATFORM`` is defaulted to ``offscreen`` so
any interface test that imports a GUI toolkit does not hard-abort on a
headless runner before pytest can report a normal result.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# Reset the live agent-status indicator before every test so state set
# in one test (e.g. the agent_status / TUI tests) doesn't leak into
# tests that assume a clean idle state. Tiny dict write; doesn't affect
# any test that doesn't read or write ``_pipeline["agent_status"]``.
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _reset_agent_status() -> None:
    """Reset the global live-activity snapshot to ``ready`` before each
    test. Prevents the previous test's status from bleeding into the
    next — important because ``set_agent_status`` is a process-global
    write, not a per-instance one."""
    try:
        from jaeger_os.main import set_agent_status
    except Exception:  # noqa: BLE001 — agent_status is optional during partial migrations
        return
    set_agent_status("ready", "")
