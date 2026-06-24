"""Run the dev surface gallery standalone:

    python -m jaeger_os.interfaces.gallery
"""

import sys

from PySide6.QtWidgets import QApplication

from jaeger_os.interfaces.gallery.window import GalleryWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    win = GalleryWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
