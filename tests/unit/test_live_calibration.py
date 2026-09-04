"""Tests for live calibration measured from settled season-ledger entries.

The live series is the season's real out-of-sample evidence, so the arithmetic has
to be checkable by hand: known event points against known frozen projections, with
the settle capture re-read from the immutable snapshot store. Refusals matter as
much as numbers — no settled gameweek, or a missing capture, is not a report.
"""

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live import (
    LIVE_CALIBRATION_CONTRACT_VERSION,
    LiveCalibrationError,
    Recommendation,
    build_recommendation,
    calibration_markdown,
    measure_live_calibration,
    project,
    read_inputs,
    record_decision,
    record_outcome,
)
from squadopt.live.ledger import extract_event_points

SEASON = "2026-27"
HISTORY_SEASON = "2025-26"
CAPTURED_AT = "2026-08-13T20:11:43Z"
SETTLE_CAPTURED_AT = "2026-08-24T09:00:00Z"

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
]
TEAMS: list[dict[str, Any]] = [
    {"id": index, "code": index * 3, "name": f"Club {index}", "short_name": f"C{index}"}
    for index in range(1, 7)
]
SHAPE: list[tuple[int, int]] = [(1, 3), (2, 8), (3, 8), (4, 5)]
EVENT_POINTS = 3


def _elements(event_points: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    code = 1000
    for element_type, count in SHAPE:
        for index in range(count):
            code += 1
            record: dict[str, Any] = {
                "code": code,
                "id": code - 1000,
                "first_name": "Player",
                "second_name": f"{code}",
                "team": (index % 6) + 1,
                "element_type": element_type,
                "now_cost": 45 + (index % 4) * 5,
                "status": "a",
                "chance_of_playing_next_round": None,
                "news": "",
                "news_added": None,
            }
            if event_points is not None:
                record["event_points"] = event_points
            records.append(record)
    return records


def _bootstrap(**overrides: Any) -> bytes:
    document: dict[str, Any] = {
        "events": EVENTS,
        "teams": TEAMS,
        "elements": _elements(),
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


def _panel() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for code in (1001, 1004, 1012):
        for gameweek in range(1, 11):
            rows.append(
                {
                    "season": HISTORY_SEASON,
                    "gameweek": gameweek,
                    "player_id": code,
                    "name": f"Player {code}",
                    "team_id": "Club 1",
                    "position": "MID",
                    "price_tenths": 50,
                    "minutes": 90,
                    "total_points": 5,
                }
            )
    return pd.DataFrame(rows)


def _residuals(spread: float) -> pd.DataFrame:
    """A symmetric residual history: quantile offsets land near +/- spread."""

    rows: list[dict[str, Any]] = []
    for position in ("GK", "DEF", "MID", "FWD"):
        for index in range(200):
            rows.append(
                {
                    "fold_id": f"f{index}",
                    "season": HISTORY_SEASON,
                    "gameweek": (index % 30) + 2,
                    "player_id": 1001 + index,
                    "team_id": "Club 1",
                    "position": position,
                    "predicted_points": 3.0,
                    "realized_points": 3.0,
                    "residual": spread * ((index % 21) - 10) / 10.0,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture(name="settled_world")
def _settled_world(tmp_path: Path) -> dict[str, Any]:
    """One decided and settled gameweek with its captures retained."""

    snapshot_root = tmp_path / "snapshots"
    decide_meta = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: _bootstrap(), FIXTURES_PAYLOAD: b"[]"},
    )
    finished = [dict(EVENTS[0], finished=True), EVENTS[1]]
    settle_meta = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=SETTLE_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: _bootstrap(
                events=finished, elements=_elements(event_points=EVENT_POINTS)
            ),
            FIXTURES_PAYLOAD: b"[]",
        },
    )
    snapshot = read_snapshot(snapshot_root, decide_meta.snapshot_id)
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel())
    recommendation = build_recommendation(inputs, projection)

    ledger_root = tmp_path / "ledger"
    record_decision(ledger_root, recommendation, projection, report_text="report")
    settle_snapshot = read_snapshot(snapshot_root, settle_meta.snapshot_id)
    points = extract_event_points(settle_snapshot, gameweek=1)
    record_outcome(ledger_root, SEASON, 1, points, source_snapshot_id=settle_meta.snapshot_id)
    return {
        "ledger_root": ledger_root,
        "snapshot_root": snapshot_root,
        "recommendation": recommendation,
        "projection": projection,
        "settle_id": settle_meta.snapshot_id,
    }


# --- the arithmetic ----------------------------------------------------------


def test_the_live_series_is_computed_from_frozen_projections(
    settled_world: dict[str, Any],
) -> None:
    recommendation: Recommendation = settled_world["recommendation"]

    result = measure_live_calibration(
        settled_world["ledger_root"], SEASON, snapshot_root=settled_world["snapshot_root"]
    )

    assert result.settled_gameweeks == 1
    row = result.rows[0]
    assert row.gameweek == 1
    assert row.source_snapshot_id == settled_world["settle_id"]
    # Every player scored EVENT_POINTS, so the realized XI is 11 starters plus the
    # captain counted again.
    assert row.realized_xi_score == pytest.approx(12 * EVENT_POINTS)
    assert row.xi_error == pytest.approx(12 * EVENT_POINTS - recommendation.projected_score)
    expected_starter_gap = float(
        (EVENT_POINTS - recommendation.starting_xi["expected_points"]).mean()
    )
    assert row.xi_optimism_per_starter == pytest.approx(expected_starter_gap)
    captain_expected = float(recommendation.captain["expected_points"])
    assert row.captain_optimism == pytest.approx(EVENT_POINTS - captain_expected)
    table = settled_world["projection"].table
    assert row.roster_players_scored == len(table)
    assert row.roster_mean_error == pytest.approx(
        float((EVENT_POINTS - table["expected_points"]).mean())
    )
    assert row.roster_mae == pytest.approx(
        float((EVENT_POINTS - table["expected_points"]).abs().mean())
    )
    assert result.interval_rule is None


def test_wide_intervals_cover_and_narrow_intervals_do_not(
    settled_world: dict[str, Any],
) -> None:
    wide = measure_live_calibration(
        settled_world["ledger_root"],
        SEASON,
        snapshot_root=settled_world["snapshot_root"],
        residual_history=_residuals(spread=50.0),
    )
    narrow = measure_live_calibration(
        settled_world["ledger_root"],
        SEASON,
        snapshot_root=settled_world["snapshot_root"],
        residual_history=_residuals(spread=0.001),
    )

    assert wide.interval_live_coverage == pytest.approx(1.0)
    assert narrow.interval_live_coverage is not None
    assert narrow.interval_live_coverage < 0.5
    assert wide.interval_nominal_coverage == pytest.approx(0.90)


# --- refusals ----------------------------------------------------------------


def test_no_settled_gameweek_means_no_report(tmp_path: Path) -> None:
    with pytest.raises(LiveCalibrationError, match="No settled gameweeks"):
        measure_live_calibration(tmp_path / "ledger", SEASON, snapshot_root=tmp_path / "snapshots")


def test_a_missing_settle_capture_is_refused(settled_world: dict[str, Any]) -> None:
    with pytest.raises(LiveCalibrationError, match="not readable"):
        measure_live_calibration(
            settled_world["ledger_root"],
            SEASON,
            snapshot_root=settled_world["snapshot_root"].parent / "elsewhere",
        )


def test_a_malformed_residual_history_is_refused(settled_world: dict[str, Any]) -> None:
    with pytest.raises(LiveCalibrationError, match="position"):
        measure_live_calibration(
            settled_world["ledger_root"],
            SEASON,
            snapshot_root=settled_world["snapshot_root"],
            residual_history=pd.DataFrame({"residual": [0.1, -0.1]}),
        )


# --- the report --------------------------------------------------------------


def test_the_markdown_states_contract_references_and_sample_caution(
    settled_world: dict[str, Any],
) -> None:
    result = measure_live_calibration(
        settled_world["ledger_root"],
        SEASON,
        snapshot_root=settled_world["snapshot_root"],
        residual_history=_residuals(spread=50.0),
    )

    markdown = calibration_markdown(result)

    assert LIVE_CALIBRATION_CONTRACT_VERSION in markdown
    assert "vs historical -2.96" in markdown
    assert "small sample" in markdown
    assert "empirical_position_residual_interval_v1" in markdown


def test_the_cli_writes_the_report_pair(
    settled_world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import scripts.run_live_calibration as cli

    json_output = tmp_path / "docs" / "live_calibration_gw01.json"
    markdown_output = tmp_path / "docs" / "live_calibration_gw01.md"
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_live_calibration",
            "--season",
            SEASON,
            "--ledger-root",
            str(settled_world["ledger_root"]),
            "--snapshot-root",
            str(settled_world["snapshot_root"]),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ],
    )

    assert cli.main() == 0
    document = json.loads(json_output.read_text(encoding="utf-8"))
    assert document["contract_version"] == LIVE_CALIBRATION_CONTRACT_VERSION
    assert document["settled_gameweeks"] == 1
    assert document["automatic_promotion"] is False
    assert LIVE_CALIBRATION_CONTRACT_VERSION in markdown_output.read_text(encoding="utf-8")


def test_the_cli_refuses_an_unsettled_season(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import scripts.run_live_calibration as cli

    monkeypatch.setattr(
        "sys.argv",
        [
            "run_live_calibration",
            "--season",
            SEASON,
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--snapshot-root",
            str(tmp_path / "snapshots"),
        ],
    )

    assert cli.main() == 1
