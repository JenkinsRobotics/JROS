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
    icon_path_for,
    menu_items_for,
)


# ── subprocess helpers ────────────────────────────────────────────


def _repo_root() -> Path:
    """Return the JROS repo root (parent of ``jaeger_os/``).

    This module lives at ``<repo>/jaeger_os/interfaces/tray/macos.py``,
    so three parents up lands on the repo root that owns ``run.sh``."""
    return Path(__file__).resolve().parents[3]


def _jaeger_executable() -> list[str]:
    """How to spawn the JROS CLI from a GUI subprocess.

    0.2.6: the canonical entry point is ``./run.sh`` in the repo root.
    It sets ``PYTHONPATH`` to the repo (required for ``import
    jaeger_os`` to work in fresh child shells), picks the venv's
    Python, and forwards all args to ``jaeger_os.run``. Earlier
    versions of this helper preferred ``shutil.which('jaeger')`` —
    that's a 0.2.2-era pip console-script and now points at a layout
    that no longer exists. Calling it from the tray would crash with
    ``ModuleNotFoundError: jaeger_os`` because the AppleScript ``do
    script`` path starts a fresh Terminal shell that inherits no
    ``PYTHONPATH`` from us.

    Returning ``run.sh`` is robust across both cases: the tray's
    own ``subprocess.Popen`` and the AppleScript path both end up
    invoking a shell wrapper that handles PYTHONPATH explicitly."""
    return [str(_repo_root() / "run.sh")]


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


def _activate_terminal() -> None:
    """Bring Terminal.app to the foreground without opening a new
    window. Used when an existing TUI is already running and the user
    clicked Open TUI again — we just surface the existing window
    rather than spawning a duplicate."""
    _spawn(["osascript", "-e", 'tell application "Terminal" to activate'])


def _daemon_socket_present_for(instance: str | None) -> bool:
    """True when the daemon socket exists for the given instance —
    cheap proxy for 'daemon is running and accepting connections'.

    Used by ``open_voice`` to decide whether to launch the voice loop
    in --attach mode (saves loading a second ~16 GB model) or in the
    standalone path (loads its own client).

    Best-effort: any import / resolution failure returns False so the
    caller falls back to standalone — never a crash, never a fake
    attach attempt against a missing daemon."""
    try:
        from pathlib import Path

        from jaeger_os.core.instance.instance import (
            default_instance_name, resolve_instance_dir,
        )
        name = instance or default_instance_name()
        sock = Path(resolve_instance_dir(name)) / "run" / "jaeger.sock"
        return sock.exists()
    except Exception:  # noqa: BLE001 — best-effort detection
        return False


def _existing_tui_pid_for(instance: str | None) -> int | None:
    """Check the per-instance TUI PID file. Returns the live PID if a
    TUI is already running, or ``None`` when the slot is free. Best-
    effort: any import / lookup failure is treated as 'no existing
    TUI' so the click still opens a window."""
    try:
        from pathlib import Path

        from jaeger_os.core.instance.instance import (
            default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.interfaces.tui.singleton import existing_tui_pid
        name = instance or default_instance_name()
        run_dir = Path(resolve_instance_dir(name)) / "run"
        return existing_tui_pid(run_dir)
    except Exception:  # noqa: BLE001
        return None


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
        # Singleton: if a TUI is already running for this instance,
        # don't spawn a duplicate — just bring Terminal.app to the
        # front so the user sees the existing window. The TUI itself
        # writes a per-instance PID file at startup (see
        # ``interfaces/tui/singleton.py``).
        if _existing_tui_pid_for(instance) is not None:
            _activate_terminal()
            return
        # When the daemon is up, the right verb is ``jaeger attach``
        # (Phase 2 wires it). Until then, ``jaeger`` standalone is the
        # in-process TUI — same agent, fresh process. We use the same
        # command in both cases; the binary picks the right path.
        cmd = " ".join(jaeger + (["--instance", instance] if instance else []))
        _open_terminal_running(cmd)

    def open_voice() -> None:
        # 0.2.6: launch the voice loop in a new Terminal window so the
        # operator sees its boot output (model load, AEC status, "say
        # 'ok jaeger'" prompt). The voice loop has its own argparse
        # and honours --instance the same way the TUI does. Default
        # behaviour: wake-word required, AEC barge-in when speexdsp
        # is installed.
        #
        # Auto-attach when the daemon is up: if the socket exists for
        # this instance, pass --attach so voice_loop skips loading its
        # own LLM client and routes turns through the daemon's
        # ``chat.send``. Saves ~16 GB RAM. When the daemon isn't
        # running, fall back to the standalone path (voice_loop loads
        # its own model). The operator sees which mode via the boot
        # banner the voice loop prints.
        # Fresh Terminal shells inherit no PYTHONPATH from us, so we
        # have to set it inline before invoking python. Using the
        # venv's python explicitly (vs ``python`` on PATH) so the
        # voice loop's deps (Whisper, Kokoro, speexdsp) resolve.
        repo = _repo_root()
        venv_py = repo / ".venv" / "bin" / "python"
        py = str(venv_py) if venv_py.exists() else "python3"
        extra = []
        if instance:
            extra += ["--instance", instance]
        if _daemon_socket_present_for(instance):
            extra.append("--attach")
        cmd = (
            f"cd {repo} && PYTHONPATH={repo} "
            f"{py} -m jaeger_os.plugins.voice_loop"
            + ("" if not extra else " " + " ".join(extra))
        )
        _open_terminal_running(cmd)

    def open_gui() -> None:
        # Placeholder until the PyQt6 floating chat lands. Wired to a
        # no-op now so the dispatcher doesn't crash on a stray click
        # (the menu entry is greyed in base.menu_items_for, but
        # defence-in-depth).
        pass

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
        open_tui=open_tui,
        open_voice=open_voice,
        open_gui=open_gui,
        open_web=open_web,
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

        # Hide the Dock icon — we're a menu-bar agent, not a windowed
        # app. Without this, every ``jaeger start`` spawns a rocket
        # icon in the Dock (Python's default) which is confusing and
        # adds nothing. The "accessory" activation policy is the
        # PyObjC equivalent of ``LSUIElement=true`` in a bundled
        # .app's Info.plist — same behaviour, no .app bundling
        # required. See ``_hide_dock_icon`` for the call.
        _hide_dock_icon()

        # Initial state — pessimistic. The first poll will correct it.
        # We prefer the bundled PNG (the brand mark, with an off/on
        # variant for daemon state); fall back to the one-character
        # glyph when the asset isn't on disk (stripped install).
        icon = icon_path_for(self.model.state)
        title = "" if icon else glyph_for(self.model.state)
        self._app = rumps.App(
            "Jaeger", title=title, icon=icon, quit_button=None,
            template=False,  # full-colour PNG; not a template image
        )

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
                # Update the menu-bar slot — swap the PNG when the
                # daemon flips on/off; fall back to a one-char glyph
                # if the asset is missing on this host.
                new_icon = icon_path_for(self.model.state)
                if new_icon is not None:
                    self._app.icon = new_icon
                    self._app.title = ""
                else:
                    self._app.icon = None
                    self._app.title = glyph_for(self.model.state)

        # Wire "Quit Jaeger OS" to a full teardown: stop the daemon,
        # sweep any stray trays, then quit this rumps app. The user
        # expects Quit to kill EVERYTHING related to the product —
        # the previous "just close the icon" behaviour left the
        # daemon (and the model load) running silently.
        def _quit_all() -> None:
            # 1) Stop the daemon. Best-effort — if it's already down
            #    we still proceed to the rest of the teardown.
            try:
                self.actions.stop()
            except Exception:  # noqa: BLE001
                pass
            # 2) Sweep every OTHER jaeger-tray process (this process
            #    is excluded by PID). Catches cases where stray
            #    trays from earlier sessions are still alive.
            try:
                _kill_stray_trays()
            except Exception:  # noqa: BLE001
                pass
            # 3) Quit ourselves last. rumps' quit_application unwinds
            #    the event loop and runs our atexit cleanup (which
            #    drops the tray PID file).
            rumps.quit_application()

        object.__setattr__(self.actions, "quit_tray", _quit_all)
        # Pull the version live from the package metadata so the About
        # dialog never drifts behind ``pyproject.toml`` / ``__version__``.
        try:
            from jaeger_os import __version__ as _ver
        except Exception:  # noqa: BLE001
            _ver = "unknown"
        object.__setattr__(self.actions, "about",
                           lambda: rumps.alert(
                               title="Jaeger OS",
                               message=(
                                   f"Jaeger OS — v{_ver}\n"
                                   "Local-first agentic assistant.\n\n"
                                   "Menu-bar tray: lifecycle controls\n"
                                   "for the Jaeger daemon."
                               ),
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


# ── Dock-icon suppression ─────────────────────────────────────────


def _hide_dock_icon() -> None:
    """Switch the process to NSApplicationActivationPolicyAccessory.

    The activation policy controls whether the running app appears in
    the Dock, Command-Tab, and the app switcher:

      * ``Regular`` (default for Python) — Dock icon, switcher entry.
      * ``Accessory`` — menu-bar / status item only; no Dock icon,
        no switcher entry. This is the policy a bundled menu-bar
        app would set via ``LSUIElement=true`` in its Info.plist;
        because rumps runs from a plain Python interpreter (no
        bundled app), we set it at runtime instead.
      * ``Prohibited`` — invisible. Inappropriate here (the tray
        IS the UI).

    Idempotent and best-effort — if PyObjC isn't loadable for some
    reason, we leave the policy alone rather than crash."""
    try:
        from AppKit import NSApplication
        # NSApplicationActivationPolicyAccessory == 1; we hard-code
        # the int so a missing AppKit constant doesn't break the
        # call.
        NSApplication.sharedApplication().setActivationPolicy_(1)
    except Exception:  # noqa: BLE001 — never crash the tray over this
        pass


# ── stale-tray reaper ─────────────────────────────────────────────


def _kill_stray_trays() -> int:
    """SIGTERM every other ``jaeger-tray`` / ``jaeger_os.interfaces.tray``
    Python process owned by this user. Used by ``--kill-others`` to
    clean up the stale icons accumulated before the singleton gate
    landed. Returns the kill count.

    Implementation: walk ``ps -Aww -o pid,command``, match anything
    invoking the tray module, skip our own PID, SIGTERM the rest.
    Pure subprocess so we don't need ``psutil`` as a dependency."""
    import signal
    killed = 0
    my_pid = os.getpid()
    try:
        out = subprocess.run(
            ["ps", "-Aww", "-o", "pid=,command="],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except Exception:  # noqa: BLE001
        return 0
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        # Lines look like "12345 /path/to/python -m jaeger_os.interfaces.tray.macos --instance default"
        # or "12345 /path/to/jaeger tray --instance default".
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmd = parts
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == my_pid:
            continue
        if "jaeger_os.interfaces.tray" not in cmd and \
           " jaeger tray" not in (" " + cmd):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed += 1
        except ProcessLookupError:
            pass
        except PermissionError:
            pass
    return killed


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
    parser.add_argument("--kill-others", action="store_true",
                        help="Terminate every other running jaeger-tray "
                             "process for this user and exit. Use to clear "
                             "stale icons left behind by older builds.")
    args = parser.parse_args(argv)

    if args.kill_others:
        killed = _kill_stray_trays()
        print(f"killed {killed} stray jaeger-tray process(es)")
        return 0

    # Lifecycle is independent of the agent — same `run/` resolution as
    # the daemon CLI, so the tray and `jaeger status` see the same files.
    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    from jaeger_os.interfaces.tray.singleton import claim_tray_slot
    name = args.instance or default_instance_name()
    root = Path(resolve_instance_dir(name))
    run_dir = root / "run"
    paths = LifecyclePaths(run_dir=run_dir)
    lifecycle = Lifecycle(paths=paths)

    # Tray singleton — ATOMIC claim. The previous check-then-acquire
    # had a TOCTOU race: when several ``jaeger start`` / ``restart``
    # calls fired trays at the same instant, every racer read "slot
    # free", every racer claimed it, and every racer drew an icon —
    # the menu bar filled with duplicates (the user's screenshot:
    # 24 icons, 8 launches × 3). ``claim_tray_slot`` uses O_CREAT|
    # O_EXCL so EXACTLY ONE process wins; the losers exit here, BEFORE
    # importing rumps or drawing anything. The slot file auto-clears
    # on clean exit, and a stale file from a hard kill is reclaimed.
    acquired, owner, _cleanup = claim_tray_slot(run_dir)
    if not acquired:
        print(f"jaeger-tray already running for instance {name!r} "
              f"(pid={owner}). Not launching a duplicate.", file=sys.stderr)
        return 0
    # We own the only slot. Sweep any OTHER tray processes still alive
    # from before this gate existed (pre-atomic builds / hard kills) so
    # their stale icons disappear. This kills others by PID, never us.
    swept = _kill_stray_trays()
    if swept:
        print(f"[jaeger-tray] swept {swept} stale tray process(es)",
              file=sys.stderr)

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
