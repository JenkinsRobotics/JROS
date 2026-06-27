"""Jaeger Studio "update available" banner — hidden until a newer release is
found. Runs offscreen (conftest defaults QT_QPA_PLATFORM=offscreen). The
network probe (_UpdateCheckThread) is plumbing onto _on_update_status, which is
what we assert here directly — no network in the test."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_banner_hidden_until_update_available(_app):
    from jaeger_os.interfaces.studio.window import JaegerStudioWindow
    w = JaegerStudioWindow()
    assert w._update_banner.isHidden()                       # nothing yet

    w._on_update_status({"available": False, "latest": None, "current": "0.5.2"})
    assert w._update_banner.isHidden()                       # up to date → hidden

    w._on_update_status({"available": True, "latest": "9.9.9", "current": "0.5.2"})
    assert not w._update_banner.isHidden()                   # newer → shown
    assert "9.9.9" in w._update_label.text()


def test_banner_ignores_none_status(_app):
    from jaeger_os.interfaces.studio.window import JaegerStudioWindow
    w = JaegerStudioWindow()
    w._on_update_status(None)                                # offline probe
    assert w._update_banner.isHidden()
