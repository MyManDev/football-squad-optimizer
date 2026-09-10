import json
from pathlib import Path

import pytest

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.platform.capture_measurement import availability_calibration, compare_captures, main


def capture(
    name: str,
    at: str,
    *,
    chance: int | None = 75,
    finished: bool = False,
    checked: bool = False,
    minutes: int = 0,
    year: int = 2026,
) -> CapturedSnapshot:
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": f"{year}-08-21T17:30:00Z",
                "finished": finished,
                "data_checked": checked,
            }
        ],
        "elements": [
            {
                "id": 123,
                "code": 456,
                "status": "d",
                "chance_of_playing_next_round": chance,
                "news": "Test",
                "news_added": None,
            }
        ],
    }
    payloads = {
        BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
        live_payload(1): json.dumps(
            {
                "elements": [
                    {
                        "id": 123,
                        "stats": {
                            "total_points": 2,
                            "minutes": minutes,
                            "starts": int(minutes > 0),
                        },
                    }
                ]
            }
        ).encode(),
    }
    return CapturedSnapshot(SnapshotMetadata(name, "fpl-live", at, "v1", {}, "x"), payloads)


def test_late_diff_keeps_unknown_distinct_from_zero_and_never_claims_gain() -> None:
    early = capture("early", "2026-08-19T12:00:00Z", chance=None)
    late = capture("late", "2026-08-21T12:00:00Z", chance=0)
    result = compare_captures(early, late, gameweek=1)
    assert result["changed"] == {
        "status": 0,
        "chance_of_playing_next_round": 1,
        "news": 0,
        "news_added": 0,
    }
    assert result["hours_before_deadline"] == 5.5
    assert result["decision_effect"] == "not_measured"


@pytest.mark.parametrize(
    "at", ["2026-08-21T17:30:00Z", "2026-08-20T12:00:00Z", "2026-08-18T12:00:00Z"]
)
def test_late_diff_refuses_deadline_leakage_and_wrong_order(at: str) -> None:
    with pytest.raises(DataError):
        compare_captures(capture("early", "2026-08-19T12:00:00Z"), capture("late", at), gameweek=1)


def test_calibration_requires_finished_and_checked_and_uses_persistent_identity() -> None:
    early = capture("early", "2026-08-19T12:00:00Z", chance=0)
    unchecked = capture("unchecked", "2026-08-22T12:00:00Z", finished=True, minutes=90)
    assert availability_calibration((early, unchecked), season="2026-27")["rows"] == []
    settled = capture("settled", "2026-08-23T12:00:00Z", finished=True, checked=True, minutes=90)
    result = availability_calibration((early, settled), season="2026-27")
    row = result["rows"][0]
    assert row["chance_of_playing_next_round"] == 0
    assert row["players"] == row["appearances"] == 1
    assert row["appearance_rate"] == 1.0
    assert row["unmatched_players_in_capture"] == 0


def test_calibration_keeps_repeated_captures_separate() -> None:
    captures = (
        capture("early", "2026-08-19T12:00:00Z"),
        capture("late", "2026-08-21T12:00:00Z", chance=100),
        capture("settled", "2026-08-23T12:00:00Z", finished=True, checked=True),
    )
    result = availability_calibration(captures, season="2026-27")
    assert result["unit"] == "player_capture"
    assert {row["snapshot_id"] for row in result["rows"]} == {"early", "late"}
    assert all(row["appearances"] == 0 for row in result["rows"])


def test_other_season_does_not_settle_same_gameweek() -> None:
    result = availability_calibration(
        (
            capture("early", "2026-08-19T12:00:00Z"),
            capture("other", "2025-08-23T12:00:00Z", year=2025, finished=True, checked=True),
        ),
        season="2026-27",
    )
    assert result["rows"] == []


def test_empty_archive_reports_no_observations(tmp_path: Path) -> None:
    out = tmp_path / "audit.json"
    assert (
        main(
            [
                "--snapshot-root",
                str(tmp_path / "snapshots"),
                "--season",
                "2026-27",
                "--out",
                str(out),
            ]
        )
        == 0
    )
    assert json.loads(out.read_text())["rows"] == []
