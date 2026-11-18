"""Check once per launch and offer an update after the main window is shown."""

import json
from pathlib import Path
from queue import Empty, SimpleQueue
import sys
from threading import Event, Thread

from PySide6.QtCore import QIODevice, QObject, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtNetwork import QLocalSocket, QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from comic_translate_core.release_update import (
    RELEASE_API, RESPONSE_LIMIT, installer_name, latest_stable, launch_update, prepare_update,
)
from comic_translate_core.windows_install import installed_product, original_package
from .. import __version__, config
from ..i18n import tr


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

    def start(self):
        if self.product:
            self.timer.start()
            self.pipe.connectToServer('ComiTrans.ReleaseCheck', QIODevice.OpenModeFlag.ReadOnly)
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
            if reply.error() == QNetworkReply.NetworkError.NoError:
                self._offer(json.loads(bytes(reply.readAll())))
        except ValueError:
            pass
        finally:
            reply.deleteLater()

    def _offer(self, data):
        update = latest_stable(data, __version__, setup=bool(self.product and self.product.setup))
        if update is None or not self.window.isVisible():
            return
        notice = QMessageBox(QMessageBox.Icon.Information, tr('发现 ComiTrans 新版本'),
                             tr('当前版本 v{current}，GitHub 已发布 v{latest}。',
                                current=__version__, latest=update.version), parent=self.window)
        install = None
        if self.product and update.installer:
            install = notice.addButton(tr('下载并更新'), QMessageBox.ButtonRole.AcceptRole)
            notice.setInformativeText(tr('下载完成后，ComiTrans 将请求关闭并通过 Windows 安装程序更新。'))
        release_page = notice.addButton(tr('查看 GitHub 发布'), QMessageBox.ButtonRole.ActionRole)
        later = notice.addButton(tr('稍后提醒'), QMessageBox.ButtonRole.RejectRole)
        notice.setDefaultButton(later)
        notice.setEscapeButton(later)
        notice.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        notice.setWindowModality(Qt.WindowModality.NonModal)

        def clicked(button):
            if button is release_page:
                QDesktopServices.openUrl(QUrl(update.url))
            elif button is install:
                self._download(update)

        notice.buttonClicked.connect(clicked)
        notice.show()

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

        progress = QProgressDialog(tr('正在下载并验证更新…'), tr('取消'), 0, 0, self.window)
        progress.setWindowTitle(tr('更新 ComiTrans'))
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
        progress.hide()
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
