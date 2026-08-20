"""Contract tests for the installed, transport-only CLI."""

import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError
from squadopt.live.runlog import configure_run_logging
from squadopt.platform.cli import CliServices, main
from squadopt.platform.fpl_capture import fetch

COMMIT = "a" * 40
NOW = datetime(2026, 8, 21, 15, 30, tzinfo=UTC)


def _base(workspace: Path) -> list[str]:
    return [
        "season",
        "tick",
        "--workspace-root",
        str(workspace),
        "--repository-commit",
        COMMIT,
        "--now",
        "2026-08-21T15:30:00Z",
    ]


def test_dry_tick_binds_manifest_lineage_and_log_to_one_run(tmp_path: Path) -> None:
    workspace = tmp_path / "portable-workspace"
    workspace.mkdir()

    exit_code = main(
        [*_base(workspace), "--dry-run"],
        services=CliServices(clock=lambda: NOW),
    )

    assert exit_code == 0
    manifest_paths = list((workspace / "data" / "runtime" / "runs").glob("*/manifest.json"))
    assert len(manifest_paths) == 1
    manifest = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
    run_id = manifest["context"]["run_id"]
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (workspace / "data" / "runtime" / "registry" / "records").glob("*.json")
    ]
    assert records and {record["run_id"] for record in records} == {run_id}
    assert {record["role"] for record in records} == {"input"}
    log_path = next((workspace / "data" / "logs" / "season_tick").glob("*.jsonl"))
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert {event["run_id"] for event in events} == {run_id}
    assert {event["message"] for event in events} >= {
        "runtime.started",
        "runtime.completed",
        "tick.plan",
    }
    configure_run_logging("test", log_root=None, console=False)


def test_unexpected_application_failure_has_exit_code_two(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def crash(_: Path):
        raise RuntimeError("scheduler adapter broke")

    exit_code = main(
        [*_base(workspace), "--log-root", "-"],
        services=CliServices(capture=crash, clock=lambda: NOW),
    )

    assert exit_code == 2
    assert len(list((workspace / "data" / "runtime" / "runs").glob("*/manifest.json"))) == 1


def test_paths_cannot_escape_the_portable_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"

    exit_code = main(
        [*_base(workspace), "--snapshot-root", str(outside), "--dry-run", "--log-root", "-"],
        services=CliServices(clock=lambda: NOW),
    )

    assert exit_code == 1
    assert not (workspace / "data" / "runtime").exists()


def test_capture_network_failures_use_the_data_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unreachable(*_: object, **__: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)

    with pytest.raises(DataSourceError, match="Could not reach"):
        fetch("https://example.invalid/fpl")
