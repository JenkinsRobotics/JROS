"""The Dev Launcher window — one floating panel, a button per Qt surface.

Each surface opens **in-process** (shared QApplication) via its `make_surface`
factory (or constructor for the class-based ones). A surface that fails to
construct is caught and reported on the status line — it never takes the
launcher down. The ctx is a minimal dev stub (no live bus/core), so surfaces
render their UI for evaluation even without a booted agent.
"""

from __future__ import annotations

import importlib
import types
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QPushButton, QVBoxLayout, QWidget,
)

_IFACE = "jaeger_os.interfaces"


def _factory(modpath: str, attr: str) -> Callable[[Any], QWidget]:
    """Open a surface via its ``make_surface(ctx)``-style factory."""
    def _open(ctx: Any) -> QWidget:
        return getattr(importlib.import_module(modpath), attr)(ctx)
    return _open


def _settings(ctx: Any) -> QWidget:
    from jaeger_os.interfaces.pyside6.settings.window import SettingsWindow
    return SettingsWindow(layout=None)


def _pill(ctx: Any) -> QWidget:
    from jaeger_os.interfaces.pyside6.pill.qt import Pill
    return Pill(on_submit=lambda _t: None)


# label → opener(ctx) -> QWidget. The active Qt surfaces (v4/ is reference-only).
SURFACES: list[tuple[str, Callable[[Any], QWidget]]] = [
    ("Jaeger Studio", _factory(f"{_IFACE}.studio.window", "make_surface")),
    ("Chat window", _factory(f"{_IFACE}.pyside6.rich_tui.window", "make_surface")),
    ("Avatar player", _factory(f"{_IFACE}.avatar_player.window", "make_surface")),
    ("Avatar window", _factory(f"{_IFACE}.avatar_player.window", "make_window_surface")),
    ("Avatar + chat", _factory(f"{_IFACE}.avatar_chat.window", "make_surface")),
    ("Agent Settings (new)", _factory(f"{_IFACE}.pyside6.agent_settings.window", "make_surface")),
    ("Gallery", _factory(f"{_IFACE}.gallery.window", "make_surface")),
    ("Media player", _factory(f"{_IFACE}.media_player.window", "make_surface")),
    ("Settings", _settings),
    ("Pill (quick-ask)", _pill),
]


def _dev_ctx() -> Any:
    """A minimal stand-in ctx — surfaces getattr what they need + degrade."""
    return types.SimpleNamespace(agent_name="jros-dev", bus=None, core=None)


class DevLauncher(QWidget):
    """Floating, always-on-top launchpad for every Qt surface."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JROS Dev Launcher")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._ctx = _dev_ctx()
        self._open: list[QWidget] = []     # keep refs so opened windows survive GC

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        title = QLabel("JROS · Dev Launcher")
        title.setStyleSheet("font-weight:700; font-size:14px;")
        v.addWidget(title)
        v.addWidget(QLabel("Open any surface (dev instance):"))
        for label, opener in SURFACES:
            b = QPushButton(label)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(
                lambda _=False, lbl=label, op=opener: self._launch(lbl, op))
            v.addWidget(b)
        v.addStretch(1)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#9aa3c0; font-size:11px;")
        v.addWidget(self._status)
        self.resize(248, 380)

    def _launch(self, label: str, opener: Callable[[Any], QWidget]) -> None:
        """Open a surface; report (not crash) on failure."""
        try:
            w = opener(self._ctx)
            w.show()
            w.raise_()
            w.activateWindow()
            self._open.append(w)
            self._status.setText(f"opened: {label}")
        except Exception as exc:  # noqa: BLE001 — one bad surface mustn't kill the launcher
            self._status.setText(f"⚠ {label}: {type(exc).__name__}: {exc}")


def run() -> int:
    app = QApplication.instance() or QApplication([])
    win = DevLauncher()
    win.show()
    win.raise_()
    win.activateWindow()
    return app.exec()
