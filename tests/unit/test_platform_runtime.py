"""Shared runtime orchestration across manifest, artifacts, logging and application."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from squadopt.application import UI_VIEW_CONTRACT_VERSION, write_ui_view_schema
from squadopt.live.runlog import configure_run_logging
from squadopt.platform import (
    FileArtifactRegistry,
    RuntimeArtifact,
    RuntimeContractError,
    RuntimeInputArtifact,
    RuntimeOperationResult,
    RuntimePreparationError,
    RuntimeRequest,
    RuntimeRunner,
    read_run_manifest,
)
from squadopt.platform.context import RunContext

NOW = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _context(
    *,
    run_id: str = "runtime-gw01",
    input_fingerprints: dict[str, str] | None = None,
) -> RunContext:
    return RunContext.create(
        repository_commit="a" * 40,
        configuration_fingerprint="b" * 64,
        input_fingerprints=(
            {"config": "c" * 64} if input_fingerprints is None else input_fingerprints
        ),
        component_versions={"application": UI_VIEW_CONTRACT_VERSION},
        deterministic_seed=42,
        run_id=run_id,
        now=NOW,
    )


def _runner(tmp_path: Path) -> tuple[RuntimeRunner, FileArtifactRegistry, Path]:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    registry = FileArtifactRegistry(tmp_path / "registry", artifact_root=artifact_root)
    return (
        RuntimeRunner(
            registry,
            tmp_path / "runs",
            clock=lambda: NOW,
            timer=iter((10.0, 10.25)).__next__,
        ),
        registry,
        artifact_root,
    )


def _request(artifact_root: Path, *, operation: str, run_id: str) -> RuntimeRequest:
    content = f'{{"run_id":"{run_id}"}}\n'.encode()
    path = artifact_root / "inputs" / f"{run_id}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    context = _context(
        run_id=run_id,
        input_fingerprints={"request": _digest(content)},
    )
    return RuntimeRequest(
        operation=operation,
        context=context,
        inputs=(RuntimeInputArtifact(path, "request", "request_v1", "request"),),
    )


def test_runtime_unifies_public_application_manifest_lineage_and_log(tmp_path: Path) -> None:
    runner, registry, artifact_root = _runner(tmp_path)
    config_path = artifact_root / "inputs" / "site.json"
    config_path.parent.mkdir()
    config_path.write_bytes(b'{"season":"2026-27"}\n')
    output_path = artifact_root / "outputs" / "ui-schema.json"
    context = _context(input_fingerprints={"site_config": _digest(config_path.read_bytes())})
    request = RuntimeRequest(
        operation="site.build",
        context=context,
        inputs=(
            RuntimeInputArtifact(
                config_path,
                "config",
                "site_config_v1",
                "site_config",
            ),
        ),
    )
    log = configure_run_logging(
        "platform_runtime",
        log_root=tmp_path / "logs",
        run_id=context.run_id,
        console=False,
    )

    def build_application_output() -> RuntimeOperationResult[Path]:
        written = write_ui_view_schema(output_path)
        return RuntimeOperationResult(
            value=written,
            outputs=(RuntimeArtifact(written, "ui_view_schema", UI_VIEW_CONTRACT_VERSION),),
        )

    result = runner.execute(request, build_application_output, events=log)

    assert result.completed and result.status == "completed"
    assert result.value == output_path
    assert result.failure is None
    assert result.runtime_seconds == pytest.approx(0.25)
    assert result.started_at_utc == result.finished_at_utc == "2026-08-19T15:00:00Z"
    assert read_run_manifest(result.manifest_path) == context
    assert result.manifest_path == (tmp_path / "runs" / context.run_id / "manifest.json")

    lineage = registry.lineage(context.run_id, verify=True)
    assert lineage == registry.lineage(context.run_id)
    assert [record.kind for record in lineage.inputs] == ["config"]
    assert [record.kind for record in lineage.outputs] == ["ui_view_schema"]
    assert lineage.inputs == result.inputs
    assert lineage.outputs == result.outputs
    assert lineage.inputs[0].checksum == _digest(config_path.read_bytes())

    assert log.log_path is not None
    events = [json.loads(line) for line in log.log_path.read_text("utf-8").splitlines()]
    assert [event["message"] for event in events] == [
        "runtime.started",
        "runtime.completed",
    ]
    assert {event["run_id"] for event in events} == {context.run_id}
    assert events[0]["fields"]["input_artifact_ids"] == [lineage.inputs[0].artifact_id]
    assert events[1]["fields"]["output_artifact_ids"] == [lineage.outputs[0].artifact_id]


def test_application_exception_becomes_a_failed_terminal_result(tmp_path: Path) -> None:
    runner, registry, artifact_root = _runner(tmp_path)
    request = _request(
        artifact_root,
        operation="gameweek.decide",
        run_id="runtime-failure",
    )
    context = request.context
    log = configure_run_logging(
        "platform_runtime",
        log_root=tmp_path / "logs",
        run_id=context.run_id,
        console=False,
    )

    def fail() -> RuntimeOperationResult[None]:
        raise LookupError("application could not resolve the snapshot")

    result = runner.execute(request, fail, events=log)

    assert not result.completed and result.status == "failed"
    assert result.value is None and result.outputs == ()
    assert result.failure is not None
    assert result.failure.phase == "application"
    assert result.failure.error_type == "LookupError"
    assert result.failure.message == "application could not resolve the snapshot"
    assert read_run_manifest(result.manifest_path) == context
    assert registry.lineage(context.run_id).outputs == ()

    assert log.log_path is not None
    events = [json.loads(line) for line in log.log_path.read_text("utf-8").splitlines()]
    assert [event["message"] for event in events] == ["runtime.started", "runtime.failed"]
    assert events[-1]["fields"]["phase"] == "application"
    assert events[-1]["fields"]["error_type"] == "LookupError"
    assert "LookupError" in events[-1]["exception"]


def test_output_registration_failure_is_recorded_without_exposing_value(tmp_path: Path) -> None:
    runner, _, artifact_root = _runner(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")

    result = runner.execute(
        _request(
            artifact_root,
            operation="site.build",
            run_id="runtime-bad-output",
        ),
        lambda: RuntimeOperationResult(
            value="must-not-escape",
            outputs=(RuntimeArtifact(outside, "decision", "decision_v1"),),
        ),
    )

    assert result.status == "failed" and result.value is None
    assert result.failure is not None
    assert result.failure.phase == "outputs"
    assert result.failure.error_type == "ArtifactRegistryError"
    assert "outside artifact_root" in result.failure.message


def test_preparation_failure_raises_before_the_application_starts(tmp_path: Path) -> None:
    runner, _, artifact_root = _runner(tmp_path)
    called = False

    def operation() -> RuntimeOperationResult[None]:
        nonlocal called
        called = True
        return RuntimeOperationResult(value=None)

    context = _context(run_id="runtime-missing-input")
    request = RuntimeRequest(
        operation="gameweek.decide",
        context=context,
        inputs=(
            RuntimeInputArtifact(
                artifact_root / "missing.json",
                "snapshot",
                "snapshot_v1",
                "config",
            ),
        ),
    )

    with pytest.raises(RuntimePreparationError, match="does not exist"):
        runner.execute(request, operation)

    assert not called
    assert not (tmp_path / "runs" / context.run_id / "manifest.json").exists()


def test_input_bytes_must_match_the_run_context_fingerprint(tmp_path: Path) -> None:
    runner, registry, artifact_root = _runner(tmp_path)
    request = _request(
        artifact_root,
        operation="gameweek.decide",
        run_id="runtime-changed-input",
    )
    request.inputs[0].path.write_text('{"changed":true}\n', encoding="utf-8")

    with pytest.raises(RuntimePreparationError, match="does not match RunContext"):
        runner.execute(request, lambda: RuntimeOperationResult(value=None))

    assert registry.lineage(request.context.run_id).inputs == ()
    assert not (tmp_path / "runs" / request.context.run_id / "manifest.json").exists()


def test_event_sink_must_share_the_context_run_id(tmp_path: Path) -> None:
    runner, _, artifact_root = _runner(tmp_path)
    request = _request(artifact_root, operation="site.build", run_id="runtime-gw01")
    mismatched = configure_run_logging(
        "platform_runtime",
        log_root=None,
        run_id="another-run",
        console=False,
    )

    with pytest.raises(RuntimeContractError, match="must match"):
        runner.execute(request, lambda: RuntimeOperationResult(value=None), events=mismatched)

    assert not (tmp_path / "runs" / request.context.run_id / "manifest.json").exists()


def test_exact_retry_is_idempotent_across_manifest_and_artifact_records(tmp_path: Path) -> None:
    runner, registry, artifact_root = _runner(tmp_path)
    output = artifact_root / "outputs" / "decision.json"
    output.parent.mkdir()
    output.write_text('{"captain":123}\n', encoding="utf-8")
    request = _request(
        artifact_root,
        operation="gameweek.decide",
        run_id="runtime-retry",
    )

    def operation() -> RuntimeOperationResult[str]:
        return RuntimeOperationResult(
            value="decision",
            outputs=(RuntimeArtifact(output, "decision", "decision_v1"),),
        )

    first = runner.execute(request, operation)
    runner.timer = iter((20.0, 20.5)).__next__
    retry = runner.execute(request, operation)

    assert retry.status == "completed" and retry.value == "decision"
    assert retry.outputs == first.outputs
    assert retry.manifest_path.read_bytes() == first.manifest_path.read_bytes()
    assert registry.lineage(request.context.run_id).outputs == first.outputs


def test_runtime_contract_rejects_ambiguous_values() -> None:
    artifact = RuntimeInputArtifact(
        Path("input.json"),
        "snapshot",
        "snapshot_v1",
        "config",
    )
    with pytest.raises(RuntimeContractError, match="operation"):
        RuntimeRequest(operation="Gameweek Decide", context=_context(), inputs=(artifact,))
    with pytest.raises(RuntimeContractError, match="repeats"):
        RuntimeRequest(operation="gameweek.decide", context=_context(), inputs=(artifact, artifact))
    with pytest.raises(RuntimeContractError, match="resolve every"):
        RuntimeRequest(
            operation="gameweek.decide",
            context=_context(input_fingerprints={"snapshot": "c" * 64}),
            inputs=(artifact,),
        )
    with pytest.raises(RuntimeContractError, match="schema_version"):
        RuntimeArtifact(Path("output.json"), "decision", "Decision V1")


def test_operation_must_return_the_runtime_envelope(tmp_path: Path) -> None:
    runner, _, artifact_root = _runner(tmp_path)
    result = runner.execute(
        _request(
            artifact_root,
            operation="site.build",
            run_id="runtime-bad-return",
        ),
        lambda: "bare application value",  # type: ignore[arg-type,return-value]
    )

    assert result.status == "failed"
    assert result.failure is not None
    assert result.failure.phase == "application"
    assert result.failure.error_type == "RuntimeContractError"
