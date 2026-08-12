"""Tests for carrying a player's earlier-season record into a new season.

This is the only feature that deliberately crosses the season boundary the rest of
the layer defends, so it is tested against that boundary specifically rather than
relying on the existing rolling-feature tests.
"""

import dataclasses

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.features import (
    CROSS_SEASON_COLUMNS,
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    FeatureConfigurationError,
    attach_cross_season_features,
    cross_season_features,
)

# min_minutes=0 keeps the threshold out of the way of the arithmetic tests.
OPEN_CONFIG = CrossSeasonConfig(decay=0.5, min_minutes=0)


def _panel(rows: list[tuple[str, int, int, int, int]]) -> pd.DataFrame:
    """Build a canonical panel from (season, gameweek, player_id, minutes, points)."""

    return pd.DataFrame(
        {
            "season": pd.Series([row[0] for row in rows], dtype="string"),
            "gameweek": pd.Series([row[1] for row in rows], dtype="int64"),
            "player_id": pd.Series([row[2] for row in rows], dtype="int64"),
            "name": pd.Series([f"P{row[2]}" for row in rows], dtype="string"),
            "team_id": pd.Series([1] * len(rows), dtype="int64"),
            "position": pd.Series(["MID"] * len(rows), dtype="string"),
            "price_tenths": pd.Series([50] * len(rows), dtype="int64"),
            "minutes": pd.Series([row[3] for row in rows], dtype="int64"),
            "total_points": pd.Series([row[4] for row in rows], dtype="int64"),
        }
    )


TWO_SEASONS = _panel(
    [
        ("2023-24", 1, 1, 90, 4),
        ("2023-24", 2, 1, 90, 6),
        ("2024-25", 1, 1, 90, 3),
    ]
)


# --- exact arithmetic -------------------------------------------------------


def test_a_single_prior_season_is_carried_verbatim() -> None:
    """2023-24 gave 10 points in 180 minutes over 2 gameweeks: 5.0 per 90, 90 per gameweek."""

    features = cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)
    later = TWO_SEASONS["season"] == "2024-25"

    assert features.loc[later, PRIOR_RATE_COLUMN].tolist() == [5.0]
    assert features.loc[later, PRIOR_MINUTES_COLUMN].tolist() == [90.0]


def test_a_nearer_season_is_weighted_above_a_further_one() -> None:
    """With decay 0.5: 0.5x(180min, 10pts) + 1.0x(90min, 9pts) = 180min, 14pts -> 7.0 per 90."""

    panel = _panel(
        [
            ("2022-23", 1, 1, 90, 4),
            ("2022-23", 2, 1, 90, 6),
            ("2023-24", 1, 1, 90, 9),
            ("2024-25", 1, 1, 90, 0),
        ]
    )

    features = cross_season_features(panel, config=OPEN_CONFIG)
    newest = panel["season"] == "2024-25"

    assert features.loc[newest, PRIOR_RATE_COLUMN].tolist() == [7.0]
    assert features.loc[newest, PRIOR_MINUTES_COLUMN].tolist() == [90.0]


def test_a_decay_of_one_weights_every_prior_season_equally() -> None:
    panel = _panel(
        [
            ("2022-23", 1, 1, 90, 3),
            ("2023-24", 1, 1, 90, 9),
            ("2024-25", 1, 1, 90, 0),
        ]
    )

    features = cross_season_features(panel, config=CrossSeasonConfig(decay=1.0, min_minutes=0))
    newest = panel["season"] == "2024-25"

    # 12 points over 180 minutes is 6.0 per 90.
    assert features.loc[newest, PRIOR_RATE_COLUMN].tolist() == [6.0]


def test_the_value_is_constant_within_a_season() -> None:
    """It summarises what was known before the season, so it cannot move during it."""

    panel = _panel(
        [
            ("2023-24", 1, 1, 90, 5),
            ("2024-25", 1, 1, 90, 1),
            ("2024-25", 2, 1, 90, 20),
            ("2024-25", 3, 1, 0, 0),
        ]
    )

    features = cross_season_features(panel, config=OPEN_CONFIG)
    later = features.loc[panel["season"] == "2024-25", PRIOR_RATE_COLUMN]

    assert later.nunique() == 1


# --- the boundary ----------------------------------------------------------


def test_a_players_first_season_has_no_carry_over() -> None:
    features = cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)
    first = TWO_SEASONS["season"] == "2023-24"

    assert features.loc[first, list(CROSS_SEASON_COLUMNS)].isna().all().all()


def test_a_later_season_cannot_change_an_earlier_one() -> None:
    """The direction of the crossing is the whole point: backwards only."""

    baseline = cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    extended = pd.concat([TWO_SEASONS, _panel([("2025-26", 1, 1, 90, 99)])], ignore_index=True)
    rebuilt = cross_season_features(extended, config=OPEN_CONFIG)

    assert_frame_equal(rebuilt.iloc[: len(TWO_SEASONS)], baseline)


def test_rewriting_a_season_cannot_change_its_own_carry_over() -> None:
    """It reads completed earlier seasons only, never the season it belongs to."""

    baseline = cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    mutated = TWO_SEASONS.copy(deep=True)
    current = mutated["season"] == "2024-25"
    mutated.loc[current, "total_points"] = 500
    mutated.loc[current, "minutes"] = 1

    assert_frame_equal(cross_season_features(mutated, config=OPEN_CONFIG), baseline)


def test_rewriting_an_earlier_season_does_change_the_later_one() -> None:
    """The complement: if it never moved, nothing would be carried at all."""

    baseline = cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    mutated = TWO_SEASONS.copy(deep=True)
    mutated.loc[mutated["season"] == "2023-24", "total_points"] = 0
    rebuilt = cross_season_features(mutated, config=OPEN_CONFIG)

    later = TWO_SEASONS["season"] == "2024-25"
    assert rebuilt.loc[later, PRIOR_RATE_COLUMN].tolist() == [0.0]
    assert baseline.loc[later, PRIOR_RATE_COLUMN].tolist() == [5.0]


def test_one_players_history_never_reaches_another() -> None:
    panel = _panel(
        [
            ("2023-24", 1, 1, 90, 10),
            ("2024-25", 1, 1, 90, 0),
            ("2024-25", 1, 2, 90, 0),
        ]
    )

    features = cross_season_features(panel, config=OPEN_CONFIG)
    later = panel["season"] == "2024-25"

    # Player 1 inherits from their own 2023-24; player 2 has no earlier season at all.
    assert features.loc[later & (panel["player_id"] == 1), PRIOR_RATE_COLUMN].tolist() == [10.0]
    assert features.loc[later & (panel["player_id"] == 2), PRIOR_RATE_COLUMN].isna().all()


def test_an_explicit_season_order_decides_which_season_is_earlier() -> None:
    reversed_features = cross_season_features(
        TWO_SEASONS, config=OPEN_CONFIG, season_order=["2024-25", "2023-24"]
    )

    # With the order inverted, 2023-24 becomes the later season and inherits instead.
    assert (
        reversed_features.loc[TWO_SEASONS["season"] == "2023-24", PRIOR_RATE_COLUMN].notna().any()
    )
    assert reversed_features.loc[TWO_SEASONS["season"] == "2024-25", PRIOR_RATE_COLUMN].isna().all()


# --- the reliability threshold ---------------------------------------------


def test_a_thin_history_is_left_missing_rather_than_reported() -> None:
    """A rate from two substitute appearances is noise dressed as a measurement."""

    panel = _panel([("2023-24", 1, 1, 20, 2), ("2024-25", 1, 1, 90, 0)])

    features = cross_season_features(panel, config=CrossSeasonConfig(min_minutes=270))

    assert features[PRIOR_RATE_COLUMN].isna().all()


def test_a_sufficient_history_passes_the_threshold() -> None:
    panel = _panel(
        [("2023-24", gameweek, 1, 90, 3) for gameweek in (1, 2, 3)] + [("2024-25", 1, 1, 90, 0)]
    )

    features = cross_season_features(panel, config=CrossSeasonConfig(min_minutes=270))
    later = panel["season"] == "2024-25"

    assert features.loc[later, PRIOR_RATE_COLUMN].tolist() == [3.0]


def test_the_threshold_applies_to_decayed_minutes() -> None:
    """Discounted history counts less towards being trustworthy, as it should."""

    panel = _panel(
        [("2022-23", gameweek, 1, 90, 3) for gameweek in (1, 2, 3)]
        + [("2023-24", 1, 2, 90, 1)]  # another player, so 2023-24 exists in the panel
        + [("2024-25", 1, 1, 90, 0)]
    )

    # Player 1's 270 minutes sit two seasons back, so 0.5 ** 1 leaves 135 effective
    # minutes, below the threshold.
    features = cross_season_features(panel, config=CrossSeasonConfig(decay=0.5, min_minutes=270))
    target = (panel["season"] == "2024-25") & (panel["player_id"] == 1)

    assert features.loc[target, PRIOR_RATE_COLUMN].isna().all()


# --- frame behaviour --------------------------------------------------------


def test_the_result_is_aligned_to_the_input_index() -> None:
    panel = TWO_SEASONS.set_axis([10, 11, 12], axis=0)

    features = cross_season_features(panel, config=OPEN_CONFIG)

    assert features.index.tolist() == [10, 11, 12]


def test_values_do_not_depend_on_row_order() -> None:
    shuffled = TWO_SEASONS.iloc[::-1].reset_index(drop=True)

    ordered = attach_cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)
    reordered = attach_cross_season_features(shuffled, config=OPEN_CONFIG)

    assert_frame_equal(reordered, ordered)


def test_attaching_returns_canonical_order_with_the_new_columns_last() -> None:
    combined = attach_cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    assert list(combined.columns)[-2:] == list(CROSS_SEASON_COLUMNS)
    assert combined.index.tolist() == list(range(len(TWO_SEASONS)))


def test_the_input_panel_is_not_mutated() -> None:
    original = TWO_SEASONS.copy(deep=True)

    attach_cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    assert_frame_equal(TWO_SEASONS, original)


def test_attaching_twice_is_refused() -> None:
    once = attach_cross_season_features(TWO_SEASONS, config=OPEN_CONFIG)

    with pytest.raises(FeatureConfigurationError, match="already present"):
        attach_cross_season_features(once, config=OPEN_CONFIG)


def test_the_rolling_group_key_is_untouched() -> None:
    """The carry-over adds a feature; it must not relax the season-scoped guard."""

    from squadopt.data.schema import PLAYER_GROUP_COLUMNS

    assert PLAYER_GROUP_COLUMNS == ("season", "player_id")


# --- guards ----------------------------------------------------------------


def test_configuration_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        OPEN_CONFIG.decay = 0.9  # type: ignore[misc]


@pytest.mark.parametrize("decay", [0.0, -0.1, 1.5, "0.5", True])
def test_an_unusable_decay_is_rejected(decay: object) -> None:
    with pytest.raises(FeatureConfigurationError, match="decay"):
        CrossSeasonConfig(decay=decay)  # type: ignore[arg-type]


@pytest.mark.parametrize("minutes", [-1, 1.5, "270", True])
def test_an_unusable_minimum_is_rejected(minutes: object) -> None:
    with pytest.raises(FeatureConfigurationError, match="min_minutes"):
        CrossSeasonConfig(min_minutes=minutes)  # type: ignore[arg-type]


def test_a_panel_missing_canonical_columns_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="missing required columns"):
        cross_season_features(TWO_SEASONS.drop(columns=["minutes"]))


def test_an_empty_panel_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="at least one row"):
        cross_season_features(TWO_SEASONS.iloc[:0])


def test_a_non_dataframe_panel_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="pandas DataFrame"):
        cross_season_features([{"season": "2024-25"}])  # type: ignore[arg-type]


def test_distance_counts_seasons_present_not_calendar_years() -> None:
    """A documented consequence: an absent season is not a gap, because it is not there.

    Deriving calendar distance would mean parsing season labels, which this project
    treats as a convention rather than a guarantee. Two consecutive entries in the
    panel are one step apart whatever their labels say, and `season_order` is how a
    caller states something different.
    """

    adjacent = _panel([("2023-24", 1, 1, 90, 9), ("2024-25", 1, 1, 90, 0)])
    labelled_gap = _panel([("2022-23", 1, 1, 90, 9), ("2024-25", 1, 1, 90, 0)])

    near = cross_season_features(adjacent, config=OPEN_CONFIG)
    far = cross_season_features(labelled_gap, config=OPEN_CONFIG)

    assert near.iloc[1][PRIOR_MINUTES_COLUMN] == far.iloc[1][PRIOR_MINUTES_COLUMN]
    assert near.iloc[1][PRIOR_RATE_COLUMN] == far.iloc[1][PRIOR_RATE_COLUMN]


@pytest.mark.parametrize("decay", [0.2, 0.5, 1.0])
def test_decay_cancels_when_only_one_earlier_season_exists(decay: float) -> None:
    """Both outputs are ratios of equally weighted sums, so a lone prior season is unaffected.

    Decay changes the *mix* of several earlier seasons; it does not scale a single
    one. Where it still bites for a thin history is the ``min_minutes`` threshold,
    which compares discounted minutes rather than raw ones.
    """

    panel = _panel(
        [
            ("2022-23", 1, 1, 90, 9),
            ("2023-24", 1, 2, 90, 1),  # another player, so the distance is two steps
            ("2024-25", 1, 1, 90, 0),
        ]
    )

    features = cross_season_features(panel, config=CrossSeasonConfig(decay=decay, min_minutes=0))
    target = (panel["season"] == "2024-25") & (panel["player_id"] == 1)

    assert features.loc[target, PRIOR_MINUTES_COLUMN].tolist() == [90.0]
    assert features.loc[target, PRIOR_RATE_COLUMN].tolist() == [9.0]
