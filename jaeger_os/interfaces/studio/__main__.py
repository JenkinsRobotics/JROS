"""Preview Jaeger Studio with no bus / model / instance:

    python -m jaeger_os.interfaces.studio
"""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from jaeger_os.interfaces.studio.window import JaegerStudioWindow

    app = QApplication(sys.argv)
    win = JaegerStudioWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
