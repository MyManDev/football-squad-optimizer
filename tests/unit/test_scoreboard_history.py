import json
from dataclasses import replace
from pathlib import Path

from tests.unit.test_capture_measurement import capture
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard_history import settled_scoreboard_entries
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.live import LedgerEntry


def test_event_live_settles_in_memory_using_codes_and_leaves_ledger_untouched(
    tmp_path: Path,
) -> None:
    decision, projections, outcomes = decision_inputs()
    projections.to_csv(tmp_path / "projections.csv", index=False)
    original = (tmp_path / "projections.csv").read_bytes()
    entry = LedgerEntry("2026-27", 1, decision, None, tmp_path)
    source = capture("checked", "2026-08-23T12:00:00Z", finished=True, checked=True)
    bootstrap = json.loads(source.payloads[BOOTSTRAP_PAYLOAD])
    bootstrap["elements"] = [{"id": player + 100, "code": player} for player in range(1, 16)]
    live = {
        "elements": [
            {
                "id": int(row.player_id) + 100,
                "stats": {
                    "minutes": int(row.minutes),
                    "total_points": int(row.total_points),
                    "starts": 0,
                },
            }
            for row in outcomes.itertuples()
        ]
    }
    source = replace(
        source,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            live_payload(1): json.dumps(live).encode(),
        },
    )
    result = settled_scoreboard_entries(
        (entry,), (source,), season="2026-27", as_of_utc="2026-08-24T12:00:00Z"
    )
    assert result[0].outcome["realized_net_score"] == 81
    assert result[0].outcome["source_snapshot_id"] == "checked"
    assert entry.outcome is None
    assert not (tmp_path / "outcome.json").exists()
    assert (tmp_path / "projections.csv").read_bytes() == original


def test_no_checked_capture_preserves_the_ledger_gap(tmp_path: Path) -> None:
    entry = LedgerEntry("2026-27", 1, {}, None, tmp_path)
    result = settled_scoreboard_entries(
        (entry,),
        (capture("pre", "2026-08-19T12:00:00Z"),),
        season="2026-27",
        as_of_utc="2026-08-24T12:00:00Z",
    )
    assert result == (entry,)
    assert result[0].outcome is None


def test_capture_after_publication_cutoff_is_not_used(tmp_path: Path) -> None:
    decision, _, _ = decision_inputs()
    entry = LedgerEntry("2026-27", 1, decision, None, tmp_path)
    result = settled_scoreboard_entries(
        (entry,),
        (capture("future", "2026-08-25T12:00:00Z", finished=True, checked=True),),
        season="2026-27",
        as_of_utc="2026-08-24T12:00:00Z",
    )
    assert result[0].outcome is None
