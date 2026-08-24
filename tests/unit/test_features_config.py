"""Tests for feature configuration, naming, and the rolling primitive's guards."""

import dataclasses

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import make_canonical_gameweeks

from squadopt.features import (
    FeatureConfig,
    FeatureConfigurationError,
    build_feature_dataset,
    feature_column_names,
    per_90_feature_name,
    rolling_feature_name,
    shifted_rolling_mean,
    shifted_rolling_sum,
    shifted_team_rolling_mean,
)

# --- configuration ----------------------------------------------------------


def test_default_configuration_declares_the_expected_features() -> None:
    assert feature_column_names(FeatureConfig()) == (
        "minutes_last_3",
        "minutes_last_5",
        "points_last_3",
        "points_last_5",
        "points_per_90_last_5",
    )


def test_windows_are_normalized_so_naming_is_order_independent() -> None:
    config = FeatureConfig(points_windows=(5, 3, 5))

    assert config.points_windows == (3, 5)


def test_configuration_is_frozen() -> None:
    config = FeatureConfig()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.min_periods = 3  # type: ignore[misc]


@pytest.mark.parametrize("windows", [(), (0,), (-1,), ("3",), (1.5,), (True,), "35"])
def test_unusable_windows_are_rejected(windows: object) -> None:
    with pytest.raises(FeatureConfigurationError):
        FeatureConfig(points_windows=windows)  # type: ignore[arg-type]


def test_min_periods_cannot_exceed_the_smallest_window() -> None:
    """Otherwise that window could never produce a value at all."""

    with pytest.raises(FeatureConfigurationError, match="cannot exceed the smallest window"):
        FeatureConfig(points_windows=(3,), minutes_windows=(3,), per_90_window=3, min_periods=4)


@pytest.mark.parametrize("min_periods", [0, -1])
def test_min_periods_must_be_positive(min_periods: int) -> None:
    with pytest.raises(FeatureConfigurationError, match="min_periods"):
        FeatureConfig(min_periods=min_periods)


def test_changing_configuration_changes_the_output_deterministically() -> None:
    canonical = make_canonical_gameweeks()

    narrow = build_feature_dataset(canonical, config=FeatureConfig(points_windows=(2,)))
    wide = build_feature_dataset(canonical, config=FeatureConfig(points_windows=(4,)))

    assert "points_last_2" in narrow.columns
    assert "points_last_4" in wide.columns
    assert not narrow["points_last_2"].equals(wide["points_last_4"])


# --- naming -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "window", "expected"),
    [("minutes", 3, "minutes_last_3"), ("total_points", 5, "points_last_5")],
)
def test_feature_names_are_derived_from_declared_stems(
    column: str,
    window: int,
    expected: str,
) -> None:
    assert rolling_feature_name(column, window) == expected


def test_a_column_without_a_declared_stem_is_rejected() -> None:
    with pytest.raises(FeatureConfigurationError, match="No feature-name stem"):
        rolling_feature_name("saves", 5)


def test_per_90_name_includes_its_window() -> None:
    assert per_90_feature_name(4) == "points_per_90_last_4"


# --- rolling primitive guards -----------------------------------------------


def test_rolling_refuses_an_unsorted_frame() -> None:
    """The builder sorts once, so the primitive verifies instead of re-sorting."""

    canonical = make_canonical_gameweeks()
    unsorted = canonical.sort_values(["player_id", "gameweek"], ascending=[True, False])

    with pytest.raises(FeatureConfigurationError, match="ascend in gameweek order"):
        shifted_rolling_mean(unsorted, "total_points", 3)


# A club's players all share a gameweek, so a player-grain frame grouped by team has a
# repeated gameweek in every group. `shift(1)` moves by row rather than by gameweek, so the
# second row of a repeated gameweek used to start its window at the first — a value from the
# very gameweek the feature describes. Measured before the guard existed, with two players of
# one club and window=2:
#
#     gameweek  player_id  total_points  rolled
#            1         10           2.0     NaN
#            1         11           8.0     2.0   <- player 10's same-gameweek value
#            2         11          40.0     6.0   <- mean(8.0, 4.0), includes gameweek 2
#
# No error, no warning, just wrong numbers. The ordering guard did not catch it because
# `is_monotonic_increasing` is non-strict: [1, 1, 2, 2] passes.
REPEATED_GAMEWEEKS = pd.DataFrame(
    {
        "season": ["2025-26"] * 6,
        "team_id": [1] * 6,
        "player_id": [10, 11, 10, 11, 10, 11],
        "gameweek": [1, 1, 2, 2, 3, 3],
        "total_points": [2.0, 8.0, 4.0, 40.0, 6.0, 60.0],
    }
)


def test_the_team_primitive_refuses_a_player_grain_frame() -> None:
    """The case the guard exists for: right function, wrong grain, silent leak."""

    with pytest.raises(FeatureConfigurationError, match="at most one row per") as raised:
        shifted_team_rolling_mean(REPEATED_GAMEWEEKS, "total_points", 2)

    # The message has to name what collided, not merely that something did.
    assert "'season', 'team_id'" in str(raised.value)
    assert "('2025-26', 1, 1)" in str(raised.value)


@pytest.mark.parametrize("rolling", [shifted_rolling_mean, shifted_rolling_sum])
def test_the_player_primitives_refuse_a_repeated_gameweek(rolling) -> None:  # type: ignore[no-untyped-def]
    """The canonical key rules this out upstream, but these are public entry points."""

    repeated = REPEATED_GAMEWEEKS.loc[REPEATED_GAMEWEEKS["player_id"] == 10].assign(
        gameweek=[1, 1, 2]
    )

    with pytest.raises(FeatureConfigurationError, match="at most one row per"):
        rolling(repeated, "total_points", 2)


def test_a_repeated_gameweek_and_an_unsorted_frame_are_different_faults() -> None:
    """One message must not stand in for the other; the fixes are not the same."""

    canonical = make_canonical_gameweeks()
    unsorted = canonical.sort_values(["player_id", "gameweek"], ascending=[True, False])

    with pytest.raises(FeatureConfigurationError, match="ascend in gameweek order"):
        shifted_rolling_mean(unsorted, "total_points", 3)
    with pytest.raises(FeatureConfigurationError, match="at most one row per"):
        shifted_team_rolling_mean(REPEATED_GAMEWEEKS, "total_points", 2)


def test_one_row_per_gameweek_is_the_shape_the_real_callers_pass() -> None:
    """Behaviour is unchanged for a frame with the grain the guard requires."""

    single = REPEATED_GAMEWEEKS.loc[REPEATED_GAMEWEEKS["player_id"] == 10].reset_index(drop=True)
    rolled = shifted_team_rolling_mean(single, "total_points", 2, min_periods=1)

    # Gameweek 1 has nothing before it; 2 sees only 1; 3 sees 1 and 2.
    assert rolled.isna().tolist() == [True, False, False]
    assert rolled.tolist()[1:] == [2.0, 3.0]


def test_rolling_refuses_a_pre_match_column() -> None:
    """Price is already known at the deadline; shifting it would discard information."""

    canonical = make_canonical_gameweeks()

    with pytest.raises(FeatureConfigurationError, match="known before its gameweek"):
        shifted_rolling_mean(canonical, "price_tenths", 3)


def test_rolling_refuses_an_unclassified_column() -> None:
    """Adding a canonical column must force an explicit time-of-knowledge decision."""

    canonical = make_canonical_gameweeks().assign(mystery_metric=1.0)

    with pytest.raises(Exception, match="no time-of-knowledge classification"):
        shifted_rolling_mean(canonical, "mystery_metric", 3)


def test_rolling_refuses_an_absent_column() -> None:
    with pytest.raises(FeatureConfigurationError, match="not present"):
        shifted_rolling_mean(make_canonical_gameweeks(), "saves", 3)


@pytest.mark.parametrize(("window", "min_periods"), [(0, 1), (3, 0), (3, 4)])
def test_rolling_rejects_inconsistent_window_arguments(window: int, min_periods: int) -> None:
    with pytest.raises(FeatureConfigurationError):
        shifted_rolling_mean(make_canonical_gameweeks(), "minutes", window, min_periods=min_periods)


# --- builder guards ---------------------------------------------------------


def test_builder_requires_the_canonical_columns() -> None:
    canonical = make_canonical_gameweeks().drop(columns=["minutes"])

    with pytest.raises(FeatureConfigurationError, match="missing required columns"):
        build_feature_dataset(canonical)


def test_builder_refuses_to_run_twice_on_its_own_output() -> None:
    """Re-running would silently build features from features."""

    built = build_feature_dataset(make_canonical_gameweeks())

    with pytest.raises(FeatureConfigurationError, match="collide with existing columns"):
        build_feature_dataset(built)


def test_builder_rejects_duplicate_columns() -> None:
    canonical = make_canonical_gameweeks()
    duplicated = pd.concat([canonical, canonical[["minutes"]]], axis=1)

    with pytest.raises(FeatureConfigurationError, match="Duplicate columns"):
        build_feature_dataset(duplicated)


def test_builder_rejects_non_dataframe_input() -> None:
    with pytest.raises(FeatureConfigurationError, match="expects a pandas DataFrame"):
        build_feature_dataset([{"season": "2025-26"}])  # type: ignore[arg-type]


def test_feature_errors_are_data_errors_not_optimizer_errors() -> None:
    from squadopt import SquadOptimizationError
    from squadopt.data import DataError

    assert issubclass(FeatureConfigurationError, DataError)
    assert not issubclass(FeatureConfigurationError, SquadOptimizationError)
