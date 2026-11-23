import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import numpy as np
from onnxruntime.datasets import get_example

from comic_translate_core import image_session


class ImageSessionTests(unittest.TestCase):
    def test_desktop_worker_survives_a_bad_model_and_matches_local_inference(self):
        path = get_example('mul_1.onnx')
        direct = image_session.create_image_session(path)
        values = np.arange(6, dtype=np.float32).reshape(3, 2)
        expected = direct.run(None, {'X': values})[0]

        with patch.object(image_session, '_host', None), patch.object(image_session, '_desktop', True):
            try:
                with self.assertRaisesRegex(Exception, 'does-not-exist'):
                    image_session.create_image_session(Path(path).with_name('does-not-exist.onnx'))
                remote = image_session.create_image_session(path)
                self.assertNotEqual(image_session._host._process.pid, os.getpid())
                self.assertEqual(remote.get_providers(), direct.get_providers())
                self.assertEqual(remote.get_inputs()[0].shape, [3, 2])
                self.assertEqual(remote.get_outputs()[0].name, 'Y')
                with ThreadPoolExecutor(2) as workers:
                    calls = [workers.submit(remote.run, ['Y'], {'X': values}) for _ in range(2)]
                    for call in calls:
                        np.testing.assert_array_equal(call.result(timeout=10)[0], expected)
                process = image_session._host._process
                process.terminate()
                process.join(5)
                np.testing.assert_array_equal(remote.run(None, {'X': values})[0], expected)
            finally:
                if image_session._host is not None:
                    image_session._host.shutdown()
