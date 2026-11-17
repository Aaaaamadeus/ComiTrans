import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QRect, QSettings, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QScrollArea

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
        window = MainWindow()
        self.addCleanup(lambda: (window.close(), self.app.processEvents()))
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
            editor._repair_undo,
            editor._fill_white_btn,
            editor._fill_black_btn,
            editor._fill_color_btn,
            editor._pick_fill_btn,
            editor._fill_custom_btn,
        ):
            mapped = QRect(btn.mapTo(toolbar, btn.rect().topLeft()), btn.size())
            self.assertTrue(bar_rect.contains(mapped), f'{btn.text()} clipped inside canvasToolBar: {mapped} vs {bar_rect}')

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


if __name__ == '__main__':
    unittest.main()
