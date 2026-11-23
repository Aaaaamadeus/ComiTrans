from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import yaml

from comic_translate_desktop import config
from comic_translate_core.detector_paths import SPLIT_PATH, LINE_FILE, LEGACY_PATH


class InstalledModelPathTests(unittest.TestCase):
    def test_relative_paths_preserve_explicit_legacy_detector_selection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / 'install/_internal/comic-translate-ai/models'
            for relative in (LEGACY_PATH, SPLIT_PATH, SPLIT_PATH.with_name(LINE_FILE)):
                target = bundled / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            with (patch.object(config, 'MODELS_ROOT', root / 'profile/models'),
                  patch.object(config, 'BUNDLED_MODELS_ROOT', bundled),
                  patch.object(config, 'CONFIG_PATH', root / 'config.yaml')):
                config.save_ai_config({'detector_model': str(bundled / LEGACY_PATH)})
                raw = yaml.safe_load(config.CONFIG_PATH.read_text('utf-8'))
                self.assertFalse(Path(raw['detector_model']).is_absolute())
                loaded = config.load_ai_config()
                self.assertEqual(loaded['detector_model'], str(bundled / LEGACY_PATH))
                self.assertNotEqual(loaded['detector_model_setting'], 'auto')
                self.assertIsNone(loaded['cuda_detector_model'])

    def test_moved_installation_recovers_saved_default_paths(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / 'removed install' / '_internal/comic-translate-ai/models'
            bundled = root / 'new install' / '_internal/comic-translate-ai/models'
            profile = root / 'profile/comic-translate-ai/models'
            defaults = {
                'charspot_ocr_model': 'charspot-small',
                'lama_model': 'manga-lama/lama-manga-dynamic.onnx',
                'korean_ocr_model': 'ppocr/korean_PP-OCRv5_rec_mobile.onnx',
                'english_ocr_model': 'ppocr/en_PP-OCRv5_rec_mobile.onnx',
            }
            for relative in (SPLIT_PATH, SPLIT_PATH.with_name(LINE_FILE),
                             'charspot-small/model.onnx', 'charspot-small/config.json',
                             'charspot-small/vocab.json', *list(defaults.values())[1:]):
                target = bundled / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch()
            raw = {key: str(old / relative) for key, relative in defaults.items()}
            raw.update(ocr_backend='auto', use_gpu=False, api_key='test-credential',
                       translation_model='test-model')
            preferences = root / 'config.yaml'
            preferences.write_text(yaml.safe_dump(raw), encoding='utf-8')
            with (patch.object(config, 'MODELS_ROOT', profile),
                  patch.object(config, 'BUNDLED_MODELS_ROOT', bundled),
                  patch.object(config, 'CONFIG_PATH', preferences)):
                loaded = config.load_ai_config()
                for key, relative in defaults.items():
                    self.assertEqual(loaded[key], str(bundled / relative))
                self.assertEqual(config.missing_models(loaded), [])
                self.assertEqual(loaded['ocr_backend'], 'auto')
                config.save_ai_config({'font_size': 20})
                saved = yaml.safe_load(preferences.read_text('utf-8'))
                self.assertEqual(saved['api_key'], raw['api_key'])
                self.assertEqual(saved['translation_model'], raw['translation_model'])
                for key, relative in defaults.items():
                    self.assertEqual(saved[key], 'models/' + relative)
                # The same saved profile must also work after a second move.
                relocated = root / 'third install/_internal/comic-translate-ai/models'
                relocated.parent.mkdir(parents=True)
                bundled.rename(relocated)
                with patch.object(config, 'BUNDLED_MODELS_ROOT', relocated):
                    loaded = config.load_ai_config()
                    for key, relative in defaults.items():
                        self.assertEqual(loaded[key], str(relocated / relative))

    def test_existing_models_and_unrelated_missing_custom_paths_are_preserved(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            bundled = root / 'install/_internal/comic-translate-ai/models'
            target = bundled / 'charspot-small'
            target.mkdir(parents=True)
            old = root / 'old/_internal/comic-translate-ai/models/charspot-small'
            old.mkdir(parents=True)
            custom = root / 'custom/charspot-small'
            with (patch.object(config, 'MODELS_ROOT', root / 'profile/models'),
                  patch.object(config, 'BUNDLED_MODELS_ROOT', bundled)):
                self.assertEqual(config._resolve_model_path(old, 'charspot-small'), old)
                self.assertEqual(config._resolve_model_path(custom, 'charspot-small'), custom)
                self.assertEqual(config._model_path_setting(custom, 'charspot-small'), custom)
                custom.mkdir(parents=True)
                self.assertEqual(config._resolve_model_path(custom, 'charspot-small'), custom)
                # Traversal outside the former bundle must not become an installed default.
                escaped = old / '../different'
                self.assertEqual(config._resolve_model_path(escaped, 'charspot-small'), escaped)
                # Optional legacy packages are not part of the current bundle.
                manga = root / 'old/_internal/comic-translate-ai/models/manga-ocr-onnx'
                self.assertEqual(config._resolve_model_path(manga, 'manga-ocr-onnx'), manga)
