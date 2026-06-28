"""Dev Launcher — a floating panel that opens every Qt surface. Offscreen
(conftest defaults QT_QPA_PLATFORM=offscreen). We assert it lists the surfaces
and that a failing opener is reported, not fatal — the actual window-opening is
walked live by the operator (`./launch --dev-gui`)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_lists_all_surfaces(_app):
    from PySide6.QtWidgets import QPushButton
    from jaeger_os.interfaces.dev_launcher.window import DevLauncher, SURFACES
    btns = {b.text() for b in DevLauncher().findChildren(QPushButton)}
    assert {label for label, _ in SURFACES} <= btns
    assert "Jaeger Studio" in btns and "Settings" in btns


def test_failing_surface_is_reported_not_fatal(_app):
    from jaeger_os.interfaces.dev_launcher.window import DevLauncher
    w = DevLauncher()

    def boom(ctx):
        raise RuntimeError("nope")

    w._launch("Broken", boom)                         # must not raise
    assert "Broken" in w._status.text() and "nope" in w._status.text()


def test_opened_window_is_kept_referenced(_app):
    from PySide6.QtWidgets import QWidget
    from jaeger_os.interfaces.dev_launcher.window import DevLauncher
    w = DevLauncher()
    widget = QWidget()
    w._launch("X", lambda ctx: widget)
    assert widget in w._open and "opened: X" in w._status.text()
