"""Tests that the projection table satisfies the agreed optimizer contract."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt import OptimizationConfig
from squadopt.data import PROJECTION_REQUIRED_COLUMNS
from squadopt.features import build_feature_dataset
from squadopt.optimization.validation import validate_players
from squadopt.prediction import PredictionConfigurationError, build_projection_table

TARGET_GAMEWEEK = 6


@pytest.fixture
def features() -> pd.DataFrame:
    return build_feature_dataset(make_canonical_gameweeks())


def test_table_has_exactly_the_agreed_columns(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    assert list(table.columns) == list(PROJECTION_REQUIRED_COLUMNS)


def test_table_passes_the_optimizer_own_validation(features: pd.DataFrame) -> None:
    """The strongest contract check available: the consumer's real validator."""

    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    validated = validate_players(table, OptimizationConfig())

    assert len(validated) == len(table)


def test_no_feature_or_history_column_leaks_into_the_table(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    for forbidden in ("season", "gameweek", "minutes", "total_points", "points_last_5"):
        assert forbidden not in table.columns


def test_one_row_per_player_for_the_target_gameweek(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)
    expected = features.loc[features["gameweek"] == TARGET_GAMEWEEK, "player_id"].nunique()

    assert len(table) == expected
    assert not table["player_id"].duplicated().any()


def test_price_comes_from_the_target_gameweek_row(features: pd.DataFrame) -> None:
    """Price is fixed at that gameweek's deadline, so row t is the correct source."""

    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)
    target_rows = features.loc[features["gameweek"] == TARGET_GAMEWEEK]
    expected = target_rows.set_index("player_id")["price_tenths"]

    actual = table.set_index("player_id")["price_tenths"]

    assert actual.to_dict() == expected.to_dict()


def test_price_differs_from_an_earlier_gameweek(features: pd.DataFrame) -> None:
    """Guards the test above: prices actually move, so it is not trivially passing."""

    early = build_projection_table(features, season=SEASON, gameweek=2)
    late = build_projection_table(features, season=SEASON, gameweek=8)

    assert not early["price_tenths"].equals(late["price_tenths"])


def test_price_stays_integral(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    assert str(table["price_tenths"].dtype) == "int64"


def test_expected_points_is_finite_and_non_negative(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    assert table["expected_points"].notna().all()
    assert (table["expected_points"] >= 0).all()
    assert str(table["expected_points"].dtype) == "float64"


def test_table_is_ordered_by_player_id_with_a_reset_index(features: pd.DataFrame) -> None:
    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)

    assert table["player_id"].tolist() == sorted(table["player_id"].tolist())
    assert table.index.tolist() == list(range(len(table)))


def test_table_is_deterministic(features: pd.DataFrame) -> None:
    assert_frame_equal(
        build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK),
        build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK),
    )


def test_table_does_not_depend_on_feature_row_order(features: pd.DataFrame) -> None:
    shuffled = features.iloc[::-1].reset_index(drop=True)

    assert_frame_equal(
        build_projection_table(shuffled, season=SEASON, gameweek=TARGET_GAMEWEEK),
        build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK),
    )


def test_input_frame_is_not_mutated(features: pd.DataFrame) -> None:
    original = features.copy(deep=True)

    table = build_projection_table(features, season=SEASON, gameweek=TARGET_GAMEWEEK)
    table.loc[0, "name"] = "Changed"

    assert_frame_equal(features, original)


def test_future_gameweeks_cannot_influence_the_table(features: pd.DataFrame) -> None:
    """The projection for gameweek t must not move when later results change."""

    canonical = make_canonical_gameweeks()
    baseline = build_projection_table(
        build_feature_dataset(canonical), season=SEASON, gameweek=TARGET_GAMEWEEK
    )

    mutated = canonical.copy(deep=True)
    future = mutated["gameweek"] >= TARGET_GAMEWEEK
    mutated.loc[future, "total_points"] = 999

    result = build_projection_table(
        build_feature_dataset(mutated), season=SEASON, gameweek=TARGET_GAMEWEEK
    )

    assert_frame_equal(result["expected_points"].to_frame(), baseline["expected_points"].to_frame())


def test_unknown_target_reports_what_is_available(features: pd.DataFrame) -> None:
    with pytest.raises(PredictionConfigurationError) as error:
        build_projection_table(features, season=SEASON, gameweek=99)

    message = str(error.value)
    assert "gameweek=99" in message
    assert "available" in message


def test_unknown_season_is_reported(features: pd.DataFrame) -> None:
    with pytest.raises(PredictionConfigurationError, match="No rows for season"):
        build_projection_table(features, season="1999-00", gameweek=TARGET_GAMEWEEK)


def test_missing_required_columns_are_reported(features: pd.DataFrame) -> None:
    with pytest.raises(PredictionConfigurationError, match="missing required columns"):
        build_projection_table(
            features.drop(columns=["price_tenths"]), season=SEASON, gameweek=TARGET_GAMEWEEK
        )


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="expects a pandas DataFrame"):
        build_projection_table([{"season": SEASON}], season=SEASON, gameweek=1)  # type: ignore[arg-type]


# --- transferred players ----------------------------------------------------


def _transfer_history() -> pd.DataFrame:
    """One player who changes club mid-season, keeping a single player_id."""

    length = 5
    return pd.DataFrame(
        {
            "season": pd.Series([SEASON] * length, dtype="string"),
            "gameweek": pd.Series(range(1, length + 1), dtype="int64"),
            "player_id": pd.Series([7] * length, dtype="int64"),
            "name": pd.Series(["Mover"] * length, dtype="string"),
            "team_id": pd.Series([1, 1, 1, 2, 2], dtype="int64"),
            "position": pd.Series(["MID"] * length, dtype="string"),
            "price_tenths": pd.Series([50, 51, 52, 53, 54], dtype="int64"),
            "minutes": pd.Series([90] * length, dtype="int64"),
            "total_points": pd.Series([2, 4, 6, 8, 10], dtype="int64"),
        }
    )


def test_a_transferred_player_keeps_one_continuous_history() -> None:
    """History follows player_id, so a club change does not restart the window."""

    features = build_feature_dataset(_transfer_history())

    # GW5 averages GW2-4 across the transfer boundary: (4 + 6 + 8) / 3.
    assert features.loc[4, "points_last_3"] == pytest.approx(6.0)


def test_a_transferred_player_reports_the_target_gameweek_club() -> None:
    """team_id is fixed at the deadline, so the new club is correct for gameweek 5."""

    features = build_feature_dataset(_transfer_history())

    table = build_projection_table(features, season=SEASON, gameweek=5)

    assert table.loc[0, "team_id"] == 2
    assert table.loc[0, "price_tenths"] == 54
