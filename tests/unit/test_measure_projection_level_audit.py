"""The projection level runner's own arithmetic: the prior, and the rows it reads."""

import numpy as np
import pandas as pd
import pytest
from scripts.measure_projection_level_audit import level_table, prior_minutes_per_week


def _panel() -> pd.DataFrame:
    rows = []
    for gameweek, (regular, newcomer) in enumerate(
        [(90, None), (90, None), (60, None), (90, 45)], 1
    ):
        rows.append({"season": "2021-22", "gameweek": gameweek, "player_id": 1, "minutes": regular})
        if newcomer is not None:
            rows.append(
                {"season": "2021-22", "gameweek": gameweek, "player_id": 2, "minutes": newcomer}
            )
    # Another season's minutes never count towards this one's prior.
    rows.append({"season": "2020-21", "gameweek": 38, "player_id": 2, "minutes": 90})
    return pd.DataFrame(rows)


def test_the_prior_is_the_seasons_minutes_before_the_target_over_its_gameweeks() -> None:
    keys = pd.DataFrame(
        {
            "season": ["2021-22", "2021-22", "2021-22"],
            "target_gameweek": [4, 4, 5],
            "player_id": [1, 2, 2],
        }
    )
    prior = prior_minutes_per_week(_panel(), keys)
    assert prior.iloc[0] == pytest.approx(240 / 3)
    # Not in the game's files before gameweek 4: he had played nothing this season.
    assert prior.iloc[1] == 0.0
    assert prior.iloc[2] == pytest.approx(45 / 4)


def test_the_table_leaves_out_blank_rows_and_early_gameweeks_and_keeps_absent_absent() -> None:
    def row(gameweek: int, player: int, fixtures: int, components: bool) -> dict[str, object]:
        return {
            "season": "2021-22",
            "target_gameweek": gameweek,
            "fold_id": f"2021-22-gw{gameweek:02d}",
            "player_id": player,
            "fixture_count": fixtures,
            "appearance_target": 1,
            "points_target": 5,
            "appearance_probability": 0.8 if components else np.nan,
            "expected_points_if_appearance": 4.0 if components else np.nan,
            "control_expected_points": 3.2,
        }

    rows = pd.DataFrame(
        [row(3, 1, 1, True), row(4, 1, 1, True), row(4, 2, 1, False), row(5, 1, 0, True)]
    )
    roster = rows.loc[:, ["season", "target_gameweek", "fold_id", "player_id"]].assign(
        position="MID"
    )
    table = level_table(rows, roster, _panel())
    assert list(table["fold_id"]) == ["2021-22-gw04", "2021-22-gw04"]
    composed, direct = table.iloc[0], table.iloc[1]
    assert composed["appeared"] == 1.0 and composed["conditional_forecast"] == 4.0
    # A direct-control row has no component forecast, so its appearance is not read either.
    assert np.isnan(direct["appeared"]) and np.isnan(direct["appearance_forecast"])
    assert direct["forecast"] == 3.2 and direct["realized"] == 5.0
