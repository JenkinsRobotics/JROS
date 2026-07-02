"""Run the Studio app:  python -m studio_app [--host H] [--port P]

Connects to a Jaeger instance's QUIC gateway. For local dev, run instance_stub.py
first (or use ./run) to have something to connect to.
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser(prog="studio_app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=45560)
    args = ap.parse_args()

    from PySide6.QtWidgets import QApplication

    from .asynclink import AsyncLink
    from .window import StudioWindow

    app = QApplication(sys.argv)
    link = AsyncLink(args.host, args.port)
    win = StudioWindow(link)
    win.show()
    link.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
