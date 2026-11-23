import json
import os
from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import ImageChops
from PySide6.QtCore import QSettings, Qt, QPointF, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem, QMenu

from comic_translate_desktop import config
from comic_translate_desktop.desktop_translation import DesktopTranslationMixin
from comic_translate_desktop.productivity import (
    UsageMeter, usage_cost, trial_projection, desktop_translation_config,
    terminology_projects, lettering_style, apply_lettering_style)
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.ui.workflow_dialogs import TerminologyDialog, UsageDialog
from comic_translate_desktop.i18n import tr
from comic_translate_desktop.worker import BatchWorker
from comic_translate_desktop.pdf_project import load_pdf_project
from comic_translate_desktop.pdf_utils import build_pdf_from_images
from tests import test_editor_live_preview as editor_fixtures
from tests import test_translation_contract as translation_fixtures
from tests import test_resume_translation as worker_fixtures


class ProductivityDataTests(unittest.TestCase):
    def test_target_only_terms_reach_the_real_translation_prompt_and_usage_counts_retries(self):
        projects = {'work': dict(name='作品甲', terms=[dict(term='真子', kind='角色', note='猫头鹰装的女孩')])}
        settings = dict(terminology_projects=projects, terminology_project='work', translation_prompt='背景')
        pipeline = translation_fixtures._pipeline()
        desktop_type = type('DesktopPipeline', (DesktopTranslationMixin, type(pipeline)), {})
        desktop = desktop_type.__new__(desktop_type)
        desktop.__dict__.update(pipeline.__dict__)
        BatchWorker._apply_api_config(desktop, {**desktop.__dict__, **settings})
        desktop.usage_meter = UsageMeter()
        sdk = Mock()
        responses = [translation_fixtures.response('bad JSON'),
                     translation_fixtures.response('{"translations":["真子回来了"]}')]
        for response in responses:
            response.usage = SimpleNamespace(prompt_tokens=100, completion_tokens=20)
        sdk.chat.completions.create.side_effect = responses
        with patch('openai.OpenAI', return_value=sdk):
            self.assertEqual(desktop.translate_page_batch(['マコが帰ってきた'], None), ['真子回来了'])
        prompt = sdk.chat.completions.create.call_args.kwargs['messages'][0]['content']
        self.assertIn('自行匹配', prompt)
        self.assertIn('猫头鹰装的女孩', prompt)
        self.assertNotIn('source_term', prompt)
        self.assertEqual(desktop.usage_meter.snapshot()['prompt_tokens'], 200)
        self.assertEqual(desktop.usage_meter.snapshot()['requests'], 2)
        self.assertEqual(settings['translation_prompt'], '背景')

    def test_missing_partial_and_invalid_usage_never_claim_zero_or_complete_cost(self):
        meter = UsageMeter()
        meter.record(SimpleNamespace(usage=dict(prompt_tokens=120, completion_tokens=30)))
        pricing = dict(enabled=True, input=2, output=6)
        self.assertAlmostEqual(usage_cost(meter.snapshot(), pricing), .00042)
        meter.record(SimpleNamespace(usage=None))
        self.assertIsNone(usage_cost(meter.snapshot(), pricing))
        meter.record(SimpleNamespace(usage=dict(prompt_tokens=-1, completion_tokens=True)))
        self.assertEqual(meter.snapshot()['reported'], 1)
        self.assertIsNone(usage_cost(meter.snapshot(), pricing))
        report = dict(completed_pages=2, total_pages=20, processing_seconds=12,
                      usage=meter.snapshot())
        self.assertEqual(trial_projection(report, pricing)['seconds'], 120)
        self.assertIsNone(trial_projection({**report, 'failed': True}, pricing))
        self.assertIsNone(trial_projection({**report, 'cancelled': True}, pricing))
        self.assertIsNone(trial_projection({**report, 'total_pages_known': False}, pricing))

    def test_style_never_copies_text_geometry_or_modifies_restored_bubbles(self):
        source = dict(font_size=24, text_color='#ff0000', direction=0, text='甲', box=[0, 0, 90, 90])
        target = dict(font_size=18, text='乙', source_text='乙原文', box=[20, 30, 50, 60], offset_x=8)
        self.assertTrue(apply_lettering_style(target, lettering_style(source)))
        self.assertEqual(target['text'], '乙')
        self.assertEqual(target['source_text'], '乙原文')
        self.assertEqual(target['box'], [20, 30, 50, 60])
        self.assertEqual(target['offset_x'], 8)
        target['restore_original'] = True
        before = deepcopy(target)
        self.assertFalse(apply_lettering_style(target, dict(font_size=60)))
        self.assertEqual(target, before)


class ProductivityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        setting = patch.object(config, 'CONFIG_PATH', self.root / 'config.yaml')
        setting.start()
        self.addCleanup(setting.stop)
        config.save_ai_config({'watermark_enabled': False})

    def editor(self):
        output, layout = editor_fixtures.EditorLivePreviewTests.page(self, two_blocks=True)
        editor = EditorPage()
        self.assertTrue(editor.load_page(output))
        self.addCleanup(editor_fixtures.EditorLivePreviewTests.destroy_editor, editor)
        return editor, output, layout

    def test_multiselect_changes_only_the_edited_attribute_and_survives_save_reload(self):
        editor, output, layout = self.editor()
        original = deepcopy(editor.items)
        editor._select_blocks([0, 1])
        editor._outline_width.setValue(4)
        self.assertTrue(editor.apply_changes())
        for row, item in enumerate(editor.items):
            self.assertEqual(item['outline_width'], 4)
            for key in ('text', 'source_text', 'box', 'mask_box'):
                self.assertEqual(item[key], original[row][key])
        self.assertEqual(editor.items[1]['font_size'], 20)
        # Text edits remain local even while several bubbles are selected.
        editor._text_input.setPlainText('只改这一个气泡')
        editor.apply_changes()
        self.assertEqual(editor.items[1]['text'], original[1]['text'])
        self.assertTrue(editor.save_image())
        saved = json.loads(layout.read_text(encoding='utf-8'))
        self.assertEqual([item['outline_width'] for item in saved], [4, 4])
        self.assertEqual(saved[1]['text'], original[1]['text'])

    def test_brush_undo_preserves_text_and_next_page_clears_undo(self):
        editor, _, _ = self.editor()
        before = deepcopy(editor.items[1])
        editor.resize(1440, 900)
        editor.show()
        self.app.processEvents()
        editor.copy_style()
        point = editor.block_list.visualItemRect(editor.block_list.item(1)).center()
        QTest.mouseClick(editor.block_list.viewport(), Qt.LeftButton, Qt.NoModifier, point)
        self.assertEqual(editor.items[1]['font_size'], 24)
        self.assertEqual(editor.items[1]['text'], before['text'])
        self.assertEqual(editor.items[1]['box'], before['box'])
        self.assertTrue(editor.undo_style())
        self.assertEqual(editor.items[1]['font_size'], 20)
        self.assertEqual(editor.items[1]['text'], before['text'])
        second, _ = editor_fixtures.EditorLivePreviewTests.page(self, name='second', two_blocks=True)
        editor._dirty = False
        self.assertTrue(editor.load_page(second))
        self.assertFalse(editor.undo_style())

    def test_selection_overlay_does_not_change_export_pixels_and_ctrl_click_toggles(self):
        editor, _, _ = self.editor()
        editor.resize(1440, 900)
        editor.show()
        self.app.processEvents()
        self.assertTrue(editor.apply_changes())
        before = editor._rendered.copy()
        editor._show_mask.setChecked(True)
        canvas = editor.preview._label
        point = canvas._box_rect(editor.items[1]['mask_box']).center().toPoint()
        QTest.mouseClick(canvas, Qt.LeftButton, Qt.ControlModifier, point)
        self.assertEqual(editor.selected_blocks(), [0, 1])
        QTest.mouseClick(canvas, Qt.LeftButton, Qt.ControlModifier, point)
        self.assertEqual(editor.selected_blocks(), [0])
        start = (canvas._box_rect(editor.items[0]['mask_box']).topLeft() - QPointF(3, 3)).toPoint()
        end = (canvas._box_rect(editor.items[1]['mask_box']).bottomRight() + QPointF(3, 3)).toPoint()
        QTest.mousePress(canvas, Qt.LeftButton, Qt.ShiftModifier, start)
        QTest.mouseMove(canvas, end)
        QTest.mouseRelease(canvas, Qt.LeftButton, Qt.ShiftModifier, end)
        self.assertEqual(editor.selected_blocks(), [0, 1])
        self.assertIsNone(ImageChops.difference(before, editor._rendered).getbbox())

    def test_switching_bubble_before_debounce_does_not_apply_style_to_new_selection(self):
        editor, _, _ = self.editor()
        editor._outline_width.setValue(5)
        editor.block_list.setCurrentRow(1)
        editor.apply_changes()
        self.assertEqual(editor.items[0]['outline_width'], 5)
        self.assertIsNone(editor.items[1].get('outline_width'))

    def test_flat_style_menu_preserves_batch_selection_and_right_click_never_paints(self):
        editor, _, _ = self.editor()
        editor.resize(1024, 720)
        editor.show()
        self.app.processEvents()
        editor.copy_style()
        editor._stop_style_brush()
        editor._select_blocks([0, 1])
        editor._style_brush_btn.setChecked(True)
        before = deepcopy(editor.items)
        with patch.object(editor, '_show_bubble_context_menu'):
            editor._show_canvas_bubble_context_menu(1, QPoint(100, 100))
        self.assertEqual(editor.selected_blocks(), [0, 1])
        self.assertEqual(editor.items, before)
        self.assertTrue(editor._brush_cancel_btn.isVisible())
        self.assertFalse(editor.preview._label.region_editable)
        menu = QMenu(editor)
        self.addCleanup(menu.deleteLater)
        editor._populate_bubble_menu(menu)
        self.assertTrue(all(action.menu() is None for action in menu.actions()))
        actions = {action.text(): action for action in menu.actions()}
        actions[tr('应用样式到所选气泡')].trigger()
        self.assertEqual([item['font_size'] for item in editor.items], [24, 24])
        self.assertEqual([item['text'] for item in editor.items], [item['text'] for item in before])
        editor._populate_bubble_menu(menu)
        {action.text(): action for action in menu.actions()}[tr('撤销样式')].trigger()
        self.assertEqual(editor.items[1]['font_size'], 20)
        editor._brush_cancel_btn.click()
        self.assertFalse(editor._style_brush_btn.isChecked())
        self.assertTrue(editor._restore_bubble_btn.isVisible())
        editor.copy_style()
        editor._repair_mode.setChecked(True)
        self.assertFalse(editor._style_brush_btn.isChecked())

    def test_project_switch_keeps_target_only_terms_and_cancel_does_not_mutate_config(self):
        original = dict(terminology_project='a', terminology_projects={
            'a': dict(name='作品甲', terms=[dict(term='真子', kind='角色', note='女孩')]),
            'b': dict(name='作品乙', terms=[])})
        dialog = TerminologyDialog(original)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.table.columnCount(), 3)
        dialog.table.setItem(0, 0, QTableWidgetItem('小真'))
        dialog.project.setCurrentIndex(dialog.project.findData('b'))
        dialog.table.insertRow(0)
        dialog.table.setItem(0, 0, QTableWidgetItem('苍蓝城'))
        values = dialog.values()
        self.assertEqual(values['terminology_projects']['a']['terms'][0]['term'], '小真')
        self.assertEqual(values['terminology_projects']['b']['terms'][0]['term'], '苍蓝城')
        self.assertEqual(original['terminology_projects']['a']['terms'][0]['term'], '真子')
        config.save_ai_config(values)
        loaded = config.load_ai_config()
        self.assertIn('苍蓝城', desktop_translation_config(loaded)['translation_prompt'])
        self.assertNotIn('小真', desktop_translation_config(loaded)['translation_prompt'])

    def test_task_menu_groups_optional_actions_and_locks_them_during_a_job(self):
        with patch.object(config, 'PROJECT_ROOT', self.root), patch.object(MainWindow, '_start_warmup'):
            window = MainWindow()
            self.addCleanup(self.destroy_main, window)
            window._warmup_timer.stop()
            window.resize(820, 640)
            window.show()
            self.app.processEvents()
            self.assertTrue(window._trial_btn.isVisible())
            self.assertTrue(window._task_menu_btn.isVisible())
            self.assertFalse(window._usage_btn.isVisible())
            self.assertFalse(window._task_usage_action.isEnabled())
            self.assertTrue(all(action.menu() is None for action in window._task_menu.actions()))
            window.config.update(terminology_project='a', terminology_projects={
                'a': dict(name='作品甲', terms=[dict(term='真子')])})
            window._refresh_terminology_summary()
            self.assertIn('作品甲', window._task_work_info.toolTip())
            window._last_usage_report = dict(completed_pages=1)
            window._update_actions()
            self.assertTrue(window._task_usage_action.isEnabled())
            window.worker = SimpleNamespace()
            window._update_actions()
            self.assertFalse(window._task_menu_btn.isEnabled())
            self.assertFalse(window._task_terms_action.isEnabled())
            self.assertFalse(window._task_usage_action.isEnabled())

    @staticmethod
    def destroy_main(window):
        window.worker = None
        window.editor_page._dirty = False
        window.close()
        window.deleteLater()


class TrialIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pdf_trial_uses_real_partial_project_and_formal_run_still_processes_every_page(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            images = []
            for number in range(5):
                image = root / f'{number}.png'
                Image.new('RGB', (100, 120), 'white').save(image)
                images.append(image)
            source = build_pdf_from_images(images, [(100, 120)] * 5, root / 'book.pdf')
            context = root / '.cache/translation-context.json'
            context.parent.mkdir()
            context.write_text('formal-context-untouched', encoding='utf-8')
            settings = dict(api_key='test', api_base_url='https://example.invalid',
                            translation_model='test', pdf_dpi=96, max_workers=2,
                            resume_enabled=True, retain_translation_context=True)
            with patch.object(config, 'PROJECT_ROOT', root):
                trial = BatchWorker([source], root / 'output/trial/sample',
                                    {**settings, 'trial_page_limit': 2},
                                    pipeline=worker_fixtures.RecordingPipeline())
                trial.run()
                report = trial.usage_report
                self.assertEqual((report['completed_pages'], report['planned_pages'], report['total_pages']), (2, 2, 5))
                self.assertEqual(len(load_pdf_project(report['outputs'][0]).images), 2)
                self.assertEqual(context.read_text(encoding='utf-8'), 'formal-context-untouched')
                pipeline = worker_fixtures.RecordingPipeline()
                full = BatchWorker([source], root / 'output', {**settings, 'retain_translation_context': False}, pipeline=pipeline)
                full.run()
                self.assertEqual(full.usage_report['completed_pages'], 5)
                self.assertEqual(len(pipeline.requests), 5)
                self.assertEqual(len(load_pdf_project(root / 'output/book_translated.pdf').images), 5)

    def test_prices_and_inactive_terms_preserve_resume_but_active_terms_invalidate(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'page.png'
            Image.new('RGB', (100, 120), 'white').save(source)
            settings = dict(api_key='test', api_base_url='https://example.invalid',
                            translation_model='test', resume_enabled=True,
                            terminology_project='a', terminology_projects={
                                'a': dict(name='甲', terms=[dict(term='真子')]),
                                'b': dict(name='乙', terms=[])})
            def run(values):
                pipeline = worker_fixtures.RecordingPipeline()
                worker = BatchWorker([source], root / 'output', values, pipeline=pipeline)
                worker.run()
                self.assertFalse(worker.usage_report['failed'])
                return pipeline.requests
            with patch.object(config, 'PROJECT_ROOT', root):
                legacy = {key: value for key, value in settings.items() if not key.startswith('terminology_')}
                self.assertEqual(run(legacy), ['page.png'])
                migrated = {**legacy, 'terminology_project': '', 'terminology_projects': {}, 'usage_pricing': {}}
                self.assertEqual(run(migrated), [])
                self.assertEqual(run(settings), ['page.png'])
                updated = deepcopy(settings)
                updated['usage_pricing'] = dict(enabled=True, input=2, output=5)
                updated['terminology_projects']['b']['terms'] = [dict(term='苍蓝城')]
                self.assertEqual(run(updated), [])
                updated['terminology_projects']['a']['terms'] = [dict(term='小真')]
                self.assertEqual(run(updated), ['page.png'])
