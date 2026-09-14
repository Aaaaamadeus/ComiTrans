from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import APP_STYLESHEET, install_ui_font


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ComiTrans")
    app.setOrganizationName("ComiTrans")
    app.setStyle("Fusion")
    install_ui_font(app)
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
