"""Capture editor/preference layouts with isolated configuration and synthetic pages."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image, ImageDraw
from PySide6.QtCore import QSettings, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from comic_translate_desktop import config
from comic_translate_desktop.i18n import set_ui_language
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.theme import (
    UI_FONT_ALLOWLIST, install_ui_font, resolved_ui_font_family)
from tests.qt_utils import destroy_widget

app = QApplication([])
app.setApplicationName('ComiTrans-Performance-Review')
app.setOrganizationName('ComiTrans-Review')
app.setStyle('Fusion')
install_ui_font(app)
assert resolved_ui_font_family() in UI_FONT_ALLOWLIST, (
    f'UI font fell back to {resolved_ui_font_family()!r}; screenshots would not represent the app')
destination = ROOT / 'docs/ui-review'
destination.mkdir(exist_ok=True)
scale = os.environ.get('QT_SCALE_FACTOR', '1')
report = []
with tempfile.TemporaryDirectory() as raw:
    root = Path(raw)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, raw)
    for directory in ('translated', 'translated_cleaned', 'translated_layout'):
        (root / directory).mkdir()
    items = [dict(text='逐页编辑，保留原始清晰度。', source_text='一ページずつ編集します。',
                  box=[150, 120, 650, 470], mask_box=[150, 120, 650, 470],
                  style='dialogue', direction=1, font_size=30, rendered_font_size=30)]
    image = Image.new('RGB', (800, 1200), '#e5d8c1')
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 50, 750, 560), outline='#333333', width=4)
    draw.ellipse((140, 90, 670, 510), fill='#fcf8ef', outline='#333333', width=3)
    draw.rectangle((50, 600, 750, 1150), outline='#333333', width=4)
    for n in range(18):
        draw.line((50, 650+n*24, 750, 950+n*8), fill='#837e75', width=2)
    for number in range(3):
        image.save(root / 'translated' / f'page{number}.png')
        image.save(root / 'translated_cleaned' / f'page{number}_cleaned.png')
        (root / 'translated_layout' / f'page{number}_layout.json').write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
    with patch.object(config, 'CONFIG_PATH', root / 'config.yaml'), patch.object(config, 'PROJECT_ROOT', root), \
         patch.object(MainWindow, '_start_warmup'):
        for language in ('zh-CN', 'en', 'ja'):
            QSettings().clear()
            set_ui_language(language)
            window = MainWindow()
            window._add_paths([root / 'translated/page0.png'])
            window.original_view.set_image(root / 'translated/page0.png')
            window._pref_toggle.setChecked(True)
            window._prompt_input.setPlainText('保持角色语气；译文简洁自然。')
            window._save_translation_preferences()
            for width, height in ((1440, 900), (850, 620)):
                window.resize(width, height)
                window.show()
                QTest.qWait(80)
                window.tabs.setCurrentWidget(window.translate_tab)
                QTest.qWait(50)
                window.grab().save(str(destination / f'large-editor-{language}-preferences-{width}-scale-{scale}.png'))
                report.append(dict(language=language, page='preferences', width=width, scale=scale,
                                   canvas_height=window.preview_tabs.height(),
                                   preference_height=window._pref_container.height(),
                                   actual_width=window.width(), actual_height=window.height()))
                assert window.preview_tabs.isVisible() and window.preview_tabs.height() >= 100, report[-1]
                assert window._pref_container.height() >= 120, report[-1]
                editor = window.editor_page
                if editor.output_path is None:
                    editor.load_page(root / 'translated/page0.png')
                    for number in (1, 2):
                        editor._add_page(root / 'translated' / f'page{number}.png')
                    editor.apply_changes()
                    editor._strip_toggle.setChecked(True)
                window.tabs.setCurrentWidget(editor)
                QTest.qWait(80)
                window.grab().save(str(destination / f'large-editor-{language}-editor-{width}-scale-{scale}.png'))
                report.append(dict(language=language, page='editor', width=width, scale=scale,
                                   canvas_width=editor.preview.width(), canvas_height=editor.preview.height(),
                                   visible_text_height=editor._text_input.visibleRegion().boundingRect().height(),
                                   desired_panels=editor._desired_panels,
                                   actual_width=window.width(), actual_height=window.height()))
                assert editor.preview.width() >= 280 and editor.preview.height() >= 180, report[-1]
                assert editor._text_input.visibleRegion().boundingRect().height() >= 64, report[-1]
            window.editor_page._dirty = False
            window.editor_page.shutdown_jobs()
            QThreadPool.globalInstance().waitForDone(5000)
            QApplication.processEvents()
            destroy_widget(window)
set_ui_language('zh-CN')
(destination / f'large-editor-review-scale-{scale}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report))
