"""EXEC-PAR BG-5c WP-D: a tiny executor whose worker threads are DAEMONS.

``ThreadPoolExecutor`` workers are joined at interpreter exit, so one hung local read (a stalled
disk, a wedged mount) would block the node's shutdown forever. These workers die with the
interpreter instead. It satisfies exactly what ``loop.run_in_executor`` needs: ``submit`` returning
a ``concurrent.futures.Future``. Workers start lazily, on the first submit.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Executor, Future
from typing import Any

__all__ = ["DaemonExecutor"]

type _Job = tuple[Future[Any], Callable[..., Any], tuple[Any, ...], dict[str, Any]]


class DaemonExecutor(Executor):
    def __init__(self, max_workers: int, thread_name_prefix: str) -> None:
        self._max = max_workers
        self._prefix = thread_name_prefix
        self._jobs: queue.SimpleQueue[_Job | None] = queue.SimpleQueue()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._shutdown = False

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future[Any]:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            future: Future[Any] = Future()
            self._jobs.put((future, fn, args, kwargs))
            if not self._threads:
                for index in range(self._max):
                    thread = threading.Thread(
                        target=self._work, name=f"{self._prefix}_{index}", daemon=True
                    )
                    thread.start()
                    self._threads.append(thread)
            return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        """Idempotent. Queued jobs are cancelled; a running one finishes on its own."""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            if cancel_futures:
                self._cancel_queued()
            for _ in self._threads:
                self._jobs.put(None)
            threads = list(self._threads)
        if wait:
            for thread in threads:
                thread.join()

    def _cancel_queued(self) -> None:
        while True:
            try:
                job = self._jobs.get_nowait()
            except queue.Empty:
                return
            if job is not None:
                job[0].cancel()

    def _work(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            future, fn, args, kwargs = job
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # noqa: BLE001 - delivered to the future, never raised here
                future.set_exception(exc)
