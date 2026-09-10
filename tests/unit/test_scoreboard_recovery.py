"""Reconciliation never creates decisions or capture-time evidence after the fact."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_capture_measurement import capture
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard import ScoreboardPublicationRequest, publish_scoreboard
from squadopt.application.scoreboard_recovery import settled_member_picks
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.platform.recover_scoreboard import recovery_scoreboard


def recovery_world(tmp_path: Path) -> CapturedSnapshot:
    decision, projections, outcomes = decision_inputs()
    rows = projections.to_dict("records")
    published = {
        **decision,
        "season": "2026-27",
        "gameweek": 1,
        "captured_at_utc": "2026-08-20T12:00:00Z",
        "deadline_utc": "2026-08-21T17:30:00Z",
        "projected_score": 120,
        "squad": rows,
        "starting_xi": [
            row for row in rows if row["player_id"] in decision["starting_xi_player_ids"]
        ],
        "bench": [row for row in rows if row["player_id"] in decision["bench_player_ids"]],
    }
    directory = tmp_path / "data/2026-27/gw01"
    directory.mkdir(parents=True)
    (directory / "recommendation.json").write_text(json.dumps({"payload": published}))
    source = capture("current", "2026-09-10T12:00:00Z", finished=True, checked=True)
    bootstrap = json.loads(source.payloads[BOOTSTRAP_PAYLOAD])
    bootstrap["elements"] = [{"id": player + 100, "code": player} for player in range(1, 16)]
    for week, day in [(2, "2026-08-28"), (3, "2026-09-04"), (4, "2026-09-12")]:
        bootstrap["events"].append(
            {
                "id": week,
                "deadline_time": f"{day}T12:00:00Z",
                "finished": week < 4,
                "data_checked": week < 4,
                "average_entry_score": 0,
            }
        )
    return replace(
        source,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            live_payload(1): json.dumps(
                {
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
            ).encode(),
        },
    )


def test_missing_decisions_stay_null_and_gw1_is_not_given_an_invented_bench(tmp_path: Path) -> None:
    source = recovery_world(tmp_path)
    result: Any = recovery_scoreboard(
        snapshot=source,
        publication_root=tmp_path,
        advice_root=tmp_path / "advice",
        league_id=1,
        entry_ids=(),
    )
    weeks = result["payload"]["gameweeks"]
    assert [week["gameweek"] for week in weeks] == [1, 2, 3]
    assert weeks[0]["ours"]["net"] == 81
    assert weeks[0]["ours"]["diagnostics"]["autosub_recovery"] is None
    for week in weeks[1:]:
        assert week["decision_record_status"] == "missing"
        assert week["ours"] is None
        assert all(row["net"] is None for row in week["comparisons"][:4])
    assert result["payload"]["recovery"]["historical_availability"] == "lost"


@pytest.mark.parametrize("wrong_score", [False, True])
def test_api_picks_use_codes_and_multipliers_and_require_reconciliation(
    tmp_path: Path,
    wrong_score: bool,
) -> None:
    source = recovery_world(tmp_path)
    gross = sum(player for player in range(1, 16) if player != 8) + 9
    picks = {
        "picks": [
            {"element": player + 100, "position": player, "multiplier": 2 if player == 9 else 1}
            for player in range(1, 16)
        ],
        "entry_history": {"event": 1, "points": gross + int(wrong_score)},
    }
    source = replace(
        source, payloads={**source.payloads, "entry-7-picks-gw01.json": json.dumps(picks).encode()}
    )
    if wrong_score:
        with pytest.raises(DataError, match="reconcile"):
            settled_member_picks(source, gameweek=1, entry_id=7)
    else:
        rows = settled_member_picks(source, gameweek=1, entry_id=7)
        assert rows[0]["player_id"] == 1
        assert rows[7]["minutes"] == 0
        assert rows[8]["multiplier"] == 2


@pytest.mark.parametrize("prior_publication", [False, True])
def test_regular_publication_uses_surviving_gw1_without_private_ledger(
    tmp_path: Path, prior_publication: bool
) -> None:
    source = recovery_world(tmp_path)
    snapshots = tmp_path / "snapshots"
    stored = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=source.metadata.captured_at_utc,
        payloads=source.payloads,
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [{"entry_id": 7, "label": "Member"}],
            }
        )
    )
    if prior_publication:
        target = tmp_path / "site/data/league/scoreboard.json"
        target.parent.mkdir(parents=True)
        target.write_text(
            json.dumps(
                {
                    "payload": {
                        "season": "2026-27",
                        "gameweeks": [
                            {"gameweek": 1, "ours": {"net": 999}},
                            {"gameweek": 2, "ours": {"net": 999}},
                        ],
                    }
                }
            )
        )
    result = publish_scoreboard(
        ScoreboardPublicationRequest(
            snapshots,
            stored.snapshot_id,
            registry,
            tmp_path / "lost-ledger",
            tmp_path / "site",
            352490,
            recovery_publication_root=tmp_path,
            advice_record_root=tmp_path / "records",
        )
    )
    payload = result.document["payload"]
    assert payload["gameweeks"][0]["ours"]["net"] == 81
    assert payload["gameweeks"][1]["decision_record_status"] == "missing"
    assert payload["gameweeks"][1]["ours"] is None
    assert payload["cumulative"]["ours_gameweeks"] == [1]
    assert not (tmp_path / "lost-ledger").exists()


def test_surviving_advice_is_visible_but_unsettled_week_is_never_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = recovery_world(tmp_path)
    decision, players, _ = decision_inputs()
    records = tmp_path / "advice"
    (records / "2026-27/gw04/entry-7").mkdir(parents=True)
    record = {
        "entry_id": 7,
        "league_id": 352490,
        "player_id_space": "fpl_element_code",
        "capture": {"snapshot_id": "original-capture"},
        "players": {str(row["player_id"]): row for row in players.to_dict("records")},
        "advice": [
            {
                "strategy": "saf-puan",
                "window": 1,
                "scoring_complete": True,
                "starting_xi": decision["starting_xi_player_ids"],
                "bench": decision["bench_player_ids"],
                "captain": 8,
                "vice_captain": 9,
                "chip": None,
                "transfer_hit_points": 4,
                "expected_own_points": 120,
                "advice_sha256": "checksum",
            }
        ],
    }
    monkeypatch.setattr(
        "squadopt.application.scoreboard_recovery.select_record", lambda *a, **k: record
    )
    result: Any = recovery_scoreboard(
        snapshot=source,
        publication_root=tmp_path,
        advice_root=records,
        league_id=352490,
        entry_ids=(7,),
    )
    week = result["payload"]["gameweeks"][-1]
    assert week["gameweek"] == 4
    assert week["finished"] is False
    advice = week["comparisons"][-1]
    assert advice["kind"] == "member_advice"
    assert advice["net"] is None
    assert advice["expected_net"] == 116
    assert all(value is None for value in advice["diagnostics"].values())


@pytest.mark.parametrize(
    "problem",
    [
        "gameweek",
        "fractional_multiplier",
        "negative_multiplier",
        "duplicate_position",
        "duplicate_mapping",
    ],
)
def test_settled_picks_reject_corruption_even_when_points_could_reconcile(
    tmp_path: Path, problem: str
) -> None:
    source = recovery_world(tmp_path)
    picks = [
        {"element": player + 100, "position": player, "multiplier": 0} for player in range(1, 16)
    ]
    document = {"picks": picks, "entry_history": {"event": 1, "points": 0}}
    if problem == "gameweek":
        document["entry_history"]["event"] = 2
    elif problem == "fractional_multiplier":
        picks[7]["multiplier"] = 0.5
    elif problem == "negative_multiplier":
        picks[7]["multiplier"] = -1
    elif problem == "duplicate_position":
        picks[0]["position"] = 2
    elif problem == "duplicate_mapping":
        bootstrap = json.loads(source.payloads[BOOTSTRAP_PAYLOAD])
        bootstrap["elements"].append(bootstrap["elements"][0])
        source = replace(
            source, payloads={**source.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()}
        )
    source = replace(
        source,
        payloads={**source.payloads, "entry-7-picks-gw01.json": json.dumps(document).encode()},
    )
    with pytest.raises(DataError):
        settled_member_picks(source, gameweek=1, entry_id=7)
