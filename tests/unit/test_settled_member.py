"""Actual contributions follow settled official multipliers, never a forecast or guessed XI."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.application.settled_member import ActualMemberDetails
from squadopt.application.weekly_suggestion_eval import _actual_member_details
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot

DEADLINE = "2026-09-12T10:00:00Z"


def capture(root: Path) -> CapturedSnapshot:
    def move(incoming: int, outgoing: int) -> dict[str, Any]:
        return {
            "entry": 101,
            "event": 4,
            "element_in": incoming,
            "element_out": outgoing,
            "element_in_cost": 50,
            "element_out_cost": 50,
            "time": "2026-09-11T09:00:00Z",
        }

    payloads = {
        "bootstrap-static.json": {
            "events": [
                {"id": 4, "deadline_time": DEADLINE, "finished": True, "data_checked": True}
            ],
            "elements": [
                {"id": i, "code": 100 + i, "web_name": f"Player {i}"} for i in range(1, 18)
            ],
        },
        "entry-101-picks-gw04.json": {
            "entry_history": {"event": 4},
            "picks": [
                {
                    "element": i,
                    "position": i,
                    "is_captain": i == 1,
                    "is_vice_captain": i == 2,
                    "multiplier": 2 if i == 1 else int(i <= 11),
                }
                for i in range(1, 16)
            ],
        },
        "entry-101-transfers.json": [move(1, 16), move(3, 17)],
    }
    meta = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc="2026-09-15T09:00:00Z",
        payloads={key: json.dumps(value).encode() for key, value in payloads.items()},
    )
    return read_snapshot(root, meta.snapshot_id)


def changed(snapshot: CapturedSnapshot, key: str, change: Any) -> CapturedSnapshot:
    payloads = dict(snapshot.payloads)
    value = json.loads(payloads[key])
    change(value)
    payloads[key] = json.dumps(value).encode()
    return replace(snapshot, payloads=payloads)


def read(snapshot: CapturedSnapshot, gross: float = 24) -> ActualMemberDetails:
    return _actual_member_details(
        snapshot,
        pd.DataFrame({"player_id": range(101, 118), "total_points": 2}),
        entry_id=101,
        gameweek=4,
        deadline_utc=DEADLINE,
        gross_points=gross,
    )


def test_two_transfers_count_actual_points_with_the_captain_multiplier(tmp_path: Path) -> None:
    result = read(capture(tmp_path))
    assert result.captain.player_id == 101
    assert result.captain.counted_points == 4
    assert [
        (row.player_out, row.player_in.name, row.player_in.counted_points)
        for row in result.transfers
    ] == [
        ("Player 16", "Player 1", 4),
        ("Player 17", "Player 3", 2),
    ]


def test_the_official_scoring_vice_is_the_realized_captain(tmp_path: Path) -> None:
    def fallback(document: Any) -> None:
        document["picks"][0]["multiplier"] = 0
        document["picks"][1]["multiplier"] = 2

    snapshot = changed(capture(tmp_path), "entry-101-picks-gw04.json", fallback)
    result = read(snapshot, gross=22)
    assert result.captain.player_id == 102
    assert result.captain.counted_points == 4
    assert result.transfers[0].player_in.counted_points == 0


def test_a_player_bought_twice_only_counts_on_the_last_acquisition(tmp_path: Path) -> None:
    def rebuy(rows: Any) -> None:
        rows.append({**rows[0], "time": "2026-09-11T10:00:00Z"})

    snapshot = changed(capture(tmp_path), "entry-101-transfers.json", rebuy)
    assert [row.player_in.counted_points for row in read(snapshot).transfers] == [0, 2, 4]


@pytest.mark.parametrize("field", ["finished", "data_checked"])
def test_an_unsettled_week_never_produces_report_values(tmp_path: Path, field: str) -> None:
    snapshot = changed(
        capture(tmp_path),
        "bootstrap-static.json",
        lambda data: data["events"][0].update({field: False}),
    )
    with pytest.raises(DataError, match="settled"):
        read(snapshot)


def test_inconsistent_gross_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="reproduce"):
        read(capture(tmp_path), gross=25)


@pytest.mark.parametrize("multiplier", [True, 4, -1, None])
def test_invalid_official_multipliers_are_refused(tmp_path: Path, multiplier: Any) -> None:
    snapshot = changed(
        capture(tmp_path),
        "entry-101-picks-gw04.json",
        lambda data: data["picks"][0].update(multiplier=multiplier),
    )
    with pytest.raises(DataError, match="multipliers"):
        read(snapshot)


def test_a_transfer_after_the_week_deadline_is_refused(tmp_path: Path) -> None:
    snapshot = changed(
        capture(tmp_path), "entry-101-transfers.json", lambda rows: rows[0].update(time=DEADLINE)
    )
    with pytest.raises(DataError, match="deadline"):
        read(snapshot)
