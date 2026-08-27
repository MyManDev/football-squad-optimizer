"""The job queue behind a protocol, and the worker loop that drains it.

The split of labour is the architecture's whole point: the **api** process writes a
job record and nothing else — it never imports a solver; the **worker** claims jobs,
calls an injected compute callable, writes the answer to the cache under its
immutable key, and records the terminal state; the **ops** process remains the only
writer of the ledger and the site. Three disjoint write sets, so there is nothing to
lock at the domain level.

The file adapter keeps one JSON document per job and makes claiming atomic with an
exclusive claim-marker file: two workers racing for one job cannot both win, because
``O_EXCL`` creation succeeds once. A worker that dies mid-job leaves a ``running``
record behind; ``recover`` walks those back to ``queued`` through the contract's own
disposable-worker edge, attempt counted, and the retry is safe because cache writes
are immutable-key.

A compute answer that *differs* from what the cache already holds under the same key
is not retried and not papered over: it is recorded as a failed job naming a
determinism defect, because under a complete key that is the only thing it can be.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from squadopt.platform.advice_cache import AdviceCacheError, AdviceCacheRepository
from squadopt.platform.jobs_contract import (
    AdviceJob,
    BackendJobsContractError,
    JobError,
)


class AdviceQueueError(ValueError):
    """A queue operation violates the store's contract."""


class JobQueue(Protocol):
    """What any job store must provide; implementations are adapters."""

    def submit(self, job: AdviceJob) -> None: ...

    def claim(self, *, at_utc: str) -> AdviceJob | None: ...

    def store(self, job: AdviceJob) -> None: ...

    def load(self, job_id: str) -> AdviceJob | None: ...

    def recover(self, *, at_utc: str) -> tuple[AdviceJob, ...]: ...


def _serialize(job: AdviceJob) -> bytes:
    import json

    return (json.dumps(job.as_payload(), sort_keys=True, indent=2) + "\n").encode("utf-8")


class FileJobQueue:
    """One JSON document per job; claims are exclusive-marker files; writes atomic."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def _path(self, job_id: str) -> Path:
        return self._root / f"{job_id}.json"

    def _claim_marker(self, job_id: str) -> Path:
        return self._root / f"{job_id}.claim"

    def submit(self, job: AdviceJob) -> None:
        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        path = self._path(job.job_id)
        if path.exists():
            raise AdviceQueueError(f"Job {job.job_id!r} already exists; submit is not upsert.")
        self._write(path, job)

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
            running = job.transition("running", at_utc=at_utc)
            self._write(self._path(job.job_id), running)
            return running
        return None

    def recover(self, *, at_utc: str) -> tuple[AdviceJob, ...]:
        """Walk abandoned running jobs back to queued through the contract's own edge.

        Called at worker start, before claiming: a record still ``running`` with no
        living worker is a crash's leavings. The claim markers are released so the
        requeued jobs are claimable again, and the attempt counter does the crash-loop
        bookkeeping.
        """

        recovered: list[AdviceJob] = []
        if not self._root.exists():
            return ()
        for path in sorted(self._root.glob("*.json")):
            job = self.load(path.stem)
            if job is None or job.status != "running":
                continue
            requeued = job.transition("queued", at_utc=at_utc)
            self._write(path, requeued)
            self._claim_marker(job.job_id).unlink(missing_ok=True)
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
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
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
            error=JobError(code="DETERMINISM_DEFECT", message=str(error)),
        )
        queue.store(failed)
        return failed
    except BackendJobsContractError:
        raise
    except Exception as error:
        failed = job.transition(
            "failed",
            at_utc=at_utc,
            error=JobError(code="ADVICE_FAILED", message=str(error) or type(error).__name__),
        )
        queue.store(failed)
        return failed
    completed = job.transition("completed", at_utc=at_utc, result_ref=job.cache_key)
    queue.store(completed)
    return completed
