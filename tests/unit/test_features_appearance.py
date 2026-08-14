"""Tests for the appearance decomposition behind the minutes stage.

The pair answers two questions a minutes average conflates: how often a player
features, and how long when he does.
"""

import pandas as pd
import pytest

from squadopt.data.schema import DERIVED_OUTCOME_COLUMNS, is_outcome_column
from squadopt.features import (
    FeatureConfig,
    build_feature_dataset,
    feature_column_names,
)

MINUTES_HISTORY = [(1, 90), (2, 0), (3, 0), (4, 80), (5, 0), (6, 90), (7, 0)]


def _panel(history: list[tuple[int, int]] | None = None, *, player_id: int = 1) -> pd.DataFrame:
    rows = [
        {
            "season": "2025-26",
            "gameweek": gameweek,
            "player_id": player_id,
            "name": "A",
            "team_id": "X",
            "position": "MID",
            "price_tenths": 80,
            "minutes": minutes,
            "total_points": 2,
        }
        for gameweek, minutes in (MINUTES_HISTORY if history is None else history)
    ]
    return pd.DataFrame(rows)


def _config(window: int = 6) -> FeatureConfig:
    return FeatureConfig(
        minutes_windows=(3,),
        points_windows=(3,),
        per_90_window=3,
        appearance_windows=(window,),
    )


# --- opt-in -----------------------------------------------------------------


def test_the_decomposition_is_absent_unless_asked_for() -> None:
    """Every configuration predating it must produce exactly its old columns."""

    assert feature_column_names(FeatureConfig()) == (
        "minutes_last_3",
        "minutes_last_5",
        "points_last_3",
        "points_last_5",
        "points_per_90_last_5",
    )


def test_asking_for_a_window_yields_both_halves() -> None:
    names = feature_column_names(_config(6))

    assert names[-2:] == ("appearance_rate_last_6", "minutes_per_appearance_last_6")


def test_the_default_feature_frame_gains_no_columns() -> None:
    panel = _panel()

    default = build_feature_dataset(panel)

    assert "appearance_rate_last_6" not in default.columns
    assert "minutes_per_appearance_last_6" not in default.columns


# --- timing classification --------------------------------------------------


def test_the_derived_indicator_is_classified_as_an_outcome() -> None:
    """It is a function of minutes, so it carries minutes' time of knowledge."""

    for column in DERIVED_OUTCOME_COLUMNS:
        assert is_outcome_column(column) is True


# --- values -----------------------------------------------------------------


def test_both_halves_are_missing_in_a_players_first_gameweek() -> None:
    frame = build_feature_dataset(_panel(), config=_config())

    first = frame.loc[frame["gameweek"] == 1].iloc[0]
    assert pd.isna(first["appearance_rate_last_6"])
    assert pd.isna(first["minutes_per_appearance_last_6"])


def test_the_appearance_rate_counts_gameweeks_featured_not_minutes() -> None:
    frame = build_feature_dataset(_panel(), config=_config()).set_index("gameweek")

    # Gameweek 4 looks back at 90, 0, 0: featured once in three.
    assert frame.loc[4, "appearance_rate_last_6"] == pytest.approx(1 / 3)


def test_minutes_per_appearance_divides_by_appearances_not_by_gameweeks() -> None:
    """This is the half a plain minutes average cannot express."""

    frame = build_feature_dataset(_panel(), config=_config()).set_index("gameweek")

    # Gameweek 4 looks back at 90, 0, 0: 90 minutes across one appearance.
    assert frame.loc[4, "minutes_per_appearance_last_6"] == pytest.approx(90.0)
    # The plain average over the same history is a different, blended number.
    assert frame.loc[4, "minutes_last_3"] == pytest.approx(30.0)


def test_the_two_halves_separate_players_a_minutes_average_cannot() -> None:
    # Both log 180 minutes over the three gameweeks before gameweek 4, so their
    # minutes averages are identical. One is rotated in and out; the other starts
    # every week and is substituted early.
    rotated = build_feature_dataset(
        _panel([(1, 90), (2, 0), (3, 90), (4, 0)]), config=_config()
    ).set_index("gameweek")
    substituted = build_feature_dataset(
        _panel([(1, 60), (2, 60), (3, 60), (4, 60)]), config=_config()
    ).set_index("gameweek")

    assert rotated.loc[4, "minutes_last_3"] == pytest.approx(60.0)
    assert substituted.loc[4, "minutes_last_3"] == pytest.approx(60.0)

    assert rotated.loc[4, "appearance_rate_last_6"] == pytest.approx(2 / 3)
    assert substituted.loc[4, "appearance_rate_last_6"] == pytest.approx(1.0)
    assert rotated.loc[4, "minutes_per_appearance_last_6"] == pytest.approx(90.0)
    assert substituted.loc[4, "minutes_per_appearance_last_6"] == pytest.approx(60.0)


def test_minutes_per_appearance_is_undefined_when_a_player_never_featured() -> None:
    """There is no answer to how long he plays, and zero would assert one."""

    frame = build_feature_dataset(_panel([(1, 0), (2, 0), (3, 0)]), config=_config()).set_index(
        "gameweek"
    )

    assert frame.loc[3, "appearance_rate_last_6"] == pytest.approx(0.0)
    assert pd.isna(frame.loc[3, "minutes_per_appearance_last_6"])


# --- leakage ----------------------------------------------------------------


def test_the_target_gameweeks_own_minutes_are_excluded() -> None:
    baseline = build_feature_dataset(_panel(), config=_config()).set_index("gameweek")

    altered = MINUTES_HISTORY.copy()
    altered[3] = (4, 0)  # change gameweek 4's own minutes
    changed = build_feature_dataset(_panel(altered), config=_config()).set_index("gameweek")

    assert changed.loc[4, "appearance_rate_last_6"] == baseline.loc[4, "appearance_rate_last_6"]
    assert (
        changed.loc[4, "minutes_per_appearance_last_6"]
        == baseline.loc[4, "minutes_per_appearance_last_6"]
    )


def test_future_gameweeks_do_not_reach_earlier_rows() -> None:
    full = build_feature_dataset(_panel(), config=_config()).set_index("gameweek")
    truncated = build_feature_dataset(_panel(MINUTES_HISTORY[:4]), config=_config()).set_index(
        "gameweek"
    )

    for gameweek in (1, 2, 3, 4):
        for column in ("appearance_rate_last_6", "minutes_per_appearance_last_6"):
            expected = full.loc[gameweek, column]
            actual = truncated.loc[gameweek, column]
            assert (pd.isna(expected) and pd.isna(actual)) or expected == actual


def test_row_order_does_not_change_the_result() -> None:
    panel = _panel()

    ordered = build_feature_dataset(panel, config=_config())
    shuffled = build_feature_dataset(
        panel.sort_values("gameweek", ascending=False).reset_index(drop=True), config=_config()
    )

    assert ordered.equals(shuffled)


def test_one_players_history_does_not_reach_another() -> None:
    first = _panel([(1, 90), (2, 90)], player_id=1)
    second = _panel([(1, 0), (2, 0)], player_id=2)

    frame = build_feature_dataset(
        pd.concat([first, second], ignore_index=True), config=_config()
    ).set_index(["player_id", "gameweek"])

    assert frame.loc[(1, 2), "appearance_rate_last_6"] == pytest.approx(1.0)
    assert frame.loc[(2, 2), "appearance_rate_last_6"] == pytest.approx(0.0)


def test_the_input_frame_is_not_modified() -> None:
    panel = _panel()
    before = panel.copy(deep=True)

    build_feature_dataset(panel, config=_config())

    assert panel.equals(before)


def test_the_indicator_is_not_left_behind_as_a_column() -> None:
    """It is scaffolding for the rolling primitive, not an output."""

    frame = build_feature_dataset(_panel(), config=_config())

    assert "appeared" not in frame.columns
