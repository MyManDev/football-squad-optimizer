"""The roll command and its CLI: the capture supplies the season's rules and the deadline
being rolled through, and is refused if it was taken before that deadline."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_gameweek_ops import CAPTURED_AT, EVENTS, SEASON, _bootstrap, _panel

from squadopt.application import DecideRequest, RollRequest, decide, roll
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import load_entry, read_season_rules
from squadopt.live.runlog import configure_run_logging
from squadopt.platform.cli import EXIT_KNOWN_FAILURE, EXIT_OK, CliServices, main

COMMIT = "a" * 40
NOW = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)
AFTER_GW2 = "2026-09-01T10:00:00Z"


@pytest.fixture(name="world")
def _world(tmp_path: Path) -> dict[str, Any]:
    """An opening decision in the ledger, plus a capture taken after GW2's deadline."""

    snapshot_root = tmp_path / "data" / "snapshots"
    ledger_root = tmp_path / "data" / "ledger"
    opening = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: b"[]"},
    )
    finished = [dict(EVENTS[0], finished=True), dict(EVENTS[1], finished=True)]
    later = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=AFTER_GW2,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(events=finished), FIXTURES_PAYLOAD: b"[]"},
    )
    decide(
        DecideRequest(
            snapshot_root=snapshot_root,
            ledger_root=ledger_root,
            archive_root=tmp_path / "archive",
            snapshot_id=opening.snapshot_id,
        ),
        panel_builder=lambda root: _panel(),
    )
    return {
        "workspace": tmp_path,
        "snapshot_root": snapshot_root,
        "ledger_root": ledger_root,
        "summary_root": tmp_path / "docs",
        "opening_id": opening.snapshot_id,
        "later_id": later.snapshot_id,
    }


def _request(world: dict[str, Any], gameweek: int, snapshot_id: str) -> RollRequest:
    return RollRequest(
        snapshot_root=world["snapshot_root"],
        ledger_root=world["ledger_root"],
        summary_root=world["summary_root"],
        gameweek=gameweek,
        reason="no run happened that week",
        snapshot_id=snapshot_id,
        recorded_at_utc="2026-09-16T12:00:00Z",
    )


def test_roll_reads_the_cap_and_the_deadline_from_the_capture(world: dict[str, Any]) -> None:
    result = roll(_request(world, 2, world["later_id"]))

    rules = read_season_rules(
        read_snapshot(world["snapshot_root"], world["later_id"]), season=SEASON
    )
    entry = load_entry(world["ledger_root"], SEASON, 2)
    block = entry.decision["transfers"]
    assert isinstance(block, dict)
    assert block["max_free_transfers"] == rules.transfers.max_free_transfers == 5
    assert block["free_transfers_after"] == 2
    assert entry.decision["deadline_utc"] == EVENTS[1]["deadline_time"]
    metadata = entry.decision["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["rules_snapshot_id"] == world["later_id"]
    assert metadata["season_rules_fingerprint"] == rules.fingerprint
    assert metadata["ops_phase"] == "roll"

    assert result.season == SEASON and result.gameweek == 2
    assert result.deadline_utc == EVENTS[1]["deadline_time"]
    assert result.rules_snapshot_id == world["later_id"]
    assert "no-transfer roll" in result.report
    summary_path = world["summary_root"] / f"season_ledger_{SEASON}.md"
    assert result.summary_path == summary_path
    assert "| 2 | - | roll |" in summary_path.read_text(encoding="utf-8")
    assert result.decision_directory / "decision.json" in result.output_paths
    assert summary_path in result.output_paths


def test_a_capture_taken_before_the_deadline_is_refused(world: dict[str, Any]) -> None:
    with pytest.raises(DataError, match="has not passed"):
        roll(_request(world, 2, world["opening_id"]))

    assert not (world["ledger_root"] / SEASON / "gw02").exists()


def test_a_gameweek_the_capture_does_not_list_is_refused(world: dict[str, Any]) -> None:
    with pytest.raises(DataError, match="lists no gameweek 3"):
        roll(_request(world, 3, world["later_id"]))


def test_a_request_without_a_reason_is_refused(world: dict[str, Any]) -> None:
    with pytest.raises(DataError, match="reason"):
        RollRequest(
            snapshot_root=world["snapshot_root"],
            ledger_root=world["ledger_root"],
            summary_root=world["summary_root"],
            gameweek=2,
            reason="   ",
        )


def test_the_cli_records_a_roll_under_the_runtime(world: dict[str, Any]) -> None:
    workspace: Path = world["workspace"]
    argv = [
        "gameweek",
        "roll",
        "--workspace-root",
        str(workspace),
        "--repository-commit",
        COMMIT,
        "--gameweek",
        "2",
        "--reason",
        "catch-up: the runner was not built yet",
        "--snapshot-id",
        world["later_id"],
    ]
    try:
        exit_code = main(argv, services=CliServices(clock=lambda: NOW))

        assert exit_code == EXIT_OK
        entry = load_entry(world["ledger_root"], SEASON, 2)
        metadata = entry.decision["metadata"]
        assert isinstance(metadata, dict)
        assert metadata["recorded_at_utc"] == "2026-09-16T12:00:00Z"
        assert metadata["reason"] == "catch-up: the runner was not built yet"
        assert (workspace / "docs" / f"season_ledger_{SEASON}.md").is_file()
        manifests = list((workspace / "data" / "runtime" / "runs").glob("*/manifest.json"))
        assert len(manifests) == 1
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
        assert manifest["context"]["repository_commit"] == COMMIT
        assert (workspace / "data" / "logs" / "gameweek_roll").is_dir()

        # The second attempt is the create-once refusal, reported as a known failure.
        assert main(argv, services=CliServices(clock=lambda: NOW)) == EXIT_KNOWN_FAILURE
    finally:
        configure_run_logging("test", log_root=None, console=False)
