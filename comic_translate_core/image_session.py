"""Keep desktop image-model sessions outside the Qt interpreter during loading."""
import io
import multiprocessing
import os
from contextlib import redirect_stdout
from multiprocessing.managers import BaseManager
from threading import Lock, Thread
from types import SimpleNamespace

from .onnx_session import create_onnx_session


class _HostedSession:
    """Lives in the helper. Only tensor data and model metadata cross the pipe."""

    def __init__(self, path, device, require_cuda, options_factory):
        with redirect_stdout(io.StringIO()) as startup_log:
            self.session = _open(path, device, require_cuda, options_factory)
        self.startup_log = startup_log.getvalue()

    def describe(self):
        def nodes(values):
            return [SimpleNamespace(name=v.name, type=v.type, shape=v.shape) for v in values]
        return (self.session.get_providers(), nodes(self.session.get_inputs()),
                nodes(self.session.get_outputs()), self.startup_log)

    def run(self, outputs, inputs):
        return self.session.run(outputs, inputs)


class _ModelHost(BaseManager):
    pass


_ModelHost.register('open_session', _HostedSession, exposed=('describe', 'run'))
_host_lock = Lock()
_host = None
_desktop = False


def enable_desktop_model_host():
    global _desktop
    _desktop = True


def _watch_desktop():
    # BaseManager shuts down on a normal exit. Also release VRAM if the
    # desktop process is killed before its shutdown finalizers can run.
    parent = multiprocessing.parent_process()

    def watch():
        parent.join()
        os._exit(0)

    Thread(target=watch, daemon=True).start()


def _open(path, device, require_cuda, options_factory):
    options = options_factory() if options_factory else None
    return create_onnx_session(path, device, require_cuda=require_cuda, sess_options=options)


class _ImageSession:
    def __init__(self, path, device, require_cuda, options_factory):
        self._settings = (str(path), device, require_cuda, options_factory)
        self._reconnect_lock = Lock()
        self._connect()

    def _connect(self):
        remote = _get_host().open_session(*self._settings)
        self._providers, self._inputs, self._outputs, log = remote.describe()
        self._remote = remote
        if log:
            print(log, end='')

    def get_inputs(self):
        return self._inputs

    def get_outputs(self):
        return self._outputs

    def get_providers(self):
        return self._providers

    def run(self, outputs, inputs):
        remote = self._remote
        try:
            return remote.run(outputs, inputs)
        except (EOFError, ConnectionError, FileNotFoundError):
            # Inference has no side effects. Recreate a lost helper session
            # once, even when concurrent pages discover the disconnect.
            with self._reconnect_lock:
                if self._remote is remote:
                    self._connect()
            return self._remote.run(outputs, inputs)


def _get_host():
    global _host
    with _host_lock:
        if _host is None or not _host._process.is_alive():
            host = _ModelHost(ctx=multiprocessing.get_context('spawn'))
            host.start(initializer=_watch_desktop)
            _host = host
        return _host


def create_image_session(path, device='cpu', *, require_cuda=False, options_factory=None):
    if _desktop:
        return _ImageSession(path, device, require_cuda, options_factory)
    return _open(path, device, require_cuda, options_factory)
