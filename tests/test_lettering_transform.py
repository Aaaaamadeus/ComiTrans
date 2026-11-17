import json
import unittest

from PIL import Image

from comic_translate_desktop.lettering_transform import text_transform, transform_layer, outline_width
from comic_translate_desktop.ui.theme import apply_theme
from tests import test_editor_live_preview as fixtures


class LayerTransformTests(unittest.TestCase):
    def test_stretch_and_clockwise_rotation_keep_ink_center_and_transparency(self):
        surface = Image.new('RGBA', (4, 8), (20, 40, 60, 255))
        layer = surface, 100, 200
        self.assertIs(transform_layer(layer, (1., 1., 0.)), layer)
        stretched, x, y = transform_layer(layer, (2., .5, 0.))
        self.assertEqual((stretched.size, x, y), ((8, 4), 98, 202))
        surface.putpixel((0, 0), (255, 0, 0, 255))
        rotated, x, y = transform_layer(layer, (1., 1., 90.))
        self.assertEqual((rotated.size, x, y), ((8, 4), 98, 202))
        self.assertEqual(rotated.getpixel((7, 0)), (255, 0, 0, 255))

    def test_invalid_metadata_defaults_and_large_layers_fail_before_allocation(self):
        self.assertEqual(text_transform(dict(text_scale_x='nan', text_scale_y=[], text_rotation='inf')), (1., 1., 0.))
        self.assertEqual(text_transform(dict(text_scale_x=8, text_scale_y=-5, text_rotation=999)), (4., .1, 180.))
        self.assertIsNone(outline_width(dict(outline_width='invalid')))
        self.assertEqual(outline_width(dict(outline_width=0)), 0)
        surface = Image.new('RGBA', (2000, 2000), 'black')
        with self.assertRaises(ValueError):
            transform_layer((surface, 0, 0), (4., 4., 45.))


class LetteringEditorTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.EditorLivePreviewTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.EditorLivePreviewTests.tearDownClass.__func__)
    setUp = fixtures.EditorLivePreviewTests.setUp
    page = fixtures.EditorLivePreviewTests.page
    editor = fixtures.EditorLivePreviewTests.editor

    @staticmethod
    def destroy_editor(editor):
        editor._dirty = False
        fixtures.EditorLivePreviewTests.destroy_editor(editor)

    def test_transform_preview_save_reload_and_reset_in_both_themes_and_directions(self):
        self.addCleanup(apply_theme, self.app, 'light')
        for theme in ('light', 'dark'):
            apply_theme(self.app, theme)
            for direction in (0, 1):
                with self.subTest(theme=theme, direction=direction):
                    output, layout = self.page(f'{theme}-{direction}', two_blocks=True)
                    editor = self.editor(output)
                    editor._direction_combo.setCurrentIndex(editor._direction_combo.findData(direction))
                    self.assertTrue(editor.apply_changes())
                    baseline = editor._rendered.copy()
                    cleaned = editor._cleaned_image.tobytes()
                    neighbour = editor._layer_cache[1]
                    editor._text_scale_x.setValue(160)
                    editor._text_scale_y.setValue(70)
                    editor._text_rotation.setValue(24.5)
                    self.assertTrue(editor.apply_changes())
                    self.assertNotEqual(editor._rendered.tobytes(), baseline.tobytes())
                    self.assertEqual(editor._cleaned_image.tobytes(), cleaned)
                    self.assertIs(editor._layer_cache[1], neighbour)
                    self.assertTrue(editor.save_image())
                    item = json.loads(layout.read_text(encoding='utf-8'))[0]
                    self.assertEqual((item['text_scale_x'], item['text_scale_y'], item['text_rotation']), (1.6, .7, 24.5))
                    with Image.open(output) as saved:
                        self.assertEqual(saved.tobytes(), editor._rendered.tobytes())
                    reopened = self.editor(output)
                    self.assertTrue(reopened.apply_changes())
                    self.assertEqual(reopened._rendered.tobytes(), editor._rendered.tobytes())
                    self.assertEqual(reopened._text_rotation.value(), 24.5)
                    reopened._reset_transform_btn.click()
                    self.assertTrue(reopened.apply_changes())
                    self.assertEqual(reopened._rendered.tobytes(), baseline.tobytes())

    def test_outline_width_and_sample_preset_are_per_bubble_and_persist(self):
        output, _ = self.page('outline', two_blocks=True)
        editor = self.editor(output)
        editor._text_input.setPlainText('ごちそうさま！')
        editor._hollow_preset_btn.click()
        self.assertTrue(editor.apply_changes())
        self.assertEqual(editor.items[0]['direction'], 1)
        self.assertEqual(editor.items[0]['text_effect'], 'hollow')
        colors = editor._layer_cache[0][1].getdata()
        self.assertIn((255, 255, 255, 255), colors)
        self.assertIn((0, 0, 0, 255), colors)
        for effect in ('outlined', 'hollow'):
            editor._effect_combo.setCurrentIndex(editor._effect_combo.findData(effect))
            editor._outline_width.setValue(.5)
            self.assertTrue(editor.apply_changes())
            thin = editor._rendered.tobytes()
            editor._outline_width.setValue(5)
            self.assertTrue(editor.apply_changes())
            self.assertNotEqual(editor._rendered.tobytes(), thin)
            self.assertNotIn('outline_width', editor.items[1])
            self.assertTrue(editor.save_image())
            reopened = self.editor(output)
            self.assertEqual(reopened._outline_width.value(), 5)
            self.assertTrue(reopened.apply_changes())
            self.assertEqual(reopened._rendered.tobytes(), editor._rendered.tobytes())
        editor._outline_width.setValue(0)
        self.assertTrue(editor.apply_changes())
        self.assertNotIn((0, 0, 0, 255), editor._layer_cache[0][1].getdata())

    def test_outline_override_is_ignored_for_automatic_processing(self):
        output, _ = self.page('automatic')
        setter = self.editor(output).typesetter
        def render(**options):
            image = Image.new('RGB', (300, 400), '#aaaaaa')
            setter.draw_text(image, [30, 30, 270, 370], '日本語', 'dialogue',
                             direction=1, text_effect='outlined', **options)
            return image.tobytes()
        self.assertEqual(render(), render(outline_width=20))
        self.assertEqual(render(manual_layout=True), render(manual_layout=True, outline_width=None))
