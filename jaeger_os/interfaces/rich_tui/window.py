"""rich_tui — the windowed chat surface (a windowed duplicate of the
CLI/TUI).

A thin PySide6 view: it publishes ``ChatMessage`` on the bus and renders
``ChatReply`` / ``AgentState`` — it never imports the agent. Swap PySide6
for Swift and the agent doesn't move (the GUI/logic-separation rule).

Mirrors ``jaeger_app_framework/demos/jros-demo/surfaces/main_window.py``,
scoped to chat — the demo's supervisor/telemetry panes belong to nodes
that haven't migrated onto the chassis bus yet.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jaeger_os.app.surfaces import make_bus_bridge
from jaeger_os.core.messages import ChatMessage

_STATUS_TEXT = {"idle": "ready", "thinking": "thinking…", "error": "error"}


class ChatWindow(QMainWindow):
    """A transcript + an input line, driven entirely by the bus. Closing
    the window hides it (the menu-bar tray is the always-on surface);
    Cmd+Q / the tray's Quit tears the app down."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        # The name hangs off the Tier-1 core (ctx is the chassis app);
        # fall back to a ctx-level name, then a generic default.
        self._agent_name = (
            getattr(getattr(ctx, "core", None), "agent_name", None)
            or getattr(ctx, "agent_name", None)
            or "agent")
        self.setWindowTitle(f"JROS — {self._agent_name}")
        self.resize(720, 560)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setFont(QFont("Menlo", 12))
        root.addWidget(self.transcript, 1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message…  (Enter to send)")
        self.input.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        root.addLayout(row)

        self.status = QLabel("ready")
        self.status.setAlignment(Qt.AlignRight)
        self.status.setStyleSheet("color: #888;")
        root.addWidget(self.status)

        # The one sanctioned bus→Qt hop (signal emission crosses threads).
        self._bridge = make_bus_bridge(
            ctx.bus, ["/sense/chat", "/sense/agent_state"])
        self._bridge.message.connect(self._on_msg)

    # ── input → bus ───────────────────────────────────────────────

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append("you", text, "#1e88e5")
        self._set_busy(True)
        self.ctx.bus.publish(ChatMessage(text=text, source="gui"))

    # ── bus → widgets ─────────────────────────────────────────────

    def _on_msg(self, msg: Any) -> None:
        if msg.topic == "/sense/chat":
            self._append(self._agent_name, msg.text, "#9c27b0")
            self._set_busy(False)
        elif msg.topic == "/sense/agent_state":
            self.status.setText(_STATUS_TEXT.get(msg.state, msg.state))
            if msg.state in ("idle", "error"):
                self._set_busy(False)
            elif msg.state == "thinking":
                self._set_busy(True)

    def _set_busy(self, busy: bool) -> None:
        # Input disabled while a turn runs (the bridge also caps its inbox
        # as a backstop). Status mirrors the state.
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)
        self.status.setText("thinking…" if busy else "ready")
        if not busy:
            self.input.setFocus()

    def _append(self, who: str, text: str, color: str) -> None:
        body = (
            (text or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        self.transcript.append(
            f'<span style="color:{color}"><b>{who}:</b></span> {body}')

    # ── tray-persist: the X hides instead of quitting ─────────────

    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        event.ignore()
        self.hide()

    def teardown(self) -> None:
        """Unsubscribe the bridge (the shell calls this, or relies on
        ``bus.close()`` clearing subscribers)."""
        try:
            self._bridge.close()
        except Exception:  # noqa: BLE001
            pass


def make_surface(ctx: Any, spec: Any = None) -> ChatWindow:  # noqa: ARG001
    return ChatWindow(ctx)
