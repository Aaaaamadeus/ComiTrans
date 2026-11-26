from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image, ImageChops
from PySide6.QtCore import QPointF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from comic_translate_core.paint_engine import BrushTool
from comic_translate_desktop import config
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.paint_filter_dialog import PaintFilterDialog
from comic_translate_desktop.ui.theme import apply_theme
from tests.qt_utils import destroy_widget


class EditorPaintIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_dir = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)

    @classmethod
    def tearDownClass(cls):
        apply_theme(cls.app, 'light')
        cls.settings_dir.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        cfg_patch = patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml')
        cfg_patch.start()
        self.addCleanup(cfg_patch.stop)
        config.save_ai_config({'watermark_enabled': False})
        apply_theme(self.app, 'light')

    def _make_page(self, name='paint_page', *, with_original=False):
        output = self.root / 'output' / f'{name}.png'
        cleaned = self.root / 'output_cleaned' / f'{name}_cleaned.png'
        layout = self.root / 'output_layout' / f'{name}_layout.json'
        for p in (output, cleaned, layout):
            p.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new('RGB', (400, 500), '#ffffff')
        img.save(output)
        img.save(cleaned)
        if with_original:
            orig = self.root / 'output_original' / f'{name}_original.png'
            orig.parent.mkdir(parents=True, exist_ok=True)
            Image.new('RGB', (400, 500), '#d0d0d0').save(orig)
        items = [
            {
                'text': '测试译文',
                'source_text': 'テスト',
                'box': [40, 40, 180, 120],
                'mask_box': [40, 40, 180, 120],
                'style': 'dialogue',
                'direction': 0,
                'font_size': 24,
                'rendered_font_size': 24,
                'offset_x': 0,
                'offset_y': 0,
            }
        ]
        layout.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        return output, cleaned, layout

    def _open_editor(self, output):
        editor = EditorPage()
        editor.resize(1280, 800)
        editor.show()
        self.assertTrue(editor.load_page(output))
        self.assertTrue(editor.apply_changes())
        self.app.processEvents()
        self.addCleanup(destroy_widget, editor)
        return editor

    def test_toolbox_all_25_tools_are_icon_only_with_dual_theme_states(self):
        output, _cleaned, _layout = self._make_page('icons')
        editor = self._open_editor(output)
        panel = editor._paint_panel

        self.assertEqual(set(panel._tool_buttons.keys()), set(BrushTool.ALL))
        self.assertEqual(len(panel._tool_buttons), 25)

        for mode in ('light', 'dark'):
            apply_theme(self.app, mode)
            self.app.processEvents()
            for tool_id, btn in panel._tool_buttons.items():
                self.assertEqual(btn.text(), '', (mode, tool_id))
                self.assertTrue(btn.property('paintTool'), (mode, tool_id))
                self.assertFalse(btn.icon().isNull(), (mode, tool_id))
                self.assertTrue(bool(btn.toolTip().strip()), (mode, tool_id))
                self.assertTrue(bool(btn.accessibleName().strip()), (mode, tool_id))
                off_img = btn.icon().pixmap(QSize(16, 16), QIcon.Normal, QIcon.Off).toImage()
                on_img = btn.icon().pixmap(QSize(16, 16), QIcon.Normal, QIcon.On).toImage()
                self.assertFalse(off_img.isNull(), (mode, tool_id))
                self.assertFalse(on_img.isNull(), (mode, tool_id))
                # Checked and unchecked states use inverse monochrome stroke polarity.
                self.assertNotEqual(off_img.constBits().tobytes(), on_img.constBits().tobytes(), (mode, tool_id))

    def test_paint_stroke_independent_text_undo_redo_and_save_reload(self):
        output, _cleaned, layout = self._make_page('paint_flow')
        editor = self._open_editor(output)

        self.assertEqual(editor._inspector_tabs.tabText(1), '排版与位置')
        editor._paint_mode_btn.setChecked(True)
        self.app.processEvents()
        self.assertTrue(editor.preview._label.paint_active)
        self.assertEqual(editor._inspector_tabs.currentIndex(), 2)
        self.assertFalse(editor.preview._label.region_editable)

        editor._paint_panel.select_tool(BrushTool.PEN)
        editor._paint_panel._set_size(14)
        editor._paint_panel.set_fg_color(QColor('#ff0000'), emit=True)

        before_clean = editor._cleaned_image.copy()
        editor._on_paint_stroke_started(250.0, 260.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_moved(310.0, 260.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_ended(310.0, 260.0, 1.0, Qt.NoModifier)

        self.assertTrue(editor._dirty)
        self.assertEqual(len(editor._repair_history), 1)
        painted_px = editor._cleaned_image.getpixel((280, 260))
        self.assertGreater(painted_px[0], 200)
        self.assertLess(painted_px[1], 50)
        after_clean = editor._cleaned_image.copy()

        # Text remains independent & editable
        editor._text_input.setPlainText('修改后的译文')
        QTest.qWait(80)
        self.assertTrue(editor.apply_changes())
        self.assertEqual(editor.items[0]['text'], '修改后的译文')
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, after_clean).getbbox())

        # Undo and Redo restore exact pixels while preserving text
        editor.preview._label.setFocus(Qt.MouseFocusReason)
        QTest.keyClick(editor.preview._label, Qt.Key_Z, Qt.ControlModifier)
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, before_clean).getbbox())
        self.assertEqual(editor.items[0]['text'], '修改后的译文')

        QTest.keyClick(editor.preview._label, Qt.Key_Y, Qt.ControlModifier)
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, after_clean).getbbox())

        # Ctrl+Z inside _text_input must NOT undo canvas paint
        editor._text_input.setFocus(Qt.MouseFocusReason)
        QTest.keyClick(editor._text_input, Qt.Key_Z, Qt.ControlModifier)
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, after_clean).getbbox())

        # Save & reload preserves painted cleaned background and layout
        self.assertTrue(editor.save_image())
        reopened = self._open_editor(output)
        self.assertEqual(reopened._cleaned_image.getpixel((280, 260)), after_clean.getpixel((280, 260)))
        self.assertEqual(json.loads(layout.read_text(encoding='utf-8'))[0]['text'], '修改后的译文')

    def test_selection_pen_fill_and_mask_repair_and_eyedropper(self):
        output, _cleaned, _layout = self._make_page('select_repair')
        editor = self._open_editor(output)
        editor._paint_mode_btn.setChecked(True)
        self.app.processEvents()

        # Paint a green block on canvas, then pick it with right-click eyedropper
        editor._paint_panel.select_tool(BrushTool.PEN)
        editor._paint_panel._set_size(24)
        editor._paint_panel.set_fg_color(QColor('#00cc44'), emit=True)
        editor._on_paint_stroke_started(300.0, 350.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_ended(300.0, 350.0, 1.0, Qt.NoModifier)

        editor._paint_panel.set_fg_color(QColor('#000000'), emit=True)
        editor._on_paint_right_clicked(300.0, 350.0)
        picked = editor._paint_panel.color_wheel.fg_color()
        self.assertGreater(picked.green(), 180)
        self.assertLess(picked.red(), 30)

        # Select pen creates mask; fill colors it; AI repair runs mask repair
        editor._paint_panel.select_tool(BrushTool.SELECT_PEN)
        editor._paint_panel._set_size(20)
        editor._on_paint_stroke_started(260.0, 220.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_moved(290.0, 220.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_ended(290.0, 220.0, 1.0, Qt.NoModifier)
        self.assertFalse(editor._selection_engine.is_empty())

        editor._paint_panel.set_fg_color(QColor('#112233'), emit=True)
        editor._on_paint_selection_action('fill')
        self.assertEqual(editor._cleaned_image.getpixel((275, 220)), (0x11, 0x22, 0x33))

        # AI repair on arbitrary selection mask
        with patch.object(editor._repair_engine, 'repair_mask', return_value=((245, 205, 305, 235), Image.new('RGB', (60, 30), '#ffffff'))):
            editor._start_background_repair()
            while editor._repair_worker is not None:
                self.app.processEvents()
                QTest.qWait(10)
        self.assertEqual(editor._cleaned_image.getpixel((275, 220)), (255, 255, 255))

    def test_rotation_and_horizontal_flip_coordinate_roundtrip(self):
        output, _cleaned, _layout = self._make_page('xform')
        editor = self._open_editor(output)
        editor._paint_mode_btn.setChecked(True)
        self.app.processEvents()

        for rot, flip in ((0.0, False), (45.0, False), (-90.0, True), (33.0, True)):
            editor.preview.set_view_transform(rot, flip, True)
            self.app.processEvents()
            canvas = editor.preview._label
            target = QPointF(180.0, 240.0)
            widget_pt = canvas.image_to_widget(target)
            mapped_back = canvas.widget_to_image(widget_pt, clamp=False)
            self.assertIsNotNone(mapped_back, (rot, flip))
            self.assertAlmostEqual(mapped_back.x(), target.x(), delta=1.0)
            self.assertAlmostEqual(mapped_back.y(), target.y(), delta=1.0)

    def test_filter_dialog_preview_cancel_and_apply(self):
        output, _cleaned, _layout = self._make_page('filters')
        editor = self._open_editor(output)
        editor._paint_mode_btn.setChecked(True)
        self.app.processEvents()
        before = editor._cleaned_image.copy()

        # Cancel must leave _cleaned_image and _rendered unmodified
        with patch.object(PaintFilterDialog, 'exec', return_value=QDialog.Rejected):
            editor._on_paint_filter_requested('bc')
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, before).getbbox())

        # Accepted invert filter mutates cleanly and can be undone
        editor._on_paint_filter_requested('invert')
        self.assertEqual(editor._cleaned_image.getpixel((300, 300)), (0, 0, 0))
        self.assertTrue(editor.undo_background_repair())
        self.assertIsNone(ImageChops.difference(editor._cleaned_image, before).getbbox())

    def test_restored_bubble_remains_protected_while_painting(self):
        output, _cleaned, _layout = self._make_page('protected_paint', with_original=True)
        editor = self._open_editor(output)
        self.assertTrue(editor.toggle_bubble_original())
        self.assertTrue(editor.items[0]['restore_original'])

        editor._paint_mode_btn.setChecked(True)
        self.app.processEvents()
        before_bubble = editor._cleaned_image.crop((40, 40, 180, 120)).copy()

        editor._paint_panel.select_tool(BrushTool.PEN)
        editor._paint_panel._set_size(30)
        editor._paint_panel.set_fg_color(QColor('#ff0000'), emit=True)
        editor._on_paint_stroke_started(80.0, 80.0, 1.0, Qt.NoModifier)
        editor._on_paint_stroke_ended(120.0, 80.0, 1.0, Qt.NoModifier)

        self.assertIsNone(ImageChops.difference(editor._cleaned_image.crop((40, 40, 180, 120)), before_bubble).getbbox())


if __name__ == '__main__':
    unittest.main()
