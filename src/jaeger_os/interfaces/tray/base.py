"""Tray logic — state machine, glyph map, menu generation.

Pure-Python, no GUI imports. The rumps adapter (:mod:`.macos`) calls
into here for every decision it makes:

  - what icon glyph to render → :func:`glyph_for`
  - which menu items, with which enabled flags → :func:`menu_items_for`
  - how to interpret a status snapshot → :class:`TrayModel.update`
  - which callback fires for a menu click → :class:`TrayActions.dispatch`

A future Linux / Windows backend uses the same surface; only the
rendering layer changes.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── state ─────────────────────────────────────────────────────────


class TrayState(enum.Enum):
    """Coarse daemon health visible from the tray.

    Finer-grained agent state (``thinking``, ``running tool``, ...) is
    Phase-2 work — the tray won't show it directly because we'd be
    polling the agent loop every two seconds, which is the wrong
    cadence. That stays on the TUI's status bar."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# Black-and-white glyphs avoid the macOS dark-mode tint problem you get
# with coloured PNGs and let us ship without any image assets.
_GLYPHS: dict[TrayState, str] = {
    TrayState.STOPPED:  "○",
    TrayState.STARTING: "◐",
    TrayState.RUNNING:  "●",
    TrayState.ERROR:    "✕",
}


def glyph_for(state: TrayState) -> str:
    """One-character glyph that goes in the menu-bar slot."""
    return _GLYPHS[state]


# ── menu items ────────────────────────────────────────────────────


@dataclass(frozen=True)
class MenuItem:
    """One row in the tray's dropdown.

    ``label`` is the human-visible text. ``action`` is a string key —
    the GUI passes it back to :meth:`TrayActions.dispatch` on click.
    ``action=None`` makes the row a label (no callback). ``enabled``
    controls greyed-out state.

    Separators carry an empty label, no action, and ``enabled=False`` —
    the rumps adapter renders ``MenuItem(label="-")`` as a divider."""
    label: str
    action: str | None = None
    enabled: bool = True


SEPARATOR = MenuItem(label="-", action=None, enabled=False)


def _status_label(state: TrayState) -> MenuItem:
    text = {
        TrayState.STOPPED:  "Daemon: stopped",
        TrayState.STARTING: "Daemon: starting…",
        TrayState.RUNNING:  "Daemon: running",
        TrayState.ERROR:    "Daemon: error — restart needed",
    }[state]
    return MenuItem(label=text, action=None, enabled=False)


def menu_items_for(state: TrayState) -> list[MenuItem]:
    """The menu that should currently be visible. Recomputed on every
    state change; identical-state polls reuse the cached list."""
    running = state is TrayState.RUNNING
    stopped = state is TrayState.STOPPED
    return [
        _status_label(state),
        SEPARATOR,
        MenuItem(label="Start Daemon",   action="start",   enabled=stopped),
        MenuItem(label="Stop Daemon",    action="stop",    enabled=running),
        MenuItem(label="Restart Daemon", action="restart", enabled=running),
        SEPARATOR,
        # 'Open TUI' is always live: with the daemon running it's
        # `jaeger attach` (Phase 2); without, it's the standalone TUI.
        # The action handler picks the right invocation.
        MenuItem(label="Open TUI",            action="open_tui"),
        # Web dashboard not built yet — disabled placeholder so users
        # see it's coming.
        MenuItem(label="Open Web Dashboard",  action="open_web", enabled=False),
        SEPARATOR,
        MenuItem(label="About Jaeger",  action="about"),
        MenuItem(label="Quit Tray",     action="quit_tray"),
    ]


# ── model: status snapshot → state ────────────────────────────────


@dataclass
class TrayModel:
    """In-memory view of the daemon's health. The poller feeds
    ``Lifecycle.status()`` dicts in; the GUI reads ``state`` and
    ``last_changed`` to decide whether to redraw."""
    state: TrayState = TrayState.STOPPED
    pid: int | None = None
    reason: str = ""
    last_changed: float = field(default_factory=time.monotonic)

    def update(self, status: dict[str, Any]) -> bool:
        """Apply a status snapshot. Returns ``True`` if the visible
        state actually changed (so the GUI can short-circuit redraws)."""
        new_state = _state_from_status(status)
        new_pid = status.get("pid")
        new_reason = str(status.get("reason") or "")
        if (new_state == self.state
                and new_pid == self.pid
                and new_reason == self.reason):
            return False
        self.state = new_state
        self.pid = new_pid
        self.reason = new_reason
        self.last_changed = time.monotonic()
        return True


def _state_from_status(status: dict[str, Any]) -> TrayState:
    """Map a ``Lifecycle.status()`` dict onto a coarse :class:`TrayState`.

    Note ERROR isn't "exception raised" — it's "daemon is in a state we
    can't usefully act on from a tray click". Today that's just "PID
    alive but socket missing" — the daemon either crashed mid-start or
    is hanging. Either way the user-facing remedy is ``restart``."""
    if status.get("running"):
        return TrayState.RUNNING
    reason = str(status.get("reason") or "").lower()
    if "socket" in reason and status.get("pid") is not None:
        # Process is alive but not serving — wedged.
        return TrayState.ERROR
    # Everything else (no pid, stale pid, garbage pid) is plain off.
    return TrayState.STOPPED


# ── actions ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrayActions:
    """The six callbacks the menu can fire. ``dispatch`` is the
    indirection the GUI uses so it doesn't have to bind by identity:
    a menu item carries the action name as a string, the dispatcher
    routes it to the right closure."""
    start: Callable[[], None]
    stop: Callable[[], None]
    restart: Callable[[], None]
    open_tui: Callable[[], None]
    open_web: Callable[[], None]
    quit_tray: Callable[[], None]
    about: Callable[[], None] | None = None

    def dispatch(self, name: str | None) -> None:
        """Fire the named action if known; otherwise silently no-op so
        a click on a status label (action=None) doesn't crash."""
        if name is None:
            return
        handler = {
            "start": self.start,
            "stop": self.stop,
            "restart": self.restart,
            "open_tui": self.open_tui,
            "open_web": self.open_web,
            "quit_tray": self.quit_tray,
            "about": self.about,
        }.get(name)
        if handler is None:
            return
        handler()


__all__ = [
    "MenuItem",
    "SEPARATOR",
    "TrayActions",
    "TrayModel",
    "TrayState",
    "glyph_for",
    "menu_items_for",
]
