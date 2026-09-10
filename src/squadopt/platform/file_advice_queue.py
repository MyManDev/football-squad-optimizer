"""Recoverable file queue with fenced, short metadata transactions.

An open-key reservation contains the complete queued intent. Publication order is intent,
job, claim, running state, immutable cache, terminal state, cleanup. Every prefix can be
reconciled under the same process-shared lock. Computation runs outside that lock.
Existing job documents keep backend_jobs_v1; legacy id-only indexes remain readable.
Drain old workers before upgrade: processes unaware of fencing must not share this store.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.advice_observability import AdviceLog
from squadopt.platform.jobs_contract import _JOB_ID_PATTERN, AdviceJob, BackendJobsContractError
from squadopt.platform.queue_contracts import (
    DEFAULT_LEASE_SECONDS,
    AdviceLeaseLostError,
    AdviceQueueError,
    AdviceQueueIntegrityError,
)


def _serialize(job: AdviceJob) -> bytes:
    return (json.dumps(job.as_payload(), sort_keys=True, indent=2) + "\n").encode("utf-8")


def _transition_clock(at_utc: str | None, clock: Callable[[], str] | None) -> Callable[[], str]:
    if clock is not None:
        if at_utc is not None:
            raise AdviceQueueError("Supply either at_utc or clock, not both.")
        return clock
    if at_utc is None:
        raise AdviceQueueError("A transition requires at_utc or clock.")
    return lambda: at_utc


class FileJobQueue:
    """One immutable identity per job, durable intent per open key, fenced attempts."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._lock = QueueFileLock(self._root / ".queue.lock")

    @staticmethod
    def _valid_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
            raise AdviceQueueError(f"job_id has an invalid format: {job_id!r}.")
        return job_id

    def _path(self, job_id: str) -> Path:
        return self._root / f"{self._valid_id(job_id)}.json"

    def _claim_marker(self, job_id: str) -> Path:
        return self._root / f"{self._valid_id(job_id)}.claim"

    def _open_index(self, cache_key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", cache_key):
            raise AdviceQueueError("cache_key must be a lowercase SHA-256 digest.")
        return self._root / f"open-{cache_key}.idx"

    def _retain_issue(self, path: Path) -> None:
        """Retain exact unreadable bytes, while the original blocks identity reuse."""
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return
        digest = hashlib.sha256(raw).hexdigest()
        identity = hashlib.sha256(path.name.encode("utf-8") + b"\0" + raw).hexdigest()
        evidence = self._root / "integrity" / f"{identity}.bin"
        if not evidence.exists():
            self._publish(evidence, raw, create=True)
        record = evidence.with_suffix(".json")
        if not record.exists():
            self._publish(
                record,
                json.dumps(
                    {"source": path.name, "sha256": digest, "evidence": evidence.name}
                ).encode("utf-8"),
                create=True,
            )
            AdviceLog("queue").event(
                "advice_queue_integrity_issue", source=path.name, sha256=digest
            )

    def integrity_issues(self) -> tuple[str, ...]:
        """Stable evidence filenames for operator reporting; originals remain in place."""
        return tuple(sorted(p.name for p in (self._root / "integrity").glob("*.bin")))

    def load(self, job_id: str) -> AdviceJob | None:
        path = self._path(job_id)
        # A Windows reader's open handle can deny a concurrent atomic replacement.
        # Polls share the same short transaction as writers; nested queue reads use
        # the existing reentrant lock, and parsing needs no open file handle.
        with self._lock.hold():
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                return None
        try:
            job = AdviceJob.from_payload(json.loads(raw))
            if job.job_id != job_id:
                raise BackendJobsContractError("Stored identity differs from its filename.")
            return job
        except (ValueError, UnicodeError, TypeError) as error:
            raise AdviceQueueIntegrityError(f"Unreadable queue record: {job_id}.") from error

    def _scan(self) -> tuple[AdviceJob, ...]:
        found = []
        for path in sorted(self._root.glob("*.json")):
            try:
                job = self.load(path.stem)
            except AdviceQueueError:
                self._retain_issue(path)
                continue
            if job is not None:
                found.append(job)
        return tuple(sorted(found, key=lambda j: (j.created_at_utc, j.job_id)))

    def jobs(self) -> tuple[AdviceJob, ...]:
        if not self._root.exists():
            return ()
        with self._lock.hold():
            return self._scan()

    def _index_job(self, index: Path, *, repair: bool) -> AdviceJob | None:
        try:
            raw = index.read_bytes()
        except FileNotFoundError:
            return None
        try:
            intent = None
            if raw.lstrip().startswith(b"{"):
                intent = AdviceJob.from_payload(json.loads(raw))
                if intent.status != "queued" or index != self._open_index(intent.cache_key):
                    raise AdviceQueueIntegrityError("Invalid open-job intent.")
                identifier = intent.job_id
            else:
                identifier = self._valid_id(raw.decode("utf-8").strip())
            job = self.load(identifier)
            if job is None and intent is not None and repair:
                self.submit(intent)
                job = intent
            if job is not None and index != self._open_index(job.cache_key):
                raise AdviceQueueIntegrityError("Open-job index points to a different key.")
            if job is None and intent is None and repair:
                # Legacy writer died before publishing a job (and before acknowledging
                # acceptance). Preserve its reservation as evidence before releasing it.
                self._retain_issue(index)
                index.unlink()
            return job
        except (ValueError, UnicodeError, TypeError) as error:
            self._retain_issue(index)
            raise AdviceQueueIntegrityError("Unreadable open-job reservation.") from error

    def _cleanup(self, job: AdviceJob) -> None:
        self._claim_marker(job.job_id).unlink(missing_ok=True)
        index = self._open_index(job.cache_key)
        winner = self._index_job(index, repair=False)
        if winner is not None and winner.job_id == job.job_id:
            index.unlink(missing_ok=True)

    def submit_unless_cached(
        self, job: AdviceJob, *, read_cached: Callable[[str], bytes | None]
    ) -> AdviceJob | bytes:
        """Recheck the validated cache and reserve work atomically with completion.

        A POST's earlier miss can outlive a worker's cache publication and open-index
        cleanup. The read callback only reads and validates immutable answer bytes;
        computation stays outside this short metadata transaction.
        """

        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        with self._lock.hold():
            cached = read_cached(job.cache_key)
            if cached is not None:
                return cached
            winner, _created = self.submit_unique(job)
            return winner

    def submit_unique(self, job: AdviceJob) -> tuple[AdviceJob, bool]:
        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        with self._lock.hold():
            index = self._open_index(job.cache_key)
            winner = self._index_job(index, repair=True)
            if winner is not None:
                if not winner.is_terminal:
                    return winner, False
                self._cleanup(winner)
            # Reject duplicate ids before publishing an intent pointing to another key.
            if self._path(job.job_id).exists():
                raise AdviceQueueError(f"Job {job.job_id!r} already exists; submit is not upsert.")
            self._publish(index, _serialize(job), create=True)
            self.submit(job)
            return job, True

    def submit(self, job: AdviceJob) -> None:
        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        with self._lock.hold():
            try:
                self._publish(self._path(job.job_id), _serialize(job), create=True)
            except FileExistsError:
                raise AdviceQueueError(
                    f"Job {job.job_id!r} already exists; submit is not upsert."
                ) from None

    def _owned(self, job: AdviceJob) -> AdviceJob:
        current = self.load(job.job_id)
        if current is None:
            raise AdviceQueueError(f"Job {job.job_id!r} is not in this queue.")
        if current.status != "running" or current.attempt != job.attempt:
            raise AdviceLeaseLostError("This attempt no longer owns the job.")
        for name in ("request_fingerprint", "cache_key", "created_at_utc", "idempotency_key"):
            if getattr(current, name) != getattr(job, name):
                raise AdviceLeaseLostError("Job identity cannot change during an attempt.")
        if not self._claim_marker(job.job_id).exists():
            raise AdviceLeaseLostError("This attempt has no active claim.")
        return current

    def store(self, job: AdviceJob) -> None:
        with self._lock.hold():
            current = self._owned(job)
            if not job.is_terminal:
                raise AdviceQueueError("Only the owning attempt may store a terminal job.")
            if job.status == "completed" and job.result_ref != job.cache_key:
                raise AdviceQueueError("A completed job must name its own cache key.")
            expected = current.transition(
                job.status, at_utc=job.updated_at_utc, result_ref=job.result_ref, error=job.error
            )
            if expected != job:
                raise AdviceQueueError("Terminal record does not match its transition.")
            self._write(self._path(job.job_id), job)
            self._cleanup(job)

    def complete(
        self, job: AdviceJob, *, cache: AdviceCacheRepository, payload: bytes, at_utc: str
    ) -> AdviceJob:
        with self._lock.hold():
            current = self._owned(job)
            completed = current.transition("completed", at_utc=at_utc, result_ref=job.cache_key)
            cache.put(job.cache_key, payload)
            self.store(completed)
            return completed

    def claim(
        self, *, at_utc: str | None = None, clock: Callable[[], str] | None = None
    ) -> AdviceJob | None:
        stamp = _transition_clock(at_utc, clock)
        with self._lock.hold():
            for job in self._scan():
                if job.status != "queued":
                    continue
                marker = self._claim_marker(job.job_id)
                if marker.exists():
                    continue
                # The selected job may have arrived or been requeued while this caller
                # waited for the lock. Live time is read at the transition, not before it.
                running = job.transition("running", at_utc=stamp())
                self._publish(marker, str(job.attempt).encode("ascii"), create=True)
                self._write(self._path(job.job_id), running)
                return running
        return None

    def heartbeat(self, job_id: str, *, attempt: int) -> None:
        with self._lock.hold():
            job = self.load(job_id)
            if job is None or job.attempt != attempt or job.status != "running":
                raise AdviceLeaseLostError("This attempt no longer owns the job.")
            self._owned(job)
            os.utime(self._claim_marker(job_id))

    def recover(
        self,
        *,
        at_utc: str | None = None,
        clock: Callable[[], str] | None = None,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> tuple[AdviceJob, ...]:
        stamp = _transition_clock(at_utc, clock)
        if not math.isfinite(lease_seconds) or lease_seconds < 0:
            raise AdviceQueueError("lease_seconds must be finite and non-negative.")
        recovered = []
        with self._lock.hold():
            # The lock excludes every conforming publisher. An interrupted intent can
            # therefore be completed immediately without racing its original writer.
            for index in sorted(self._root.glob("open-*.idx")):
                try:
                    self._index_job(index, repair=True)
                except AdviceQueueIntegrityError:
                    continue
            now = time.time()
            for job in self._scan():
                marker = self._claim_marker(job.job_id)
                if job.is_terminal:
                    try:
                        self._cleanup(job)
                    except AdviceQueueIntegrityError:
                        continue
                    continue
                if job.status == "queued":
                    # A claim marker with no running state is an interrupted claim.
                    # No worker received ownership; the next attempt can claim it.
                    marker.unlink(missing_ok=True)
                    continue
                try:
                    age = now - marker.stat().st_mtime
                except FileNotFoundError:
                    age = float("inf")
                if age < lease_seconds:
                    continue
                requeued = job.transition("queued", at_utc=stamp())
                self._write(self._path(job.job_id), requeued)
                marker.unlink(missing_ok=True)
                recovered.append(requeued)
        return tuple(recovered)

    def _write(self, path: Path, job: AdviceJob) -> None:
        self._publish(path, _serialize(job), create=False)

    @staticmethod
    def _publish(path: Path, payload: bytes, *, create: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if create:
                os.link(temporary, path)
            else:
                os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(temporary)
