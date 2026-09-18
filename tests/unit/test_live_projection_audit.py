"""The live projection audit's arithmetic, and the reader of the game's own forecast."""

import json

import pandas as pd
import pytest

from squadopt.data.sources.fpl_live import game_forecast
from squadopt.evaluation.live_projection_audit import (
    TOP_PER_POSITION,
    LiveProjectionAuditError,
    audit_frame,
    paired_difference,
    pool,
    summarise_forecast,
    summarise_gameweek,
)


def _bootstrap(elements: list[dict[str, object]]) -> bytes:
    return json.dumps({"elements": elements}).encode("utf-8")


def test_the_games_forecast_leaves_out_what_it_does_not_say() -> None:
    forecast = game_forecast(
        _bootstrap(
            [
                {"code": 11, "element_type": 3, "ep_next": "4.5"},
                {"code": 12, "element_type": 2, "ep_next": None},
                {"code": 13, "element_type": 4, "ep_next": "not a number"},
                {"code": 14, "element_type": 1, "ep_next": "0.0"},
                # Not a squad-eligible player (the manager entries the platform added).
                {"code": 15, "element_type": 5, "ep_next": "9.9"},
            ]
        )
    )
    # A null and an unparseable value are absent, never zero; a stated zero is a zero.
    assert dict(forecast) == {11: 4.5, 14: 0.0}


def _players() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "position": ["MID", "MID", "MID", "DEF"],
            "price_tenths": [45, 60, 110, 50],
        }
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {"player_id": [1, 2, 3, 4], "minutes": [90, 0, 60, 30], "total_points": [2, 0, 9, 1]}
    )


def test_a_player_a_forecast_does_not_name_is_left_out_of_that_forecast() -> None:
    frame = audit_frame(
        _players(),
        _outcomes(),
        expected_points={1: 3.0, 2: 4.0, 3: 6.0},  # nothing for player 4
        multipliers={2: 0.0},  # ruled out; everyone else is unnamed and so unchanged
        game={1: 2.5, 3: 7.0, 4: 1.0},
    )
    row = frame.set_index("player_id")
    assert row.loc[2, "ours_unconditional"] == 4.0 and row.loc[2, "ours_decided"] == 0.0
    assert row.loc[1, "ours_decided"] == 3.0
    assert pd.isna(row.loc[4, "ours_decided"]) and pd.isna(row.loc[2, "game"])
    ours = summarise_forecast(frame, "ours_decided")["all_players"]
    assert isinstance(ours, dict) and ours["players"] == 3
    # realized 2, 0, 9 against 3, 0, 6: errors -1, 0, +3.
    assert ours["mean_absolute_error"] == pytest.approx(4 / 3)
    assert ours["bias"] == pytest.approx(2 / 3)


def test_the_appearance_split_says_how_much_sat_on_players_who_did_not_appear() -> None:
    frame = audit_frame(
        _players(),
        _outcomes(),
        expected_points={1: 3.0, 2: 4.0, 3: 6.0, 4: 2.0},
        multipliers={},
        game=None,
    )
    split = summarise_forecast(frame, "ours_unconditional")["appearance_split"]
    assert isinstance(split, dict)
    assert split["forecast_points_on_players_who_did_not_appear"] == 4.0
    assert split["share_on_players_who_did_not_appear"] == pytest.approx(4.0 / 15.0)
    buckets = split["by_minutes"]
    assert isinstance(buckets, dict)
    assert buckets["1_to_59"]["players"] == 1 and buckets["60_and_above"]["players"] == 2


def test_the_paired_difference_is_negative_when_the_first_forecast_is_closer() -> None:
    frame = audit_frame(
        _players(),
        _outcomes(),
        expected_points={1: 2.0, 2: 0.0, 3: 9.0, 4: 1.0},  # exact
        multipliers={},
        game={1: 4.0, 2: 2.0, 3: 5.0, 4: 1.0},
    )
    paired = paired_difference(frame, "ours_decided", "game")
    assert paired["players"] == 4
    assert paired["mean_absolute_error_difference"] == pytest.approx(-(2 + 2 + 4 + 0) / 4)
    record = summarise_gameweek(frame)
    assert "ours_decided_minus_game" in record
    # Without the game's forecast there is nothing to pair, and the record does not pretend.
    alone = audit_frame(
        _players(), _outcomes(), expected_points={1: 2.0}, multipliers={}, game=None
    )
    assert "ours_decided_minus_game" not in summarise_gameweek(alone)


def test_pooled_gameweeks_are_never_ranked_against_each_other() -> None:
    def week(shift: float) -> pd.DataFrame:
        count = TOP_PER_POSITION + 5
        players = pd.DataFrame(
            {"player_id": range(count), "position": ["MID"] * count, "price_tenths": [60] * count}
        )
        outcomes = pd.DataFrame(
            {
                "player_id": range(count),
                "minutes": [90] * count,
                "total_points": [float(i % 7) for i in range(count)],
            }
        )
        forecast = {i: shift + i / 10 for i in range(count)}
        return audit_frame(
            players, outcomes, expected_points=forecast, multipliers={}, game=forecast
        )

    pooled = pool({4: week(0.0), 5: week(100.0)})
    assert pooled["rests_on_gameweeks"] == 2
    forecasts = pooled["forecasts"]
    assert isinstance(forecasts, dict)
    top = forecasts["ours_decided"]["top_per_position"]
    # Forty from each week, not the forty highest of the two weeks together (which would be
    # all of the shifted week and none of the other).
    assert top["players"] == 2 * TOP_PER_POSITION
    groups = forecasts["ours_decided"]["rank_agreement_within_position"]["groups"]
    assert set(groups) == {"4|MID", "5|MID"}
    assert pool({}) == {"gameweeks": []}


def test_tables_that_cannot_be_paired_are_refused() -> None:
    with pytest.raises(LiveProjectionAuditError, match="lacks"):
        audit_frame(
            _players().drop(columns=["position"]),
            _outcomes(),
            expected_points={},
            multipliers={},
            game=None,
        )
    doubled = pd.concat([_players(), _players().head(1)], ignore_index=True)
    with pytest.raises(LiveProjectionAuditError, match="twice"):
        audit_frame(doubled, _outcomes(), expected_points={}, multipliers={}, game=None)
    with pytest.raises(LiveProjectionAuditError, match="Unknown forecast"):
        summarise_forecast(
            audit_frame(_players(), _outcomes(), expected_points={}, multipliers={}, game=None),
            "somebody_elses",
        )
