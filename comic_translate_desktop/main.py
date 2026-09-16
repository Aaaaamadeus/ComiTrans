from __future__ import annotations

import sys
import argparse

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.theme import APP_STYLESHEET, install_ui_font


def main() -> int:
    parser = argparse.ArgumentParser(description="ComiTrans desktop client")
    parser.add_argument("--smoke-test", metavar="OUTPUT_DIR", help="Verify startup/resources/models, write evidence, then exit")
    args = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("ComiTrans")
    app.setOrganizationName("ComiTrans")
    app.setStyle("Fusion")
    install_ui_font(app)
    app.setStyleSheet(APP_STYLESHEET)
    if args.smoke_test:
        from .smoke_test import run_smoke_test
        return run_smoke_test(app, args.smoke_test)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
