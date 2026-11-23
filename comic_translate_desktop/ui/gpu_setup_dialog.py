"""Install the portable CUDA runtime or open the official driver and SDK instructions."""
from PySide6.QtCore import QThread, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from comic_translate_core.gpu_install import install
from comic_translate_core.gpu_runtime import CUDA_DOWNLOAD_URL, CUDNN_DOWNLOAD_URL, MSVC_DOWNLOAD_URL
from ..i18n import tr
from .manga_components import PanelHeading
from .motion import MonochromeShimmerBar
from .theme import set_themed_icon, ui_font
from .window_chrome import apply_window_chrome


class RuntimeInstall(QThread):
    status = Signal(str)

    def run(self):
        try:
            path = install(self.status.emit, canceled=self.isInterruptionRequested)
            self.status.emit(tr('运行库已就绪，请重启 ComiTrans。') + str(path))
        except Exception as exc:
            self.status.emit(str(exc))


class GpuSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('GPU 安装说明与下载'))
        screen = QApplication.primaryScreen().availableGeometry() if QApplication.primaryScreen() else None
        target_w = min(780, int(screen.width() * 0.9)) if screen else 780
        target_h = min(750, int(screen.height() * 0.9)) if screen else 750
        self.resize(target_w, target_h)
        self.setMinimumSize(520, 440)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName('dialogHeader')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 10)
        header_layout.setSpacing(4)
        header_layout.addWidget(PanelHeading('', 'GPU 安装说明与下载'))
        intro = QLabel(tr('程序包不附带 CUDA/cuDNN。已有兼容环境无需重复安装；CPU 用户可以关闭“使用 GPU”。以下链接打开 NVIDIA 或 Microsoft 官方网站。'))
        intro.setProperty('muted', True)
        intro.setWordWrap(True)
        header_layout.addWidget(intro)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setObjectName('dialogScroll')
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName('dialogScrollContent')
        body = QVBoxLayout(content)
        body.setContentsMargins(20, 10, 20, 10)
        body.setSpacing(8)

        self.installer = RuntimeInstall(self)

        runtime_card = QFrame()
        runtime_card.setObjectName('dialogCard')
        runtime_layout = QVBoxLayout(runtime_card)
        runtime_layout.setContentsMargins(16, 10, 16, 10)
        runtime_layout.setSpacing(6)
        runtime_title = QLabel(tr('便携 GPU 运行库'))
        runtime_title.setObjectName('cardTitle')
        runtime_title.setFont(ui_font(14, QFont.Bold))
        runtime_layout.addWidget(runtime_title)
        self.install_status = QLabel(tr('从 NVIDIA 发布的 PyPI 软件包下载至程序目录。需要兼容的 NVIDIA 驱动，下载后重启生效。'))
        self.install_status.setObjectName('statusCallout')
        self.install_status.setWordWrap(True)
        runtime_layout.addWidget(self.install_status)
        self.install_progress = MonochromeShimmerBar()
        self.install_progress.setFixedHeight(6)
        self.install_progress.setTextVisible(False)
        self.install_progress.setRange(0, 0)
        self.install_progress.hide()
        runtime_layout.addWidget(self.install_progress)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 2, 0, 0)
        self.install_button = QPushButton(tr('下载安装便携 GPU 运行库（约 1.53 GB）'))
        self.install_button.setProperty('role', 'primary')
        self.install_button.setCursor(Qt.PointingHandCursor)
        self.install_button.clicked.connect(self.start_install)
        action_row.addWidget(self.install_button)
        action_row.addStretch(1)
        runtime_layout.addLayout(action_row)
        self.installer.status.connect(self.install_status.setText)
        self.installer.finished.connect(self._install_finished)
        body.addWidget(runtime_card)

        steps_card = QFrame()
        steps_card.setObjectName('dialogCard')
        steps_layout = QVBoxLayout(steps_card)
        steps_layout.setContentsMargins(16, 10, 16, 10)
        steps_layout.setSpacing(6)
        steps_title = QLabel(tr('手动安装步骤'))
        steps_title.setObjectName('cardTitle')
        steps_title.setFont(ui_font(14, QFont.Bold))
        steps_layout.addWidget(steps_title)
        paragraphs = (
            '1. 确认有支持 CUDA 的 NVIDIA 显卡及兼容驱动。安装 CUDA 12.8 Update 1，选择 Windows / x86_64 与对应系统版本。',
            '2. 安装 cuDNN 9.10.2，选择适用于 CUDA 12 的 Windows x86_64 版本。CUDA Toolkit 不包含 cuDNN，两个都需要。',
            '3. 将 CUDA 和 cuDNN 中实际存放 DLL 的 bin 目录加入系统 PATH。默认安装目录会自动识别；自定义目录也可通过 CUDA_PATH、CUDNN_PATH 指定。',
            '4. 完全退出并重新打开 ComiTrans，勾选“使用 GPU”并保存。模型加载日志应显示 CUDA；显示“实际使用 CPU”说明加速未生效。若提示缺少 MSVCP140/VCRUNTIME140，安装下方 Microsoft 运行库。',
        )
        for index, paragraph in enumerate(paragraphs, 1):
            row = QHBoxLayout()
            row.setSpacing(12)
            badge = QLabel(f'{index:02d}')
            badge.setObjectName('stepBadge')
            badge.setFont(ui_font(11, QFont.Bold, mono=True))
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(28, 22)
            label = QLabel(tr(paragraph))
            label.setWordWrap(True)
            row.addWidget(badge, 0, Qt.AlignTop)
            row.addWidget(label, 1)
            steps_layout.addLayout(row)
        body.addWidget(steps_card)

        links_card = QFrame()
        links_card.setObjectName('dialogCard')
        links_layout = QVBoxLayout(links_card)
        links_layout.setContentsMargins(16, 10, 16, 10)
        links_layout.setSpacing(6)
        links_title = QLabel(tr('官方下载'))
        links_title.setObjectName('cardTitle')
        links_title.setFont(ui_font(14, QFont.Bold))
        links_layout.addWidget(links_title)
        links_grid = QGridLayout()
        links_grid.setContentsMargins(0, 0, 0, 0)
        links_grid.setSpacing(8)
        self.download_buttons = []
        for idx, (title, url) in enumerate((
            (tr('打开 CUDA 12.8 官方下载'), CUDA_DOWNLOAD_URL),
            (tr('打开 cuDNN 9.10.2 官方下载'), CUDNN_DOWNLOAD_URL),
            (tr('下载 Microsoft VC++ x64 运行库'), MSVC_DOWNLOAD_URL),
        )):
            button = QPushButton(title)
            button.setProperty('role', 'utility')
            button.setCursor(Qt.PointingHandCursor)
            set_themed_icon(button, 'external-link', size=14)
            button.clicked.connect(lambda checked=False, link=url: QDesktopServices.openUrl(QUrl(link)))
            if idx < 2:
                links_grid.addWidget(button, 0, idx)
            else:
                links_grid.addWidget(button, 1, 0, 1, 2)
            self.download_buttons.append(button)
        links_layout.addLayout(links_grid)
        body.addWidget(links_card)
        body.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName('pageActions')
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 10, 24, 10)
        footer_layout.addStretch(1)
        close = QPushButton(tr('关闭'))
        close.setProperty('role', 'utility')
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer_layout.addWidget(close)
        root.addWidget(footer)

    def start_install(self):
        self.install_button.setEnabled(False)
        self.install_progress.show()
        self.installer.start()

    def _install_finished(self):
        self.install_progress.hide()
        self.install_button.setEnabled(True)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)

    def reject(self):
        if self.installer.isRunning():
            self.installer.requestInterruption()
            self.install_status.setText(tr('正在取消下载…'))
            return
        super().reject()

    def closeEvent(self, event):
        if self.installer.isRunning():
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)

    def accept(self):
        if self.installer.isRunning():
            self.reject()
        else:
            super().accept()
