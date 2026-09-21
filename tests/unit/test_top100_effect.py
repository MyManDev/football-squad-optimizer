"""Synthetic fixed effects and week-cluster uncertainty, not a real read-out."""

import copy

import pandas as pd
import pytest

from squadopt.evaluation.top100_effect import plan_changed, plan_reading, player_reading


def players(weeks: int = 8) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "gameweek": week,
                "player_id": player,
                "position": position,
                "m": 2.0,
                "s": player / 10,
                "y": 2 + 0.08 * (2 * player / 10) + week + offset,
                "minutes": 90,
            }
            for week in range(5, 5 + weeks)
            for position, offset in (("GK", 1), ("DEF", 2))
            for player in (1 + 10 * offset, 2 + 10 * offset, 3 + 10 * offset)
        ]
    ).assign(
        s=lambda f: (f.player_id % 10) / 10,
        y=lambda f: 2 + 0.08 * 2 * f.s + f.gameweek + f.player_id // 10,
    )


def test_fixed_effects_remove_week_and_position_intercepts() -> None:
    reading = player_reading(players())
    assert reading["all"]["weight_slope"] == pytest.approx(0.08)
    assert reading["all"]["weight_slope_interval90"] == pytest.approx([0.08, 0.08])
    assert reading["all"]["rank_mean"] == pytest.approx(1)
    assert reading["all"]["gameweeks"] == 8
    assert "rough" in reading["all"]["interval_note"]


def test_fewer_than_six_weeks_and_constant_support_are_unidentified() -> None:
    frame = players(5)
    assert player_reading(frame)["all"]["weight_slope_interval90"] is None
    frame["s"] = 0
    reading = player_reading(frame)
    assert reading["all"]["weight_slope"] is None
    assert reading["all"]["rank_mean"] is None
    assert reading["nonplayer_share"] is None


def test_appearance_and_nonplayer_mass_are_separate() -> None:
    frame = players(1)
    frame.loc[frame.player_id % 10 == 3, "minutes"] = 0
    reading = player_reading(frame)
    assert reading["all"]["rows"] == 6
    assert reading["appeared"]["rows"] == 4
    assert reading["nonplayer_share"] == pytest.approx(0.5)


def test_top40_is_selected_per_week_not_across_weeks() -> None:
    frame = pd.DataFrame(
        [
            {
                "gameweek": week,
                "player_id": i,
                "position": "MID",
                "m": 100 - i + week * 100,
                "s": i / 50,
                "y": 100 - i + week * 100 + (i if i < 40 else -i * 100),
                "minutes": 90,
            }
            for week in (5, 6)
            for i in range(50)
        ]
    )
    reading = player_reading(frame)["all"]
    assert [x["rows"] for x in reading["rank_groups"]] == [40, 40]
    assert reading["rank_mean"] == pytest.approx(1)


def test_empty_and_bad_player_inputs() -> None:
    assert player_reading(players(1).iloc[:0])["all"]["rows"] == 0


@pytest.mark.parametrize("column,value", [("s", 2), ("m", -1), ("y", float("nan"))])
def test_invalid_readings_refused(column: str, value: float) -> None:
    frame = players(1)
    frame.loc[0, column] = value
    with pytest.raises(ValueError):
        player_reading(frame)


def test_plan_clusters_do_not_multiply_when_members_are_copied() -> None:
    rows = pd.DataFrame(
        [
            {"gameweek": w, "weight": 5, "difference": d, "changed": d != 0, "published_cost": 0.2}
            for w, d in enumerate((-2, -1, 0, 1, 2, 3, 4, 5), 6)
        ]
    )
    original = plan_reading(rows)["5"]
    repeated = plan_reading(pd.concat([rows] * 15, ignore_index=True))["5"]
    assert original["interval90"] == repeated["interval90"]
    assert repeated["gameweeks"] == 8
    assert original["mean_difference"] == 1.5
    assert original["wins"] == 5 and original["ties"] == 1 and original["losses"] == 2
    assert original["mean_published_cost_same_pairs"] == pytest.approx(0.2)
    rows.loc[0, "published_cost"] = None
    assert plan_reading(rows)["5"]["mean_published_cost_same_pairs"] is None


def test_changed_plan_includes_bench_vice_chip_hits_not_pitch_order() -> None:
    base = {
        "starting_xi": [1, 2],
        "bench": [3, 4],
        "captain": 1,
        "vice_captain": 2,
        "chip": None,
        "transfer_hit_points": 0,
        "moves": [],
    }
    weighted = copy.deepcopy(base)
    weighted["starting_xi"] = [2, 1]
    assert not plan_changed(base, weighted)
    for key, value in (
        ("bench", [4, 3]),
        ("vice_captain", 1),
        ("chip", "3xc"),
        ("transfer_hit_points", 4),
    ):
        assert plan_changed(base, {**base, key: value})
