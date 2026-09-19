"""The live projection audit's arithmetic, and the reader of the game's own forecast."""

import json

import pandas as pd
import pytest

from squadopt.data.sources.fpl_live import game_forecast
from squadopt.evaluation.live_projection_audit import (
    TOP_PER_POSITION,
    LiveProjectionAuditError,
    absent_forecast,
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


def test_the_absent_forecast_says_on_whom_the_points_sat() -> None:
    players = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6],
            "position": ["MID", "MID", "DEF", "DEF", "FWD", "GK"],
            "price_tenths": [45, 60, 110, 50, 80, 40],
        }
    )
    outcomes = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6],
            "minutes": [90, 0, 0, 0, 0, 0],
            "total_points": [2, 0, 0, 0, 0, 0],
        }
    )
    frame = audit_frame(
        players,
        outcomes,
        # Player 6 is absent from our projection: not a zero, and not counted.
        expected_points={1: 3.0, 2: 4.0, 3: 2.0, 4: 0.5, 5: 3.0},
        multipliers={2: 0.5, 5: 0.0},
        game={2: 1.0, 6: 0.8},
    )
    decided = absent_forecast(frame, "ours_decided")
    # 2.0 (named, halved), 2.0, 0.5, and the ruled-out forward at nothing.
    assert decided["players"] == 4 and decided["forecast_points"] == pytest.approx(4.5)
    rule = decided["by_our_availability_rule"]
    assert isinstance(rule, dict)
    assert rule["named"] == {
        "players": 2,
        "forecast_points": pytest.approx(2.0),
        "share_of_absent_forecast": pytest.approx(2.0 / 4.5),
    }
    assert rule["not_named"]["forecast_points"] == pytest.approx(2.5)
    sizes = decided["by_forecast_size"]
    assert isinstance(sizes, dict)
    assert [sizes[label]["players"] for label in sizes] == [2, 2, 0]
    positions = decided["by_position"]
    assert isinstance(positions, dict)
    assert positions["DEF"]["forecast_points"] == pytest.approx(2.5)
    assert positions["GK"]["players"] == 0
    bands = decided["by_price_band"]
    assert isinstance(bands, dict)
    assert sum(block["players"] for block in bands.values()) == 4
    largest = decided["largest"]
    assert isinstance(largest, list)
    assert [row["player_id"] for row in largest] == [2, 3, 4, 5]
    assert largest[0]["named_by_our_availability_rule"] is True
    assert largest[1]["named_by_our_availability_rule"] is False

    # The game's forecast is read against the same flags. The goalkeeper our projection
    # never scored is a player nobody named, not a player the rule named.
    game = absent_forecast(frame, "game")
    assert game["players"] == 2
    game_rule = game["by_our_availability_rule"]
    assert isinstance(game_rule, dict)
    assert game_rule["named"]["forecast_points"] == pytest.approx(1.0)
    assert game_rule["not_named"]["forecast_points"] == pytest.approx(0.8)

    # The block agrees with the appearance split it decomposes.
    summary = summarise_forecast(frame, "ours_decided")
    split = summary["appearance_split"]
    assert isinstance(split, dict)
    assert split["forecast_points_on_players_who_did_not_appear"] == pytest.approx(4.5)
    assert summary["absent_forecast"] == decided


def test_the_error_is_read_by_how_much_the_player_had_been_playing() -> None:
    frame = audit_frame(
        _players(),
        _outcomes(),
        expected_points={1: 3.0, 2: 4.0, 3: 6.0, 4: 2.0},
        multipliers={},
        game=None,
        # Player 4 is not named: no prior, which is not a prior of nothing.
        prior_minutes_per_week={1: 90.0, 2: 0.0, 3: 60.0},
    )
    reading = summarise_forecast(frame, "ours_decided")["by_prior_minutes"]
    assert isinstance(reading, dict) and reading["players"] == 3
    buckets = reading["buckets"]
    assert isinstance(buckets, dict)
    assert buckets["none"]["players"] == 1 and buckets["none"]["appeared"] == 0
    assert buckets["none"]["forecast_points"] == 4.0
    assert buckets["under_30"]["players"] == 0 and buckets["30_to_60"]["players"] == 0
    regulars = buckets["60_and_above"]
    assert regulars["players"] == 2 and regulars["appeared"] == 2
    assert regulars["forecast_points"] == 9.0 and regulars["realized_points"] == 11.0
    assert regulars["bias"] == pytest.approx(1.0)

    # With no prior handed over the reading is absent, and nothing else changes.
    bare = audit_frame(_players(), _outcomes(), expected_points={1: 3.0}, multipliers={}, game=None)
    assert summarise_forecast(bare, "ours_decided")["by_prior_minutes"] == {"players": 0}


def test_nobody_absent_is_an_empty_reading_and_not_an_error() -> None:
    frame = audit_frame(
        _players().iloc[[0]],
        _outcomes().iloc[[0]],
        expected_points={1: 3.0},
        multipliers={},
        game=None,
    )
    reading = absent_forecast(frame, "ours_decided")
    assert reading["players"] == 0 and reading["largest"] == []
    rule = reading["by_our_availability_rule"]
    assert isinstance(rule, dict)
    assert rule["named"]["share_of_absent_forecast"] is None


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
