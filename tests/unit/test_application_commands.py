"""Public application command contracts, independent of CLI parsing and exit codes."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_gameweek_ops as gameweek_world

from squadopt.application import (
    DecideRequest,
    DecideResult,
    DecisionVerificationError,
    SettleRequest,
    SettleResult,
    TickRequest,
    decide,
    run_season_tick,
    settle,
)
from squadopt.application.build import recommendation_view_from_ledger
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.live import LedgerError, load_ledger
from squadopt.platform.cli import main as cli_main


@pytest.fixture(name="world")
def _world(tmp_path: Path) -> dict[str, Any]:
    snapshot_root = tmp_path / "snapshots"
    decide_metadata = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=gameweek_world.CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: gameweek_world._bootstrap(),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    finished = [
        dict(gameweek_world.EVENTS[0], finished=True, data_checked=True),
        gameweek_world.EVENTS[1],
    ]
    settle_metadata = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=gameweek_world.SETTLE_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: gameweek_world._bootstrap(
                events=finished,
                elements=gameweek_world._elements(event_points=3),
            ),
            FIXTURES_PAYLOAD: b"[]",
            live_payload(1): gameweek_world._live(3),
        },
    )
    return {
        "snapshot_root": snapshot_root,
        "ledger_root": tmp_path / "ledger",
        "archive_root": tmp_path / "archive",
        "decide_id": decide_metadata.snapshot_id,
        "settle_id": settle_metadata.snapshot_id,
        "summary": tmp_path / "season.md",
    }


def _decide_request(world: dict[str, Any]) -> DecideRequest:
    return DecideRequest(
        snapshot_root=world["snapshot_root"],
        snapshot_id=world["decide_id"],
        ledger_root=world["ledger_root"],
        archive_root=world["archive_root"],
    )


def test_missing_capture_names_an_existing_season_command(
    world: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    request = replace(_decide_request(world), snapshot_root=tmp_path / "empty", snapshot_id=None)
    with pytest.raises(DataError) as error:
        decide(request, panel_builder=lambda root: gameweek_world._panel())
    assert "squadopt season tick --dry-run" in str(error.value)
    assert "'squadopt season tick'" in str(error.value)
    with pytest.raises(SystemExit) as help_exit:
        cli_main(["season", "tick", "--help"])
    assert help_exit.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


def test_decide_returns_a_typed_result_and_every_published_output(world: dict[str, Any]) -> None:
    result = decide(_decide_request(world), panel_builder=lambda root: gameweek_world._panel())

    assert isinstance(result, DecideResult)
    assert (result.season, result.gameweek, result.snapshot_id) == (
        gameweek_world.SEASON,
        1,
        world["decide_id"],
    )
    assert {path.name for path in result.output_paths} == {
        "decision.json",
        "manifest.json",
        "projections.csv",
        "report.txt",
    }


@pytest.mark.parametrize("failure", ["none", "exception", "invalid_json", "nonfinite"])
def test_optional_shadow_cannot_change_or_block_the_verified_publication(
    world: dict[str, Any], failure: str
) -> None:
    request = _decide_request(world)
    baseline = decide(request, panel_builder=lambda root: gameweek_world._panel())
    calls = []

    def shadow(snapshot, projection):
        calls.append(snapshot.metadata.snapshot_id)
        projection.table.loc[:, "expected_points"] = 999.0
        if failure == "exception":
            raise ValueError("synthetic shadow failure")
        if failure == "invalid_json":
            return {"bad": {1, 2}}
        if failure == "nonfinite":
            return {"bad": float("nan")}
        return {"status": "NOT_READY", "internal_only": True, "published_decision_changed": False}

    measured = decide(
        replace(request, ledger_root=world["ledger_root"].parent / "shadow-ledger"),
        panel_builder=lambda root: gameweek_world._panel(),
        phase_e_shadow=shadow,
    )
    assert calls == [world["decide_id"]]
    for name in ("projections.csv", "report.txt"):
        assert (baseline.decision_directory / name).read_bytes() == (
            measured.decision_directory / name
        ).read_bytes()
    control = json.loads(
        (baseline.decision_directory / "decision.json").read_text(encoding="utf-8")
    )
    outcome = json.loads(
        (measured.decision_directory / "decision.json").read_text(encoding="utf-8")
    )
    diagnostic = outcome["metadata"].pop("phase_e_shadow")
    assert diagnostic["status"] == ("NOT_READY" if failure == "none" else "ERROR")
    assert outcome == control
    assert measured.report == baseline.report
    control_entry = load_ledger(request.ledger_root, baseline.season)[0]
    shadow_entry = load_ledger(world["ledger_root"].parent / "shadow-ledger", measured.season)[0]
    assert recommendation_view_from_ledger(control_entry) == recommendation_view_from_ledger(
        shadow_entry
    )


def test_verification_failure_is_typed_and_publishes_nothing(world: dict[str, Any]) -> None:
    with pytest.raises(DecisionVerificationError) as caught:
        decide(
            _decide_request(world),
            panel_builder=lambda root: gameweek_world._panel(),
            verifier=lambda recommendation, projection, held=None, **kw: ["synthetic refusal"],
        )

    assert caught.value.failures == ("synthetic refusal",)
    assert not world["ledger_root"].exists()


def test_settle_returns_the_outcome_and_regenerated_summary(world: dict[str, Any]) -> None:
    decide(_decide_request(world), panel_builder=lambda root: gameweek_world._panel())

    result = settle(
        SettleRequest(
            snapshot_root=world["snapshot_root"],
            snapshot_id=world["settle_id"],
            ledger_root=world["ledger_root"],
            summary_root=world["summary"].parent,
            gameweek=1,
            summary_output=world["summary"],
        )
    )

    assert isinstance(result, SettleResult)
    assert result.outcome_path.is_file()
    assert result.summary_path == world["summary"]
    assert "Settled gameweeks: 1" in result.summary


def _capture_after_the_next_deadline(world: dict[str, Any], *, holds_week_one: bool) -> str:
    """A capture on GW2: the bootstrap's event_points are GW2's running points, not GW1's."""

    events = [
        dict(gameweek_world.EVENTS[0], finished=True, data_checked=True, is_current=False),
        dict(gameweek_world.EVENTS[1], data_checked=False, is_current=True),
    ]
    payloads = {
        BOOTSTRAP_PAYLOAD: gameweek_world._bootstrap(
            events=events, elements=gameweek_world._elements(event_points=9)
        ),
        FIXTURES_PAYLOAD: b"[]",
        live_payload(2): gameweek_world._live(9),
    }
    if holds_week_one:
        payloads[live_payload(1)] = gameweek_world._live(3)
    metadata = write_snapshot(
        world["snapshot_root"],
        source="fpl-live",
        captured_at_utc="2026-08-29T09:00:00Z",
        payloads=payloads,
    )
    return metadata.snapshot_id


def _settle_week_one(world: dict[str, Any], snapshot_id: str | None) -> SettleResult:
    return settle(
        SettleRequest(
            snapshot_root=world["snapshot_root"],
            snapshot_id=snapshot_id,
            ledger_root=world["ledger_root"],
            summary_root=world["summary"].parent,
            gameweek=1,
            summary_output=world["summary"],
        )
    )


def test_a_late_settle_records_the_week_it_names_not_the_captures_current_week(
    world: dict[str, Any],
) -> None:
    decide(_decide_request(world), panel_builder=lambda root: gameweek_world._panel())
    late_id = _capture_after_the_next_deadline(world, holds_week_one=True)

    # No capture named: the newest is picked, and it is already on GW2.
    result = _settle_week_one(world, None)

    assert result.snapshot_id == late_id
    outcome = json.loads(result.outcome_path.read_text(encoding="utf-8"))
    # Every player scored 3 in GW1 (9 so far in GW2): eleven starters plus the captain again.
    assert outcome["realized_xi_score"] == pytest.approx(12 * 3.0)
    assert set(outcome["realized_points_by_player"].values()) == {3.0}
    assert outcome["source_snapshot_id"] == late_id


def test_a_capture_without_the_named_weeks_live_document_records_nothing(
    world: dict[str, Any],
) -> None:
    decide(_decide_request(world), panel_builder=lambda root: gameweek_world._panel())
    late_id = _capture_after_the_next_deadline(world, holds_week_one=False)

    with pytest.raises(LedgerError, match=r"holds no event-gw01-live\.json") as refused:
        _settle_week_one(world, late_id)

    assert late_id in str(refused.value)
    assert load_ledger(world["ledger_root"], gameweek_world.SEASON)[0].outcome is None


def test_tick_dry_run_needs_no_network_capture(tmp_path: Path) -> None:
    result = run_season_tick(
        TickRequest(
            snapshot_root=tmp_path / "snapshots",
            ledger_root=tmp_path / "ledger",
            archive_root=tmp_path / "archive",
            handoff_root=tmp_path / "handoffs",
            summary_root=tmp_path / "docs",
            now_utc="2026-08-21T15:00:00Z",
        ),
        panel_builder=lambda root: gameweek_world._panel(),
        dry_run=True,
    )

    assert result.dry_run
    assert result.action_count == 0
    assert result.final_plan.wants_capture
