import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from comic_translate_core.gpu_runtime import runtime_directories, CUDA_DOWNLOAD_URL, CUDNN_DOWNLOAD_URL, MSVC_DOWNLOAD_URL
from comic_translate_desktop import config
from comic_translate_desktop.ui.gpu_setup_dialog import GpuSetupDialog
from tests.qt_utils import destroy_widget


class GpuSetupTests(unittest.TestCase):
    def test_new_install_prefers_gpu_but_preserves_explicit_cpu_choice(self):
        with patch.object(config, 'load_yaml', return_value={}):
            self.assertTrue(config.load_ai_config()['use_gpu'])
        with patch.object(config, 'load_yaml', return_value={'use_gpu': False}):
            self.assertFalse(config.load_ai_config()['use_gpu'])

    def test_external_install_and_path_directories_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as root:
            cuda, cudnn = Path(root) / 'cuda/bin', Path(root) / 'cudnn/bin/12.8'
            for path, name in ((cuda, 'cudart64_12.dll'), (cudnn, 'cudnn64_9.dll')):
                path.mkdir(parents=True)
                (path / name).touch()
            env = {'CUDA_PATH': str(cuda.parent), 'CUDNN_PATH': str(cudnn.parent.parent),
                   'PATH': os.pathsep.join((str(cuda), '', '.', str(cudnn), str(Path(root) / 'missing'))),
                   'ProgramFiles': root}
            self.assertEqual(runtime_directories(env), [cuda.resolve(), cudnn.resolve()])

    def test_standard_install_paths_without_path_environment(self):
        with tempfile.TemporaryDirectory() as root:
            cuda = Path(root) / 'NVIDIA GPU Computing Toolkit/CUDA/v12.8/bin'
            cudnn = Path(root) / 'NVIDIA/CUDNN/v9.10/bin'
            for path, name in ((cuda, 'cudart64_12.dll'), (cudnn, 'cudnn64_9.dll')):
                path.mkdir(parents=True)
                (path / name).touch()
            self.assertEqual(runtime_directories({'ProgramFiles': root}), [cuda.resolve(), cudnn.resolve()])

    def test_portable_app_finds_versioned_and_user_installs_without_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cuda = root / "NVIDIA GPU Computing Toolkit/CUDA/v12.6/bin"
            cudnn = root / "NVIDIA/CUDNN/v9.14/bin/12.6"
            user_lib = root / "Local/ComiTrans/gpu-runtime/bin"
            for directory, dll in ((cuda, "cudart64_12.dll"), (cudnn, "cudnn64_9.dll"), (user_lib, "cudnn64_9.dll")):
                directory.mkdir(parents=True)
                (directory / dll).touch()
            self.assertEqual(runtime_directories({"ProgramFiles": str(root), "LOCALAPPDATA": str(root / "Local")}),
                             [cuda, cudnn, user_lib])

    def test_download_buttons_open_only_the_corresponding_official_link_when_clicked(self):
        app = QApplication.instance() or QApplication([])
        with patch('comic_translate_desktop.ui.gpu_setup_dialog.QDesktopServices.openUrl') as open_url:
            dialog = GpuSetupDialog()
            try:
                open_url.assert_not_called()
                for button, url in zip(dialog.download_buttons, (CUDA_DOWNLOAD_URL, CUDNN_DOWNLOAD_URL, MSVC_DOWNLOAD_URL)):
                    button.click()
                    self.assertEqual(open_url.call_args.args[0].toString(), url)
                self.assertEqual(open_url.call_count, 3)
            finally:
                destroy_widget(dialog)
