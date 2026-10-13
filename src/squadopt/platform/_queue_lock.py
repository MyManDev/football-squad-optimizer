"""One-release alias (ADR 0011, decision 8): the lock lives in
`squadopt.platform.storage._queue_lock`. Removed in the release after the next `site-*` tag.
"""

from __future__ import annotations

from squadopt.platform.storage._queue_lock import (
    QueueFileLock as QueueFileLock,
)
from squadopt.platform.storage._queue_lock import (
    QueueLockTimeout as QueueLockTimeout,
)

__all__ = ["QueueFileLock", "QueueLockTimeout"]
