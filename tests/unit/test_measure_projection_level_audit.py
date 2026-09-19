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


def test_the_table_leaves_out_what_it_cannot_read_and_scores_the_absent_as_nothing() -> None:
    def row(
        gameweek: int,
        player: int,
        *,
        fixtures: int = 1,
        appeared: bool = True,
        forecast: bool = True,
    ) -> dict[str, object]:
        return {
            "season": "2021-22",
            "target_gameweek": gameweek,
            "fold_id": f"2021-22-gw{gameweek:02d}",
            "player_id": player,
            "fixture_count": fixtures,
            "appearance_target": 1 if appeared else 0,
            # Conditional: stated for those who appeared, absent for the rest.
            "points_target": 5.0 if appeared else np.nan,
            "appearance_probability": 0.8 if forecast else np.nan,
            "expected_points_if_appearance": 4.0 if forecast else np.nan,
            "control_expected_points": 3.2 if forecast else np.nan,
        }

    rows = pd.DataFrame(
        [
            row(3, 1),  # before the first gameweek read
            row(4, 1),
            row(4, 2, appeared=False),
            row(4, 3, forecast=False),  # thin history: no forecast in the table
            row(5, 1, fixtures=0),  # blank
        ]
    )
    roster = rows.loc[:, ["season", "target_gameweek", "fold_id", "player_id"]].assign(
        position="MID"
    )
    table = level_table(rows, roster, _panel())
    assert list(table["player_id"]) == [1, 2]
    played, absent = table.iloc[0], table.iloc[1]
    assert played["realized"] == 5.0 and played["appeared"] == 1.0
    assert played["conditional_forecast"] == 4.0 and played["forecast"] == 3.2
    # He did not appear, so he scored nothing: that is an outcome, not a missing one.
    assert absent["realized"] == 0.0 and absent["appeared"] == 0.0
