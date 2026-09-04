"""Pinning the pre-season difficulty: what it refuses, what it records, what drift means.

Synthetic captures written into a temporary snapshot store — the point of these tests is the
provenance rules, not the football.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from squadopt.data.errors import SnapshotIntegrityError
from squadopt.data.snapshots import write_snapshot
from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.preseason_difficulty import (
    TEAM_STRENGTH_FIELDS,
    build_preseason_record,
    compare_to_later,
    drift_to_dict,
    record_to_dict,
    record_to_markdown,
)

FIRST_KICKOFF = "2026-08-21T19:00:00Z"
BEFORE = "2026-08-16T08:12:59Z"
AFTER = "2026-08-22T09:00:00Z"


def _bootstrap(*, strengths_populated: bool = False) -> bytes:
    teams = [
        {
            "id": index,
            "code": 100 + index,
            "name": f"Club {index}",
            **{
                field: ((1000 + index) if strengths_populated else 0)
                for field in TEAM_STRENGTH_FIELDS
            },
        }
        for index in (1, 2, 3, 4)
    ]
    events = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
        {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
    ]
    document = {"teams": teams, "events": events, "elements": []}
    return json.dumps(document).encode("utf-8")


def _fixtures(*, finished: bool = False, difficulty: tuple[int, int] = (2, 4)) -> bytes:
    home_difficulty, away_difficulty = difficulty
    records = [
        {
            "id": 1,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "team_h_difficulty": home_difficulty,
            "team_a_difficulty": away_difficulty,
            "kickoff_time": FIRST_KICKOFF,
            "finished": finished,
            "provisional_start_time": False,
        },
        {
            "id": 2,
            "event": 1,
            "team_h": 3,
            "team_a": 4,
            "team_h_difficulty": 3,
            "team_a_difficulty": 3,
            "kickoff_time": "2026-08-22T14:00:00Z",
            "finished": False,
            "provisional_start_time": False,
        },
    ]
    return json.dumps(records).encode("utf-8")


def _store(
    root: Path,
    *,
    captured_at: str = BEFORE,
    finished: bool = False,
    difficulty: tuple[int, int] = (2, 4),
    strengths_populated: bool = False,
) -> str:
    metadata = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={
            "bootstrap-static.json": _bootstrap(strengths_populated=strengths_populated),
            "fixtures.json": _fixtures(finished=finished, difficulty=difficulty),
        },
    )
    return metadata.snapshot_id


def test_a_capture_before_the_first_kickoff_is_recorded(tmp_path: Path) -> None:
    snapshot_id = _store(tmp_path)
    record = build_preseason_record(tmp_path, snapshot_id, season="2026-27")
    assert record.season == "2026-27"
    assert record.fixtures == 2
    assert record.clubs == 4
    assert record.captured_at_utc == BEFORE
    assert record.first_deadline_utc == "2026-08-21T17:30:00Z"
    assert len(record.difficulty) == 4
    assert record.diagnostics["sides_without_a_rating"] == 0
    assert float(record.diagnostics["hours_before_first_kickoff"]) > 100.0


def test_a_capture_taken_after_the_first_kickoff_is_refused(tmp_path: Path) -> None:
    """The refusal is the whole point: late evidence must not look like early evidence."""

    snapshot_id = _store(tmp_path, captured_at=AFTER)
    with pytest.raises(ExperimentExecutionError, match="at or after the first"):
        build_preseason_record(tmp_path, snapshot_id, season="2026-27")


def test_a_capture_carrying_a_played_fixture_is_refused(tmp_path: Path) -> None:
    snapshot_id = _store(tmp_path, captured_at="2026-08-20T09:00:00Z", finished=True)
    with pytest.raises(ExperimentExecutionError, match="not a pre-season capture"):
        build_preseason_record(tmp_path, snapshot_id, season="2026-27")


def test_a_missing_season_is_refused(tmp_path: Path) -> None:
    snapshot_id = _store(tmp_path)
    with pytest.raises(ExperimentConfigurationError, match="season"):
        build_preseason_record(tmp_path, snapshot_id, season="   ")


def test_an_edited_payload_is_caught_before_it_is_recorded(tmp_path: Path) -> None:
    """The snapshot store verifies checksums; the record inherits that protection."""

    snapshot_id = _store(tmp_path)
    payload = tmp_path / snapshot_id / "payloads" / "fixtures.json"
    payload.write_bytes(_fixtures(difficulty=(5, 5)))
    with pytest.raises(SnapshotIntegrityError):
        build_preseason_record(tmp_path, snapshot_id, season="2026-27")


def test_unpublished_strength_fields_are_counted_as_unpublished(tmp_path: Path) -> None:
    empty = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    populated_root = tmp_path / "populated"
    filled = build_preseason_record(
        populated_root,
        _store(populated_root, strengths_populated=True),
        season="2026-27",
    )
    assert all(
        count == 0 for count in dict(empty.diagnostics["team_strength_fields_populated"]).values()
    )
    assert all(
        count == 4 for count in dict(filled.diagnostics["team_strength_fields_populated"]).values()
    )


def test_an_identical_later_reading_shows_no_drift(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    drift = compare_to_later(record, record.difficulty)
    assert drift.unchanged is True
    assert drift.changed_rows == 0
    assert drift.compared_rows == 4
    assert drift.changed_share == 0.0


def test_a_revised_rating_is_reported_as_drift(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    later = record.difficulty.copy()
    later.loc[later["fixture_id"] == 1, "fixture_difficulty"] = 5
    drift = compare_to_later(record, later)
    assert drift.unchanged is False
    assert drift.changed_rows == 2
    assert drift.changed_share == pytest.approx(0.5)
    assert drift.mean_absolute_change > 0.0
    assert len(drift.examples) == 2


def test_a_fixture_absent_from_the_later_reading_is_counted_not_compared(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    later = record.difficulty.loc[record.difficulty["fixture_id"] == 1].copy()
    drift = compare_to_later(record, later)
    assert drift.compared_rows == 2
    assert drift.missing_rows == 2
    assert drift.changed_rows == 0


def test_a_later_table_without_the_columns_is_refused(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    with pytest.raises(ExperimentExecutionError, match="lacks columns"):
        compare_to_later(record, pd.DataFrame({"season": ["2026-27"]}))


def test_the_record_serializes_to_json_native_values(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    document = record_to_dict(record)
    round_tripped = json.loads(json.dumps(document))
    assert round_tripped["season"] == "2026-27"
    assert len(round_tripped["difficulty"]) == 4
    assert round_tripped["difficulty"][0]["fixture_difficulty"] in (2, 3, 4, 5)
    assert len(round_tripped["team_strength"]) == 4
    assert set(round_tripped["checksums"]) == {"bootstrap-static.json", "fixtures.json"}


def test_the_markdown_states_the_capture_and_the_drift(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    later = record.difficulty.copy()
    later.loc[later["fixture_id"] == 1, "fixture_difficulty"] = 5
    text = record_to_markdown(record, compare_to_later(record, later))
    assert record.snapshot_id in text
    assert "has moved" in text
    assert "2026-27" in text
    assert "no drift" not in text


def test_drift_serializes_to_json_native_values(tmp_path: Path) -> None:
    record = build_preseason_record(tmp_path, _store(tmp_path), season="2026-27")
    document = drift_to_dict(compare_to_later(record, record.difficulty))
    assert json.loads(json.dumps(document))["unchanged"] is True
