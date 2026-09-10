"""Durable sequential stage execution; domain work is supplied as typed callables.

An OS lock excludes simultaneous owners and is released on process exit. A crash leaves
the running stage visible. Only explicitly repeatable operations may resume automatically;
unknown external publication outcomes require reconciliation outside this runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.platform._queue_lock import QueueFileLock, QueueLockTimeout

SCHEMA_VERSION = "weekly_run_v1"
_IDENTIFIER = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,95}")


class WeeklyJournalError(RuntimeError):
    """A run cannot safely start, continue or be described as successful."""


class WeeklyReconciliationRequired(WeeklyJournalError):
    """An external side effect may have happened; automatic repetition is unsafe."""


@dataclass(frozen=True, slots=True)
class WeeklyStageResult:
    output_paths: tuple[Path, ...]
    value: Mapping[str, Any] = field(default_factory=dict)
    exit_code: int = 0
    skipped_reason: str | None = None


def _utc() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise WeeklyJournalError("Run and stage identifiers must be simple path components.")
    return value


def _safe(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    for candidate in (absolute, *absolute.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400
        ):
            raise WeeklyJournalError(
                f"Symlink/reparse artifact path is not supported: {candidate}."
            )
    return absolute


def _file(path: Path) -> dict[str, Any]:
    _safe(path)
    if not path.is_file():
        raise WeeklyJournalError(f"Declared artifact is missing: {path}.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            size += len(block)
            digest.update(block)
    return {"path": str(path), "size": size, "sha256": digest.hexdigest()}


def fingerprint_paths(
    paths: Sequence[Path], *, allow_missing: bool = False
) -> list[dict[str, Any]]:
    """Bind directory membership too, so additions and missing capture payloads drift."""

    records = []
    seen: set[str] = set()
    for supplied in sorted(paths, key=str):
        path = _safe(supplied)
        if str(path) in seen:
            continue
        seen.add(str(path))
        if allow_missing and not path.exists():
            records.append({"path": str(path), "missing": True})
        elif path.is_dir():
            files = []
            directories = []
            pending = [path]
            while pending:
                current = pending.pop()
                _safe(current)
                directories.append(str(current.relative_to(path)))
                for child in sorted(current.iterdir()):
                    _safe(child)
                    if child.is_dir():
                        pending.append(child)
                    else:
                        files.append(_file(child))
            records.append({"path": str(path), "directories": sorted(directories), "files": files})
        else:
            records.append(_file(path))
    return records


def _verify(records: Sequence[Mapping[str, Any]]) -> None:
    try:
        observed = fingerprint_paths(
            [Path(record["path"]) for record in records], allow_missing=True
        )
    except (KeyError, TypeError) as error:
        raise WeeklyJournalError("Invalid artifact records in weekly journal.") from error
    if observed != list(records):
        raise WeeklyJournalError("Recorded artifact inputs/outputs have changed; resume refused.")


def _write(path: Path, document: Mapping[str, Any]) -> None:
    raw = (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with QueueFileLock(path.parent / ".journal.lock").hold():
        _replace(path, raw)


def _replace(path: Path, raw: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".weekly-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read(path: Path) -> dict[str, Any]:
    _safe(path)
    try:
        # Status remains available while a stage owns the run lock. Its short read must
        # nevertheless exclude replacement while Windows holds this file handle open.
        with QueueFileLock(path.parent / ".journal.lock").hold():
            raw = path.read_bytes()
        value = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise WeeklyJournalError("Invalid weekly run journal JSON.") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        raise WeeklyJournalError("Invalid weekly run journal.")
    if not isinstance(value.get("stages"), list) or not isinstance(value.get("request"), dict):
        raise WeeklyJournalError("Weekly journal lacks its stage plan or request.")
    states = {"pending", "running", "completed", "skipped", "failed", "interrupted", "uncertain"}
    if value.get("status") not in states | {"validation_failed"} or not value["stages"]:
        raise WeeklyJournalError("Invalid weekly run state.")
    names = []
    for stage in value["stages"]:
        if (
            not isinstance(stage, dict)
            or not isinstance(stage.get("name"), str)
            or stage.get("status") not in states
            or not isinstance(stage.get("attempts"), list)
            or any(not isinstance(attempt, dict) for attempt in stage["attempts"])
        ):
            raise WeeklyJournalError("Invalid weekly stage record.")
        names.append(_identifier(stage["name"]))
        if stage["status"] in {"completed", "skipped"} and (
            not isinstance(stage.get("outputs"), list)
            or not isinstance(stage.get("value"), dict)
            or (not stage["outputs"] and not stage.get("skipped_reason"))
        ):
            raise WeeklyJournalError("Completed weekly stage lacks verified result records.")
    if len(set(names)) != len(names) or (
        value["status"] == "completed"
        and any(stage["status"] not in {"completed", "skipped"} for stage in value["stages"])
    ):
        raise WeeklyJournalError("Weekly completion conflicts with its stage plan.")
    return value


def read_run_request(root: Path, run_id: str) -> dict[str, Any]:
    """Read the original immutable request through the journal metadata lock."""

    return dict(_read(_safe(root / _identifier(run_id)) / "run.json")["request"])


class WeeklyRun:
    """One locked invocation, with a fixed request and ordered stage catalogue."""

    def __init__(
        self,
        root: Path,
        run_id: str,
        request: Mapping[str, Any],
        stages: Sequence[str],
        *,
        resume: bool = False,
        clock: Callable[[], str] = _utc,
    ) -> None:
        self.directory = _safe(root / _identifier(run_id))
        self.path = self.directory / "run.json"
        self._request = json.loads(json.dumps(request, sort_keys=True, allow_nan=False))
        self._names = [_identifier(name) for name in stages]
        if not self._names or len(set(self._names)) != len(self._names):
            raise WeeklyJournalError("A run requires distinct, ordered stages.")
        self._run_id, self._resume, self._clock = run_id, resume, clock
        self._document: dict[str, Any] = {}
        self._held = False

    @contextmanager
    def hold(self) -> Iterator[WeeklyRun]:
        self.directory.mkdir(parents=True, exist_ok=True)
        # Reuse the tested OS lock primitive with an independent, permanent run lock.
        lock = QueueFileLock(self.directory / ".run.lock", timeout_seconds=0)
        try:
            with lock.hold():
                if self.path.exists():
                    self._document = _read(self.path)
                    if not self._resume:
                        raise WeeklyJournalError(
                            "Run already exists; use its explicit resume mode."
                        )
                    if (
                        self._document["request"] != self._request
                        or [stage["name"] for stage in self._document["stages"]] != self._names
                    ):
                        raise WeeklyJournalError(
                            "Run request, source identity or stage plan changed."
                        )
                else:
                    if self._resume:
                        raise WeeklyJournalError("Cannot resume a run with no journal.")
                    self._document = {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": self._run_id,
                        "request": self._request,
                        "created_at_utc": self._clock(),
                        "status": "pending",
                        "stages": [
                            {"name": name, "status": "pending", "attempts": []}
                            for name in self._names
                        ],
                    }
                    _write(self.path, self._document)
                self._held = True
                try:
                    yield self
                finally:
                    self._held = False
        except QueueLockTimeout as error:
            raise WeeklyJournalError("Another process owns this weekly run.") from error

    def stage(
        self,
        name: str,
        *,
        inputs: Sequence[Path],
        operation: Callable[[], WeeklyStageResult],
        repeatable: bool = True,
    ) -> WeeklyStageResult:
        if not self._held or name not in self._names:
            raise WeeklyJournalError("Stages execute only inside their run's exclusive lock.")
        index = self._names.index(name)
        stage = self._document["stages"][index]
        for previous in self._document["stages"][:index]:
            if previous["status"] not in {"completed", "skipped"}:
                raise WeeklyJournalError("Previous stage has not completed.")
        try:
            current_inputs = fingerprint_paths(inputs, allow_missing=True)
        except (OSError, WeeklyJournalError) as error:
            self._document.update(status="validation_failed", validation_error=str(error))
            _write(self.path, self._document)
            raise
        if stage["status"] != "pending":
            if stage.get("inputs") != current_inputs:
                self._document.update(
                    status="validation_failed", validation_error="Stage inputs changed."
                )
                _write(self.path, self._document)
                raise WeeklyJournalError("Stage inputs changed; use a new reviewed run.")
            if stage["status"] in {"completed", "skipped"}:
                _verify(stage["outputs"])
                return WeeklyStageResult(
                    tuple(Path(row["path"]) for row in stage["outputs"]),
                    stage["value"],
                    skipped_reason=stage.get("skipped_reason"),
                )
            if not repeatable or stage.get("repeatable") is False:
                stage["status"] = "uncertain"
                self._document["status"] = "uncertain"
                _write(self.path, self._document)
                raise WeeklyReconciliationRequired(
                    f"Stage {name} may have external effects; "
                    "reconcile its outcome before proceeding."
                )
            for previous_attempt in stage["attempts"]:
                if previous_attempt.get("status") == "running":
                    previous_attempt.update(status="interrupted", observed_at_utc=self._clock())
        attempt: dict[str, Any] = {"started_at_utc": self._clock(), "status": "running"}
        stage["attempts"].append(attempt)
        stage.update(status="running", inputs=current_inputs, repeatable=repeatable)
        self._document["status"] = "running"
        _write(self.path, self._document)
        try:
            result = operation()
            if result.exit_code != 0:
                raise WeeklyJournalError(f"Stage {name} returned exit {result.exit_code}.")
            if not result.output_paths and not result.skipped_reason:
                raise WeeklyJournalError("A completed stage must declare verifiable artifacts.")
            outputs = fingerprint_paths(result.output_paths)
            # Prevent a computation from quietly crossing a mutable capture/alias update.
            _verify(current_inputs)
            state = "skipped" if result.skipped_reason else "completed"
            value = json.loads(json.dumps(result.value, sort_keys=True, allow_nan=False))
            stage.update(
                status=state, outputs=outputs, value=value, skipped_reason=result.skipped_reason
            )
            attempt.update(status=state, finished_at_utc=self._clock(), exit_code=0)
        except BaseException as error:
            state = "failed" if isinstance(error, Exception) else "interrupted"
            if not repeatable:
                state = "uncertain"
            stage["status"] = state
            attempt.update(status=state, finished_at_utc=self._clock(), error=str(error))
            self._document["status"] = state
            _write(self.path, self._document)
            raise
        self._document["status"] = "running"
        _write(self.path, self._document)
        return result

    def finish(self) -> Path:
        if not self._held:
            raise WeeklyJournalError("Finishing requires exclusive run ownership.")
        for stage in self._document["stages"]:
            if stage["status"] not in {"completed", "skipped"}:
                raise WeeklyJournalError("Not every planned stage has finished.")
            _verify(stage["outputs"])
        self._document["status"] = "completed"
        self._document.setdefault("completed_at_utc", self._clock())
        _write(self.path, self._document)
        return self.path


def inspect_run(
    root: Path,
    run_id: str,
    *,
    expected_at_utc: str | None = None,
    now_utc: str | None = None,
) -> dict[str, Any]:
    """Read observed state; missed completion is evaluated only against an explicit time."""

    directory = _safe(root / _identifier(run_id))
    path = directory / "run.json"
    result: dict[str, Any] = {"run_id": run_id, "status": "not_started", "missed": None}
    if path.exists():
        document = _read(path)
        status = document["status"]
        try:
            with QueueFileLock(directory / ".run.lock", timeout_seconds=0).hold():
                if status == "running":
                    running = [
                        stage for stage in document["stages"] if stage["status"] == "running"
                    ]
                    status = (
                        "uncertain"
                        if any(not s.get("repeatable") for s in running)
                        else "interrupted"
                    )
        except QueueLockTimeout:
            status = "running"
        if status == "completed":
            try:
                for stage in document["stages"]:
                    _verify(stage["outputs"])
            except (OSError, WeeklyJournalError) as error:
                status = "invalid_artifacts"
                result["reason"] = str(error)
        result.update(status=status, stages=document["stages"])
        if document.get("completed_at_utc"):
            result["completed_at_utc"] = document["completed_at_utc"]
        if document.get("validation_error"):
            result["reason"] = document["validation_error"]
    if expected_at_utc is not None:
        expected = datetime.fromisoformat(expected_at_utc.replace("Z", "+00:00"))
        now = datetime.fromisoformat((now_utc or _utc()).replace("Z", "+00:00"))
        if expected.utcoffset() is None or now.utcoffset() is None:
            raise WeeklyJournalError("Expected and observed times must include a UTC offset.")
        result["expected_at_utc"] = expected_at_utc
        result["missed"] = now >= expected and result["status"] != "completed"
        if result["status"] == "completed":
            result["missed"] = (
                datetime.fromisoformat(result["completed_at_utc"].replace("Z", "+00:00")) > expected
            )
    return result
