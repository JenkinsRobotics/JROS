"""Jaeger Studio hosts the reusable UpdateBanner widget. Offscreen (conftest
defaults QT_QPA_PLATFORM=offscreen). Constructing the window is network-free
(the banner auto-checks off-thread, but we drive it directly here)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_hosts_update_banner_hidden_by_default(_app, tmp_path, monkeypatch):
    from jaeger_os.interfaces.pyside6.widgets.update_banner import UpdateBanner
    from jaeger_os.interfaces.studio.window import JaegerStudioWindow

    # Pin the media-library scan to an empty dir. Since the studio split,
    # _default_media_dir()'s <pkg>/assets candidate (now jaeger-studio/assets)
    # doesn't exist, so it falls back to Path.home() and the constructor
    # rglobs the whole home directory — minutes, not milliseconds. This test
    # is about the update banner, not the media page.
    monkeypatch.setattr(JaegerStudioWindow, "_default_media_dir",
                        lambda self: str(tmp_path))
    w = JaegerStudioWindow()
    assert isinstance(w._update_banner, UpdateBanner)
    assert w._update_banner.isHidden()                       # nothing yet

    # feeding a newer release reveals the shared widget in-place
    w._update_banner.set_status(
        {"available": True, "latest": "9.9.9", "current": "0.5.2"})
    assert not w._update_banner.isHidden()
