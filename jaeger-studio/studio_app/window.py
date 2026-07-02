"""The Studio shell: migrated chrome (sidebar/theme/backdrop) + a page stack.

Only the Dashboard is live today — it's driven entirely by the QUIC seam, proving
a page can run with zero jaeger_os imports. Every other tab is a stub until its
capability is migrated (its direct JROS calls turned into seam messages).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from link import wire

from . import theme
from .asynclink import AsyncLink
from .background import GradientBackground
from .sidebar import NAV, Sidebar


class DashboardPage(QWidget):
    """First live-over-the-seam page: instance status from QUIC telemetry."""

    def __init__(self, link: AsyncLink):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 28, 32, 28)
        v.setSpacing(12)

        self._status = theme._label("connecting…", color=theme.INK_DIM)
        self._cpu = theme._label("cpu —", size=26, bold=True)
        self._seq = theme._label("frames —", color=theme.INK_DIM)
        self._pose = theme._label("pose —", color=theme.INK_DIM)
        self._ack = theme._label("", color=theme.GOOD)

        v.addWidget(theme._label("Dashboard", size=20, bold=True))
        v.addWidget(self._status)
        v.addSpacing(8)
        v.addWidget(self._cpu)
        v.addWidget(self._seq)
        v.addWidget(self._pose)

        ping = QPushButton("Send ping")
        ping.setObjectName("AddonBtn")
        ping.clicked.connect(lambda: link.send_command("ping"))
        v.addSpacing(8)
        v.addWidget(ping)
        v.addWidget(self._ack)
        v.addStretch(1)

        link.connected.connect(lambda: self._status.setText("● connected over QUIC/UDP"))
        link.disconnected.connect(lambda e: self._status.setText(f"○ disconnected — {e}"))
        link.telemetry.connect(self._on_telem)
        link.ack.connect(lambda a: self._ack.setText(f"ack {a.id}: {a.detail}"))

    def _on_telem(self, t: wire.Telemetry) -> None:
        self._cpu.setText(f"cpu {t.cpu:.0%}")
        self._seq.setText(f"frames {t.seq}")
        self._pose.setText(f"pose {t.pose}")


def _stub(name: str) -> QWidget:
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(32, 28, 32, 28)
    v.addWidget(theme._label(name, size=20, bold=True))
    v.addWidget(theme._label("not yet migrated — still in jaeger_os.interfaces.studio",
                             color=theme.INK_DIM))
    v.addStretch(1)
    return w


class StudioWindow(QWidget):
    def __init__(self, link: AsyncLink):
        super().__init__()
        self.setObjectName("JaegerStudio")
        self.setStyleSheet(theme.stylesheet())
        self.resize(1100, 720)
        self._bg = GradientBackground(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        sidebar = Sidebar("Jaeger")
        self._stack = QStackedWidget()
        row.addWidget(sidebar)
        row.addWidget(self._stack, 1)

        self._index: dict[str, int] = {}
        for key, name in NAV:
            page = DashboardPage(link) if key == "dashboard" else _stub(name)
            self._index[name] = self._stack.addWidget(page)
        sidebar.navSelected.connect(
            lambda nav_name: self._stack.setCurrentIndex(self._index[nav_name]))

    def resizeEvent(self, e):
        self._bg.setGeometry(self.rect())
        self._bg.lower()
        super().resizeEvent(e)
