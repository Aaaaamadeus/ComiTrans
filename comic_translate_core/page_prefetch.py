"""Bounded page preparation with configurable, ordered translation execution."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import BoundedSemaphore, Event, Thread


class PagePrefetch:
    """Hold at most `capacity` pages, including the page being finished.

    Preparation has one owner (also for PDF/native resources). Translation
    starts as soon as a page is prepared. Consumers finish pages in input order.
    Releasing an item admits the next page, without a batch-wide barrier.
    """
    def __init__(self, pages, prepare, translate, *, capacity, cancelled, close_preparation,
                 translation_workers=None, repair=None):
        self.pages = pages
        self.prepare = prepare
        self.translate = translate
        self.repair = repair
        self.cancelled = cancelled
        self.close_preparation = close_preparation
        self.capacity = max(1, capacity)
        self.translation_workers = max(1, translation_workers or self.capacity)
        self._slots = BoundedSemaphore(self.capacity)
        self._queue = Queue()
        self._closing = Event()
        self._end = object()

    def _stopped(self):
        return self._closing.is_set() or self.cancelled()

    def __enter__(self):
        self._pool = ThreadPoolExecutor(max_workers=self.translation_workers, thread_name_prefix='page-api')
        self._repair_pool = (ThreadPoolExecutor(max_workers=1, thread_name_prefix='page-repair')
                             if self.repair is not None else None)
        self._producer = Thread(target=self._produce, name='page-prepare')
        self._iterator = self._consume()
        self._producer.start()
        return self._iterator

    def _produce(self):
        try:
            for page in self.pages:
                while not self._stopped():
                    if self._slots.acquire(timeout=.1):
                        break
                else:
                    break
                if self._stopped():
                    self._slots.release()
                    break
                try:
                    prepared = self.prepare(page)
                    if prepared is None:
                        self._slots.release()
                        continue
                    if self._stopped():
                        prepared = None
                        self._slots.release()
                        break
                    if self._repair_pool is not None and not prepared.get('context_replay'):
                        prepared['repair_future'] = self._repair_pool.submit(self.repair, page, prepared)
                    future = self._pool.submit(self.translate, page, prepared)
                    self._queue.put((page, prepared, future))
                    # Neither producer locals nor completed Future objects may
                    # retain the preceding image when its slot is reused.
                    prepared = future = None
                except BaseException:
                    self._slots.release()
                    raise
        except BaseException as exc:
            self._queue.put(exc)
        finally:
            try:
                self.close_preparation()
            except BaseException as exc:
                self._queue.put(exc)
            self._queue.put(self._end)

    def _consume(self):
        while True:
            item = self._queue.get()
            if item is self._end:
                break
            if isinstance(item, BaseException):
                raise item
            try:
                yield item
            finally:
                item = None
                self._slots.release()

    def __exit__(self, *_args):
        self._closing.set()
        self._iterator.close()
        self._producer.join()
        # Responses already in flight are validated/cached by the callback,
        # including when the user cancels while an HTTP request is running.
        self._pool.shutdown(wait=True, cancel_futures=True)
        if self._repair_pool is not None:
            self._repair_pool.shutdown(wait=True, cancel_futures=True)
        while not self._queue.empty():
            self._queue.get_nowait()
