"""Background-process agent tools.

The long-running counterpart to ``run_python`` / ``run_in_venv``
(which are synchronous + capped). These start a process that outlives
the turn, then let the agent check on it later.

  • start_background(code, name)   — launch a detached Python process
  • list_background()              — every background process + status
  • check_background(process_id)   — one process's status + output
  • stop_background(process_id)    — terminate a running process

``start_background`` / ``stop_background`` are gated at WRITE_LOCAL
(tier 1) — they spawn / kill processes inside the instance. The read
tools are tier-0.
"""

from __future__ import annotations

from typing import Any

from ._common import _require_layout
from ..permissions import PermissionTier, requires_tier
from .. import processes as _proc


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="background",
    operation="start_background",
    summary="launch a long-running background process",
)
def start_background(code: str, name: str = "") -> dict[str, Any]:
    """Launch Python code as a detached background process that
    OUTLIVES the current turn.

    Use this — not run_python / run_in_venv — for work that genuinely
    takes minutes or longer: a long render, a bot that stays connected,
    a watcher. The code runs against the instance venv (installed
    packages are visible). Returns a ``process_id`` — use
    check_background to monitor it, stop_background to end it. Output
    streams to the process's log; nothing is lost when the turn ends."""
    layout = _require_layout()
    return _proc.start_background(layout, code, name=name)


def list_background() -> dict[str, Any]:
    """List every background process for this instance with live status
    (running / exited / stopped, exit code, elapsed). Read-only."""
    layout = _require_layout()
    return _proc.list_background(layout)


def check_background(process_id: str, lines: int = 20) -> dict[str, Any]:
    """Status of one background process plus the last ``lines`` lines of
    its output (default 20, max 2000 — raise it to read fuller output).
    Use this to see whether a process you started is still running and
    what it produced. Read-only."""
    layout = _require_layout()
    return _proc.process_status(layout, process_id, lines=lines)


@requires_tier(
    PermissionTier.WRITE_LOCAL,
    skill="background",
    operation="stop_background",
    summary="terminate a running background process",
)
def stop_background(process_id: str) -> dict[str, Any]:
    """Terminate a running background process by id."""
    layout = _require_layout()
    return _proc.stop_background(layout, process_id)
