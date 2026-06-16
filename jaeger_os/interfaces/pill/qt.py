"""Pill — a floating Claude-style quick-input launcher.

A tray-spawned window (not a boot-time ``[[surface]]``): the tray shows it
on click, the user types one line, and submitting hands the text to the
tray's ``on_submit`` callback — which opens the chat window and renders it
there. The Pill itself is pure UI: no bus, no agent, no window refs. The
card aesthetic is adapted from the Lilith-AI concept; the dead
"permission/screenshots" placeholders are dropped (no spec ahead of code).
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class Pill(QWidget):
    """Frameless, stay-on-top quick-input card. Dismisses on focus loss."""

    def __init__(self, on_submit: Callable[[str], None],
                 agent_name: str = "agent",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_submit = on_submit
        self._agent_name = agent_name

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(640, 96)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)

        card = QFrame()
        card.setObjectName("PillCard")
        card.setStyleSheet("""
            QFrame#PillCard {
                background-color: #F7F7F8;
                border-radius: 16px;
                border: 1px solid #E5E7EB;
            }
            QLabel#PillGlyph { font-size: 20px; background: transparent; }
            QLineEdit#PillInput {
                background: transparent;
                border: none;
                font-size: 16px;
                color: #222222;
            }
            QPushButton#PillSend {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }
            QPushButton#PillSend:hover { background-color: #0A84FF; }
            QPushButton#PillSend:disabled { background-color: #B2D9FF; }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(0, 0, 0, 30))
        shadow.setOffset(0, 8)
        card.setGraphicsEffect(shadow)

        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        glyph = QLabel("🎇")
        glyph.setObjectName("PillGlyph")
        row.addWidget(glyph)

        self.input = QLineEdit()
        self.input.setObjectName("PillInput")
        self.input.setPlaceholderText(f"Ask {self._agent_name}…  (Enter to send)")
        self.input.returnPressed.connect(self._send)
        row.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("PillSend")
        self.send_btn.setFixedSize(32, 32)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.send_btn)

        outer.addWidget(card)

    # ── behavior ──────────────────────────────────────────────────
    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.hide()
        self._on_submit(text)   # tray opens the chat window + renders it there

    def popup(self) -> None:
        """Center near the bottom of the primary screen, show, and focus."""
        from PySide6.QtWidgets import QApplication

        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.geometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.bottom() - self.height() - 100)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def focusOutEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        # A quick-launcher dismisses on focus loss.
        self.hide()
        super().focusOutEvent(event)
