"""The league view: our season against the game's own weekly summary, and ownership.

The capture is synthetic and small, so what is asserted is the reading of it: an
unscored gameweek has no average and no verdict, a scored one is compared, and ownership
is keyed by the persistent player code rather than the per-season element number.
"""

import json
from typing import Any

import pytest
from tests.unit.test_season_ledger import CAPTURED_AT

from squadopt.application.league import (
    DIFFERENTIAL_OWNERSHIP_PERCENT,
    LeagueError,
    league_view,
    ownership_by_player,
    ownership_view,
)
from squadopt.application.views import LedgerRowView, LedgerView, PlayerView
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD

SEASON = "2026-27"


def _element(element_id: int, code: int, owned: str) -> dict[str, Any]:
    return {
        "id": element_id,
        "code": code,
        "web_name": f"Player {code}",
        "selected_by_percent": owned,
        "now_cost": 50,
        "element_type": 3,
        "team": 1,
    }


def _capture(*, finished_gameweeks: int = 0, averages: tuple[int, ...] = ()) -> CapturedSnapshot:
    events = []
    for gameweek in range(1, 4):
        finished = gameweek <= finished_gameweeks
        events.append(
            {
                "id": gameweek,
                "deadline_time": f"2026-08-{20 + gameweek:02d}T17:30:00Z",
                "finished": finished,
                "average_entry_score": averages[gameweek - 1] if finished and averages else 0,
                "highest_score": 120 if finished else None,
            }
        )
    document = {
        "events": events,
        "elements": [
            _element(1, 900_001, "73.3"),
            _element(2, 900_002, "8.1"),
            _element(3, 900_003, "0.4"),
        ],
    }
    metadata = SnapshotMetadata(
        snapshot_id="fpl-live-test",
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        schema_version="snapshot_v1",
        checksums={},
        fingerprint="0" * 64,
    )
    return CapturedSnapshot(
        metadata=metadata,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(document).encode("utf-8"),
            FIXTURES_PAYLOAD: b"[]",
        },
    )


def _player(player_id: int, role: str) -> PlayerView:
    return PlayerView(
        player_id=player_id,
        name=f"Player {player_id}",
        short_name=f"P{player_id}",
        team="Club",
        position="MID",
        price_tenths=50,
        expected_points=4.0,
        role=role,
    )


def _ledger(*rows: LedgerRowView) -> LedgerView:
    settled = [row for row in rows if row.settled]
    return LedgerView(
        season=SEASON,
        rows=rows,
        decided_gameweeks=len(rows),
        settled_gameweeks=len(settled),
        total_projected_score=sum(row.projected_score for row in rows),
        total_projected_score_settled=sum(row.projected_score for row in settled) or None,
        total_realized_score=sum(row.realized_score or 0.0 for row in settled) or None,
        total_projection_error=None,
        total_realized_net_score=sum(row.realized_net_score or 0.0 for row in settled) or None,
        total_transfer_hit_points=0.0,
        chips_played=(),
    )


def _row(gameweek: int, *, realized: float | None, net: float | None = None) -> LedgerRowView:
    return LedgerRowView(
        gameweek=gameweek,
        snapshot_id="fpl-live-test",
        deadline_utc=f"2026-08-{20 + gameweek:02d}T17:30:00Z",
        solver_status="OPTIMAL",
        decision_kind="opening" if gameweek == 1 else "transfer",
        captain_player_id=900_001,
        projected_score=55.0,
        realized_score=realized,
        projection_error=None,
        transfer_count=0,
        transfer_hit_points=0.0,
        realized_net_score=net if net is not None else realized,
        chip=None,
        unavailable_player_count=0,
        settled=realized is not None,
        cumulative_projected_score=55.0 * gameweek,
        cumulative_realized_score=realized,
    )


def test_an_unscored_season_compares_nothing_and_says_so() -> None:
    view = league_view(_capture(), _ledger(_row(1, realized=None)))

    assert view.scored_gameweeks == 0
    assert view.total_difference_to_average is None
    assert view.our_total_realized_net_score is None
    assert "nothing to compare" in view.verdict
    first = view.weeks[0]
    assert first.finished is False
    assert first.average_entry_score is None and first.highest_score is None
    assert first.our_projected_score == pytest.approx(55.0)
    assert first.difference_to_average is None


def test_a_scored_gameweek_is_compared_with_the_games_own_average() -> None:
    capture = _capture(finished_gameweeks=2, averages=(48, 60, 0))
    view = league_view(capture, _ledger(_row(1, realized=62.0), _row(2, realized=55.0, net=51.0)))

    week_one, week_two = view.weeks[0], view.weeks[1]
    assert week_one.average_entry_score == 48.0 and week_one.difference_to_average == 14.0
    assert week_two.difference_to_average == pytest.approx(51.0 - 60.0)
    assert view.scored_gameweeks == 2
    assert view.total_difference_to_average == pytest.approx(62.0 + 51.0 - 108.0)
    assert view.verdict.startswith("+5 points against the game's average over 2 scored gameweeks")
    assert "noise, not evidence" in view.verdict
    # A gameweek in the ledger but not yet finished contributes nothing.
    assert view.weeks[2].difference_to_average is None


def test_ownership_is_keyed_by_the_persistent_player_code() -> None:
    capture = _capture()
    owned = ownership_by_player(capture)
    assert owned == {900_001: 73.3, 900_002: 8.1, 900_003: 0.4}

    view = ownership_view(
        capture,
        gameweek=1,
        starters=[_player(900_001, "starter"), _player(900_002, "starter")],
        bench=[_player(900_003, "bench")],
        captain_player_id=900_001,
    )
    assert view.mean_starter_ownership == pytest.approx((73.3 + 8.1) / 2)
    # Effective ownership counts the captain again, as the field's exposure does.
    assert view.effective_ownership == pytest.approx(73.3 + 8.1 + 73.3)
    assert view.differentials == (900_002,)
    assert view.differential_threshold_percent == DIFFERENTIAL_OWNERSHIP_PERCENT
    assert view.most_owned_starter == 900_001 and view.least_owned_starter == 900_002
    assert set(view.ownership_percent) == {"900001", "900002", "900003"}
    assert [p.player_id for p in view.squad] == [900_001, 900_002, 900_003]


def test_the_verdict_carries_the_ownership_when_there_is_one() -> None:
    capture = _capture(finished_gameweeks=1, averages=(48, 0, 0))
    ownership = ownership_view(
        capture,
        gameweek=1,
        starters=[_player(900_001, "starter")],
        bench=[],
        captain_player_id=900_001,
    )
    view = league_view(capture, _ledger(_row(1, realized=62.0)), ownership=ownership)
    assert "73% ownership" in view.verdict
    assert view.ownership is not None and view.ownership.gameweek == 1


def test_a_capture_without_a_bootstrap_is_refused() -> None:
    metadata = SnapshotMetadata(
        snapshot_id="empty",
        source="fpl-live",
        captured_at_utc=CAPTURED_AT,
        schema_version="snapshot_v1",
        checksums={},
        fingerprint="0" * 64,
    )
    empty = CapturedSnapshot(metadata=metadata, payloads={FIXTURES_PAYLOAD: b"[]"})
    with pytest.raises(LeagueError, match="no bootstrap"):
        league_view(empty, _ledger())
