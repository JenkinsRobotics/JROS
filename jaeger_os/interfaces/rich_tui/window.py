"""rich_tui — the windowed chat surface (Pattern 1's main window).

A thin PySide6 view over the chassis bus: it publishes ``ChatMessage`` and
renders ``ChatReply`` / ``AgentState`` — it never imports the agent (the
GUI/logic-separation rule), so swapping PySide6 for Swift moves no logic.

The visual design (iMessage-style ``ChatBubble``s, header + composer +
status) is adapted from the Lilith-AI concept window, re-fitted to JROS
standards: a chassis ``make_surface(ctx, spec)`` factory, the
``make_bus_bridge`` bus→Qt hop, ``ctx.core.agent_name``, and the
``/act/chat`` → ``/sense/chat`` topic contract. Tool-execution chips are
deferred until the bridge emits per-tool events.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from jaeger_os.app.surfaces import make_bus_bridge
from jaeger_os.core.messages import ChatMessage

_STATUS_TEXT = {"idle": "", "thinking": "thinking…", "error": "error"}


class ChatBubble(QFrame):
    """One message in the history — sender label on top, body below.

    Object-name-scoped styling so the window stylesheet can't repaint the
    child backgrounds; the body is a read-only transparent QTextEdit so
    long/multi-line text wraps and selects cleanly, auto-sized to fit.
    """

    USER_BG = "#007AFF"
    USER_FG = "#FFFFFF"
    USER_META = "#D6EBFF"
    ASSISTANT_BG = "#F1F1F3"
    ASSISTANT_FG = "#1F2937"
    ASSISTANT_META = "#6B7280"

    MAX_BUBBLE_WIDTH = 640

    def __init__(self, role: str, text: str, sender: str,
                 parent: QWidget | None = None,
                 max_width: int | None = None) -> None:
        super().__init__(parent)
        if max_width is not None and max_width > 0:
            self.MAX_BUBBLE_WIDTH = max_width
        is_user = role == "user"
        bg = self.USER_BG if is_user else self.ASSISTANT_BG
        fg = self.USER_FG if is_user else self.ASSISTANT_FG
        meta_fg = self.USER_META if is_user else self.ASSISTANT_META

        # Outer row controls left/right alignment.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(0)

        bubble = QFrame()
        bubble.setObjectName("Bubble")
        bubble.setStyleSheet(f"""
            QFrame#Bubble {{
                background-color: {bg};
                border-radius: 14px;
            }}
            QLabel#BubbleMeta {{
                background: transparent;
                color: {meta_fg};
                font-size: 10px;
                font-weight: 600;
                padding: 0;
            }}
            QTextEdit#BubbleBody {{
                background: transparent;
                color: {fg};
                font-size: 14px;
                font-family: -apple-system, "San Francisco", "Segoe UI", system-ui, Helvetica, Arial, sans-serif;
                border: none;
                padding: 0;
            }}
        """)
        bubble.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        bubble.setMaximumWidth(self.MAX_BUBBLE_WIDTH + 28)

        inner = QVBoxLayout(bubble)
        inner.setContentsMargins(14, 8, 14, 14)
        inner.setSpacing(4)

        meta = QLabel(sender)
        meta.setObjectName("BubbleMeta")
        inner.addWidget(meta)

        body = QTextEdit()
        body.setObjectName("BubbleBody")
        body.setPlainText(text)
        body.setReadOnly(True)
        body.setFrameShape(QFrame.Shape.NoFrame)
        body.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        body.document().setDocumentMargin(0)
        body.document().setTextWidth(self.MAX_BUBBLE_WIDTH)
        # Actual rendered height after wrap, plus a buffer so descenders on
        # the last line aren't clipped by the bubble's bottom edge.
        fm = QFontMetrics(body.font())
        ideal_h = int(body.document().size().height()) + fm.descent() + 6
        if ideal_h <= 6:
            ideal_h = max(fm.height() + 6, 24)
        body.setFixedHeight(ideal_h)
        body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        inner.addWidget(body)

        if is_user:
            outer.addStretch()
            outer.addWidget(bubble)
        else:
            outer.addWidget(bubble)
            outer.addStretch()


class ChatWindow(QWidget):
    """Bus-backed chat window. Publishes ``ChatMessage`` on send; renders
    ``ChatReply`` / ``AgentState`` as bubbles + a status line. Closing the
    window hides it (the menu-bar tray is the always-on surface)."""

    def __init__(self, ctx: Any) -> None:
        super().__init__()
        self.ctx = ctx
        # The name hangs off the Tier-1 core (ctx is the chassis app);
        # fall back to a ctx-level name, then a generic default.
        self._agent_name = (
            getattr(getattr(ctx, "core", None), "agent_name", None)
            or getattr(ctx, "agent_name", None)
            or "agent")
        self._messages: list[tuple[str, str]] = []   # (role, text) view-model

        self.setObjectName("JrosChatWindow")
        self.setWindowTitle(f"JROS — {self._agent_name}")
        self.resize(720, 640)
        self._build_ui()

        # The one sanctioned bus→Qt hop (signal emission crosses threads).
        self._bridge = make_bus_bridge(
            ctx.bus, ["/sense/chat", "/sense/agent_state"])
        self._bridge.message.connect(self._on_msg)

    # ── UI ────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self.setStyleSheet("""
            QWidget#JrosChatWindow { background-color: #FFFFFF; }
            QWidget#HistoryHost { background-color: #FFFFFF; }
            QScrollArea#HistoryScroll { background-color: #FFFFFF; border: none; }
            QLineEdit#Composer {
                background: #F7F7F8;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 10px 14px;
                font-size: 14px;
                color: #1F2937;
            }
            QPushButton#SendBtn {
                background-color: #007AFF;
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                padding: 8px 18px;
            }
            QPushButton#SendBtn:hover { background-color: #0A84FF; }
            QPushButton#SendBtn:disabled { background-color: #B2D9FF; }
            QLabel#HeaderLabel {
                font-size: 14px;
                font-weight: 600;
                color: #1F2937;
                padding: 12px 16px;
                background: #FAFAFA;
                border-bottom: 1px solid #E5E7EB;
            }
            QLabel#StatusLabel {
                color: #888;
                padding: 4px 16px;
                font-size: 11px;
                background: #FFFFFF;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = QLabel(f"{self._agent_name} — local")
        self.header.setObjectName("HeaderLabel")
        root.addWidget(self.header)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("HistoryScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.history_host = QWidget()
        self.history_host.setObjectName("HistoryHost")
        self.history_layout = QVBoxLayout(self.history_host)
        self.history_layout.setContentsMargins(16, 12, 16, 12)
        self.history_layout.setSpacing(2)
        self.history_layout.addStretch()
        self.scroll.setWidget(self.history_host)
        root.addWidget(self.scroll, stretch=1)

        self.status = QLabel("")
        self.status.setObjectName("StatusLabel")
        root.addWidget(self.status)

        composer = QHBoxLayout()
        composer.setContentsMargins(12, 8, 12, 12)
        composer.setSpacing(8)

        self.input = QLineEdit()
        self.input.setObjectName("Composer")
        self.input.setPlaceholderText(f"Message {self._agent_name}…")
        self.input.returnPressed.connect(self._send)
        composer.addWidget(self.input, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("SendBtn")
        self.send_btn.clicked.connect(self._send)
        composer.addWidget(self.send_btn)
        root.addLayout(composer)

    # ── input → bus ───────────────────────────────────────────────
    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._append_bubble("user", text)
        self._set_busy(True)
        self.ctx.bus.publish(ChatMessage(text=text, source="gui"))

    def submit_external(self, text: str) -> None:
        """Inject a message from another surface (e.g. the tray Pill): render
        the user bubble + publish, exactly as if typed here."""
        text = (text or "").strip()
        if not text:
            return
        self._append_bubble("user", text)
        self._set_busy(True)
        self.ctx.bus.publish(ChatMessage(text=text, source="gui"))

    # ── bus → widgets ─────────────────────────────────────────────
    def _on_msg(self, msg: Any) -> None:
        if msg.topic == "/sense/chat":
            if msg.text:
                self._append_bubble("assistant", msg.text)
            self._set_busy(False)
        elif msg.topic == "/sense/agent_state":
            self.status.setText(_STATUS_TEXT.get(msg.state, msg.state))
            if msg.state in ("idle", "error"):
                self._set_busy(False)
            elif msg.state == "thinking":
                self._set_busy(True)

    # ── helpers ───────────────────────────────────────────────────
    def _bubble_max_width(self) -> int:
        # iMessage-style: bubbles cap at ~78% of the chat area.
        scroll_w = self.scroll.viewport().width() if self.scroll else self.width()
        if scroll_w <= 0:
            scroll_w = self.width()
        usable = max(scroll_w - 32, 240)   # outer history margins (16 + 16)
        return min(int(usable * 0.78), 720)

    def _append_bubble(self, role: str, text: str) -> None:
        self._messages.append((role, text))
        sender = "You" if role == "user" else self._agent_name
        bubble = ChatBubble(role, text, sender, max_width=self._bubble_max_width())
        # Insert before the trailing stretch so bubbles stack top-down.
        self.history_layout.insertWidget(self.history_layout.count() - 1, bubble)
        QTimer.singleShot(20, self._scroll_to_bottom)

    def _scroll_to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _set_busy(self, busy: bool) -> None:
        # Input disabled while a turn runs (the bridge also caps its inbox).
        self.input.setEnabled(not busy)
        self.send_btn.setEnabled(not busy)
        self.status.setText("thinking…" if busy else "")
        if not busy:
            self.input.setFocus()

    def rendered_text(self) -> str:
        """All message bodies joined — a stable surface for tests/inspection
        (the bubbles are the view; this is the view-model)."""
        return "\n".join(t for _role, t in self._messages)

    # ── tray-persist: the X hides instead of quitting ─────────────
    def closeEvent(self, event: Any) -> None:  # noqa: N802 — Qt override
        event.ignore()
        self.hide()

    def teardown(self) -> None:
        try:
            self._bridge.close()
        except Exception:  # noqa: BLE001
            pass


def make_surface(ctx: Any, spec: Any = None) -> ChatWindow:  # noqa: ARG001
    return ChatWindow(ctx)
