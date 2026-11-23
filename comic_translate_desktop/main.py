from __future__ import annotations

import sys
import argparse
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import __version__
from .i18n import initialize_ui_language
from .config import load_ai_config
from .ui.theme import apply_theme, install_ui_font
from .ui.window_chrome import install_window_chrome


def main() -> int:
    from comic_translate_core.image_session import enable_desktop_model_host

    enable_desktop_model_host()
    parser = argparse.ArgumentParser(description="ComiTrans desktop client")
    parser.add_argument('project', type=Path, nargs='?', help='Open an editable .comitrans PDF project')
    parser.add_argument("--smoke-test", metavar="OUTPUT_DIR", help="Verify startup/resources/models, write evidence, then exit")
    parser.add_argument("--smoke-test-require-gpu", action="store_true", help="Fail smoke verification if CUDA is not actually active")
    args = parser.parse_args()
    if args.project and args.project.suffix.lower() != '.comitrans':
        parser.error('Expected a .comitrans PDF project')
    app = QApplication(sys.argv[:1])
    app.setApplicationName("ComiTrans")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("ComiTrans")
    app.setStyle("Fusion")
    install_window_chrome(app)
    install_ui_font(app)
    apply_theme(app, load_ai_config().get('ui_theme', 'auto'))
    if args.smoke_test:
        from .smoke_test import run_smoke_test
        return run_smoke_test(app, args.smoke_test, require_gpu=args.smoke_test_require_gpu)
    initialize_ui_language(app)
    install_ui_font(app)
    from .ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    if args.project:
        window.tabs.setCurrentWidget(window.editor_page)
        window.editor_page.request_import([args.project])
    from .ui.update_notice import UpdateNotice
    update = UpdateNotice(window)
    update.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
