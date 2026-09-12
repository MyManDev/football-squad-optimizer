"""Short queue metadata transactions; OS releases the lock when a process dies.

The lock file is permanent. Unlinking it would allow two independent lock identities.
Only metadata and immutable cache publication run under this lock, never a computation.
Deployment acceptance must exercise locking across processes on the actual shared mount.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path


class QueueLockTimeout(TimeoutError):
    """Another queue transaction did not release its lock within the bounded wait."""


class QueueFileLock:
    def __init__(self, path: Path, *, timeout_seconds: float = 5.0) -> None:
        self._path = path
        self._timeout = timeout_seconds
        self._thread_lock = threading.RLock()
        self._depth = 0

    @contextlib.contextmanager
    def hold(self) -> Iterator[None]:
        if not self._thread_lock.acquire(timeout=self._timeout):
            raise QueueLockTimeout("Queue metadata transaction is busy.")
        try:
            if self._depth:
                self._depth += 1
                try:
                    yield
                finally:
                    self._depth -= 1
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                deadline = time.monotonic() + self._timeout
                while True:
                    try:
                        _acquire(descriptor)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise QueueLockTimeout("Queue metadata transaction is busy.") from None
                        time.sleep(0.01)
                self._depth = 1
                try:
                    yield
                finally:
                    self._depth = 0
                    _release(descriptor)
            finally:
                os.close(descriptor)
        finally:
            self._thread_lock.release()


def _acquire(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            import errno

            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise BlockingIOError from error
            raise
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release(descriptor: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
