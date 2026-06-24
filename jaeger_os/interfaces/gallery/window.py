"""The surface gallery window — buttons that open each prealpha surface.

Every surface exposes ``make_surface(ctx, spec)``, so the launcher is
uniform: import the module, call it, show the window, keep a reference so
it isn't garbage-collected.  A failed open shows a dialog instead of
taking the gallery down — these surfaces are under development.
"""

from __future__ import annotations

import importlib
from typing import Any

from PySide6.QtWidgets import (
    QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

# (button label, module exposing make_surface)
_SURFACES: list[tuple[str, str]] = [
    ("Jaeger Studio", "jaeger_os.interfaces.studio.window"),
    ("Avatar Player", "jaeger_os.interfaces.avatar_player.window"),
    ("Media Player", "jaeger_os.interfaces.media_player.window"),
]


class GalleryWindow(QWidget):
    """A dev launcher: one button per prealpha surface."""

    def __init__(self, ctx: Any = None) -> None:
        super().__init__()
        self._ctx = ctx
        self._open: list[QWidget] = []  # keep refs so windows survive
        self.setWindowTitle("JROS — Surface Gallery (dev)")
        self.resize(320, 70 + 50 * len(_SURFACES))

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 18)
        v.setSpacing(10)
        title = QLabel("Prealpha surfaces — open to test")
        title.setStyleSheet("font-size:14px; font-weight:600;")
        v.addWidget(title)
        for label, module in _SURFACES:
            btn = QPushButton(label)
            btn.setMinimumHeight(38)
            btn.clicked.connect(
                lambda _=False, m=module, lbl=label: self.open_surface(m, lbl))
            v.addWidget(btn)
        v.addStretch(1)

    def open_surface(self, module: str, label: str) -> "QWidget | None":
        try:
            win = importlib.import_module(module).make_surface(self._ctx)
            if not win.windowTitle():
                win.setWindowTitle(label)
            win.show()
            self._open.append(win)
            return win
        except Exception as exc:  # noqa: BLE001 — under development; report, don't die
            QMessageBox.warning(
                self, "Open failed", f"{label}:\n{type(exc).__name__}: {exc}")
            return None


def make_surface(ctx: Any = None, spec: Any = None) -> GalleryWindow:  # noqa: ARG001
    return GalleryWindow(ctx)
