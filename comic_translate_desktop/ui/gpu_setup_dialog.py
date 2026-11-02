"""Explicit links to official installers; no automatic downloads or installation."""
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from comic_translate_core.gpu_runtime import CUDA_DOWNLOAD_URL, CUDNN_DOWNLOAD_URL, MSVC_DOWNLOAD_URL
from ..i18n import tr


class GpuSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('GPU 安装说明与下载'))
        self.resize(660, 560)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setSpacing(16)
        paragraphs = (
            '程序包不附带 CUDA/cuDNN。已有兼容环境无需重复安装；CPU 用户可以关闭“使用 GPU”。以下链接打开 NVIDIA 或 Microsoft 官方网站。',
            '1. 确认有支持 CUDA 的 NVIDIA 显卡及兼容驱动。安装 CUDA 12.8 Update 1，选择 Windows / x86_64 与对应系统版本。',
            '2. 安装 cuDNN 9.10.2，选择适用于 CUDA 12 的 Windows x86_64 版本。CUDA Toolkit 不包含 cuDNN，两个都需要。',
            '3. 将 CUDA 和 cuDNN 中实际存放 DLL 的 bin 目录加入系统 PATH。默认安装目录会自动识别；自定义目录也可通过 CUDA_PATH、CUDNN_PATH 指定。',
            '4. 完全退出并重新打开 ComiTrans，勾选“使用 GPU”并保存。模型加载日志应显示 CUDA；显示“实际使用 CPU”说明加速未生效。若提示缺少 MSVCP140/VCRUNTIME140，安装下方 Microsoft 运行库。',
        )
        for paragraph in paragraphs:
            label = QLabel(tr(paragraph))
            label.setWordWrap(True)
            body.addWidget(label)
        self.download_buttons = []
        for title, url in ((tr('打开 CUDA 12.8 官方下载'), CUDA_DOWNLOAD_URL),
                           (tr('打开 cuDNN 9.10.2 官方下载'), CUDNN_DOWNLOAD_URL),
                           (tr('下载 Microsoft VC++ x64 运行库'), MSVC_DOWNLOAD_URL)):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            body.addWidget(button)
            self.download_buttons.append(button)
        body.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        close = QPushButton(tr('关闭'))
        close.clicked.connect(self.accept)
        layout.addWidget(close)
