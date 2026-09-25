"""Recoverable file queue with fenced, short metadata transactions.

An open-key reservation contains the complete queued intent. Publication order is intent,
job, claim, running state, immutable cache, terminal state, cleanup. Every prefix can be
reconciled under the same process-shared lock. Computation runs outside that lock.
Existing job documents keep backend_jobs_v1; legacy id-only indexes remain readable.
Drain old workers before upgrade: processes unaware of fencing must not share this store.

A finished record (completed or failed) never changes again. A scan remembers the ones it
has read, by file name, modification time and size, and does not read them again, so after
a process's first scan claim, recover and the job listing read only open or changed records.
Once a finished record is older than the retention window, ``archive`` moves it unchanged
into ``archive/`` beside two small indexes (by idempotency key and by cache key). ``load``
and ``history`` still find it there, and its id is never given to another job.
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
from datetime import timedelta
from pathlib import Path
from typing import Final

from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.advice_observability import AdviceLog
from squadopt.platform.jobs_contract import (
    _JOB_ID_PATTERN,
    AdviceJob,
    BackendJobsContractError,
    _instant,
    _utc,
)
from squadopt.platform.queue_contracts import (
    DEFAULT_ARCHIVE_AFTER_SECONDS,
    DEFAULT_LEASE_SECONDS,
    AdviceLeaseLostError,
    AdviceQueueError,
    AdviceQueueIntegrityError,
)

#: At most this many records move per ``archive`` call, and the call stops early once it
#: has held the lock for ``DEFAULT_ARCHIVE_BUDGET_SECONDS``: every other queue transaction
#: waits on the same lock for at most 5 s.
DEFAULT_ARCHIVE_BATCH: Final = 100
DEFAULT_ARCHIVE_BUDGET_SECONDS: Final = 1.0


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
        # Finished records this process has read, by file name, with the (mtime_ns, size)
        # they were read at. Only touched under the lock.
        self._finished: dict[str, tuple[tuple[int, int], AdviceJob]] = {}
        # Finished jobs whose claim marker and open reservation this process has removed.
        self._settled: set[str] = set()

    @staticmethod
    def _valid_id(job_id: str) -> str:
        if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
            raise AdviceQueueError(f"job_id has an invalid format: {job_id!r}.")
        return job_id

    def _path(self, job_id: str) -> Path:
        return self._root / f"{self._valid_id(job_id)}.json"

    def _archived_path(self, job_id: str) -> Path:
        return self._root / "archive" / f"{self._valid_id(job_id)}.json"

    def _key_index(self, idempotency_key: str) -> Path:
        # Hashed: an idempotency key may hold characters a file name cannot.
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return self._root / "archive" / "idempotency" / f"{digest}.json"

    def _answer_index(self, cache_key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", cache_key):
            raise AdviceQueueError("cache_key must be a lowercase SHA-256 digest.")
        return self._root / "archive" / "answers" / f"{cache_key}.json"

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
        """The job's record, from ``jobs/`` or, once it has been archived, from the archive."""

        path = self._path(job_id)
        # A Windows reader's open handle can deny a concurrent atomic replacement.
        # Polls share the same short transaction as writers; nested queue reads use
        # the existing reentrant lock, and parsing needs no open file handle.
        with self._lock.hold():
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                try:
                    raw = self._archived_path(job_id).read_bytes()
                except FileNotFoundError:
                    return None
        return self._parse(raw, job_id)

    def _load_live(self, job_id: str) -> AdviceJob | None:
        path = self._path(job_id)
        with self._lock.hold():
            try:
                raw = path.read_bytes()
            except FileNotFoundError:
                return None
        return self._parse(raw, job_id)

    @staticmethod
    def _parse(raw: bytes, job_id: str) -> AdviceJob:
        try:
            job = AdviceJob.from_payload(json.loads(raw))
            if job.job_id != job_id:
                raise BackendJobsContractError("Stored identity differs from its filename.")
            return job
        except (ValueError, UnicodeError, TypeError) as error:
            raise AdviceQueueIntegrityError(f"Unreadable queue record: {job_id}.") from error

    def _scan(self) -> tuple[AdviceJob, ...]:
        """Every record in ``jobs/``, reading a finished one only the first time it is seen.

        Callers hold the lock, so no conforming writer changes a file during the scan. A
        finished record is never rewritten; the stamp check still rereads one that was.
        """

        try:
            entries = sorted(os.scandir(self._root), key=lambda entry: entry.name)
        except FileNotFoundError:
            entries = []
        found = []
        finished: dict[str, tuple[tuple[int, int], AdviceJob]] = {}
        for entry in entries:
            if not entry.name.endswith(".json"):
                continue
            try:
                info = entry.stat()
            except FileNotFoundError:
                continue
            stamp = (info.st_mtime_ns, info.st_size)
            held = self._finished.get(entry.name)
            if held is not None and held[0] == stamp:
                finished[entry.name] = held
                found.append(held[1])
                continue
            path = Path(entry.path)
            try:
                job = self._load_live(path.stem)
            except AdviceQueueError:
                self._retain_issue(path)
                continue
            if job is None:
                continue
            if job.is_terminal:
                finished[entry.name] = (stamp, job)
            found.append(job)
        self._finished = finished
        self._settled &= {job.job_id for _stamp, job in finished.values()}
        return tuple(sorted(found, key=lambda j: (j.created_at_utc, j.job_id)))

    def jobs(self) -> tuple[AdviceJob, ...]:
        """The records in ``jobs/``: open work, and finished work not yet archived."""

        if not self._root.exists():
            return ()
        with self._lock.hold():
            return self._scan()

    def history(self, *, idempotency_key: str | None, cache_key: str) -> tuple[AdviceJob, ...]:
        """``jobs()``, plus the archived jobs that used this idempotency key or this answer.

        What a submission decides from: whether its idempotency key was already used for a
        different request, and how many jobs this answer's address has had (the next job's
        id counts them). The archive is read through its two indexes, never listed.
        """

        if not self._root.exists():
            return ()
        with self._lock.hold():
            live = self._scan()
            names = set(self._archived_ids(self._answer_index(cache_key), "cache_key", cache_key))
            if idempotency_key is not None:
                names.update(
                    self._archived_ids(
                        self._key_index(idempotency_key), "idempotency_key", idempotency_key
                    )
                )
            # A record the indexes name that has not moved yet is already in ``live``.
            names -= {job.job_id for job in live}
            archived = []
            for name in sorted(names):
                job = self.load(name)
                if job is None:
                    raise AdviceQueueIntegrityError(f"Archived job {name!r} is missing.")
                archived.append(job)
        return tuple(sorted((*live, *archived), key=lambda j: (j.created_at_utc, j.job_id)))

    def _archived_ids(self, index: Path, field: str, value: str) -> tuple[str, ...]:
        try:
            raw = index.read_bytes()
        except FileNotFoundError:
            return ()
        try:
            document = json.loads(raw)
            if not isinstance(document, dict) or document.get(field) != value:
                raise AdviceQueueIntegrityError("Archive index names a different key.")
            ids = document.get("job_ids")
            if not isinstance(ids, list) or not ids:
                raise AdviceQueueIntegrityError("Archive index holds no job ids.")
            return tuple(self._valid_id(name) for name in ids)
        except (ValueError, UnicodeError, TypeError) as error:
            self._retain_issue(index)
            raise AdviceQueueIntegrityError("Unreadable archive index.") from error

    def _add_to_archive_index(self, index: Path, field: str, value: str, job_id: str) -> None:
        held = self._archived_ids(index, field, value)
        if job_id in held:
            return
        document = {field: value, "job_ids": sorted({*held, job_id})}
        self._publish(
            index, (json.dumps(document, sort_keys=True) + "\n").encode("utf-8"), create=False
        )

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
        self,
        job: AdviceJob,
        *,
        read_cached: Callable[[str], bytes | None],
        admit: Callable[[], contextlib.AbstractContextManager[None]] | None = None,
        prepare: Callable[[], None] | None = None,
    ) -> AdviceJob | bytes:
        """Recheck the validated cache and reserve work atomically with completion.

        A POST's earlier miss can outlive a worker's cache publication and open-index
        cleanup. The read callback only reads and validates immutable answer bytes;
        computation stays outside this short metadata transaction.

        For genuinely new work, ``admit`` checks the caller's owned job IDs and holds
        a memory-only reservation through preparation and publication, removing it
        if either fails. ``prepare`` writes the spec before a worker can claim it.
        Both run under this transaction; this adapter receives no client identity.
        """

        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        with self._lock.hold():
            cached = read_cached(job.cache_key)
            if cached is not None:
                return cached
            if admit is not None or prepare is not None:
                existing = self._index_job(self._open_index(job.cache_key), repair=True)
                if existing is not None and not existing.is_terminal:
                    return existing
            with admit() if admit is not None else contextlib.nullcontext():
                if prepare is not None:
                    prepare()
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
            if self._path(job.job_id).exists() or self._archived_path(job.job_id).exists():
                raise AdviceQueueError(f"Job {job.job_id!r} already exists; submit is not upsert.")
            self._publish(index, _serialize(job), create=True)
            self.submit(job)
            return job, True

    def submit(self, job: AdviceJob) -> None:
        if job.status != "queued":
            raise AdviceQueueError("Only a queued job can be submitted.")
        with self._lock.hold():
            # An archived id stays taken: its record is still served under it.
            if self._archived_path(job.job_id).exists():
                raise AdviceQueueError(f"Job {job.job_id!r} already exists; submit is not upsert.")
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
            self._settled.add(job.job_id)

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
                    # Once removed, a finished job's marker and reservation never return:
                    # a claim marks only queued work, and a newer job's reservation for the
                    # same key names that job.
                    if job.job_id in self._settled:
                        continue
                    try:
                        self._cleanup(job)
                    except AdviceQueueIntegrityError:
                        continue
                    self._settled.add(job.job_id)
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

    def archive(
        self,
        *,
        now_utc: str,
        retention_seconds: float = DEFAULT_ARCHIVE_AFTER_SECONDS,
        max_records: int = DEFAULT_ARCHIVE_BATCH,
        budget_seconds: float = DEFAULT_ARCHIVE_BUDGET_SECONDS,
    ) -> tuple[AdviceJob, ...]:
        """Move finished records last updated ``retention_seconds`` before now into the archive.

        Oldest first, at most ``max_records`` of them, and no new one once the lock has been
        held for ``budget_seconds``; what is left waits for the next call. Open work is never
        moved, and neither is a finished record whose reservation cannot be read.
        """

        if not math.isfinite(retention_seconds) or retention_seconds < 0:
            raise AdviceQueueError("retention_seconds must be finite and non-negative.")
        if max_records < 1:
            raise AdviceQueueError("max_records must be at least one.")
        cutoff = _instant(_utc(now_utc, label="now_utc")) - timedelta(seconds=retention_seconds)
        if not self._root.exists():
            return ()
        moved: list[AdviceJob] = []
        with self._lock.hold():
            deadline = time.monotonic() + budget_seconds
            for job in self._scan():
                if len(moved) >= max_records or time.monotonic() >= deadline:
                    break
                if not job.is_terminal or _instant(job.updated_at_utc) > cutoff:
                    continue
                try:
                    self._archive_one(job)
                except AdviceQueueIntegrityError:
                    continue
                moved.append(job)
        return tuple(moved)

    def _archive_one(self, job: AdviceJob) -> None:
        # Read again rather than trusting the scan's copy: only a finished record moves.
        current = self._load_live(job.job_id)
        if current is None or current != job or not current.is_terminal:
            raise AdviceQueueIntegrityError(f"Job {job.job_id!r} changed before archiving.")
        # Its claim marker and a reservation still naming it go first: once the record has
        # left jobs/, recovery's scan no longer sees it to remove them.
        self._cleanup(current)
        # The indexes first: a crash before the move leaves the record where it was, and
        # the next call adds nothing twice.
        if current.idempotency_key is not None:
            self._add_to_archive_index(
                self._key_index(current.idempotency_key),
                "idempotency_key",
                current.idempotency_key,
                current.job_id,
            )
        self._add_to_archive_index(
            self._answer_index(current.cache_key), "cache_key", current.cache_key, current.job_id
        )
        source, target = self._path(current.job_id), self._archived_path(current.job_id)
        if target.exists():
            if target.read_bytes() != source.read_bytes():
                self._retain_issue(source)
                raise AdviceQueueIntegrityError(f"Archived job {job.job_id!r} differs.")
            source.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        self._finished.pop(source.name, None)
        self._settled.discard(current.job_id)

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
