"""Check once per launch and offer an update after the main window is shown."""

import json
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Event, Thread

from PySide6.QtCore import QIODevice, QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtNetwork import QLocalSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout,
)

from comic_translate_core.release_update import (
    RELEASE_API, RESPONSE_LIMIT, installer_name, latest_stable, launch_update, prepare_update,
)
from comic_translate_core.windows_install import installed_product, original_package
from .. import __version__, config
from ..i18n import tr

from .manga_components import PanelHeading
from .motion import MonochromeShimmerBar
from .theme import set_themed_icon, ui_font
from .window_chrome import apply_window_chrome

SERVICE_PIPE = 'ComiTrans.ReleaseCheck'


class UpdateProgressDialog(QDialog):
    """Themed monochrome indeterminate progress modal for update downloads."""

    canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('更新 ComiTrans'))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(400)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame(self)
        header.setObjectName('dialogHeader')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 12)
        header_layout.addWidget(PanelHeading('', '更新 ComiTrans'))
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 16)
        card = QFrame(self)
        card.setObjectName('dialogCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(10)

        status = QLabel(tr('正在下载并验证更新…'), card)
        status.setWordWrap(True)
        card_layout.addWidget(status)

        self.progress = MonochromeShimmerBar(card)
        self.progress.setAccessibleName(status.text())
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(6)
        card_layout.addWidget(self.progress)
        body.addWidget(card)
        root.addLayout(body, 1)

        actions = QFrame(self)
        actions.setObjectName('pageActions')
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(24, 12, 24, 12)
        actions_layout.addStretch(1)

        cancel_button = QPushButton(tr('取消'), actions)
        cancel_button.setProperty('role', 'utility')
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.clicked.connect(self.reject)
        actions_layout.addWidget(cancel_button)
        root.addWidget(actions)

        self.rejected.connect(self.canceled.emit)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)

    def dismiss(self) -> None:
        self.accept()


class UpdateOfferDialog(QDialog):
    """Non-modal monochrome update prompt matched to the app palette."""

    def __init__(self, current_version: str, update, *, can_install: bool, on_release, on_install, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('发现 ComiTrans 新版本'))
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setMinimumWidth(440)
        self.resize(480, 260)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName('dialogHeader')
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 18, 24, 14)
        header_layout.setSpacing(8)
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(PanelHeading('', '发现 ComiTrans 新版本'), 1)
        version_pill = QLabel(f'v{current_version} → v{update.version}')
        version_pill.setObjectName('badgePill')
        version_pill.setFont(ui_font(12, QFont.Bold, mono=True))
        top_row.addWidget(version_pill, 0, Qt.AlignVCenter)
        header_layout.addLayout(top_row)
        root.addWidget(header)

        body = QVBoxLayout()
        body.setContentsMargins(24, 16, 24, 16)
        body.setSpacing(10)
        card = QFrame()
        card.setObjectName('dialogCard')
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(18, 16, 18, 16)
        card_layout.setSpacing(8)
        summary = QLabel(tr('当前版本 v{current}，GitHub 已发布 v{latest}。',
                            current=current_version, latest=update.version))
        summary.setFont(ui_font(14, QFont.Bold))
        summary.setWordWrap(True)
        card_layout.addWidget(summary)
        if can_install:
            detail = QLabel(tr('下载完成后，ComiTrans 将请求关闭并通过 Windows 安装程序更新。'))
            detail.setProperty('muted', True)
            detail.setWordWrap(True)
            card_layout.addWidget(detail)
        body.addWidget(card)
        root.addLayout(body, 1)

        footer = QFrame()
        footer.setObjectName('pageActions')
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(24, 12, 24, 12)
        actions.setSpacing(8)
        self.later_button = QPushButton(tr('稍后提醒'))
        self.later_button.setProperty('role', 'quiet')
        self.later_button.setCursor(Qt.PointingHandCursor)
        self.later_button.clicked.connect(self.reject)
        actions.addWidget(self.later_button)
        actions.addStretch(1)

        release_action = '查看 GitHub 发布' if can_install else '前往发布页下载安装'
        self.release_button = QPushButton(tr(release_action))
        self.release_button.setProperty('role', 'utility' if can_install else 'primary')
        self.release_button.setCursor(Qt.PointingHandCursor)
        if can_install:
            set_themed_icon(self.release_button, 'external-link', size=13)
        self.release_button.clicked.connect(lambda: (on_release(), self.accept()))
        actions.addWidget(self.release_button)

        self.install_button = None
        if can_install:
            self.install_button = QPushButton(tr('下载并更新'))
            self.install_button.setProperty('role', 'primary')
            self.install_button.setDefault(True)
            self.install_button.setCursor(Qt.PointingHandCursor)
            self.install_button.clicked.connect(lambda: (on_install(), self.accept()))
            actions.addWidget(self.install_button)
            self._initial_focus = self.install_button
        else:
            self.release_button.setDefault(True)
            self._initial_focus = self.release_button
        root.addWidget(footer)

    def showEvent(self, event):
        super().showEvent(event)
        apply_window_chrome(self)
        self._initial_focus.setFocus()


class UpdateNotice(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.product = installed_product(Path(sys.executable).parent)
        self.pipe = QLocalSocket(self)
        self.pipe_data = bytearray()
        self.pipe.readyRead.connect(self._read_service)
        self.pipe.errorOccurred.connect(self._service_error)
        self.pipe.disconnected.connect(self._service_finished)
        self.timer = QTimer(self, singleShot=True, interval=5500)
        self.timer.timeout.connect(self._request_github)
        self.network = QNetworkAccessManager(self)
        self.requested_directly = False
        self.poll = QTimer(self, interval=100)
        self.poll.timeout.connect(self._download_finished)
        self.available_update = None
        self.window.update_button.clicked.connect(self._show_offer)
        self.notice_dialog = None

    def start(self):
        if self.product:
            self.timer.start()
            self.pipe.connectToServer(SERVICE_PIPE, QIODevice.OpenModeFlag.ReadOnly)
        else:
            self._request_github()

    def _read_service(self):
        self.pipe_data.extend(bytes(self.pipe.readAll()))
        if len(self.pipe_data) > RESPONSE_LIMIT:
            self._request_github()

    def _service_finished(self):
        if self.requested_directly:
            return
        self.timer.stop()
        try:
            data = json.loads(self.pipe_data)
        except ValueError:
            self._request_github()
        else:
            if isinstance(data, dict) and isinstance(data.get('tag_name'), str):
                self._offer(data)
            else:
                self._request_github()

    def _service_error(self, error):
        if error != QLocalSocket.LocalSocketError.PeerClosedError:
            self._request_github()

    def _request_github(self):
        if self.requested_directly:
            return
        self.requested_directly = True
        self.timer.stop()
        self.pipe.abort()
        request = QNetworkRequest(QUrl(RELEASE_API))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, f'ComiTrans/{__version__}')
        request.setRawHeader(b'Accept', b'application/vnd.github+json')
        request.setTransferTimeout(5000)
        reply = self.network.get(request)
        reply.setReadBufferSize(RESPONSE_LIMIT + 1)
        reply.readyRead.connect(lambda: reply.abort() if reply.bytesAvailable() > RESPONSE_LIMIT else None)
        reply.finished.connect(lambda: self._github_finished(reply))

    def _github_finished(self, reply):
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._check_failed(reply.errorString())
                return
            data = json.loads(bytes(reply.readAll()))
            if isinstance(data, dict) and isinstance(data.get('tag_name'), str):
                self._offer(data)
            else:
                self._check_failed(tr('发布信息格式无效'))
        except ValueError:
            self._check_failed(tr('发布信息格式无效'))
        finally:
            reply.deleteLater()

    def _check_failed(self, reason):
        self.window.diagnostics.append(tr('检查更新失败：{reason}', reason=reason), 'WARNING')

    def _offer(self, data):
        update = latest_stable(data, __version__, setup=bool(self.product and self.product.setup))
        self.available_update = update
        button = self.window.update_button
        button.setVisible(update is not None)
        if update is not None:
            detail = tr('新版本 v{version} 可用，点击查看详情', version=update.version)
            button.setToolTip(detail)
            button.setAccessibleName(detail)

    def _show_offer(self):
        update = self.available_update
        if update is None or self.poll.isActive():
            return
        can_install = bool(self.product and update.installer)
        notice = UpdateOfferDialog(
            __version__,
            update,
            can_install=can_install,
            on_release=lambda: QDesktopServices.openUrl(QUrl(update.url)),
            on_install=lambda: self._download(update),
            parent=self.window,
        )
        self.notice_dialog = notice
        self.window.update_button.setEnabled(False)
        notice.finished.connect(self._offer_finished)
        notice.show()

    def _offer_finished(self):
        self.window.update_button.setEnabled(not self.poll.isActive())

    def _download(self, update):
        cache = config.PROJECT_ROOT / 'updates'
        base = cache / installer_name(__version__, setup=update.setup)
        if not base.is_file():
            base = original_package(self.product)
        canceled = Event()
        result = SimpleQueue()

        def fetch():
            try:
                result.put(prepare_update(update, __version__, cache, base, canceled.is_set))
            except Exception as exc:
                result.put(exc)

        progress = UpdateProgressDialog(self.window)
        progress.canceled.connect(canceled.set)
        self.window.destroyed.connect(canceled.set)
        self.download = (result, progress, canceled)
        self.poll.start()
        progress.show()
        Thread(target=fetch, daemon=True).start()

    def _download_finished(self):
        result, progress, canceled = self.download
        try:
            outcome = result.get_nowait()
        except Empty:
            return
        self.poll.stop()
        self.window.update_button.setEnabled(True)
        progress.dismiss()
        progress.deleteLater()
        if canceled.is_set() or not self.window.isVisible():
            return
        if isinstance(outcome, Exception):
            self.window.diagnostics.append(str(outcome), 'WARNING')
            QMessageBox.warning(self.window, tr('更新 ComiTrans'), tr('更新下载或验证失败。请在 GitHub 发布页重试。'))
        else:
            def launch():
                try:
                    launch_update(outcome)
                except OSError as exc:
                    self.window.diagnostics.append(str(exc), 'WARNING')

            self.window.close_for_update(launch)
