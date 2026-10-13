from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from comic_translate_desktop.ai_diagnosis import AiDiagnosis
from comic_translate_desktop.worker import BatchWorker


ROOT = Path(__file__).resolve().parents[1]


class ProjectCleanupTests(unittest.TestCase):
    def test_detector_import_does_not_capture_an_unrelated_utils_package(self):
        script = (
            "import sys, types\n"
            f"sys.path.insert(0, {str(ROOT / 'comic-translate-ai/main')!r})\n"
            "unrelated = types.ModuleType('utils')\n"
            "unrelated.__path__ = []\n"
            "sys.modules['utils'] = unrelated\n"
            "import onnx_text_detector\n"
            "assert sys.modules['utils'] is unrelated\n"
            "assert onnx_text_detector.group_output.__module__ == 'comic_text_detector.utils.textblock'\n"
            "assert 'torch' not in sys.modules\n"
        )
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_model_warmup_does_not_create_output_or_document_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'uncreated-output'
            worker = BatchWorker([], output, {})
            pipeline = SimpleNamespace()
            ready, finished = [], []
            worker.pipeline_ready.connect(ready.append)
            worker.finished.connect(lambda good, bad: finished.append((good, bad)))
            with patch.object(worker, '_build_pipeline', return_value=pipeline), \
                 patch.object(worker, '_make_document_jobs', side_effect=AssertionError('Warmup must not schedule documents')):
                worker.run()
            self.assertEqual(ready, [pipeline])
            self.assertEqual(finished, [(0, 0)])
            self.assertFalse(output.exists())

    def _diagnosis(self):
        return AiDiagnosis(SimpleNamespace(build_prompt=lambda: 'test diagnostics'))

    def test_diagnosis_closes_http_client_after_success(self):
        diagnosis = self._diagnosis()
        config = dict(api_key='test-key', api_base_url='https://example.invalid/v1', translation_model='test')
        with patch('comic_translate_desktop.ai_diagnosis.load_ai_config', return_value=config), \
             patch('openai.OpenAI') as constructor:
            client = constructor.return_value.__enter__.return_value
            client.chat.completions.create.return_value = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=' checked '))])
            self.assertEqual(diagnosis.diagnose('why?'), 'checked')
            constructor.return_value.__exit__.assert_called_once()
            self.assertEqual(len(diagnosis._history), 2)

    def test_failed_diagnosis_closes_client_without_polluting_history(self):
        diagnosis = self._diagnosis()
        config = dict(api_key='test-key', api_base_url='https://example.invalid/v1', translation_model='test')
        with patch('comic_translate_desktop.ai_diagnosis.load_ai_config', return_value=config), \
             patch('openai.OpenAI') as constructor:
            client = constructor.return_value.__enter__.return_value
            client.chat.completions.create.side_effect = RuntimeError('service down')
            with self.assertRaisesRegex(RuntimeError, 'service down'):
                diagnosis.diagnose('why?')
            constructor.return_value.__exit__.assert_called_once()
            self.assertEqual(diagnosis._history, [])


if __name__ == '__main__':
    unittest.main()
