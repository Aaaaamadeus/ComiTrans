import json
from pathlib import Path
import sys
import tempfile
import unittest
import hashlib
import zipfile
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'comic-translate-ai/main'))
from onnx_baberu_ocr import OnnxBaberuOcr, Vocab, generation_profile
from scripts.download_baberu_v12 import install
from package_release import validate_model_budget, verify_reused_models
from comic_translate_core.ocr import create_ocr


class ModelUpgradeTests(unittest.TestCase):
    def test_model_access_denied_is_reported_during_startup(self):
        from comic_translate_desktop.config import load_ai_config, missing_models

        config = load_ai_config()
        denied = PermissionError(13, "Access denied", config["detector_model"])
        with patch.object(Path, "exists", side_effect=denied):
            self.assertIn(f"模型读取权限不足：{config['detector_model']}", missing_models(config))

    def test_detector_migration_and_explicit_rollback(self):
        from comic_translate_core.detector_paths import LEGACY_PATH, SPLIT_PATH, LINE_FILE
        from comic_translate_desktop import config

        with tempfile.TemporaryDirectory() as directory, patch.object(config, "MODELS_ROOT", Path(directory)):
            old = Path(directory) / LEGACY_PATH
            new = Path(directory) / SPLIT_PATH
            old.parent.mkdir()
            old.touch()
            saved_default = str(Path("models") / LEGACY_PATH)
            self.assertEqual(config._detector_path(saved_default), old)
            new.parent.mkdir()
            new.touch()
            self.assertEqual(config._detector_path("auto"), old)
            new.with_name(LINE_FILE).touch()
            self.assertEqual(config._detector_path(saved_default), new)
            self.assertEqual(config._detector_path("auto"), new)
            self.assertEqual(config._detector_path(str(old)), old)
            with patch.object(config, "CONFIG_PATH", Path(directory) / "config.yaml"):
                self.assertEqual(config.load_ai_config()["cuda_detector_model"], str(old))
                self.assertIsNone(config.save_ai_config({"use_gpu": False})["cuda_detector_model"])
                explicit = config.save_ai_config({"use_gpu": True, "detector_model": str(new)})
                self.assertIsNone(explicit["cuda_detector_model"])

    def test_auto_detector_uses_legacy_only_when_cuda_is_active(self):
        from onnx_text_detector import create_text_detector
        from comic_translate_core.detector_paths import REGION_FILE

        with (patch('onnx_text_detector.create_onnx_session') as session,
              patch('onnx_split_detector.SplitTextDetector') as split):
            self.assertIs(create_text_detector(REGION_FILE, "cpu", cuda_model_path="fast.onnx"),
                          split.return_value)
            session.assert_not_called()
            session.return_value.get_providers.return_value = ["CUDAExecutionProvider"]
            fast = create_text_detector(REGION_FILE, "cuda", cuda_model_path="fast.onnx")
            self.assertIs(fast.session, session.return_value)
            session.assert_called_once_with("fast.onnx", "cuda", require_cuda=True)
            session.side_effect = RuntimeError("CUDA unavailable")
            self.assertIs(create_text_detector(REGION_FILE, "cuda", cuda_model_path="fast.onnx"),
                          split.return_value)

    def test_cuda_only_session_rejects_silent_cpu_fallback(self):
        from comic_translate_core.onnx_session import create_onnx_session

        with (patch('onnxruntime.get_available_providers', return_value=['CUDAExecutionProvider']),
              patch('comic_translate_core.onnx_session._preload_cuda'),
              patch('onnxruntime.InferenceSession') as session):
            session.return_value.get_providers.return_value = ['CPUExecutionProvider']
            with self.assertRaisesRegex(RuntimeError, 'did not activate CUDA'):
                create_onnx_session("fast.onnx", "cuda", require_cuda=True)
            session.assert_called_once()

    def test_overlapping_regions_own_lines_once_and_ignore_orphans(self):
        from onnx_split_detector import assign_lines, midpoint_box

        boxes = [([0, 0, 100, 100], 1), ([10, 10, 60, 60], 1)]
        line = np.array([[20, 20], [40, 20], [40, 30], [20, 30]])
        groups = assign_lines(boxes, [line, line + 120])
        self.assertEqual(list(map(len, groups)), [0, 1])
        self.assertEqual(midpoint_box(boxes[0][0], groups[0], 150, 150), boxes[0][0])
        self.assertEqual(midpoint_box(boxes[1][0], groups[1], 150, 150), [15, 15, 50, 45])

    def test_single_model_auto_and_legacy_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {"source_language": "ja", "ocr_backend": "auto", "charspot_ocr_model": root / "charspot",
                      "baberu_ocr_model": root / "baberu", "ocr_model": root / "manga"}
            with (patch('comic_translate_core.onnx_charspot.OnnxCharSpot') as charspot,
                  patch('onnx_baberu_ocr.OnnxBaberuOcr') as baberu,
                  patch('onnx_manga_ocr.OnnxMangaOcr') as manga):
                config['charspot_ocr_model'].mkdir()
                self.assertEqual(create_ocr(config).name, "charspot")
                baberu.assert_not_called()
                manga.assert_not_called()
                config['charspot_ocr_model'].rmdir()
                self.assertEqual(create_ocr(config).name, "baberu")
                baberu.side_effect = FileNotFoundError
                self.assertEqual(create_ocr(config).name, "manga-ocr")
                config['charspot_ocr_model'].mkdir()
                self.assertEqual(create_ocr(dict(config, ocr_backend="manga")).name, "manga-ocr")
                charspot.assert_called_once()

    def test_legacy_generation_and_explicit_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(generation_profile(root), {'max_new_tokens': 128, 'max_symbol_run': 0})
            profile = json.loads((ROOT / 'docs/models/baberu-v1.2.json').read_text())['profile']
            (root / 'comitrans-model.json').write_text(json.dumps(profile))
            self.assertEqual(generation_profile(root)['max_new_tokens'], 256)
            (root / 'comitrans-model.json').write_text('{"revision":"unknown"}')
            with self.assertRaises(ValueError):
                generation_profile(root)

    def test_symbol_cap_stops_loop_but_legacy_is_unchanged(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'vocab.json'
            path.write_text(json.dumps(['ー', 'あ']), encoding='utf-8')
            model = OnnxBaberuOcr.__new__(OnnxBaberuOcr)
            model.vocab = Vocab(path)
            model.vision, model.decoder_prefill, model.decoder_step = object(), object(), object()
            model.max_new_tokens = 24
            def inference(session, names, feeds):
                if session is model.vision:
                    return [np.zeros((1, 257, 8), np.float32)]
                logits = np.zeros((1, 1, 6), np.float32)
                logits[0, 0, 4], logits[0, 0, 2] = 10, 5
                return [logits] + [np.zeros((1, 1, 1, 1), np.float32)] * 12
            with patch('onnx_baberu_ocr.run_inference', side_effect=inference):
                model.max_symbol_run = 16
                self.assertEqual(model(Image.new('RGB', (20, 20))), 'ー' * 16)
                model.max_symbol_run = 0
                self.assertEqual(model(Image.new('RGB', (20, 20))), 'ー' * 24)

    def test_install_mismatch_never_overwrites_existing_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / 'baberu-ocr-v1.2'
            target.mkdir()
            sentinel = target / 'user.txt'
            sentinel.write_text('keep me')
            with self.assertRaises(ValueError):
                install(root)
            self.assertEqual(sentinel.read_text(), 'keep me')

    def test_failed_offline_install_does_not_leave_complete_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(FileNotFoundError):
                install(root / 'models', root / 'missing-source')
            self.assertEqual(list((root / 'models').iterdir()), [])

    def test_budget_counts_uncompressed_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'highly-compressible.data'
            path.write_bytes(b'0' * 1001)
            with patch('package_release.MODEL_LIMIT_BYTES', 1000):
                with self.assertRaises(ValueError):
                    validate_model_budget([(path, 'weights.data')])

    def test_app_only_rejects_extra_legacy_weights_and_same_size_substitution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive, inventory = root / "models.zip", root / "inventory.json"
            inventory.write_text(json.dumps({"files": [{"path": "new.onnx", "bytes": 3,
                "sha256": hashlib.sha256(b"new").hexdigest()}]}))
            for data, extra in [(b"new", True), (b"bad", False)]:
                with zipfile.ZipFile(archive, "w") as bundle:
                    bundle.writestr("new.onnx", data)
                    if extra:
                        bundle.writestr("manga-ocr-onnx/encoder_model.onnx", b"old")
                with self.assertRaises(ValueError):
                    verify_reused_models(archive, inventory)


if __name__ == '__main__':
    unittest.main()
