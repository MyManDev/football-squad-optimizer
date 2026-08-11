"""Proof that features for gameweek t cannot see gameweek t or later.

Structural arguments are claims until they are measured, so leakage is attacked
from five independent directions:

1. future-mutation invariance: changing later outcomes leaves earlier features intact;
2. truncation equivalence: features do not change when later gameweeks never existed;
3. season isolation: one season's history never enters another's;
4. row-order invariance: results do not depend on how the source was ordered;
5. exact values: hand-computed numbers, so the test is not re-deriving the code.

Truncation equivalence is the strongest of the five. Mutation testing can be
fooled by an operation that reads the whole column's shape rather than its
values, such as a whole-dataset normalization; deleting the future cannot.
"""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_canonical_gameweeks,
    make_two_season_gameweeks,
)

from squadopt.features import (
    DEFAULT_FEATURE_CONFIG,
    FeatureConfig,
    build_feature_dataset,
    feature_column_names,
)

FEATURES = feature_column_names(DEFAULT_FEATURE_CONFIG)
SPLIT_GAMEWEEK = 5
OUTCOME_COLUMNS_UNDER_TEST = ("total_points", "minutes")


def _features_before(frame: pd.DataFrame, gameweek: int, season: str = SEASON) -> pd.DataFrame:
    """Return the feature block for rows strictly before a gameweek."""

    built = build_feature_dataset(frame)
    earlier = built.loc[(built["season"] == season) & (built["gameweek"] < gameweek)]
    return earlier.loc[:, ["player_id", "gameweek", *FEATURES]].reset_index(drop=True)


# --- 1. future-mutation invariance ------------------------------------------


@pytest.mark.parametrize("column", OUTCOME_COLUMNS_UNDER_TEST)
def test_mutating_future_outcomes_leaves_earlier_features_unchanged(column: str) -> None:
    canonical = make_canonical_gameweeks()
    baseline = _features_before(canonical, SPLIT_GAMEWEEK)

    mutated = canonical.copy(deep=True)
    future = mutated["gameweek"] >= SPLIT_GAMEWEEK
    mutated.loc[future, column] = mutated.loc[future, column] + 1000

    assert_frame_equal(_features_before(mutated, SPLIT_GAMEWEEK), baseline)


def test_mutating_the_target_gameweek_itself_changes_nothing_for_that_gameweek() -> None:
    """The canonical failure: gameweek t's own result entering its own feature."""

    canonical = make_canonical_gameweeks()
    target = canonical["gameweek"] == SPLIT_GAMEWEEK

    baseline = build_feature_dataset(canonical)
    mutated = canonical.copy(deep=True)
    mutated.loc[target, "total_points"] = 999

    result = build_feature_dataset(mutated)
    rows = result["gameweek"] == SPLIT_GAMEWEEK

    assert_frame_equal(
        result.loc[rows, list(FEATURES)].reset_index(drop=True),
        baseline.loc[rows, list(FEATURES)].reset_index(drop=True),
    )


def test_removing_all_future_players_does_not_alter_earlier_features() -> None:
    canonical = make_canonical_gameweeks()
    baseline = _features_before(canonical, SPLIT_GAMEWEEK)

    dropped = canonical.loc[
        ~((canonical["gameweek"] >= SPLIT_GAMEWEEK) & (canonical["player_id"] % 2 == 0))
    ].reset_index(drop=True)

    assert_frame_equal(_features_before(dropped, SPLIT_GAMEWEEK), baseline)


# --- 2. truncation equivalence ----------------------------------------------


def test_features_match_a_world_where_the_future_never_existed() -> None:
    """Catches whole-dataset operations that value mutation cannot detect."""

    canonical = make_canonical_gameweeks()
    truncated = canonical.loc[canonical["gameweek"] < SPLIT_GAMEWEEK].reset_index(drop=True)

    assert_frame_equal(
        _features_before(truncated, SPLIT_GAMEWEEK),
        _features_before(canonical, SPLIT_GAMEWEEK),
    )


@pytest.mark.parametrize("gameweek", [2, 3, 4, 6, 8])
def test_truncation_equivalence_holds_at_every_cut_point(gameweek: int) -> None:
    canonical = make_canonical_gameweeks()
    truncated = canonical.loc[canonical["gameweek"] < gameweek].reset_index(drop=True)

    assert_frame_equal(
        _features_before(truncated, gameweek),
        _features_before(canonical, gameweek),
    )


# --- 3. season isolation ----------------------------------------------------


def test_a_new_season_starts_with_no_history() -> None:
    two_seasons = make_two_season_gameweeks()

    built = build_feature_dataset(two_seasons)
    opening = built.loc[(built["season"] == SEASON) & (built["gameweek"] == 1)]

    assert opening[list(FEATURES)].isna().all().all()


def test_earlier_season_results_never_enter_the_later_season() -> None:
    two_seasons = make_two_season_gameweeks()
    single_season = make_canonical_gameweeks()

    from_pair = build_feature_dataset(two_seasons)
    from_pair = from_pair.loc[from_pair["season"] == SEASON].reset_index(drop=True)
    from_alone = build_feature_dataset(single_season).reset_index(drop=True)

    assert_frame_equal(from_pair[list(FEATURES)], from_alone[list(FEATURES)])


def test_mutating_the_earlier_season_cannot_move_the_later_one() -> None:
    two_seasons = make_two_season_gameweeks()
    baseline = build_feature_dataset(two_seasons)
    baseline = baseline.loc[baseline["season"] == SEASON, list(FEATURES)].reset_index(drop=True)

    mutated = two_seasons.copy(deep=True)
    previous = mutated["season"] == PREVIOUS_SEASON
    mutated.loc[previous, "total_points"] = -777

    result = build_feature_dataset(mutated)
    result = result.loc[result["season"] == SEASON, list(FEATURES)].reset_index(drop=True)

    assert_frame_equal(result, baseline)


# --- 4. row-order invariance ------------------------------------------------


def test_features_do_not_depend_on_input_row_order() -> None:
    canonical = make_canonical_gameweeks()
    baseline = build_feature_dataset(canonical)

    reversed_rows = canonical.iloc[::-1].reset_index(drop=True)
    interleaved = canonical.sort_values(["gameweek", "player_id"]).reset_index(drop=True)

    assert_frame_equal(build_feature_dataset(reversed_rows), baseline)
    assert_frame_equal(build_feature_dataset(interleaved), baseline)


def test_features_do_not_depend_on_the_input_index() -> None:
    canonical = make_canonical_gameweeks()
    reindexed = canonical.set_axis(range(500, 500 + len(canonical)), axis=0)

    assert_frame_equal(build_feature_dataset(reindexed), build_feature_dataset(canonical))


def test_scattered_player_rows_are_still_grouped_correctly() -> None:
    """Groups need not be contiguous; only order within a group matters."""

    canonical = make_canonical_gameweeks()
    scattered = canonical.sort_values(["gameweek", "team_id"]).reset_index(drop=True)

    assert_frame_equal(build_feature_dataset(scattered), build_feature_dataset(canonical))


# --- 5. exact hand-computed values ------------------------------------------


def _single_player_frame(points: list[int], minutes: list[int]) -> pd.DataFrame:
    gameweeks = list(range(1, len(points) + 1))
    return pd.DataFrame(
        {
            "season": pd.Series([SEASON] * len(points), dtype="string"),
            "gameweek": pd.Series(gameweeks, dtype="int64"),
            "player_id": pd.Series([1] * len(points), dtype="int64"),
            "name": pd.Series(["Solo"] * len(points), dtype="string"),
            "team_id": pd.Series([1] * len(points), dtype="int64"),
            "position": pd.Series(["MID"] * len(points), dtype="string"),
            "price_tenths": pd.Series([50] * len(points), dtype="int64"),
            "minutes": pd.Series(minutes, dtype="int64"),
            "total_points": pd.Series(points, dtype="int64"),
        }
    )


def test_rolling_points_mean_matches_hand_computation() -> None:
    frame = _single_player_frame([2, 4, 6, 8, 10], [90] * 5)

    built = build_feature_dataset(frame, config=FeatureConfig(points_windows=(3,), per_90_window=3))

    # GW1 has no prior gameweek; GW5 averages GW2-4 only, because the window is 3.
    assert_series_equal(
        built["points_last_3"],
        pd.Series([float("nan"), 2.0, 3.0, 4.0, 6.0], name="points_last_3"),
    )


def test_rolling_minutes_mean_matches_hand_computation() -> None:
    frame = _single_player_frame([1] * 5, [90, 0, 45, 90, 60])

    built = build_feature_dataset(
        frame, config=FeatureConfig(minutes_windows=(2,), per_90_window=2)
    )

    assert_series_equal(
        built["minutes_last_2"],
        pd.Series([float("nan"), 90.0, 45.0, 22.5, 67.5], name="minutes_last_2"),
    )


def test_points_per_90_is_a_ratio_of_sums() -> None:
    frame = _single_player_frame([2, 4, 6, 8, 10], [90] * 5)

    built = build_feature_dataset(frame, config=FeatureConfig(per_90_window=3))

    # GW5: previous three gameweeks are 4+6+8 = 18 points over 270 minutes.
    assert built.loc[4, "points_per_90_last_3"] == pytest.approx(18 / 270 * 90)


def test_points_per_90_weights_a_cameo_below_a_full_match() -> None:
    """A mean of per-gameweek rates would rate these equally; a ratio of sums does not."""

    steady = _single_player_frame([4, 4], [90, 90])
    cameo = _single_player_frame([4, 4], [10, 90])

    config = FeatureConfig(per_90_window=1, minutes_windows=(1,), points_windows=(1,))
    steady_rate = build_feature_dataset(steady, config=config).loc[1, "points_per_90_last_1"]
    cameo_rate = build_feature_dataset(cameo, config=config).loc[1, "points_per_90_last_1"]

    assert steady_rate == pytest.approx(4.0)
    assert cameo_rate == pytest.approx(36.0)


def test_points_per_90_is_undefined_when_no_minutes_were_played() -> None:
    """Undefined, not zero: the prediction layer decides what no minutes implies."""

    frame = _single_player_frame([0, 0, 5], [0, 0, 90])

    built = build_feature_dataset(frame, config=FeatureConfig(per_90_window=2))

    assert pd.isna(built.loc[1, "points_per_90_last_2"])
    assert pd.isna(built.loc[2, "points_per_90_last_2"])


# --- gap policy -------------------------------------------------------------


def test_the_first_gameweek_of_a_season_has_no_features() -> None:
    built = build_feature_dataset(make_canonical_gameweeks())
    opening = built.loc[built["gameweek"] == 1]

    assert opening[list(FEATURES)].isna().all().all()


def test_missing_early_values_are_never_filled_from_later_gameweeks() -> None:
    """A back-fill would import the future into the past; gaps must stay gaps."""

    built = build_feature_dataset(make_canonical_gameweeks())
    first_rows = built.loc[built["gameweek"] == 1, "points_last_5"]

    assert first_rows.isna().all()


def test_partial_history_is_used_rather_than_discarded() -> None:
    """min_periods=1, so gameweek 2 already carries one real prior observation."""

    built = build_feature_dataset(make_canonical_gameweeks())
    second = built.loc[built["gameweek"] == 2, "points_last_5"]

    assert second.notna().all()


def test_strict_min_periods_withholds_values_until_the_window_is_full() -> None:
    frame = _single_player_frame([2, 4, 6, 8, 10], [90] * 5)

    built = build_feature_dataset(
        frame, config=FeatureConfig(points_windows=(3,), per_90_window=3, min_periods=3)
    )

    assert built["points_last_3"].isna().tolist() == [True, True, True, False, False]


# --- structural guarantees --------------------------------------------------


def test_no_target_column_is_produced() -> None:
    """Features are already shifted, so the row's own total_points is the label."""

    built = build_feature_dataset(make_canonical_gameweeks())

    assert "target_next_gw_points" not in built.columns
    assert not [column for column in built.columns if column.startswith("target")]


def test_input_frame_is_not_mutated() -> None:
    canonical = make_canonical_gameweeks()
    original = canonical.copy(deep=True)

    built = build_feature_dataset(canonical)
    built.loc[0, "points_last_5"] = -1.0

    assert_frame_equal(canonical, original)


def test_output_is_deterministic() -> None:
    canonical = make_canonical_gameweeks()

    assert_frame_equal(build_feature_dataset(canonical), build_feature_dataset(canonical))


def test_canonical_columns_are_preserved_untouched() -> None:
    canonical = make_canonical_gameweeks()

    built = build_feature_dataset(canonical)

    assert_frame_equal(built.loc[:, list(canonical.columns)], canonical)


def test_feature_columns_are_appended_in_declared_order() -> None:
    canonical = make_canonical_gameweeks()

    built = build_feature_dataset(canonical)

    assert list(built.columns) == [*canonical.columns, *FEATURES]
