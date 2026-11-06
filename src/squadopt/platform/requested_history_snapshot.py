"""Capture completed request evidence while the backend keeps serving and computing."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from squadopt.data._long_paths import addressable
from squadopt.data.atomic import document_bytes, replace_retrying
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.platform.advice_job_spec import AdviceJobSpec
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.requested_suggestion_history import _requested_history
from squadopt.platform.storage._queue_lock import QueueFileLock
from squadopt.platform.storage.backup_recovery import _safe_path, create_backup, verify_backup

FORMAT = "requested_history_snapshot_v1"
_BACKUP = re.compile(r"snapshots/[0-9]{8}T[0-9]{6}Z-[0-9a-f]{16}")


@dataclass(frozen=True)
class HistorySnapshot:
    source: Path
    store: Path
    receipt: dict[str, Any]


def read_history_snapshot(
    source: Path, *, pinned: Mapping[str, Any] | None = None
) -> HistorySnapshot:
    """Verify the receipt's complete backup; a resumed run supplies its pinned receipt."""
    source = _safe_path(source)
    record = dict(pinned) if pinned is not None else json.loads(source.read_bytes())
    if (
        not isinstance(record, dict)
        or set(record) != {"format", "backup", "manifest_sha256", "captured_at_utc"}
        or record.get("format") != FORMAT
        or not isinstance(record.get("backup"), str)
        or not _BACKUP.fullmatch(record["backup"])
        or not isinstance(record.get("manifest_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", record["manifest_sha256"])
    ):
        raise ValueError("Invalid requested-history snapshot receipt.")
    normalize_utc_timestamp(record["captured_at_utc"], label="captured_at_utc")
    backup = source.parent / record["backup"]
    verify_backup(backup, manifest_sha256=record["manifest_sha256"])
    store = Path(addressable(backup / "files" / "store"))
    capture = json.loads((store / "capture.json").read_bytes())
    if capture != {"format": FORMAT, "captured_at_utc": record["captured_at_utc"]}:
        raise ValueError("The requested-history capture differs from its receipt.")
    if not all((store / part).is_dir() for part in ("jobs", "specs", "cache")):
        raise ValueError("The requested-history snapshot has no complete store.")
    return HistorySnapshot(source, store, record)


def _frozen_jobs(
    store: Path, *, clock: Callable[[], datetime], lock_budget_seconds: float
) -> tuple[str, dict[str, bytes], tuple[Path, ...]]:
    """Freeze live metadata and the archive inventory, never copy answers under the lock.

    Archive files are immutable and never removed by the queue. Live records are read
    now, so a job finishing after this transaction cannot enter the snapshot, even when
    its second-resolution completion timestamp equals an earlier job's timestamp.
    """
    jobs = store / "jobs"
    with QueueFileLock(_safe_path(jobs / ".queue.lock")).hold():
        started = time.monotonic()
        captured = normalize_utc_timestamp(clock().isoformat(), label="capture clock")
        archived = tuple(sorted((jobs / "archive").glob("*.json")))
        live = {}
        for path in sorted(jobs.glob("*.json")):
            if time.monotonic() - started >= lock_budget_seconds:
                raise TimeoutError("Requested-history metadata snapshot exceeded its lock budget.")
            live[path.stem] = _safe_path(path).read_bytes()
        if time.monotonic() - started >= lock_budget_seconds:
            raise TimeoutError("Requested-history metadata snapshot exceeded its lock budget.")
    return captured, live, archived


def snapshot_requested_history(
    store: Path,
    output_root: Path,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    lock_budget_seconds: float = 1.0,
    group_readable: bool = False,
) -> HistorySnapshot:
    """Publish an immutable, verified subset and atomically advance its private receipt.

    This is history evidence, not a queue restore: only completed plain one-week
    requests are copied, with idempotency keys removed. Source files are never repaired.
    """
    store, output_root = _safe_path(store), _safe_path(output_root)
    if store == output_root or store in output_root.parents or output_root in store.parents:
        raise ValueError("The snapshot destination and backend store must be disjoint.")
    if not math.isfinite(lock_budget_seconds) or lock_budget_seconds <= 0:
        raise ValueError("The metadata lock budget must be positive and finite.")
    for part in ("jobs", "specs", "cache"):
        if not _safe_path(store / part).is_dir():
            raise ValueError("Expected a backend store with jobs, specs and cache.")
    _safe_path(store / "jobs" / "archive")
    output_root.mkdir(parents=True, mode=0o700, exist_ok=True)
    source = _safe_path(output_root / "latest.json")
    with QueueFileLock(output_root / ".snapshot.lock", timeout_seconds=0).hold():
        previous = read_history_snapshot(source) if source.exists() else None
        captured, live, archived = _frozen_jobs(
            store, clock=clock, lock_budget_seconds=lock_budget_seconds
        )
        if previous is not None and as_instant(captured) < as_instant(
            previous.receipt["captured_at_utc"]
        ):
            raise ValueError("An older snapshot clock cannot replace a newer receipt.")
        for path in archived:
            raw = _safe_path(path).read_bytes()
            if path.stem in live and live[path.stem] != raw:
                raise ValueError("Live and archived copies of a job disagree.")
            live[path.stem] = raw
        identity = as_instant(captured).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8)
        relative = f"snapshots/{identity}"
        destination = _safe_path(output_root / relative)
        destination.parent.mkdir(mode=0o700, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".building-", dir=output_root) as temporary:
            staged = Path(temporary).resolve()
            if staged.parent != output_root.resolve():
                raise ValueError("The temporary snapshot must stay within its output root.")
            staged = Path(addressable(staged))
            for part in ("jobs", "specs", "cache"):
                (staged / part).mkdir()
            cutoff = (as_instant(captured) + timedelta(microseconds=1)).isoformat()
            for job_id, raw in sorted(live.items()):
                job = AdviceJob.from_payload(json.loads(raw))
                if job.job_id != job_id:
                    raise ValueError("A job's filename differs from its recorded identity.")
                if job.status != "completed":
                    continue
                if as_instant(job.updated_at_utc) > as_instant(captured):
                    raise ValueError("A completed job has a timestamp after the snapshot clock.")
                key = job.cache_key
                spec_path = _safe_path(store / "specs" / key[:2] / f"{key}.json")
                spec_raw = spec_path.read_bytes()
                spec = AdviceJobSpec.from_payload(json.loads(spec_raw))
                _safe_path(store / "cache" / key[:2] / f"{key}.json")
                exported = _requested_history(
                    store,
                    season=spec.context.season,
                    gameweek=spec.context.gameweek,
                    entry_id=spec.entry_id,
                    deadline_utc=cutoff,
                    jobs=[job],
                )
                if not exported["records"]:
                    continue
                (record,) = exported["records"]
                for part, content in (
                    ("specs", spec_raw),
                    ("cache", record["response_json"].encode("utf-8")),
                ):
                    target = staged / part / key[:2] / f"{key}.json"
                    target.parent.mkdir(exist_ok=True)
                    if target.exists() and target.read_bytes() != content:
                        raise ValueError("Two jobs disagree on one immutable answer.")
                    target.write_bytes(content)
                (staged / "jobs" / f"{job_id}.json").write_bytes(
                    document_bytes(replace(job, idempotency_key=None).as_payload())
                )
            (staged / "capture.json").write_bytes(
                document_bytes({"format": FORMAT, "captured_at_utc": captured})
            )
            destination.mkdir(mode=0o700)
            # The private staging subset has one writer, finished above. The backend
            # keeps running; writers_stopped applies only to this isolated source.
            receipt = create_backup({"store": staged}, destination, writers_stopped=True)
        record = {
            "format": FORMAT,
            "backup": relative,
            "manifest_sha256": receipt.manifest_sha256,
            "captured_at_utc": captured,
        }
        result = read_history_snapshot(source, pinned=record)
        if group_readable:
            # The service's primary group is the weekly runner's group. No world access.
            for path in (output_root, destination.parent, destination, *destination.rglob("*")):
                path.chmod(0o750 if path.is_dir() else 0o640)
        descriptor, temporary_name = tempfile.mkstemp(prefix=".latest-", dir=output_root)
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(document_bytes(record))
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.chmod(0o640 if group_readable else 0o600)
            replace_retrying(temporary_path, source)
        finally:
            temporary_path.unlink(missing_ok=True)
        return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--group-readable", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = snapshot_requested_history(
            args.store, args.output_root, group_readable=args.group_readable
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Requested history snapshot refused: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {"receipt": str(result.source), "manifest_sha256": result.receipt["manifest_sha256"]}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
