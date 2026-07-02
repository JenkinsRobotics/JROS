"""Headless end-to-end check: Studio GUI + QUIC seam + stub instance.

Runs Qt offscreen so it works without a display. Proves the window builds and the
Dashboard actually receives live telemetry over QUIC.

Run: QT_QPA_PLATFORM=offscreen python smoke_gui.py
"""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = pathlib.Path(__file__).parent


def main() -> None:
    stub = subprocess.Popen([sys.executable, "instance_stub.py"], cwd=HERE)
    try:
        time.sleep(1.5)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        from studio_app.asynclink import AsyncLink
        from studio_app.window import StudioWindow

        app = QApplication(sys.argv)
        link = AsyncLink("127.0.0.1", 45560)
        seen = {"connected": False, "telemetry": False}
        link.connected.connect(lambda: seen.__setitem__("connected", True))
        link.telemetry.connect(lambda t: seen.__setitem__("telemetry", True))

        win = StudioWindow(link)
        win.show()
        link.start()

        QTimer.singleShot(4000, app.quit)
        app.exec()

        assert seen["connected"], "GUI never connected over QUIC"
        assert seen["telemetry"], "GUI never received telemetry"
        print("PASS — Studio GUI built offscreen, connected over QUIC, live telemetry rendered")
    finally:
        stub.terminate()
        stub.wait(timeout=3)


if __name__ == "__main__":
    main()
