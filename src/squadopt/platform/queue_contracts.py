"""Adapter-neutral advice queue operations and attempt ownership errors."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Final, Protocol

from squadopt.platform._queue_lock import QueueLockTimeout as QueueLockTimeout
from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.jobs_contract import AdviceJob

DEFAULT_LEASE_SECONDS: Final = 300.0
#: How long a finished job (completed or failed) stays among the queue's records before it
#: is archived: seven days after its last update. A member's page stops polling a job after
#: at most 600 s, and an archived job is still found by its id and its idempotency key.
DEFAULT_ARCHIVE_AFTER_SECONDS: Final = 7 * 24 * 3600.0


class AdviceQueueError(ValueError):
    """A queue operation violates the store's contract."""


class AdviceLeaseLostError(AdviceQueueError):
    """This attempt no longer owns the job and may publish no result or heartbeat."""


class AdviceQueueIntegrityError(AdviceQueueError):
    """A retained queue record cannot be trusted; its identity stays reserved."""


class JobQueue(Protocol):
    def submit(self, job: AdviceJob) -> None: ...

    def submit_unique(self, job: AdviceJob) -> tuple[AdviceJob, bool]: ...

    def submit_unless_cached(
        self,
        job: AdviceJob,
        *,
        read_cached: Callable[[str], bytes | None],
        admit: Callable[[], AbstractContextManager[None]] | None = None,
        prepare: Callable[[], None] | None = None,
    ) -> AdviceJob | bytes: ...

    def claim(
        self, *, at_utc: str | None = None, clock: Callable[[], str] | None = None
    ) -> AdviceJob | None: ...

    def store(self, job: AdviceJob) -> None: ...

    def complete(
        self, job: AdviceJob, *, cache: AdviceCacheRepository, payload: bytes, at_utc: str
    ) -> AdviceJob: ...

    def load(self, job_id: str) -> AdviceJob | None: ...

    def jobs(self) -> tuple[AdviceJob, ...]: ...

    def history(self, *, idempotency_key: str | None, cache_key: str) -> tuple[AdviceJob, ...]: ...

    def heartbeat(self, job_id: str, *, attempt: int) -> None: ...

    def recover(
        self,
        *,
        at_utc: str | None = None,
        clock: Callable[[], str] | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> tuple[AdviceJob, ...]: ...

    def archive(
        self, *, now_utc: str, retention_seconds: float = DEFAULT_ARCHIVE_AFTER_SECONDS
    ) -> tuple[AdviceJob, ...]: ...
