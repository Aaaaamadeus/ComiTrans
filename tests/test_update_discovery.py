import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtNetwork import QHostAddress, QLocalServer, QNetworkProxy, QTcpServer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QPushButton

from comic_translate_desktop.ui import update_notice
from tests.qt_utils import destroy_widget


class UpdateDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = QMainWindow()
        self.addCleanup(destroy_widget, self.window)
        self.window.update_button = QPushButton(self.window)
        self.window.update_button.hide()
        self.window.diagnostics = Mock()
        self.window.show()
        with patch.object(update_notice, 'installed_product', return_value=None):
            self.notice = update_notice.UpdateNotice(self.window)
        self.notice.network.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
        self.endpoint = QTcpServer(self.window)
        self.assertTrue(self.endpoint.listen(QHostAddress.LocalHost, 0))
        self.requests = 0
        self.endpoint.newConnection.connect(self.serve_http)
        for key, value in (('RELEASE_API', f'http://127.0.0.1:{self.endpoint.serverPort()}/releases/latest'),
                           ('SERVICE_PIPE', 'ComiTrans-Test-' + uuid4().hex)):
            setting = patch.object(update_notice, key, value)
            setting.start()
            self.addCleanup(setting.stop)
        major, minor, patch_number = map(int, update_notice.__version__.split('.'))
        self.new_version = f'{major}.{minor}.{patch_number + 1}'
        self.body = json.dumps({'tag_name': f'v{self.new_version}'}).encode()
        self.status = b'200 OK'

    def serve_http(self):
        socket = self.endpoint.nextPendingConnection()

        def reply():
            if not socket.canReadLine():
                return
            self.requests += 1
            socket.readAll()
            socket.write(b'HTTP/1.1 ' + self.status + b'\r\nConnection: close\r\nContent-Length: ' +
                         str(len(self.body)).encode() + b'\r\n\r\n' + self.body)
            socket.disconnectFromHost()
        socket.readyRead.connect(reply)
        reply()

    def provide_service(self, body):
        self.notice.product = SimpleNamespace(setup=True)
        server = QLocalServer(self.window)
        self.assertTrue(server.listen(update_notice.SERVICE_PIPE), server.errorString())

        def connected():
            client = server.nextPendingConnection()
            client.write(body)
            client.disconnectFromServer()
        server.newConnection.connect(connected)
        return server

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_new_release_shows_button_and_opens_one_offer_on_click(self):
        self.notice.start()
        button = self.window.update_button
        self.wait_for(button.isVisible)
        self.assertIn(self.new_version, button.toolTip())
        self.assertFalse(self.window.findChildren(QDialog))
        button.click()
        dialogs = [dialog for dialog in self.window.findChildren(QDialog) if dialog.isVisible()]
        self.assertEqual(len(dialogs), 1)
        self.assertFalse(button.isEnabled())
        dialogs[0].reject()
        self.assertTrue(button.isVisible() and button.isEnabled())

    def test_service_current_release_is_silent_and_skips_http(self):
        self.provide_service(json.dumps({'tag_name': f'v{update_notice.__version__}'}).encode())
        with patch.object(self.notice, '_offer', wraps=self.notice._offer) as offered:
            self.notice.start()
            self.wait_for(lambda: offered.called)
        self.assertFalse(self.window.update_button.isVisible())
        self.assertEqual(self.requests, 0)
        self.window.diagnostics.append.assert_not_called()

    def test_invalid_service_response_falls_back_once(self):
        self.provide_service(b'{}')
        self.notice.start()
        self.wait_for(self.window.update_button.isVisible)
        self.assertEqual(self.requests, 1)

    def test_older_and_unpublished_releases_clear_the_indicator(self):
        major, minor, patch_number = map(int, update_notice.__version__.split('.'))
        if patch_number:
            older = f'v{major}.{minor}.{patch_number - 1}'
        elif minor:
            older = f'v{major}.{minor - 1}.0'
        else:
            older = f'v{major - 1}.0.0'
        new_tag = f'v{self.new_version}'
        for release in ({'tag_name': older}, {'tag_name': new_tag, 'draft': True},
                        {'tag_name': new_tag, 'prerelease': True}, {'tag_name': new_tag + '-rc.1'}):
            with self.subTest(release=release):
                self.notice._offer({'tag_name': new_tag})
                self.assertTrue(self.window.update_button.isVisible())
                self.notice._offer(release)
                self.assertFalse(self.window.update_button.isVisible())

    def test_missing_service_falls_back_to_http(self):
        self.notice.product = SimpleNamespace(setup=False)
        self.notice.start()
        self.wait_for(self.window.update_button.isVisible)
        self.assertEqual(self.requests, 1)

    def test_silent_service_times_out_and_uses_http(self):
        self.notice.product = SimpleNamespace(setup=True)
        server = QLocalServer(self.window)
        self.assertTrue(server.listen(update_notice.SERVICE_PIPE))
        self.notice.timer.setInterval(50)
        self.notice.start()
        self.wait_for(self.window.update_button.isVisible)
        self.assertEqual(self.requests, 1)

    def test_http_failure_is_logged_without_an_offer(self):
        self.status = b'503 Service Unavailable'
        self.notice.start()
        self.wait_for(lambda: self.window.diagnostics.append.called)
        self.assertFalse(self.window.update_button.isVisible())
        self.assertEqual(self.window.diagnostics.append.call_args.args[-1], 'WARNING')

    def test_invalid_json_is_logged_without_an_offer(self):
        self.body = b'not json'
        self.notice.start()
        self.wait_for(lambda: self.window.diagnostics.append.called)
        self.assertFalse(self.window.update_button.isVisible())
