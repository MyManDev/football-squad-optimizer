import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard_history import settled_scoreboard_entries
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.live import LedgerEntry


def capture(
    name: str, at: str, *, checked: bool = True, year: int = 2026, bonus: int = 0
) -> CapturedSnapshot:
    _, _, outcomes = decision_inputs()
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": f"{year}-08-21T17:30:00Z",
                "finished": True,
                "data_checked": checked,
            }
        ],
        "elements": [{"id": player + 100, "code": player} for player in range(1, 16)],
    }
    live = {
        "elements": [
            {
                "id": int(row.player_id) + 100,
                "stats": {
                    "minutes": int(row.minutes),
                    "total_points": int(row.total_points) + bonus,
                    "starts": 0,
                },
            }
            for row in outcomes.itertuples()
        ]
    }
    return CapturedSnapshot(
        SnapshotMetadata(name, "fpl-live", at, "v1", {}, "test"),
        {
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            live_payload(1): json.dumps(live).encode(),
        },
    )


def entry_at(path: Path, outcome: dict[str, Any] | None = None) -> LedgerEntry:
    decision, projections, _ = decision_inputs()
    projections.to_csv(path / "projections.csv", index=False)
    return LedgerEntry("2026-27", 1, decision, outcome, path)


def test_latest_checked_capture_at_cutoff_is_used_without_mutating_ledger(tmp_path: Path) -> None:
    entry = entry_at(tmp_path)
    before = (tmp_path / "projections.csv").read_bytes()
    sources = [
        capture("new", "2026-08-24T12:00:00Z", bonus=1),
        capture("old", "2026-08-23T12:00:00Z"),
        capture("future", "2026-08-25T12:00:00Z", bonus=10),
    ]
    result = settled_scoreboard_entries(
        (entry,), iter(sources), season="2026-27", as_of_utc="2026-08-24T12:00:00Z"
    )
    assert result[0].outcome["source_snapshot_id"] == "new"
    assert result[0].outcome["realized_net_score"] == 93
    assert entry.outcome is None
    assert not (tmp_path / "outcome.json").exists()
    assert (tmp_path / "projections.csv").read_bytes() == before


@pytest.mark.parametrize(
    "source",
    [
        capture("unchecked", "2026-08-23T12:00:00Z", checked=False),
        capture("other-season", "2025-08-23T12:00:00Z", year=2025),
        capture("predeadline", "2026-08-21T12:00:00Z"),
        capture("future", "2026-08-25T12:00:00Z"),
    ],
)
def test_ineligible_captures_preserve_the_existing_ledger_outcome(
    tmp_path: Path, source: CapturedSnapshot
) -> None:
    entry = entry_at(tmp_path, {"realized_net_score": 42.0})
    result = settled_scoreboard_entries(
        (entry,), (source,), season="2026-27", as_of_utc="2026-08-24T12:00:00Z"
    )
    assert result == (entry,)
    assert result[0] is entry


def test_empty_ledger_does_not_read_the_archive() -> None:
    def unreadable():
        raise AssertionError("An empty ledger must not consume captures")
        yield

    assert (
        settled_scoreboard_entries(
            (), unreadable(), season="2026-27", as_of_utc="2026-08-24T12:00:00Z"
        )
        == ()
    )


def test_missing_frozen_projections_refuses_settlement(tmp_path: Path) -> None:
    entry = LedgerEntry("2026-27", 1, {}, None, tmp_path)
    with pytest.raises(DataError, match="projections missing"):
        settled_scoreboard_entries(
            (entry,),
            (capture("checked", "2026-08-23T12:00:00Z"),),
            season="2026-27",
            as_of_utc="2026-08-24T12:00:00Z",
        )


def test_wrong_ledger_season_is_refused(tmp_path: Path) -> None:
    entry = replace(entry_at(tmp_path), season="2025-26")
    with pytest.raises(DataError, match="another season"):
        settled_scoreboard_entries((entry,), (), season="2026-27", as_of_utc="2026-08-24T12:00:00Z")
