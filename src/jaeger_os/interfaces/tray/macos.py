"""macOS menu-bar tray — ``rumps`` adapter wired to the tray logic.

Two responsibilities:

  1. Render the :mod:`.base` model in the macOS menu bar.
  2. Wire menu clicks to subprocesses (``jaeger start|stop|restart`` etc.).

It explicitly does **not** import the agent or pipeline; every action
is an ``subprocess.Popen([...])``. Same constraint Lilith's ``tray.py``
follows — keeping the GUI dumb means a crash in the rumps event loop
can't take the daemon down with it.

Run via::

    python -m jaeger_os.interfaces.tray.macos [--instance NAME] [--poll-s 2.0]

The tray polls ``Lifecycle.status()`` on its own (no daemon round-trip)
so it works even when the daemon is down — that's the whole point.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from jaeger_os.daemon.lifecycle import Lifecycle, LifecyclePaths
from jaeger_os.interfaces.tray.base import (
    MenuItem,
    SEPARATOR,
    TrayActions,
    TrayModel,
    TrayState,
    glyph_for,
    menu_items_for,
)


# ── subprocess helpers ────────────────────────────────────────────


def _jaeger_executable() -> list[str]:
    """How to spawn the ``jaeger`` CLI from a GUI subprocess. Prefer a
    ``jaeger`` on PATH (installed entry point); fall back to running
    the package via the current interpreter so a development checkout
    works without ``pip install -e .``."""
    on_path = shutil.which("jaeger")
    if on_path:
        return [on_path]
    return [sys.executable, "-m", "jaeger_os"]


def _spawn(args: list[str], *, env: dict[str, str] | None = None) -> None:
    """Fire-and-forget subprocess. The tray doesn't care about stdout/
    exit code — the daemon's status poll will report the outcome on
    the next tick (or not, if the spawn itself failed silently). We
    redirect stdio so a noisy subprocess doesn't ride the tray's
    Console output."""
    subprocess.Popen(
        args,
        env=env or os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _open_terminal_running(cmd: str) -> None:
    """Open Terminal.app and run ``cmd`` inside a fresh window.

    We use ``osascript`` instead of ``open -a Terminal`` because the
    latter only opens the *app* — it doesn't carry a command to run.
    Terminal.app's AppleScript ``do script`` is the documented way to
    spawn a window with a command pre-typed."""
    script = f'tell application "Terminal" to do script "{cmd}"'
    _spawn(["osascript", "-e", script])


# ── action handlers ───────────────────────────────────────────────


def _make_actions(instance: str | None) -> TrayActions:
    """Build the six closures the menu fires. They're tiny — one
    subprocess each — so we just inline them here."""
    inst_args = ["--instance", instance] if instance else []
    jaeger = _jaeger_executable()

    def start() -> None:
        _spawn([*jaeger, "start", *inst_args])

    def stop() -> None:
        _spawn([*jaeger, "stop", *inst_args])

    def restart() -> None:
        _spawn([*jaeger, "restart", *inst_args])

    def open_tui() -> None:
        # When the daemon is up, the right verb is ``jaeger attach``
        # (Phase 2 wires it). Until then, ``jaeger`` standalone is the
        # in-process TUI — same agent, fresh process. We use the same
        # command in both cases; the binary picks the right path.
        cmd = " ".join(jaeger + (["--instance", instance] if instance else []))
        _open_terminal_running(cmd)

    def open_web() -> None:
        # Disabled in the menu today; the handler is registered so the
        # day it lights up we don't have to touch the wiring.
        _spawn(["open", "http://127.0.0.1:9119/"])

    def about() -> None:
        # rumps.alert is the obvious place for this, but importing
        # rumps here would break the unit-testable module boundary.
        # The MacosTray class below installs its own about callback
        # via rumps directly when it builds the app.
        pass

    def quit_tray() -> None:
        # The macOS adapter overrides this with rumps.quit_application
        # at construction time. The fallback exits the process cleanly.
        os._exit(0)

    return TrayActions(
        start=start, stop=stop, restart=restart,
        open_tui=open_tui, open_web=open_web,
        about=about, quit_tray=quit_tray,
    )


# ── the rumps app ─────────────────────────────────────────────────


class MacosTray:
    """``rumps``-backed tray. Constructed lazily so the module imports
    cleanly off macOS / in CI — ``rumps`` only loads inside ``run()``."""

    def __init__(self, *, lifecycle: Lifecycle, actions: TrayActions,
                 poll_s: float = 2.0) -> None:
        self.lifecycle = lifecycle
        self.actions = actions
        self.poll_s = poll_s
        self.model = TrayModel()
        self._app: Any = None    # rumps.App, populated in run()

    def run(self) -> None:
        """Start the rumps event loop. Blocks until quit."""
        import rumps    # local import so the module is testable off macOS

        # Initial state — pessimistic. The first poll will correct it.
        title = glyph_for(self.model.state)
        self._app = rumps.App("Jaeger", title=title, quit_button=None)

        # Build the menu the first time.
        self._rebuild_menu()

        # Poll the daemon status; on change, rebuild + retint.
        @rumps.timer(self.poll_s)
        def _tick(sender):       # noqa: ANN001 — rumps timer shape
            try:
                snapshot = self.lifecycle.status()
            except Exception:    # noqa: BLE001 — tray must never crash
                return
            if self.model.update(snapshot):
                self._rebuild_menu()
                # Update the menu-bar glyph too.
                self._app.title = glyph_for(self.model.state)

        # Wire Quit Tray to rumps.quit_application so the event loop
        # actually exits (os._exit is a fallback for non-rumps mains).
        object.__setattr__(self.actions, "quit_tray",
                           lambda: rumps.quit_application())
        object.__setattr__(self.actions, "about",
                           lambda: rumps.alert(
                               title="Jaeger",
                               message="Jaeger menu-bar tray\n"
                                       "Phase 1.6 — lifecycle controls",
                           ))

        self._app.run()

    # ── menu plumbing ──────────────────────────────────────────────

    def _rebuild_menu(self) -> None:
        """Tear down the rumps Menu and rebuild it from the current
        :func:`menu_items_for` output. Cheaper than diffing — the menu
        has fewer than 10 items."""
        import rumps

        self._app.menu.clear()
        for item in menu_items_for(self.model.state):
            if item.label == "-":
                self._app.menu.add(rumps.separator)
                continue
            if item.action is None:
                # Status label — non-clickable header row.
                mi = rumps.MenuItem(item.label)
                mi.set_callback(None)
                self._app.menu.add(mi)
                continue
            action_name = item.action
            handler = self._make_click_handler(action_name)
            mi = rumps.MenuItem(item.label, callback=handler)
            if not item.enabled:
                mi.set_callback(None)   # rumps idiom for grey-out
            self._app.menu.add(mi)

    def _make_click_handler(self, action_name: str):
        """Build a closure rumps can call with its own ``(sender,)``
        signature. We don't pass sender into our action callbacks
        because the action is fully described by ``action_name`` —
        no per-item state to inspect."""
        def _on_click(sender):  # noqa: ANN001 — rumps shape
            self.actions.dispatch(action_name)
        return _on_click


# ── entry point ───────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger-tray",
        description="Menu-bar indicator + lifecycle controls for the Jaeger daemon.",
    )
    parser.add_argument("--instance", default=None,
                        help="Instance name (default: $JAEGER_INSTANCE_NAME or 'default').")
    parser.add_argument("--poll-s", type=float, default=2.0,
                        help="Polling cadence in seconds (default: 2.0).")
    args = parser.parse_args(argv)

    # Lifecycle is independent of the agent — same `run/` resolution as
    # the daemon CLI, so the tray and `jaeger status` see the same files.
    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    name = args.instance or default_instance_name()
    root = Path(resolve_instance_dir(name))
    paths = LifecyclePaths(run_dir=root / "run")
    lifecycle = Lifecycle(paths=paths)

    actions = _make_actions(args.instance)

    try:
        tray = MacosTray(lifecycle=lifecycle, actions=actions, poll_s=args.poll_s)
        tray.run()
    except ImportError as exc:
        print(
            f"jaeger-tray needs ``rumps`` (macOS): pip install rumps\n  ({exc})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover — GUI entry
    sys.exit(main())
