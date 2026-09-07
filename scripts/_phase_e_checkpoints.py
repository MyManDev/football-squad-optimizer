"""Identity-bound checkpoints and crash-safe JSON writes for the E2 probe.

A checkpoint belongs to exactly one run identity: the sampler and its settings, the candidate
counts, the sensitivity seeds, the budget, the scoring flag, the Phase C source digests and the
producer commit. A directory holding a checkpoint of a different identity is refused rather
than merged or overwritten, so a foundation run and a conditional run, or two commits, can never
share partial work. Files are written through a private temporary file and an atomic replace,
retried on the transient Windows sharing error that stopped an earlier run.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final

Record = dict[str, Any]
CHECKPOINT_CONTRACT: Final = "phase_e_probe_checkpoint_v1"
STATUS_CONTRACT: Final = "phase_e_probe_status_v1"
REPLACE_ATTEMPTS: Final = 40
REPLACE_PAUSE_SECONDS: Final = 0.25


class CheckpointError(ValueError):
    """Raised when a checkpoint directory holds work of another run identity."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def jsonable(value: object) -> Any:
    """A JSON-shaped copy of configs and records, including read-only mapping fields."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Enum):
        return jsonable(value.value)
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json_atomic(path: Path, value: object) -> None:
    """Write ``value`` so that ``path`` is either the old or the new document, never partial.

    ``os.replace`` fails with ``PermissionError`` on Windows while another process still holds
    the target open (an antivirus scan, an indexer or a reader). The replace is retried for a
    bounded time before the error is raised; the temporary file never survives a failure.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                temporary.unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_PAUSE_SECONDS)


def read_json_retry(path: Path) -> Any:
    """Read a JSON document, retrying the same transient sharing error on the read side."""

    for attempt in range(REPLACE_ATTEMPTS):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_PAUSE_SECONDS)
    raise AssertionError("unreachable")


@dataclass(frozen=True, slots=True)
class CheckpointStore:
    """Per-pool checkpoints under ``directory / checkpoints``, all bound to ``identity``."""

    directory: Path
    identity: Mapping[str, Any]

    @property
    def checkpoint_directory(self) -> Path:
        return self.directory / "checkpoints"

    def path(self, label: str) -> Path:
        return self.checkpoint_directory / f"{label}.json"

    def refuse_foreign_work(self, pool_digests: Mapping[str, str] | None = None) -> None:
        """Stop before any computation if the directory carries another identity's work.

        ``pool_digests`` maps each label this run will probe to the digest of the pool it will
        probe; a checkpoint written for another pool under the same label is foreign work.
        """

        if not self.checkpoint_directory.exists():
            return
        for path in sorted(self.checkpoint_directory.glob("*.json")):
            document = self._verify(path, read_json_retry(path))
            label = str(document.get("label"))
            if pool_digests is not None and label in pool_digests:
                self._verify_pool(path, document, pool_digests[label])

    def _verify(self, path: Path, document: object) -> Record:
        if (
            not isinstance(document, dict)
            or document.get("contract_version") != CHECKPOINT_CONTRACT
            or document.get("run_identity") != dict(self.identity)
        ):
            raise CheckpointError(
                f"{path} belongs to a different probe run identity (sampler, settings, source, "
                "execution or commit); it is neither reused nor overwritten."
            )
        return document

    @staticmethod
    def _verify_pool(path: Path, document: Record, pool_sha256: str) -> None:
        if document.get("pool_sha256") != pool_sha256:
            raise CheckpointError(
                f"{path} was measured on a different pool than the one this run prepared for "
                "its label; it is neither reused nor overwritten."
            )

    def load(self, label: str, *, pool_sha256: str | None = None) -> Record | None:
        """The verified checkpoint of ``label``, or None when it was never written."""

        path = self.path(label)
        if not path.exists():
            return None
        document = self._verify(path, read_json_retry(path))
        if pool_sha256 is not None:
            self._verify_pool(path, document, pool_sha256)
        return document

    def save(
        self,
        label: str,
        *,
        kind: str,
        completed_counts: list[int],
        record: Record,
        pool_sha256: str | None = None,
    ) -> None:
        write_json_atomic(
            self.path(label),
            {
                "contract_version": CHECKPOINT_CONTRACT,
                "run_identity": dict(self.identity),
                "label": label,
                "kind": kind,
                "pool_sha256": pool_sha256,
                "completed_counts": list(completed_counts),
                "record": record,
                "updated_at_utc": utc_now(),
            },
        )


def write_status(
    directory: Path,
    *,
    status: str,
    identity: Mapping[str, Any],
    workers: int,
    expected_labels: int,
    completed_labels: list[str],
    failed_labels: Mapping[str, str],
    started_at_utc: str,
    elapsed_seconds: float,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """The coordinator's own progress file; workers never write it and never read it."""

    write_json_atomic(
        directory / "status.json",
        {
            "contract_version": STATUS_CONTRACT,
            "status": status,
            "run_identity": dict(identity),
            "workers": workers,
            "expected_labels": expected_labels,
            "completed_label_count": len(completed_labels),
            "completed_labels": list(completed_labels),
            "failed_labels": dict(failed_labels),
            "started_at_utc": started_at_utc,
            "updated_at_utc": utc_now(),
            "elapsed_seconds": elapsed_seconds,
            **(dict(extra) if extra else {}),
        },
    )
