"""Qt menu-bar tray — the always-on surface of the windowed app.

A thin ``QSystemTrayIcon`` adapter (a chassis ``make_surface(ctx, spec)``
surface). Left-click pops the floating Pill quick-launcher; the menu opens
the full chat window or quits. Submitting from the Pill opens the chat
window and renders the message there, so the user bubble is consistent
with a typed one.

Thin by design (the GUI/logic-separation rule): the chassis owns the app /
bus / core; this surface only shows windows and publishes nothing the chat
window doesn't. Lilith's persona/voice menus + global hotkey are runtime
logic JROS doesn't expose on the chassis bus yet — deliberately omitted.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon


def _agent_name(ctx: Any) -> str:
    return (getattr(getattr(ctx, "core", None), "agent_name", None)
            or getattr(ctx, "agent_name", None) or "JROS")


class QtTray:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._pill: Any = None
        self._name = _agent_name(ctx)

        pix = QPixmap(18, 18)
        pix.fill(QColor("#1e88e5"))
        self._icon = QSystemTrayIcon(QIcon(pix))
        self._icon.setToolTip(f"JROS — {self._name}")

        menu = QMenu()
        menu.addAction("Quick input…", self._show_pill)
        menu.addAction("Open chat window", self._open_chat)
        menu.addSeparator()
        menu.addAction("Quit JROS", self._quit)
        self._icon.setContextMenu(menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    # ── activation ────────────────────────────────────────────────
    def _on_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:   # left-click
            self._show_pill()

    # ── Pill quick-launcher ───────────────────────────────────────
    def _show_pill(self) -> None:
        if self._pill is None:
            from jaeger_os.interfaces.pill.qt import Pill
            self._pill = Pill(on_submit=self._submit_from_pill,
                              agent_name=self._name)
        self._pill.popup()

    def _submit_from_pill(self, text: str) -> None:
        win = self._open_chat()
        submit = getattr(win, "submit_external", None)
        if callable(submit):
            submit(text)

    # ── chat window ───────────────────────────────────────────────
    def _open_chat(self) -> Any:
        """Show + raise the chat window (found among the process's top-level
        widgets) and return it. Returns None if it isn't up yet."""
        win = getattr(self.ctx, "window", None) or self._find_chat_window()
        if win is not None:
            win.show()
            win.raise_()
            win.activateWindow()
        return win

    @staticmethod
    def _find_chat_window() -> Any:
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "submit_external"):   # the ChatWindow
                return w
        return None

    # ── lifecycle ─────────────────────────────────────────────────
    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def close(self) -> None:
        if self._pill is not None:
            try:
                self._pill.close()
            except Exception:  # noqa: BLE001
                pass
        self._icon.hide()


def make_surface(ctx: Any, spec: Any = None) -> QtTray:  # noqa: ARG001
    return QtTray(ctx)
