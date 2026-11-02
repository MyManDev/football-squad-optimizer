"""Adapter-neutral advice queue operations, attempt ownership errors and job progress."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Final, Protocol

from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.jobs_contract import _JOB_ID_PATTERN, AdviceJob
from squadopt.platform.storage._queue_lock import QueueLockTimeout as QueueLockTimeout

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


def claim_order(job: AdviceJob) -> tuple[str, str]:
    """Where a queued job stands in line: by arrival, then by id.

    A queue claims its queued jobs in this order, and the job view counts a job's place in
    the queue by it, so the two cannot drift. A job walked back by recovery keeps its
    arrival and so goes back to its old place, ahead of the jobs that came after it.
    """

    return (job.created_at_utc, job.job_id)


JOB_PROGRESS_CONTRACT_VERSION: Final = "advice_job_progress_v1"


@dataclass(frozen=True, slots=True)
class JobProgress:
    """How far one attempt of a running job has got: documents solved out of those it must.

    ``total`` is fixed when the attempt starts and is at least one, the asked document;
    ``done`` only goes up and never passes it. The attempt is part of the record, so a
    count left by an earlier attempt is never read as the current one's.
    """

    job_id: str
    attempt: int
    done: int
    total: int
    contract_version: str = JOB_PROGRESS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != JOB_PROGRESS_CONTRACT_VERSION:
            raise AdviceQueueError("Unsupported job progress contract_version.")
        if not isinstance(self.job_id, str) or not _JOB_ID_PATTERN.fullmatch(self.job_id):
            raise AdviceQueueError(f"job_id has an invalid format: {self.job_id!r}.")
        for label, value, least in (
            ("attempt", self.attempt, 1),
            ("done", self.done, 0),
            ("total", self.total, 1),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < least:
                raise AdviceQueueError(f"{label} must be an integer of at least {least}.")
        if self.done > self.total:
            raise AdviceQueueError("done may not pass total.")

    def as_payload(self) -> dict[str, object]:
        return {
            "attempt": self.attempt,
            "contract_version": self.contract_version,
            "done": self.done,
            "job_id": self.job_id,
            "total": self.total,
        }

    @classmethod
    def from_payload(cls, payload: object) -> "JobProgress":
        if not isinstance(payload, dict) or set(payload) != {
            "attempt",
            "contract_version",
            "done",
            "job_id",
            "total",
        }:
            raise AdviceQueueError("A job progress record has unexpected fields.")
        return cls(
            job_id=payload["job_id"],
            attempt=payload["attempt"],
            done=payload["done"],
            total=payload["total"],
            contract_version=payload["contract_version"],
        )

    def as_view(self) -> dict[str, int]:
        """What the job view serves: the two counts, nothing about the attempt."""

        return {"done": self.done, "total": self.total}


class ProgressRecorder(Protocol):
    """Records the owning attempt's count; the worker calls it as documents are solved."""

    def __call__(self, job: AdviceJob, *, done: int, total: int) -> None: ...


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
