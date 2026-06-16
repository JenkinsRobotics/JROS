"""Qt menu-bar tray — the always-on surface of the windowed app.

A ``QSystemTrayIcon`` adapter: click / "Show / raise window" to surface
the chat window, "Quit" to tear the whole app down. This is the Qt
sibling of the rumps ``macos.py`` adapter — both are thin views. For the
windowed app the actions are **in-process** (show the window, quit the Qt
app), not the daemon-era ``jaeger start/stop`` subprocesses.

Mirrors ``jaeger_app_framework/demos/jros-demo/surfaces/tray.py``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


class QtTray:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        pix = QPixmap(18, 18)
        pix.fill(QColor("#1e88e5"))
        self._icon = QSystemTrayIcon(QIcon(pix))
        name = (getattr(getattr(ctx, "core", None), "agent_name", None)
                or getattr(ctx, "agent_name", None) or "JROS")
        self._icon.setToolTip(f"JROS — {name}")

        menu = QMenu()
        act_show = menu.addAction("Show / raise window")
        act_show.triggered.connect(self._raise_window)
        menu.addSeparator()
        act_quit = menu.addAction("Quit JROS")
        act_quit.triggered.connect(self._quit)
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    def _on_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.Trigger:   # left-click
            self._raise_window()

    def _raise_window(self) -> None:
        win = getattr(self.ctx, "window", None)
        targets = [win] if win is not None else [
            w for w in QApplication.topLevelWidgets() if w.isWindow()
        ]
        for w in targets:
            if w is None:
                continue
            w.show()
            w.raise_()
            w.activateWindow()

    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def close(self) -> None:
        self._icon.hide()


def make_surface(ctx: Any, spec: Any = None) -> QtTray:  # noqa: ARG001
    return QtTray(ctx)
