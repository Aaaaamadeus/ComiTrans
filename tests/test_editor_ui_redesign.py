import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QSettings, Qt
from PySide6.QtGui import QContextMenuEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QMenu, QPushButton, QScrollArea

from comic_translate_desktop import config
from comic_translate_desktop.i18n import install_qt_language, set_ui_language
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.text_editor_dialog import TextEditorDialog


def _write_sample_editor_page(base: Path, name: str = 'page_01') -> Path:
    out_dir = base / 'output'
    cleaned_dir = base / 'output_cleaned'
    layout_dir = base / 'output_layout'
    out_dir.mkdir(parents=True, exist_ok=True)
    cleaned_dir.mkdir(parents=True, exist_ok=True)
    layout_dir.mkdir(parents=True, exist_ok=True)

    output_path = out_dir / f'{name}.png'
    cleaned_path = cleaned_dir / f'{name}_cleaned.png'
    layout_path = layout_dir / f'{name}_layout.json'

    img = Image.new('RGB', (480, 680), 'white')
    img.save(output_path)
    img.save(cleaned_path)
    items = [
        {
            'box': [40, 40, 180, 220],
            'mask_box': [40, 40, 180, 220],
            'text': '从一页漫画开始。',
            'raw_text': '一ページから始めよう。',
            'direction': 1,
            'style': 'dialogue',
            'font_size': 26,
        },
        {
            'box': [240, 320, 430, 500],
            'mask_box': [240, 320, 430, 500],
            'text': '检查译文，再完成排版。',
            'raw_text': '訳文を確認しよう。',
            'direction': 0,
            'style': 'dialogue',
            'font_size': 22,
        },
    ]
    layout_path.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
    return output_path


class EditorUiRedesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._ini = Path(self._tmp.name) / 'settings.ini'
        self._prev_fmt = QSettings.defaultFormat()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(self._tmp.name))
        self.addCleanup(lambda: QSettings.setDefaultFormat(self._prev_fmt))

    def _make_window(self, width=1280, height=800) -> MainWindow:
        with patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
        def _cleanup():
            window.editor_page._dirty = False
            window.close()
            self.app.processEvents()
        self.addCleanup(_cleanup)
        window.resize(width, height)
        window.show()
        self.app.processEvents()
        return window

    def _load_editor_sample(self, editor: EditorPage) -> Path:
        page = _write_sample_editor_page(Path(self._tmp.name))
        editor._add_page(str(page))
        self.assertTrue(editor.load_page(page))
        self.app.processEvents()
        return page

    def test_block_stepping_counter_and_delegate_payload(self):
        window = self._make_window()
        window._nav_editor.click()
        editor = window.editor_page
        self._load_editor_sample(editor)

        self.assertEqual(editor._page_count_label.text(), '1 页')
        self.assertEqual(editor._block_counter.text(), '1 / 2')
        self.assertFalse(editor._prev_block_btn.isEnabled())
        self.assertTrue(editor._next_block_btn.isEnabled())

        first_payload = editor.block_list.item(0).data(Qt.UserRole + 2)
        self.assertEqual(first_payload[0], '01')
        self.assertIn('26px', first_payload[2])

        editor._next_block_btn.click()
        self.app.processEvents()
        self.assertEqual(editor.block_list.currentRow(), 1)
        self.assertEqual(editor._block_counter.text(), '2 / 2')
        self.assertTrue(editor._prev_block_btn.isEnabled())
        self.assertFalse(editor._next_block_btn.isEnabled())

        editor._step_block(-1)
        self.app.processEvents()
        self.assertEqual(editor.block_list.currentRow(), 0)
        self.assertEqual(editor._block_counter.text(), '1 / 2')

    def test_zoom_buttons_and_canvas_toolbar_containment(self):
        window = self._make_window(1024, 720)
        window._nav_editor.click()
        editor = window.editor_page
        self._load_editor_sample(editor)
        QTest.qWait(40)

        events = []
        editor.preview.zoom_changed.connect(events.append)
        idx_100 = editor._zoom.findData(1.0)
        self.assertGreaterEqual(idx_100, 0)
        editor._zoom.setCurrentIndex(idx_100)
        self.app.processEvents()
        events.clear()

        editor._zoom_in_btn.click()
        self.app.processEvents()
        self.assertTrue(events)
        zoomed_in = float(events[-1])
        self.assertGreater(zoomed_in, 1.0)

        editor._zoom_out_btn.click()
        self.app.processEvents()
        self.assertLess(float(events[-1]), zoomed_in)

        toolbar = editor.preview.parentWidget().findChild(type(editor._pages_panel), 'canvasToolBar')
        self.assertIsNotNone(toolbar)
        bar_rect = toolbar.rect()
        for btn in (
            editor._repair_mode,
            editor._add_bubble_btn,
            editor._repair_btn,
            editor._fill_menu_btn,
            editor._repair_undo,
        ):
            mapped = QRect(btn.mapTo(toolbar, btn.rect().topLeft()), btn.size())
            self.assertTrue(bar_rect.contains(mapped), f'{btn.text()} clipped inside canvasToolBar: {mapped} vs {bar_rect}')
        self.assertLessEqual(toolbar.height(), 46, f'canvasToolBar wrapped to multiple rows at 1024x720: {toolbar.height()}px')

    def test_compact_820x480_editor_layout_keeps_text_and_outline_unclipped(self):
        window = self._make_window(820, 480)
        window._nav_editor.click()
        editor = window.editor_page
        self._load_editor_sample(editor)
        QTest.qWait(40)

        self.assertFalse(editor._canvas_heading.isVisible())
        self.assertFalse(editor._inspector_heading.isVisible())
        self.assertFalse(editor._break_hint.isVisible())
        self.assertTrue(editor._text_input.isVisible())
        self.assertGreaterEqual(editor._text_input.height(), 40)

        src_rect = editor._source_toggle.geometry()
        inp_rect = editor._text_input.geometry()
        self.assertFalse(src_rect.intersects(inp_rect))

        editor._inspector_tabs.setCurrentIndex(1)
        editor._advanced_style_toggle.setChecked(True)
        self.app.processEvents()
        QTest.qWait(40)
        self.assertIs(editor._properties_scroll.parentWidget().parentWidget().parentWidget(),
                      editor._inspector_tabs.findChildren(QScrollArea)[0].parentWidget().parentWidget().parentWidget())
        editor._properties_scroll.ensureWidgetVisible(editor._hollow_preset_btn, 0, 8)
        editor._properties_scroll.ensureWidgetVisible(editor._outline_width, 0, 8)
        vp_rect = editor._properties_scroll.viewport().rect()
        for widget in (editor._outline_width, editor._hollow_preset_btn):
            pos = widget.mapTo(editor._properties_scroll.viewport(), widget.rect().topLeft())
            box = QRect(pos, widget.size())
            self.assertTrue(vp_rect.contains(box), f'{widget.objectName()} clipped in viewport: {box} vs {vp_rect}')

    def test_text_editor_dialog_stats_and_insert_line_break(self):
        dialog = TextEditorDialog()
        self.addCleanup(dialog.close)
        dialog.set_block(1, '原文行', '第一行')
        self.assertEqual(dialog._stats.text(), '3 · 1')
        dialog.target.moveCursor(QTextCursor.End)

        insert_btn = next(
            btn for btn in dialog.findChildren(QPushButton) if btn.text() == '插入换行'
        )
        insert_btn.click()
        self.app.processEvents()
        self.assertEqual(dialog.target.toPlainText(), '第一行\n')
        self.assertEqual(dialog._stats.text(), '4 · 2')

    def test_main_window_context_preferences_fit_at_820x480_with_queue(self):
        window = self._make_window(1280, 800)
        page = _write_sample_editor_page(Path(self._tmp.name), name='queue_item')
        window._add_paths([str(page)])
        window.resize(820, 480)
        self.app.processEvents()
        window._pref_toggle.click()
        QTest.qWait(50)

        self.assertTrue(window._pref_container.isVisible())
        card = window.findChild(type(window._pref_container.parentWidget()), 'controlCard')
        self.assertIsNotNone(card)
        card_rect = card.rect()
        pref_rect = QRect(
            window._pref_container.mapTo(card, window._pref_container.rect().topLeft()),
            window._pref_container.size(),
        )
        self.assertTrue(card_rect.contains(pref_rect), f'pref_container overflowed controlCard: {pref_rect} vs {card_rect}')
        vp_rect = window._pref_container.viewport().rect()
        for box in window._pref_container.findChildren(QCheckBox):
            if box.isVisibleTo(window._pref_container):
                window._pref_container.ensureWidgetVisible(box, 0, 4)
                self.app.processEvents()
                vp_box = QRect(box.mapTo(window._pref_container.viewport(), box.rect().topLeft()), box.size())
                self.assertTrue(vp_rect.contains(vp_box), f'{box.text()} clipped inside viewport: {vp_box} vs {vp_rect}')
                card_box = QRect(box.mapTo(card, box.rect().topLeft()), box.size())
                self.assertTrue(card_rect.contains(card_box), f'{box.text()} overflowed controlCard: {card_box} vs {card_rect}')

    def test_820x640_text_editor_height_and_direct_quick_size_sync(self):
        window = self._make_window(820, 640)
        window._nav_editor.click()
        editor = window.editor_page
        self._load_editor_sample(editor)
        QTest.qWait(60)

        self.assertFalse(editor._favorite_fonts.isVisible())
        self.assertFalse(editor._source_text.isVisible())
        self.assertTrue(editor._text_input.isVisible())
        self.assertGreaterEqual(editor._text_input.height(), 110)
        self.assertTrue(editor._quick_size_spin.isVisible())
        self.assertEqual(editor._quick_size_spin.value(), 26)

        editor._quick_size_spin.setValue(33)
        self.assertEqual(editor._size_spin.value(), 33)
        QTest.qWait(90)
        self.assertEqual(editor.items[0]['font_size'], 33)
        self.assertEqual(editor.items[0]['rendered_font_size'], 33)

        editor._size_spin.setValue(27)
        self.assertEqual(editor._quick_size_spin.value(), 27)

        editor._source_toggle.click()
        QTest.qWait(240)
        self.assertTrue(editor._source_text.isVisible())
        self.assertLessEqual(editor._source_text.height(), 60)
        self.assertGreaterEqual(editor._text_input.height(), 110)

    def test_secondary_menus_single_level_containment_and_state_preservation(self):
        window = self._make_window(1440, 900)
        window._nav_editor.click()
        editor = window.editor_page
        self._load_editor_sample(editor)
        QTest.qWait(50)

        for menu in (
            editor._view_menu,
            editor._file_menu,
            editor._fill_menu,
            editor._font_menu,
            editor._favorite_fonts.manage_menu,
            window._font_picker.manage_menu,
        ):
            self.assertFalse(any(action.menu() is not None for action in menu.actions()))

        self.assertFalse(editor._advanced_style_toggle.isChecked())
        self.assertFalse(editor._advanced_style_panel.isVisible())
        self.assertNotIn('已自定义', editor._advanced_style_toggle.text())
        editor._outline_width.setValue(3.0)
        self.assertIn('已自定义', editor._advanced_style_toggle.text())

        editor._text_input.setPlainText('保留这段未保存译文')
        editor.preview.set_zoom(1.5)
        editor._repair_mode.setChecked(True)
        editor._repair_box = (40, 40, 120, 120)
        editor._update_repair_controls()
        QTest.qWait(70)

        editor._pages_action.trigger()
        self.assertFalse(editor._pages_panel.isVisible())
        editor._pages_action.trigger()
        self.assertTrue(editor._pages_panel.isVisible())

        self.assertFalse(editor._focus_btn.isVisible())
        editor._focus_action.trigger()
        self.assertTrue(editor._focus_btn.isChecked())
        self.assertTrue(editor._focus_btn.isVisible())
        self.assertFalse(editor._pages_panel.isVisible())
        self.assertFalse(editor._properties_panel.isVisible())
        self.assertEqual(editor._text_input.toPlainText(), '保留这段未保存译文')
        self.assertEqual(editor.block_list.currentRow(), 0)
        self.assertEqual(editor._repair_box, (40, 40, 120, 120))
        self.assertAlmostEqual(editor.preview._zoom, 1.5)
        self.assertTrue(editor._dirty)

        editor._focus_btn.click()
        self.assertFalse(editor._focus_btn.isChecked())
        self.assertFalse(editor._focus_btn.isVisible())
        self.assertTrue(editor._properties_panel.isVisible())

        self.assertFalse(editor._pick_cancel_btn.isVisible())
        editor._pick_fill_action.trigger()
        self.assertTrue(editor._pick_fill_btn.isChecked())
        self.assertTrue(editor._pick_cancel_btn.isVisible())
        editor._pick_cancel_btn.click()
        self.assertFalse(editor._pick_fill_btn.isChecked())
        self.assertFalse(editor._pick_cancel_btn.isVisible())

        editor._repair_mode.setChecked(False)
        bubble_menu = QMenu(editor)
        editor._populate_bubble_menu(bubble_menu)
        self.assertFalse(any(action.menu() is not None for action in bubble_menu.actions()))
        by_text = {action.text().split('\t')[0]: action for action in bubble_menu.actions() if not action.isSeparator()}
        self.assertTrue(by_text['全屏编辑译文'].isEnabled())
        self.assertTrue(by_text['白字黑边竖排'].isEnabled())

        editor.items[0]['restore_original'] = True
        editor._set_editable(True)
        editor._populate_bubble_menu(bubble_menu)
        by_text = {action.text().split('\t')[0]: action for action in bubble_menu.actions() if not action.isSeparator()}
        self.assertTrue(by_text['恢复处理结果'].isEnabled())
        self.assertFalse(by_text['全屏编辑译文'].isEnabled())
        self.assertFalse(by_text['字体库…'].isEnabled())
        self.assertFalse(by_text['白字黑边竖排'].isEnabled())
        self.assertFalse(by_text['重置文字变形'].isEnabled())

        editor.items[0]['restore_original'] = False
        editor._set_editable(True)
        canvas = editor.preview._label
        page_rect = canvas.page_rect()
        x1, y1, x2, y2 = editor.items[1]['box']
        cx = page_rect.left() + ((x1 + x2) / 2) * page_rect.width() / canvas.image_size.width()
        cy = page_rect.top() + ((y1 + y2) / 2) * page_rect.height() / canvas.image_size.height()
        seen = []
        with patch.object(editor, '_show_bubble_context_menu', side_effect=lambda pos: seen.append(pos)):
            QApplication.sendEvent(
                canvas,
                QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(round(cx), round(cy)), QPoint(100, 100)),
            )
        self.assertEqual(len(seen), 1)
        self.assertEqual(editor.block_list.currentRow(), 1)

        editor._pick_fill_btn.setChecked(True)
        with patch.object(editor, '_show_bubble_context_menu', side_effect=lambda pos: seen.append(pos)):
            QTest.mouseClick(canvas, Qt.RightButton, pos=QPoint(round(cx), round(cy)))
            QApplication.sendEvent(
                canvas,
                QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(round(cx), round(cy)), QPoint(100, 100)),
            )
        self.assertEqual(len(seen), 1)
        self.assertFalse(editor._pick_fill_btn.isChecked())

    def test_en_and_ja_toolbar_and_canvas_toolbar_unclipped_at_820_and_1024(self):
        self.addCleanup(lambda: (set_ui_language('zh-CN'), install_qt_language(self.app)))
        for lang in ('en', 'ja'):
            with patch.object(config, 'PROJECT_ROOT', Path(self._tmp.name)), \
                 patch.object(config, 'CONFIG_PATH', Path(self._tmp.name) / 'config.yaml'):
                config.save_ai_config({'ui_language': lang, 'ui_language_selected': True})
                set_ui_language(lang)
                install_qt_language(self.app)
                for width, height in ((1024, 720), (820, 640)):
                    with self.subTest(language=lang, width=width, height=height):
                        window = self._make_window(width, height)
                        window._nav_editor.click()
                        editor = window.editor_page
                        self._load_editor_sample(editor)
                        QTest.qWait(50)

                        toolbar = editor.findChild(type(editor._pages_panel), 'editorToolbar')
                        self.assertIsNotNone(toolbar)
                        toolbar_buttons = [
                            editor._view_menu_btn, editor._zoom_out_btn, editor._zoom,
                            editor._zoom_in_btn, editor._file_menu_btn, editor._save_btn,
                        ]
                        for prev, nxt in zip(toolbar_buttons, toolbar_buttons[1:]):
                            gap = nxt.mapTo(toolbar, nxt.rect().topLeft()).x() - prev.mapTo(toolbar, prev.rect().topRight()).x()
                            self.assertGreaterEqual(gap, 0, (lang, width, prev.objectName(), nxt.objectName()))
                        for widget in toolbar_buttons:
                            mapped = QRect(widget.mapTo(toolbar, widget.rect().topLeft()), widget.size())
                            self.assertTrue(toolbar.rect().contains(mapped), (lang, width, mapped, toolbar.rect()))

                        canvas_bar = editor.preview.parentWidget().findChild(type(editor._pages_panel), 'canvasToolBar')
                        self.assertIsNotNone(canvas_bar)
                        for btn in (
                            editor._repair_mode, editor._add_bubble_btn, editor._repair_btn,
                            editor._fill_menu_btn, editor._repair_undo,
                        ):
                            mapped = QRect(btn.mapTo(canvas_bar, btn.rect().topLeft()), btn.size())
                            self.assertTrue(canvas_bar.rect().contains(mapped), (lang, width, btn.text(), mapped, canvas_bar.rect()))
                            extra = 26 if btn.property('menuButton') else 16
                            self.assertGreaterEqual(btn.width(), btn.fontMetrics().horizontalAdvance(btn.text()) + extra)
                        if width == 1024:
                            self.assertLessEqual(canvas_bar.height(), 46, (lang, canvas_bar.height()))

                        for btn in (editor._line_break_btn, editor._expand_btn):
                            self.assertTrue(btn.isVisible(), (lang, width, btn.text()))
                            self.assertGreaterEqual(btn.width(), btn.fontMetrics().horizontalAdvance(btn.text()) + 14, (lang, width, btn.text(), btn.width()))
                            parent = btn.parentWidget()
                            mapped = QRect(btn.mapTo(parent, btn.rect().topLeft()), btn.size())
                            self.assertTrue(parent.rect().contains(mapped), (lang, width, btn.text(), mapped, parent.rect()))
                        self.assertLess(
                            editor._line_break_btn.mapTo(editor._properties_panel, editor._line_break_btn.rect().topRight()).x(),
                            editor._expand_btn.mapTo(editor._properties_panel, editor._expand_btn.rect().topLeft()).x(),
                        )


if __name__ == '__main__':
    unittest.main()
