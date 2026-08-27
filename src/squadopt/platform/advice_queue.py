"""The job queue behind a protocol, and the worker loop that drains it.

The split of labour is the architecture's whole point: the **api** process writes a
job record and nothing else — it never imports a solver; the **worker** claims jobs,
calls an injected compute callable, writes the answer to the cache under its
immutable key, and records the terminal state; the **ops** process remains the only
writer of the ledger and the site. Three disjoint write sets, so there is nothing to
lock at the domain level.

The file adapter keeps one JSON document per job and makes claiming atomic with an
exclusive claim-marker file: two workers racing for one job cannot both win, because
``O_EXCL`` creation succeeds once. The marker doubles as the claim's **heartbeat**:
its mtime is refreshed by the owning worker, and ``recover`` walks a ``running``
record back to ``queued`` only when that heartbeat is older than the lease — a live
worker's job is live work, and a horizontal deployment must not let one replica's
startup steal another replica's claim. The retry stays safe because cache writes are
immutable-key.

A compute answer that *differs* from what the cache already holds under the same key
is not retried and not papered over: it is recorded as a failed job naming a
determinism defect, because under a complete key that is the only thing it can be.
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Final, Protocol

from squadopt.platform.advice_cache import AdviceCacheError, AdviceCacheRepository
from squadopt.platform.jobs_contract import (
    _JOB_ID_PATTERN,
    AdviceJob,
    BackendJobsContractError,
    JobError,
)

#: How stale a claim's heartbeat must be before recovery may treat it as abandoned.
DEFAULT_LEASE_SECONDS: Final = 300.0

_SANITIZE_PATTERNS: Final = (
    re.compile(r"[A-Za-z]:[\\/][^\s'\"]*"),  # windows paths
    re.compile(r"/(?:home|tmp|var|usr|etc)/[^\s'\"]*"),  # unix paths
)


def sanitize_error_message(message: str, *, limit: int = 200) -> str:
    """A failure reason fit for a public record: no host paths, one line, bounded.

    The stored job record travels out through the jobs endpoint, so whatever a worker
    exception carries — file locations, mount points, usernames inside paths — must
    not be persisted verbatim.
    """

    first_line = message.splitlines()[0] if message.strip() else "unspecified failure"
    for pattern in _SANITIZE_PATTERNS:
        first_line = pattern.sub("<path>", first_line)
    trimmed = first_line.strip()[:limit]
    return trimmed or "unspecified failure"


class AdviceQueueError(ValueError):
    """A queue operation violates the store's contract."""


class JobQueue(Protocol):
    """What any job store must provide; implementations are adapters."""

    def submit(self, job: AdviceJob) -> None: ...

    def claim(self, *, at_utc: str) -> AdviceJob | None: ...

    def store(self, job: AdviceJob) -> None: ...

    def load(self, job_id: str) -> AdviceJob | None: ...

    def jobs(self) -> tuple[AdviceJob, ...]: ...

    def recover(
        self, *, at_utc: str, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> tuple[AdviceJob, ...]: ...


def _serialize(job: AdviceJob) -> bytes:
    import json

    return (json.dumps(job.as_payload(), sort_keys=True, indent=2) + "\n").encode("utf-8")


class FileJobQueue:
    """One JSON document per job; claims are exclusive-marker files; writes atomic."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, job_id: str) -> Path:
        return self._root / f"{self._valid_id(job_id)}.json"

    def _claim_marker(self, job_id: str) -> Path:
        return self._root / f"{self._valid_id(job_id)}.claim"

    @staticmethod
    def _valid_id(job_id: str) -> str:
        # The GET route hands this store untrusted ids; the jobs contract's own
        # grammar is the gate, so a traversal cannot even compose a path.
        if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
            raise AdviceQueueError(f"job_id has an invalid format: {job_id!r}.")
        return job_id

    def submit(self, job: AdviceJob) -> None:
        """Create the record atomically: at most one submission ever wins an id.

        An existence check followed by a write lets two submitters interleave past
        each other; creation therefore goes through a finished temporary file linked
        onto the final name, which succeeds exactly once."""

        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        import tempfile

        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_serialize(job))
            try:
                os.link(temporary, path)
            except FileExistsError:
                raise AdviceQueueError(
                    f"Job {job.job_id!r} already exists; submit is not upsert."
                ) from None
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)

    def store(self, job: AdviceJob) -> None:
        path = self._path(job.job_id)
        if not path.exists():
            raise AdviceQueueError(f"Job {job.job_id!r} is not in this queue.")
        self._write(path, job)
        if job.is_terminal:
            self._claim_marker(job.job_id).unlink(missing_ok=True)

    def load(self, job_id: str) -> AdviceJob | None:
        try:
            raw = self._path(job_id).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        import json

        return AdviceJob.from_payload(json.loads(raw))

    def jobs(self) -> tuple[AdviceJob, ...]:
        """Every record in the store, oldest first; league-scale, so a scan is fine."""

        if not self._root.exists():
            return ()
        found = [self.load(path.stem) for path in sorted(self._root.glob("*.json"))]
        return tuple(
            sorted(
                (job for job in found if job is not None),
                key=lambda item: (item.created_at_utc, item.job_id),
            )
        )

    def claim(self, *, at_utc: str) -> AdviceJob | None:
        """Move the oldest queued job to running, or return None.

        The exclusive claim marker is what makes two racing workers safe: creating it
        with ``O_EXCL`` succeeds exactly once, and the loser moves on to the next
        queued job rather than double-running this one.
        """

        candidates: list[AdviceJob] = []
        if self._root.exists():
            for path in self._root.glob("*.json"):
                job = self.load(path.stem)
                if job is not None and job.status == "queued":
                    candidates.append(job)
        for job in sorted(candidates, key=lambda item: (item.created_at_utc, item.job_id)):
            marker = self._claim_marker(job.job_id)
            try:
                descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            os.close(descriptor)
            os.utime(marker)  # the heartbeat starts now
            running = job.transition("running", at_utc=at_utc)
            self._write(self._path(job.job_id), running)
            return running
        return None

    def heartbeat(self, job_id: str) -> None:
        """Refresh the claim's lease; the owning worker calls this while computing."""

        with contextlib.suppress(FileNotFoundError):
            os.utime(self._claim_marker(job_id))

    def recover(
        self, *, at_utc: str, lease_seconds: float = DEFAULT_LEASE_SECONDS
    ) -> tuple[AdviceJob, ...]:
        """Walk abandoned running jobs back to queued through the contract's own edge.

        Abandoned means the claim's heartbeat is stale: the marker's mtime is older
        than the lease, or the marker is gone entirely. A live worker within its
        lease keeps its job — one replica's startup must not steal another replica's
        claim (the reviewed two-worker case, pinned in tests). The attempt counter
        does the crash-loop bookkeeping.
        """

        recovered: list[AdviceJob] = []
        if not self._root.exists():
            return ()
        now = time.time()
        for path in sorted(self._root.glob("*.json")):
            job = self.load(path.stem)
            if job is None or job.status != "running":
                continue
            marker = self._claim_marker(job.job_id)
            try:
                age = now - marker.stat().st_mtime
            except FileNotFoundError:
                age = float("inf")
            if age < lease_seconds:
                continue  # live work stays claimed
            requeued = job.transition("queued", at_utc=at_utc)
            self._write(path, requeued)
            marker.unlink(missing_ok=True)
            recovered.append(requeued)
        return tuple(recovered)

    def _write(self, path: Path, job: AdviceJob) -> None:
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_serialize(job))
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
            raise


def run_advice_worker_once(
    queue: JobQueue,
    cache: AdviceCacheRepository,
    compute: Callable[[AdviceJob], bytes],
    *,
    at_utc: str,
) -> AdviceJob | None:
    """Claim one job, compute it, cache the answer, record the terminal state.

    ``compute`` is injected — the worker knows how to run a job, not what advice is,
    and the api process that shares this module's import graph never receives a
    compute callable at all, which is how "the api imports no solver" stays a property
    of the composition rather than a hope. Returns the terminal record, or ``None``
    when the queue is empty.
    """

    job = queue.claim(at_utc=at_utc)
    if job is None:
        return None
    try:
        payload = compute(job)
        if not isinstance(payload, bytes) or not payload:
            raise AdviceQueueError("compute must return non-empty bytes.")
        cache.put(job.cache_key, payload)
    except AdviceCacheError as error:
        # Different bytes under a complete key: a determinism defect, recorded as
        # exactly that — never retried, never papered over.
        failed = job.transition(
            "failed",
            at_utc=at_utc,
            error=JobError(code="DETERMINISM_DEFECT", message=sanitize_error_message(str(error))),
        )
        queue.store(failed)
        return failed
    except BackendJobsContractError:
        raise
    except Exception as error:
        failed = job.transition(
            "failed",
            at_utc=at_utc,
            error=JobError(
                code="ADVICE_FAILED",
                message=sanitize_error_message(str(error) or type(error).__name__),
            ),
        )
        queue.store(failed)
        return failed
    completed = job.transition("completed", at_utc=at_utc, result_ref=job.cache_key)
    queue.store(completed)
    return completed
