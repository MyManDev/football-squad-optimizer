"""Adapter-neutral advice queue operations and attempt ownership errors."""

from collections.abc import Callable
from typing import Final, Protocol

from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.jobs_contract import AdviceJob

DEFAULT_LEASE_SECONDS: Final = 300.0


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
        self, job: AdviceJob, *, read_cached: Callable[[str], bytes | None]
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

    def heartbeat(self, job_id: str, *, attempt: int) -> None: ...

    def recover(
        self,
        *,
        at_utc: str | None = None,
        clock: Callable[[], str] | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> tuple[AdviceJob, ...]: ...
