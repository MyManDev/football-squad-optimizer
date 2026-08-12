"""Tests for the deterministic baseline expected-points projection."""

import dataclasses

import pandas as pd
import pytest
from pandas.testing import assert_series_equal
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.features import (
    CROSS_SEASON_COLUMNS,
    CrossSeasonConfig,
    FeatureConfig,
    build_feature_dataset,
)
from squadopt.prediction import (
    DEFAULT_OPENING_EXPECTED_POINTS,
    BaselineProjectionConfig,
    PredictionConfigurationError,
    baseline_expected_points,
    required_feature_columns,
)

WINDOW = 5
CONFIG = BaselineProjectionConfig(minutes_window=WINDOW, per_90_window=WINDOW)


def _solo_history(points: list[int], minutes: list[int], position: str = "MID") -> pd.DataFrame:
    """One player, ascending gameweeks, fully controlled history."""

    length = len(points)
    return pd.DataFrame(
        {
            "season": pd.Series([SEASON] * length, dtype="string"),
            "gameweek": pd.Series(range(1, length + 1), dtype="int64"),
            "player_id": pd.Series([1] * length, dtype="int64"),
            "name": pd.Series(["Solo"] * length, dtype="string"),
            "team_id": pd.Series([1] * length, dtype="int64"),
            "position": pd.Series([position] * length, dtype="string"),
            "price_tenths": pd.Series([50] * length, dtype="int64"),
            "minutes": pd.Series(minutes, dtype="int64"),
            "total_points": pd.Series(points, dtype="int64"),
        }
    )


def _project(points: list[int], minutes: list[int], **kwargs: object) -> pd.Series:
    frame = _solo_history(points, minutes, **kwargs)  # type: ignore[arg-type]
    features = build_feature_dataset(
        frame,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
    )
    return baseline_expected_points(features, config=CONFIG)


# --- exact hand-computed values ---------------------------------------------


def test_projection_matches_hand_computation() -> None:
    """GW4 reads GW1-3: 12 points over 270 minutes is 4.0 per 90, times 90/90 minutes."""

    result = _project([2, 4, 6, 8, 10], [90] * 5)

    assert_series_equal(
        result,
        pd.Series([3.0, 2.0, 3.0, 4.0, 5.0], name="expected_points"),
    )


def test_partial_playing_time_scales_the_rate_down() -> None:
    """Rate 6.0 per 90 with 45 expected minutes projects half of it."""

    result = _project([3, 3], [45, 45])

    assert result.iloc[1] == pytest.approx(3.0)


def test_a_high_rate_with_low_minutes_is_not_over_projected() -> None:
    """The weakness of a plain points average: a cameo scorer would be overrated."""

    cameo = _project([6, 0], [10, 90])

    # 6 points in 10 minutes is 54 per 90, but only 10 expected minutes.
    assert cameo.iloc[1] == pytest.approx(6.0)


# --- the three precedence cases --------------------------------------------


def test_opening_gameweek_uses_the_declared_fallback() -> None:
    result = _project([5, 5], [90, 90])

    assert result.iloc[0] == DEFAULT_OPENING_EXPECTED_POINTS


def test_fallback_is_per_position() -> None:
    config = dataclasses.replace(
        CONFIG,
        opening_expected_points={"GK": 1.0, "DEF": 2.0, "MID": 3.5, "FWD": 4.0},
    )
    frame = _solo_history([5, 5], [90, 90], position="FWD")
    features = build_feature_dataset(
        frame,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
    )

    result = baseline_expected_points(features, config=config)

    assert result.iloc[0] == 4.0


def test_known_but_idle_history_projects_zero_not_the_fallback() -> None:
    """The player demonstrably did not feature; that is information, not a gap."""

    result = _project([0, 0, 0], [0, 0, 0])

    assert result.iloc[0] == DEFAULT_OPENING_EXPECTED_POINTS
    assert result.iloc[1] == 0.0
    assert result.iloc[2] == 0.0


def test_a_returning_player_recovers_a_projection() -> None:
    result = _project([0, 0, 8, 8], [0, 0, 90, 90])

    assert result.iloc[2] == 0.0
    assert result.iloc[3] > 0.0


# --- guarantees the optimizer depends on ------------------------------------


def test_negative_history_is_clamped_to_zero() -> None:
    """Realized points may be negative; a projection may not be."""

    result = _project([-5, -5, -5], [90, 90, 90])

    assert (result >= 0).all()
    assert result.iloc[2] == 0.0


def test_projection_is_always_finite_and_non_negative() -> None:
    features = build_feature_dataset(make_canonical_gameweeks())

    result = baseline_expected_points(features, config=CONFIG)

    assert result.notna().all()
    assert (result >= 0).all()
    assert str(result.dtype) == "float64"


def test_projection_is_deterministic() -> None:
    features = build_feature_dataset(make_canonical_gameweeks())

    assert_series_equal(
        baseline_expected_points(features, config=CONFIG),
        baseline_expected_points(features, config=CONFIG),
    )


def test_input_frame_is_not_mutated() -> None:
    features = build_feature_dataset(make_canonical_gameweeks())
    original = features.copy(deep=True)

    baseline_expected_points(features, config=CONFIG)

    pd.testing.assert_frame_equal(features, original)


def test_changing_configuration_changes_the_projection_deterministically() -> None:
    # Minutes must vary, or a 2-gameweek and a 5-gameweek window agree by accident
    # and the test would pass for the wrong reason.
    frame = _solo_history([2, 4, 6, 8, 10], [90, 0, 90, 45, 90])
    features = build_feature_dataset(
        frame, config=FeatureConfig(minutes_windows=(2, 5), points_windows=(5,), per_90_window=5)
    )

    narrow = baseline_expected_points(
        features, config=BaselineProjectionConfig(minutes_window=2, per_90_window=5)
    )
    wide = baseline_expected_points(features, config=CONFIG)

    assert not narrow.equals(wide)


# --- configuration validation -----------------------------------------------


def test_required_feature_columns_follow_the_windows() -> None:
    config = BaselineProjectionConfig(minutes_window=3, per_90_window=4)

    assert required_feature_columns(config) == ("minutes_last_3", "points_per_90_last_4")


def test_missing_feature_columns_are_reported_with_a_hint() -> None:
    frame = _solo_history([2, 4], [90, 90])
    mismatched = build_feature_dataset(
        frame, config=FeatureConfig(minutes_windows=(2,), points_windows=(2,), per_90_window=2)
    )

    with pytest.raises(PredictionConfigurationError, match="matching windows"):
        baseline_expected_points(mismatched, config=CONFIG)


def test_configuration_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        CONFIG.minutes_window = 3  # type: ignore[misc]


@pytest.mark.parametrize("window", [0, -1, 1.5, True, "5"])
def test_unusable_windows_are_rejected(window: object) -> None:
    with pytest.raises(PredictionConfigurationError):
        BaselineProjectionConfig(minutes_window=window)  # type: ignore[arg-type]


def test_fallback_must_cover_every_position() -> None:
    with pytest.raises(PredictionConfigurationError, match="must cover exactly"):
        BaselineProjectionConfig(opening_expected_points={"GK": 1.0})


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf"), "3", True])
def test_unusable_fallback_values_are_rejected(value: object) -> None:
    with pytest.raises(PredictionConfigurationError):
        BaselineProjectionConfig(
            opening_expected_points={"GK": value, "DEF": 3.0, "MID": 3.0, "FWD": 3.0}  # type: ignore[dict-item]
        )


def test_default_fallback_is_uniform_across_positions() -> None:
    """A differentiated prior would imply a fitted claim this project has not earned."""

    values = set(BaselineProjectionConfig().opening_expected_points.values())

    assert values == {DEFAULT_OPENING_EXPECTED_POINTS}


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="expects a pandas DataFrame"):
        baseline_expected_points([{"position": "MID"}])  # type: ignore[arg-type]


# --- the opening gameweek, once earlier seasons are carried ------------------


def _two_season_history() -> pd.DataFrame:
    """One player with a full earlier season, then the opening gameweek of the next."""

    rows = [("2023-24", gameweek, 90, 6) for gameweek in (1, 2)]
    rows.append(("2024-25", 1, 90, 0))
    length = len(rows)
    return pd.DataFrame(
        {
            "season": pd.Series([row[0] for row in rows], dtype="string"),
            "gameweek": pd.Series([row[1] for row in rows], dtype="int64"),
            "player_id": pd.Series([1] * length, dtype="int64"),
            "name": pd.Series(["Solo"] * length, dtype="string"),
            "team_id": pd.Series([1] * length, dtype="int64"),
            "position": pd.Series(["MID"] * length, dtype="string"),
            "price_tenths": pd.Series([50] * length, dtype="int64"),
            "minutes": pd.Series([row[2] for row in rows], dtype="int64"),
            "total_points": pd.Series([row[3] for row in rows], dtype="int64"),
        }
    )


def _features_with_carry_over() -> pd.DataFrame:
    return build_feature_dataset(
        _two_season_history(),
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
        cross_season=CrossSeasonConfig(min_minutes=0),
    )


def test_the_opening_gameweek_uses_the_earlier_season_when_it_is_carried() -> None:
    """12 points over 180 minutes is 6.0 per 90, at 90 expected minutes: 6.0."""

    features = _features_with_carry_over()

    result = baseline_expected_points(features, config=CONFIG)
    opening = features["gameweek"] == 1
    later_season = features["season"] == "2024-25"

    assert result.loc[opening & later_season].tolist() == [6.0]


def test_the_opening_gameweek_still_falls_back_without_a_carried_record() -> None:
    """A caller that never attached the carry-over keeps the previous behaviour."""

    features = build_feature_dataset(
        _two_season_history(),
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
    )

    result = baseline_expected_points(features, config=CONFIG)
    opening = (features["gameweek"] == 1) & (features["season"] == "2024-25")

    assert result.loc[opening].tolist() == [DEFAULT_OPENING_EXPECTED_POINTS]


def test_a_player_with_no_earlier_record_still_gets_the_fallback() -> None:
    """A genuine debut has no signal anywhere, so the declared constant remains."""

    history = _two_season_history()
    newcomer = history.loc[history["season"] == "2024-25"].copy(deep=True)
    newcomer["player_id"] = 2
    newcomer["name"] = "Newcomer"
    combined = pd.concat([history, newcomer], ignore_index=True)

    features = build_feature_dataset(
        combined,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
        cross_season=CrossSeasonConfig(min_minutes=0),
    )
    result = baseline_expected_points(features, config=CONFIG)
    debut = (features["player_id"] == 2) & (features["gameweek"] == 1)

    assert result.loc[debut].tolist() == [DEFAULT_OPENING_EXPECTED_POINTS]


def test_within_season_history_still_takes_precedence() -> None:
    """The carry-over fills a gap; it must not override recent form."""

    rows = _two_season_history()
    extended = pd.concat(
        [
            rows,
            rows.loc[rows["season"] == "2024-25"].assign(gameweek=2, minutes=90, total_points=0),
        ],
        ignore_index=True,
    )

    features = build_feature_dataset(
        extended,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
        cross_season=CrossSeasonConfig(min_minutes=0),
    )
    result = baseline_expected_points(features, config=CONFIG)
    second = (features["season"] == "2024-25") & (features["gameweek"] == 2)

    # Gameweek 1 of the new season scored nothing, so within-season form says 0.0 —
    # not the 6.0 the earlier season would have suggested.
    assert result.loc[second].tolist() == [0.0]


def test_a_carried_projection_is_still_clamped_and_finite() -> None:
    history = _two_season_history()
    history.loc[history["season"] == "2023-24", "total_points"] = -6

    features = build_feature_dataset(
        history,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
        cross_season=CrossSeasonConfig(min_minutes=0),
    )
    result = baseline_expected_points(features, config=CONFIG)

    assert result.notna().all()
    assert (result >= 0).all()


def test_the_builder_attaches_the_carry_over_only_when_asked() -> None:
    history = _two_season_history()
    settings = FeatureConfig(
        minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
    )

    without = build_feature_dataset(history, config=settings)
    with_carry = build_feature_dataset(
        history, config=settings, cross_season=CrossSeasonConfig(min_minutes=0)
    )

    assert not [column for column in CROSS_SEASON_COLUMNS if column in without.columns]
    assert list(with_carry.columns)[-2:] == list(CROSS_SEASON_COLUMNS)


def test_a_carried_opening_projection_ignores_later_gameweeks() -> None:
    """The leakage rule holds across the new path too."""

    history = _two_season_history()
    baseline = baseline_expected_points(_features_with_carry_over(), config=CONFIG)

    mutated = pd.concat(
        [
            history,
            history.loc[history["season"] == "2024-25"].assign(
                gameweek=2, minutes=90, total_points=999
            ),
        ],
        ignore_index=True,
    )
    features = build_feature_dataset(
        mutated,
        config=FeatureConfig(
            minutes_windows=(WINDOW,), points_windows=(WINDOW,), per_90_window=WINDOW
        ),
        cross_season=CrossSeasonConfig(min_minutes=0),
    )
    rebuilt = baseline_expected_points(features, config=CONFIG)
    opening = (features["season"] == "2024-25") & (features["gameweek"] == 1)

    assert rebuilt.loc[opening].tolist() == baseline.iloc[[2]].tolist()
