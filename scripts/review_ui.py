"""Capture real Qt layouts with isolated preferences and no model/API requests.

Run: .venv/Scripts/python scripts/review_ui.py
Optional: --output DIR, or QT_SCALE_FACTOR=2 for the high-DPI review.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont
from PySide6.QtCore import QSettings, QTimer, QPointF, Qt, QEvent
from PySide6.QtGui import QFontInfo, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QToolButton

from comic_translate_desktop import config
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.preview import studio_illustration
from comic_translate_desktop.font_library import font_reference
from comic_translate_desktop.ui.theme import APP_STYLESHEET, install_ui_font
from comic_translate_desktop.ui.font_library_dialog import FontLibraryDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('docs/ui-review'))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path('tmp/ui-qa/style-review').resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName('ComiTrans-Style-Review')
    app.setOrganizationName('ComiTrans-Style-Review')
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(scratch / 'settings'))
    QSettings().clear()
    app.setStyle('Fusion')
    install_ui_font(app)
    app.setStyleSheet(APP_STYLESHEET)
    report = {'source': 'running Qt Widgets', 'model_requests': False, 'api_requests': False, 'captures': []}

    def check_action(window, button):
        name = button.text() if hasattr(button, 'text') else button.currentText()
        assert button.isVisible(), name
        for point in (button.rect().topLeft(), button.rect().bottomRight()):
            assert window.rect().contains(button.mapTo(window, point)), (name, window.size())

    def check_font_search(combo):
        editor = combo.lineEdit()
        for button in editor.findChildren(QToolButton):
            if button.isVisible():
                assert editor.rect().contains(button.geometry()), (editor.rect(), button.geometry())

    with patch.object(config, 'CONFIG_PATH', scratch / 'defaults.yaml'), \
         patch.object(config, 'PROJECT_ROOT', scratch), \
         patch.object(config, 'DEFAULT_OUTPUT_DIR', scratch / 'output'), \
         patch.object(MainWindow, '_start_warmup'):
        window = MainWindow()
        screen = app.primaryScreen().availableGeometry()
        window.resize(min(1440, int(screen.width() * .94)), min(900, int(screen.height() * .94)))
        window.show()

        def capture(name, page, buttons=()):
            window.tabs.setCurrentWidget(page)
            app.processEvents()
            QTest.qWait(80)
            for button in buttons:
                check_action(window, button)
            header_widgets = [widget for widget in (window._brand_title, window._nav_auto, window._nav_editor,
                              window.status_label, window._stop_btn, window._settings_btn, window._logs_btn,
                              window._output_btn, window._issue_btn, window._more_btn) if widget.isVisible()]
            for first, second in zip(header_widgets, header_widgets[1:]):
                assert not first.geometry().intersects(second.geometry()), (first.text(), second.text())
            for widget in header_widgets:
                check_action(window, widget)
            if name == 'automatic':
                report['topbar_geometry'] = {widget.objectName() or widget.text(): widget.geometry().getRect()
                                            for widget in (window._brand_title, window._nav_auto, window._nav_editor,
                                                           window.status_label, window._settings_btn, window._logs_btn,
                                                           window._output_btn, window._issue_btn, window._more_btn)
                                            if widget.isVisible()}
            path = output / f'{name}-style-review.png'
            assert window.grab().save(str(path))
            report['captures'].append(dict(file=path.name, width=window.width(), height=window.height(),
                                           dpr=window.devicePixelRatioF(), actions_visible=True))

        def wait_preview(editor):
            deadline = time.perf_counter() + 5
            while time.perf_counter() < deadline:
                QTest.qWait(30)
                if not editor._preview_timer.isActive() and not editor._preview_dirty:
                    return
            raise AssertionError(editor._status.text())

        def review():
            try:
                report['illustrations'] = []
                for asset in ('studio-import-v1.png', 'studio-editor-v1.png'):
                    pixmap = studio_illustration(asset)
                    assert not pixmap.isNull(), f'Missing illustration: {asset}'
                    assert pixmap.hasAlphaChannel(), f'Missing transparency: {asset}'
                    report['illustrations'].append(dict(file=asset, width=pixmap.width(),
                                                       height=pixmap.height(), transparent=True))
                capture('automatic', window.translate_tab,
                        (window._add_btn, window._start_btn, window._font_picker.combo, window._font_picker.import_button, window._font_picker.library_button))
                check_font_search(window._font_picker.combo)
                library = FontLibraryDialog(window.config, window)
                library.resize(min(820, int(screen.width() * .9)), min(660, int(screen.height() * .9)))
                library.show()
                QTest.qWait(80)
                for name, query in (('font-library', ''), ('font-library-search', '中文 手写')):
                    library.search.setText(query)
                    app.processEvents()
                    QTest.qWait(80)
                    assert library.font_list.count() > 0
                    path = output / f'{name}-style-review.png'
                    assert library.grab().save(str(path))
                    report['captures'].append(dict(file=path.name, width=library.width(), height=library.height(),
                                                   dpr=library.devicePixelRatioF(), actions_visible=True))
                report['font_catalog'] = dict(families=len(library._families),
                                              chinese_handwriting_results=library.font_list.count(), offline_search=True)
                library.close()
                imported_font = window._font_picker.import_paths([config.AI_ROOT / 'font_file/CN/special/851tegaki_zatsu_normal_0883.ttf'])[0]
                assert window._font_picker.combo.currentData() == font_reference(imported_font.path)
                assert config.load_ai_config()['translation_font_active']
                capture('automatic-custom-font', window.translate_tab, (window._font_picker.combo, window._font_picker.import_button))
                window._font_picker.combo.setCurrentIndex(0)
                editor = window.editor_page
                capture('editor-empty', editor, (editor.preview.import_button, editor._focus_btn))
                settings = window.api_config_page
                settings._model_input.setText('你的翻译模型')
                capture('settings', settings, (settings._save_btn,))
                settings._sections.setCurrentIndex(1)
                capture('settings-ocr', settings, (settings._save_btn,))
                settings._sections.setCurrentIndex(2)
                capture('settings-output', settings, (settings._save_btn,))
                diagnosis = window.error_log_page
                capture('diagnosis', diagnosis, (diagnosis._copy_prompt_btn,))
                diagnosis._sections.setCurrentIndex(1)
                capture('diagnosis-chat', diagnosis, (diagnosis._send_btn,))

                # A labelled UI fixture exercises original image colours and real layout loading.
                page = scratch / 'output' / '界面检查页.png'
                page.parent.mkdir(exist_ok=True)
                image = Image.new('RGB', (720, 1000), 'white')
                draw = ImageDraw.Draw(image)
                font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 26)
                draw.text((32, 24), 'ComiTrans · 界面检查页', fill='black', font=font)
                for box in ((30, 80, 690, 450), (30, 480, 330, 960), (360, 480, 690, 960)):
                    draw.rectangle(box, outline='black', width=5)
                draw.ellipse((70, 125, 300, 300), outline='black', width=3)
                draw.ellipse((395, 550, 650, 730), outline='black', width=3)
                draw.rectangle((395, 130, 640, 390), fill='#dce8e8')
                draw.text((410, 235), '原图色彩保留', fill='black', font=font)
                image.save(page)
                cleaned = scratch / 'output_cleaned'
                layouts = scratch / 'output_layout'
                cleaned.mkdir(exist_ok=True)
                layouts.mkdir(exist_ok=True)
                image.save(cleaned / f'{page.stem}_cleaned.png')
                (layouts / f'{page.stem}_layout.json').write_text(json.dumps([
                    dict(text='从一页漫画开始。', source_text='一ページから始めよう。', box=[100, 150, 270, 280],
                         style='dialogue', font_size=26, direction=1, offset_x=0, offset_y=0),
                    dict(text='检查译文，再完成排版。', source_text='訳文を確認しましょう。', box=[435, 575, 625, 710],
                         style='dialogue', font_size=24, direction=0, offset_x=0, offset_y=0),
                ], ensure_ascii=False), encoding='utf-8')
                assert editor.load_page(page)
                assert editor.apply_changes()
                capture('editor', editor, (editor._save_btn, editor._apply_btn))
                editor._focus_btn.setChecked(True)
                capture('editor-focus', editor, (editor._save_btn, editor._focus_btn))
                editor._focus_btn.setChecked(False)
                editor._inspector_tabs.setCurrentIndex(1)
                capture('editor-layout', editor, (editor._save_btn, editor._apply_btn))
                original_bytes = page.read_bytes()
                editor._size_spin.setValue(31)
                editor._offset_x.setValue(12)
                editor._offset_y.setValue(8)
                wait_preview(editor)
                assert not editor._preview_dirty
                assert editor.items[0]['rendered_font_size'] == 31
                assert page.read_bytes() == original_bytes
                editor._properties_scroll.ensureWidgetVisible(editor._size_spin)
                capture('editor-live-preview', editor, (editor._save_btn, editor._size_spin))
                editor._mask_width.setValue(210)
                editor._mask_height.setValue(180)
                wait_preview(editor)
                assert editor.items[0]['mask_width'] == 210
                assert editor.items[0]['mask_height'] == 180
                editor._properties_scroll.ensureWidgetVisible(editor._mask_height)
                capture('editor-mask-preview', editor, (editor._save_btn, editor._mask_width, editor._mask_height))
                assert editor.save_image()
                with Image.open(page) as saved:
                    assert saved.tobytes() == editor._rendered.tobytes()
                report['editor_live_preview'] = dict(font_size=31, offset_x=12, offset_y=8,
                                                   mask_width=210, mask_height=180,
                                                   edits_preserve_file_until_save=True,
                                                   saved_pixels_match_preview=True,
                                                   guide_excluded_from_export=True)
                # Measure a subsequent cached edit separately from screenshot capture time.
                editor._offset_x.setValue(13)
                app.processEvents()
                start = time.perf_counter()
                assert editor.apply_changes()
                report['editor_live_preview']['cached_edit_ms'] = round((time.perf_counter() - start) * 1000, 1)
                assert editor.save_image()
                canvas = editor.preview._label
                original_region = canvas.region
                start_point = canvas._region_handles()['se'].toPoint()
                page_rect = canvas.page_rect()
                end_point = (QPointF(start_point) + QPointF(
                    32 * page_rect.width() / canvas.image_size.width(),
                    24 * page_rect.height() / canvas.image_size.height())).toPoint()
                dx = round((end_point.x() - start_point.x()) * canvas.image_size.width() / page_rect.width())
                dy = round((end_point.y() - start_point.y()) * canvas.image_size.height() / page_rect.height())
                QTest.mouseMove(canvas, start_point)
                QTest.mousePress(canvas, Qt.LeftButton, pos=start_point)
                assert canvas._region_drag is not None, ('drag did not start', canvas.region, start_point, canvas.region_rect())
                # Send a held-button move directly; native QTest.mouseMove relies on
                # OS cursor delivery, unavailable in some desktop execution sessions.
                move_event = QMouseEvent(QEvent.MouseMove, QPointF(end_point),
                                         QPointF(canvas.mapToGlobal(end_point)),
                                         Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
                app.sendEvent(canvas, move_event)
                wait_preview(editor)
                assert not editor._preview_dirty, editor._status.text()
                assert canvas.region == (*original_region[:2], original_region[2] + dx, original_region[3] + dy), (canvas.region, original_region, dx, dy, canvas._region_drag)
                capture('editor-mask-drag', editor, (editor._save_btn, editor._mask_width, editor._mask_height))
                QTest.mouseRelease(canvas, Qt.LeftButton, pos=end_point)
                assert editor.save_image()
                with Image.open(page) as saved:
                    assert saved.tobytes() == editor._rendered.tobytes()
                report['editor_mask_drag'] = dict(handles=8, geometry=list(canvas.region),
                                                 live_during_drag=True, fields_synchronized=True,
                                                 saved_pixels_match_preview=True)
                default_reference = font_reference(config.AI_ROOT / config.FONT_DEFAULTS['bold_dialogue'])
                window._font_picker.combo.setCurrentIndex(window._font_picker.combo.findData(default_reference))
                default_pixels = editor._rendered.tobytes()
                editor._style_combo.setCurrentIndex(editor._style_combo.findData('serious'))
                wait_preview(editor)
                assert editor._rendered.tobytes() != default_pixels
                assert editor.items[0]['font_reference'] == font_reference(config.AI_ROOT / config.FONT_DEFAULTS['serious'])
                assert 'font_reference' not in editor.items[1]
                editor._properties_scroll.ensureWidgetVisible(editor._style_combo)
                capture('editor-font-switch', editor, (editor._style_combo, editor._font_library_btn, editor._save_btn))
                check_font_search(editor._style_combo)
                assert editor.save_image()
                restored = type(editor)()
                assert restored.load_page(page)
                assert restored.apply_changes()
                assert restored._rendered.tobytes() == editor._rendered.tobytes()
                restored.close()
                manual_layer = editor._layer_cache[0][1].tobytes()
                window._font_picker.combo.setCurrentIndex(0)
                assert editor._layer_cache[0][1].tobytes() == manual_layer
                assert editor.save_image()
                report['editor_font_switch'] = dict(manual_overrides_default=True, only_selected_block=True,
                                                    save_reload_pixels_match=True, subsequent_default_keeps_manual_font=True)
                editor._inspector_tabs.setCurrentIndex(0)
                window._add_paths([page])
                capture('automatic-preview', window.translate_tab)
                for width, height in ((1024, 720), (960, 540), (820, 480)):
                    window.resize(min(width, int(screen.width() * .94)), min(height, int(screen.height() * .94)))
                    capture(f'automatic-{width}', window.translate_tab,
                            (window._add_btn, window._start_btn, window._font_picker.combo, window._font_picker.import_button, window._font_picker.library_button))
                    capture(f'settings-{width}', settings, (settings._save_btn,))
                    capture(f'diagnosis-{width}', diagnosis, (diagnosis._send_btn,))
                    window.tabs.setCurrentWidget(editor)
                    app.processEvents()
                    editor._properties_toggle.setChecked(True)
                    capture(f'editor-{width}', editor, (editor._save_btn, editor._apply_btn))
                    editor._inspector_tabs.setCurrentIndex(1)
                    editor._properties_scroll.ensureWidgetVisible(editor._mask_height)
                    app.processEvents()
                    check_action(window, editor._mask_height)
                    assert editor._properties_scroll.viewport().rect().contains(
                        editor._mask_height.mapTo(editor._properties_scroll.viewport(), editor._mask_height.rect().center()))
                    editor._properties_scroll.ensureWidgetVisible(editor._font_library_btn)
                    app.processEvents()
                    check_action(window, editor._font_library_btn)
                    assert editor._properties_scroll.viewport().rect().contains(
                        editor._font_library_btn.mapTo(editor._properties_scroll.viewport(), editor._font_library_btn.rect().center()))
                    editor._inspector_tabs.setCurrentIndex(0)
                    editor._focus_btn.setChecked(True)
                    capture(f'editor-focus-{width}', editor, (editor._save_btn, editor._focus_btn))
                    assert not editor._pages_panel.isVisible()
                    assert not editor._properties_panel.isVisible()
                    editor._focus_btn.setChecked(False)
                report['brand_font'] = QFontInfo(window._brand_title.font()).family()
                report['log_font'] = QFontInfo(window.log_view.font()).family()
                report['workspace_banners'] = {
                    name: sum(widget.__class__.__name__ == 'ChapterBanner' for widget in page.findChildren(QWidget))
                    for name, page in (('automatic', window.translate_tab), ('editor', editor),
                                       ('settings', settings), ('diagnosis', diagnosis))
                }
                assert not any(report['workspace_banners'].values())
                report['success'] = True
            except Exception as exc:
                report.update(success=False, error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
            finally:
                (output / 'style-review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps(report, ensure_ascii=False), flush=True)
                window.editor_page.preview.cancel_region_drag()
                window.editor_page._dirty = False
                window.close()
                app.exit(0 if report.get('success') else 1)

        QTimer.singleShot(500, review)
        return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
