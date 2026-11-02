"""Interleave GPU inference calls without overlapping their workspaces."""
from collections import deque
from contextlib import contextmanager
from threading import Condition, local


class InferenceGate:
    def __init__(self):
        self._condition = Condition()
        self._waiting = deque()
        self._busy = False

    @contextmanager
    def slot(self, check_cancelled=None):
        ticket = object()
        with self._condition:
            self._waiting.append(ticket)
            try:
                while self._busy or self._waiting[0] is not ticket:
                    if check_cancelled:
                        check_cancelled()
                    self._condition.wait(.1)
                if check_cancelled:
                    check_cancelled()
                self._waiting.popleft()
                self._busy = True
            except BaseException:
                self._waiting.remove(ticket)
                self._condition.notify_all()
                raise
        try:
            yield
        finally:
            with self._condition:
                self._busy = False
                self._condition.notify_all()


_gpu_gate = InferenceGate()
_context = local()


@contextmanager
def inference_cancellation(check_cancelled):
    previous = getattr(_context, 'check_cancelled', None)
    _context.check_cancelled = check_cancelled
    try:
        yield
    finally:
        _context.check_cancelled = previous


def run_inference(session, *args, check_cancelled=None, **kwargs):
    check = check_cancelled or getattr(_context, 'check_cancelled', None)
    if check:
        check()
    if 'CUDAExecutionProvider' in session.get_providers():
        with _gpu_gate.slot(check):
            return session.run(*args, **kwargs)
    return session.run(*args, **kwargs)
