"""Shared execution lifecycle for transport-neutral application operations.

Entry points adapt a public application service to a zero-argument operation and hand it
to :class:`RuntimeRunner`.  The runner owns the surrounding platform concerns: immutable
manifest publication, input/output provenance, one run id across structured events, and a
typed terminal result.  It deliberately knows nothing about CLI, HTTP, queues or databases.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from squadopt.platform.artifacts import ArtifactRecord, FileArtifactRegistry, artifact_checksum
from squadopt.platform.context import RunContext
from squadopt.platform.manifest import write_run_manifest

RuntimePhase = Literal["application", "outputs"]
RuntimeStatus = Literal["completed", "failed"]

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_SCHEMA_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")

T = TypeVar("T")


class RuntimeContractError(ValueError):
    """A runtime request or operation result violates the shared contract."""


class RuntimePreparationError(RuntimeError):
    """A run could not resolve its inputs or publish its immutable manifest."""


@runtime_checkable
class RuntimeEventSink(Protocol):
    """Structural seam implemented by the existing live ``RunLog``."""

    run_id: str

    def event(self, name: str, **fields: object) -> None: ...

    def failure(self, name: str, **fields: object) -> None: ...


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    """One file an operation consumes or produces, with its domain schema identity."""

    path: Path
    kind: str
    schema_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        if not isinstance(self.kind, str) or not _NAME_PATTERN.fullmatch(self.kind):
            raise RuntimeContractError(f"artifact kind has an invalid format: {self.kind!r}.")
        if not isinstance(self.schema_version, str) or not _SCHEMA_PATTERN.fullmatch(
            self.schema_version
        ):
            raise RuntimeContractError(
                f"artifact schema_version has an invalid format: {self.schema_version!r}."
            )


@dataclass(frozen=True, slots=True)
class RuntimeInputArtifact(RuntimeArtifact):
    """An input file bound to one named fingerprint in its ``RunContext``."""

    fingerprint_name: str

    def __post_init__(self) -> None:
        RuntimeArtifact.__post_init__(self)
        if not isinstance(self.fingerprint_name, str) or not _NAME_PATTERN.fullmatch(
            self.fingerprint_name
        ):
            raise RuntimeContractError(
                f"input fingerprint_name has an invalid format: {self.fingerprint_name!r}."
            )


def _validate_artifact_slots(
    artifacts: tuple[RuntimeArtifact, ...],
    *,
    label: str,
    artifact_type: type[RuntimeArtifact] = RuntimeArtifact,
) -> None:
    if not isinstance(artifacts, tuple) or not all(
        isinstance(artifact, artifact_type) for artifact in artifacts
    ):
        raise RuntimeContractError(f"{label} must be a tuple of {artifact_type.__name__} values.")
    slots: set[tuple[str, Path]] = set()
    for artifact in artifacts:
        slot = (artifact.kind, artifact.path.resolve())
        if slot in slots:
            raise RuntimeContractError(
                f"{label} repeats artifact kind {artifact.kind!r} at {artifact.path}."
            )
        slots.add(slot)


@dataclass(frozen=True, slots=True)
class RuntimeRequest:
    """Validated platform inputs for one application operation."""

    operation: str
    context: RunContext
    inputs: tuple[RuntimeInputArtifact, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.operation, str) or not _NAME_PATTERN.fullmatch(self.operation):
            raise RuntimeContractError(
                f"operation must be a lowercase platform name, got {self.operation!r}."
            )
        if not isinstance(self.context, RunContext):
            raise RuntimeContractError("context must be a RunContext.")
        _validate_artifact_slots(
            self.inputs,
            label="inputs",
            artifact_type=RuntimeInputArtifact,
        )
        fingerprint_names = [artifact.fingerprint_name for artifact in self.inputs]
        if len(fingerprint_names) != len(set(fingerprint_names)):
            raise RuntimeContractError("inputs repeat a RunContext fingerprint_name.")
        expected = set(self.context.input_fingerprints)
        declared = set(fingerprint_names)
        if declared != expected:
            raise RuntimeContractError(
                "inputs must resolve every RunContext input_fingerprint exactly once: "
                f"missing={sorted(expected - declared)!r}, "
                f"unexpected={sorted(declared - expected)!r}."
            )


@dataclass(frozen=True, slots=True)
class RuntimeOperationResult(Generic[T]):
    """Application value plus the files produced by the adapted public service."""

    value: T
    outputs: tuple[RuntimeArtifact, ...] = ()

    def __post_init__(self) -> None:
        _validate_artifact_slots(self.outputs, label="outputs")


@dataclass(frozen=True, slots=True)
class RuntimeFailure:
    """Transport-neutral terminal failure safe to expose through a later CLI or API."""

    phase: RuntimePhase
    error_type: str
    message: str

    def __post_init__(self) -> None:
        if self.phase not in {"application", "outputs"}:
            raise RuntimeContractError(f"runtime failure phase is invalid: {self.phase!r}.")
        if not isinstance(self.error_type, str) or not self.error_type.strip():
            raise RuntimeContractError("runtime failure error_type must be non-empty text.")
        if not isinstance(self.message, str):
            raise RuntimeContractError("runtime failure message must be text.")


@dataclass(frozen=True, slots=True)
class RuntimeResult(Generic[T]):
    """The complete terminal reading of one started run."""

    operation: str
    context: RunContext
    status: RuntimeStatus
    manifest_path: Path
    started_at_utc: str
    finished_at_utc: str
    runtime_seconds: float
    inputs: tuple[ArtifactRecord, ...] = ()
    outputs: tuple[ArtifactRecord, ...] = ()
    value: T | None = None
    failure: RuntimeFailure | None = None

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed"}:
            raise RuntimeContractError(f"runtime result status is invalid: {self.status!r}.")
        if self.status == "completed" and self.failure is not None:
            raise RuntimeContractError("a completed runtime result cannot contain a failure.")
        if self.status == "failed" and self.failure is None:
            raise RuntimeContractError("a failed runtime result must contain a failure.")
        if self.runtime_seconds < 0.0:
            raise RuntimeContractError("runtime_seconds cannot be negative.")

    @property
    def completed(self) -> bool:
        """Whether the operation and all output registrations completed."""

        return self.status == "completed"


def _utc_moment(clock: Callable[[], datetime]) -> datetime:
    moment = clock()
    if not isinstance(moment, datetime):
        raise RuntimeContractError("runtime clock must return a datetime.")
    offset = moment.utcoffset()
    if moment.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
        raise RuntimeContractError("runtime clock must return a timezone-aware UTC datetime.")
    return moment


def _utc_text(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class RuntimeRunner:
    """Execute application operations with one reproducible platform lifecycle."""

    artifact_registry: FileArtifactRegistry
    manifest_root: Path
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    timer: Callable[[], float] = field(default=perf_counter)

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_registry, FileArtifactRegistry):
            raise RuntimeContractError("artifact_registry must be a FileArtifactRegistry.")
        self.manifest_root = Path(self.manifest_root).resolve()
        if not callable(self.clock) or not callable(self.timer):
            raise RuntimeContractError("clock and timer must be callable.")

    def _register(
        self,
        artifact: RuntimeArtifact,
        *,
        run_id: str,
        role: Literal["input", "output"],
    ) -> ArtifactRecord:
        return self.artifact_registry.register_artifact(
            artifact.path,
            run_id=run_id,
            role=role,
            kind=artifact.kind,
            schema_version=artifact.schema_version,
            now=_utc_moment(self.clock),
        )

    def _preflight_inputs(
        self,
        inputs: tuple[RuntimeInputArtifact, ...],
        context: RunContext,
    ) -> None:
        """Resolve every input before publishing any run-specific state."""

        root = self.artifact_registry.artifact_root.resolve()
        for artifact in inputs:
            try:
                path = artifact.path.resolve(strict=True)
            except FileNotFoundError as error:
                raise RuntimePreparationError(
                    f"Input artifact file does not exist: {artifact.path}."
                ) from error
            if not path.is_file():
                raise RuntimePreparationError(
                    f"Input artifact path is not a regular file: {artifact.path}."
                )
            try:
                path.relative_to(root)
            except ValueError as error:
                raise RuntimePreparationError(
                    f"Input artifact {path} is outside artifact_root {root}."
                ) from error
            checksum = artifact_checksum(path)
            expected = context.input_fingerprints[artifact.fingerprint_name]
            if checksum != expected:
                raise RuntimePreparationError(
                    f"Input artifact {artifact.fingerprint_name!r} checksum does not match "
                    f"RunContext: expected {expected!r}, computed {checksum!r}."
                )

    def execute(
        self,
        request: RuntimeRequest,
        operation: Callable[[], RuntimeOperationResult[T]],
        *,
        events: RuntimeEventSink | None = None,
    ) -> RuntimeResult[T]:
        """Run one adapted application service and return its structured terminal state.

        Preparation errors are raised because no application run has started. Once the
        manifest exists and ``runtime.started`` is emitted, application or output-registry
        errors become a failed :class:`RuntimeResult` and a structured failure event.
        ``KeyboardInterrupt`` and other ``BaseException`` subclasses are never swallowed.
        """

        if not isinstance(request, RuntimeRequest):
            raise RuntimeContractError("request must be a RuntimeRequest.")
        if not callable(operation):
            raise RuntimeContractError("operation must be callable.")
        if events is not None:
            if not isinstance(events, RuntimeEventSink):
                raise RuntimeContractError(
                    "events must expose run_id, event() and failure() as a RuntimeEventSink."
                )
            if events.run_id != request.context.run_id:
                raise RuntimeContractError(
                    "event sink run_id must match RunContext.run_id: "
                    f"{events.run_id!r} != {request.context.run_id!r}."
                )

        run_id = request.context.run_id
        try:
            self._preflight_inputs(request.inputs, request.context)
            manifest_path = self.manifest_root / run_id / "manifest.json"
            write_run_manifest(manifest_path, request.context)
            inputs = tuple(
                self._register(artifact, run_id=run_id, role="input") for artifact in request.inputs
            )
        except RuntimePreparationError:
            raise
        except (OSError, ValueError, RuntimeError) as error:
            raise RuntimePreparationError(
                f"Could not prepare run {run_id!r}: {type(error).__name__}: {error}"
            ) from error

        started = _utc_moment(self.clock)
        timer_started = self.timer()
        if events is not None:
            events.event(
                "runtime.started",
                operation=request.operation,
                reproducibility_fingerprint=request.context.reproducibility_fingerprint,
                manifest_path=manifest_path,
                input_artifact_ids=[record.artifact_id for record in inputs],
            )

        outputs: list[ArtifactRecord] = []
        phase: RuntimePhase = "application"
        try:
            operation_result = operation()
            if not isinstance(operation_result, RuntimeOperationResult):
                raise RuntimeContractError("operation must return a RuntimeOperationResult.")
            phase = "outputs"
            outputs.extend(
                self._register(artifact, run_id=run_id, role="output")
                for artifact in operation_result.outputs
            )
        except Exception as error:
            finished = _utc_moment(self.clock)
            elapsed = max(0.0, self.timer() - timer_started)
            failure = RuntimeFailure(
                phase=phase,
                error_type=type(error).__name__,
                message=str(error),
            )
            if events is not None:
                events.failure(
                    "runtime.failed",
                    operation=request.operation,
                    phase=phase,
                    error_type=failure.error_type,
                    error=failure.message,
                    runtime_seconds=elapsed,
                    output_artifact_ids=[record.artifact_id for record in outputs],
                )
            return RuntimeResult(
                operation=request.operation,
                context=request.context,
                status="failed",
                manifest_path=manifest_path,
                started_at_utc=_utc_text(started),
                finished_at_utc=_utc_text(finished),
                runtime_seconds=elapsed,
                inputs=inputs,
                outputs=tuple(outputs),
                failure=failure,
            )

        finished = _utc_moment(self.clock)
        elapsed = max(0.0, self.timer() - timer_started)
        if events is not None:
            events.event(
                "runtime.completed",
                operation=request.operation,
                runtime_seconds=elapsed,
                output_artifact_ids=[record.artifact_id for record in outputs],
            )
        return RuntimeResult(
            operation=request.operation,
            context=request.context,
            status="completed",
            manifest_path=manifest_path,
            started_at_utc=_utc_text(started),
            finished_at_utc=_utc_text(finished),
            runtime_seconds=elapsed,
            inputs=inputs,
            outputs=tuple(outputs),
            value=operation_result.value,
        )
