from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageChops

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "comic-translate-ai/main"))

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication
from comic_translate_core.watermark import apply_watermark
from comic_translate_desktop import config as app_config
from comic_translate_desktop.pdf_utils import build_pdf_from_images, render_pdf_pages
from comic_translate_desktop.ui.api_config_page import ApiConfigPage
from comic_translate_desktop.ui.editor_page import EditorPage
from comic_translate_desktop.ui.main_window import MainWindow
from comic_translate_desktop.worker import BatchWorker
from comic_translator_pipeline import ComicTranslatorPipeline


class _BlankPipeline(ComicTranslatorPipeline):
    """Exercise the real output stages without loading models or contacting an API."""

    def __init__(self):
        self.multimodal = False
        self.progress_callback = self.cancel_callback = None

    def prepare_comic_page(self, path):
        with Image.open(path) as image:
            pixels = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        return dict(img_cv=pixels, bubbles_data=[], bubble_metadata=[], ocr_texts=[])


class WatermarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.settings_dir = tempfile.TemporaryDirectory()
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, cls.settings_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings_dir.cleanup()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        config_patch = patch.object(app_config, "CONFIG_PATH", self.root / "config.yaml")
        config_patch.start()
        self.addCleanup(config_patch.stop)

    def assert_corner_only(self, original, marked):
        self.assertEqual(original.size, marked.size)
        self.assertEqual(original.mode, marked.mode)
        bounds = ImageChops.difference(original.convert("RGB"), marked.convert("RGB")).getbbox()
        self.assertIsNotNone(bounds)
        x1, y1, x2, y2 = bounds
        self.assertGreater(x1, original.width * .80)
        self.assertGreater(y1, original.height * .85)
        self.assertLess(x2, original.width)
        self.assertLess(y2, original.height)

    def test_disabled_is_pixel_identical_and_does_not_load_font(self):
        source = Image.new("RGBA", (1200, 1800), (50, 80, 110, 160))
        with patch("comic_translate_core.watermark.ImageFont.truetype", side_effect=AssertionError):
            self.assertIs(apply_watermark(source), source)
            self.assertIs(apply_watermark(source, enabled=False), source)

    def test_enabled_preserves_source_and_stays_in_corner_on_light_and_dark_pages(self):
        for mode, color in (("RGB", "white"), ("RGB", "black"), ("RGBA", "#12345680"), ("L", 180)):
            for size in ((1220, 1750), (1750, 1220), (200, 300)):
                with self.subTest(mode=mode, color=color, size=size):
                    original = Image.new(mode, size, color)
                    before = original.tobytes()
                    marked = apply_watermark(original, enabled=True)
                    self.assertEqual(original.tobytes(), before)
                    self.assert_corner_only(original, marked)

    def test_small_and_extreme_aspect_ratios_do_not_clip_or_fail(self):
        for size in ((1, 1), (8, 8), (20, 1000), (4000, 20)):
            with self.subTest(size=size):
                image = Image.new("RGB", size, "white")
                marked = apply_watermark(image, enabled=True)
                self.assertEqual(marked.size, size)
                self.assertEqual(marked.getpixel((size[0] - 1, size[1] - 1)), (255, 255, 255))

    def test_config_defaults_off_and_round_trips_both_settings(self):
        self.assertFalse(app_config.load_ai_config()["watermark_enabled"])
        page = ApiConfigPage(app_config.load_ai_config())
        self.addCleanup(page.close)
        self.assertFalse(page._watermark_check.isChecked())
        for enabled in (True, False):
            page._watermark_check.setChecked(enabled)
            app_config.save_ai_config(page.values())
            loaded = app_config.load_ai_config()
            self.assertEqual(loaded["watermark_enabled"], enabled)
            page.load_config(loaded)
            self.assertEqual(page._watermark_check.isChecked(), enabled)

    def run_worker(self, source, output, pipeline, *, enabled):
        config = dict(api_key="", api_base_url="", translation_model="", pdf_dpi=96, watermark_enabled=enabled)
        worker = BatchWorker([source], output, config, pipeline=pipeline)
        summary, errors = [], []
        worker.finished.connect(lambda success, failure: summary.append((success, failure)))
        worker.image_failed.connect(lambda name, message: errors.append((name, message)))
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(summary, [(1, 0)])

    def test_worker_updates_reused_pipeline_and_keeps_clean_base_unmarked(self):
        source = self.root / "page.png"
        image = Image.new("RGB", (600, 900), "white")
        image.save(source)
        before = source.read_bytes()
        pipeline = _BlankPipeline()
        for enabled in (True, False):
            out = self.root / str(enabled)
            self.run_worker(source, out, pipeline, enabled=enabled)
            with Image.open(out / "page_translated.png") as result:
                if enabled:
                    self.assert_corner_only(image, result)
                else:
                    self.assertEqual(result.tobytes(), image.tobytes())
            with Image.open(self.root / f"{enabled}_cleaned/page_translated_cleaned.png") as clean:
                self.assertEqual(clean.tobytes(), image.tobytes())
            self.assertEqual(source.read_bytes(), before)

    def test_pdf_marks_every_page_and_preserves_page_sizes(self):
        paths = [self.root / "portrait.png", self.root / "landscape.png"]
        sizes = [(360, 540), (540, 360)]
        for path, size in zip(paths, sizes):
            Image.new("RGB", size, "white").save(path)
        source = self.root / "comic.pdf"
        build_pdf_from_images(paths, sizes, source)
        self.run_worker(source, self.root / "output", _BlankPipeline(), enabled=True)
        pages = render_pdf_pages(self.root / "output/comic_translated.pdf", self.root / "rendered", dpi=96)
        self.assertEqual(len(pages), 2)
        for page, size in zip(pages, sizes):
            self.assertAlmostEqual(page.width_points, size[0], delta=1.5)
            self.assertAlmostEqual(page.height_points, size[1], delta=1.5)
            with Image.open(page.image_path) as result:
                self.assert_corner_only(Image.new(result.mode, result.size, "white"), result)

    def test_editor_toggle_preserves_drafts_and_repeated_saves_do_not_accumulate(self):
        output = self.root / "output/page.png"
        clean = self.root / "output_cleaned/page_cleaned.png"
        layout = self.root / "output_layout/page_layout.json"
        for path in (output, clean, layout):
            path.parent.mkdir()
        image = Image.new("RGB", (600, 900), "white")
        image.save(output)
        image.save(clean)
        layout.write_text(json.dumps([dict(box=[30, 30, 130, 300], text="", custom_metadata="keep")]), encoding="utf-8")
        editor = EditorPage()
        self.addCleanup(editor.close)
        editor.load_page(output)
        editor._text_input.setPlainText("保留修改")
        editor.set_watermark_enabled(True)
        self.assertEqual(editor.items[0]["text"], "保留修改")
        editor._text_input.setPlainText("")
        self.assertTrue(editor.save_image())
        first = output.read_bytes()
        editor.render()
        editor._dirty = True
        self.assertTrue(editor.save_image())
        self.assertEqual(output.read_bytes(), first)
        editor.set_watermark_enabled(False)
        self.assertTrue(editor.save_image())
        with Image.open(output) as result:
            self.assertEqual(result.tobytes(), image.tobytes())
        self.assertEqual(json.loads(layout.read_text(encoding="utf-8"))[0]["custom_metadata"], "keep")

    def test_saving_settings_updates_editor_without_reloading_models(self):
        with patch.object(MainWindow, "_start_warmup"):
            window = MainWindow()
        self.addCleanup(window.close)
        pipeline = _BlankPipeline()
        window.pipeline = pipeline
        window.pipeline_fingerprint = app_config.config_fingerprint(window.config)
        window.api_config_page._watermark_check.setChecked(True)
        window._save_api_config()
        self.assertTrue(app_config.load_ai_config()["watermark_enabled"])
        self.assertTrue(window.editor_page.config["watermark_enabled"])
        self.assertIs(window.pipeline, pipeline)


if __name__ == "__main__":
    unittest.main()
