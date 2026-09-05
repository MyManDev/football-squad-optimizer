"""Live outcome history supplied to the operational Phase C component model."""

import json

import pytest

from squadopt.data.sources.fpl_live import (
    IncompleteLiveHistoryError,
    build_live_player_history,
)


def _bootstrap() -> bytes:
    return json.dumps(
        {
            "events": [
                {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True},
                {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": True},
                {"id": 3, "deadline_time": "2026-09-04T17:30:00Z", "finished": False},
            ],
            "teams": [{"id": 1, "code": 10, "name": "Club A"}],
            "elements": [
                {
                    "id": element,
                    "code": code,
                    "first_name": "Player",
                    "second_name": str(code),
                    "team": 1,
                    "element_type": 3,
                    "now_cost": 50,
                }
                for element, code in ((1, 101), (2, 202))
            ],
        }
    ).encode("utf-8")


def _fixtures(*, second_finished: bool = True) -> bytes:
    return json.dumps(
        [
            {"event": 1, "finished": True},
            {"event": 2, "finished": second_finished},
        ]
    ).encode("utf-8")


def _live(rows: tuple[tuple[int, int, int], ...]) -> bytes:
    return json.dumps(
        {
            "elements": [
                {"id": player, "stats": {"minutes": minutes, "total_points": points}}
                for player, minutes, points in rows
            ]
        }
    ).encode("utf-8")


def test_only_players_with_complete_history_receive_rolling_rows() -> None:
    panel, incomplete = build_live_player_history(
        _bootstrap(),
        _fixtures(),
        {
            1: _live(((1, 90, 6),)),
            2: _live(((1, 30, 2), (2, 90, 8))),
        },
        season="2026-27",
        target_gameweek=3,
        source_snapshot_id="capture-v1",
    )

    assert incomplete == (202,)
    assert panel.loc[panel["gameweek"] < 3, "player_id"].tolist() == [101, 101]
    target = panel.loc[panel["gameweek"] == 3]
    assert target["player_id"].tolist() == [101, 202]
    assert target["minutes"].tolist() == [0, 0]
    assert target["total_points"].tolist() == [0, 0]


def test_provisional_history_is_refused_instead_of_becoming_a_training_outcome() -> None:
    with pytest.raises(IncompleteLiveHistoryError, match="not fully settled"):
        build_live_player_history(
            _bootstrap(),
            _fixtures(second_finished=False),
            {2: _live(((1, 30, 2), (2, 90, 8)))},
            season="2026-27",
            target_gameweek=3,
            source_snapshot_id="capture-v1",
        )
