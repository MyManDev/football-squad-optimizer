"""Tests for projecting a season that has not started yet."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt import OptimizationConfig
from squadopt.data import PROJECTION_REQUIRED_COLUMNS
from squadopt.features import CrossSeasonConfig
from squadopt.optimization.validation import validate_players
from squadopt.prediction import (
    DEFAULT_OPENING_EXPECTED_POINTS,
    PredictionConfigurationError,
    build_opening_projection_table,
)

UPCOMING = "2026-27"
OPEN_CARRY = CrossSeasonConfig(min_minutes=0)


def _panel(rows: list[tuple[str, int, int, int, int]]) -> pd.DataFrame:
    """Canonical history from (season, gameweek, player_id, minutes, points)."""

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


def _roster(entries: list[tuple[int, str, int, str, int]]) -> pd.DataFrame:
    """Roster from (code, web_name, team, position, now_cost)."""

    return pd.DataFrame(
        {
            "code": [entry[0] for entry in entries],
            "web_name": [entry[1] for entry in entries],
            "team": [entry[2] for entry in entries],
            "position": [entry[3] for entry in entries],
            "now_cost": [entry[4] for entry in entries],
        }
    )


HISTORY = _panel(
    [
        ("2025-26", 1, 101, 90, 6),
        ("2025-26", 2, 101, 90, 6),
    ]
)
ROSTER = _roster([(101, "Known", 3, "MID", 75), (202, "Newcomer", 4, "FWD", 45)])


def _table(**kwargs: object) -> pd.DataFrame:
    return build_opening_projection_table(
        HISTORY, ROSTER, season=UPCOMING, cross_season=OPEN_CARRY, **kwargs
    )  # type: ignore[arg-type]


# --- shape and contract -----------------------------------------------------


def test_the_table_carries_the_contract_columns_plus_the_provenance_flag() -> None:
    table = _table()

    assert list(table.columns) == [*PROJECTION_REQUIRED_COLUMNS, "has_prior_record"]


def _full_roster() -> pd.DataFrame:
    """A pool that satisfies the default squad quotas, so the validator can be used."""

    positions = ["GK"] * 3 + ["DEF"] * 6 + ["MID"] * 6 + ["FWD"] * 4
    return _roster(
        [
            (500 + index, f"Player{index}", (index % 5) + 1, position, 45 + index)
            for index, position in enumerate(positions)
        ]
    )


def test_the_contract_columns_satisfy_the_optimizer_validator() -> None:
    """The strongest available check: the consumer's own validator, not a copy of it."""

    table = build_opening_projection_table(
        HISTORY, _full_roster(), season=UPCOMING, cross_season=OPEN_CARRY
    ).drop(columns=["has_prior_record"])

    validated = validate_players(table, OptimizationConfig())

    assert len(validated) == len(table)


def test_the_table_is_ordered_by_player_with_a_reset_index() -> None:
    table = _table()

    assert table["player_id"].tolist() == sorted(table["player_id"].tolist())
    assert table.index.tolist() == list(range(len(table)))


def test_one_row_per_roster_player() -> None:
    table = _table()

    assert len(table) == len(ROSTER)
    assert set(table["player_id"]) == set(ROSTER["code"])


# --- where the projection comes from ----------------------------------------


def test_a_player_with_history_is_projected_from_it() -> None:
    """12 points over 180 minutes is 6.0 per 90, at 90 expected minutes: 6.0."""

    table = _table().set_index("player_id")

    assert table.loc[101, "expected_points"] == pytest.approx(6.0)
    assert bool(table.loc[101, "has_prior_record"]) is True


def test_a_player_with_no_history_gets_the_declared_constant() -> None:
    table = _table().set_index("player_id")

    assert table.loc[202, "expected_points"] == DEFAULT_OPENING_EXPECTED_POINTS
    assert bool(table.loc[202, "has_prior_record"]) is False


def test_the_provenance_flag_separates_the_two_populations() -> None:
    """It exists so a caller can see how much of the pool rests on a constant."""

    table = _table()

    assert table["has_prior_record"].tolist() == [True, False]


def test_price_comes_from_the_roster_not_from_history() -> None:
    """The opening price is the roster's, and the season has not begun to move it."""

    table = _table().set_index("player_id")

    assert table.loc[101, "price_tenths"] == 75
    assert table.loc[202, "price_tenths"] == 45


def test_identity_team_and_position_come_from_the_roster() -> None:
    table = _table().set_index("player_id")

    assert table.loc[101, "name"] == "Known"
    assert table.loc[101, "team_id"] == 3
    assert table.loc[202, "position"] == "FWD"


# --- guarantees -------------------------------------------------------------


def test_projections_are_finite_and_non_negative() -> None:
    negative = _panel([("2025-26", 1, 101, 90, -10)])

    table = build_opening_projection_table(
        negative, ROSTER, season=UPCOMING, cross_season=OPEN_CARRY
    )

    assert table["expected_points"].notna().all()
    assert (table["expected_points"] >= 0).all()


def test_prices_stay_integral() -> None:
    assert str(_table()["price_tenths"].dtype) == "int64"


def test_the_target_season_need_not_appear_in_the_panel() -> None:
    """The whole point: a season with no played gameweeks still gets projections."""

    assert UPCOMING not in set(HISTORY["season"])
    assert len(_table()) == len(ROSTER)


def test_the_inputs_are_not_mutated() -> None:
    panel_before = HISTORY.copy(deep=True)
    roster_before = ROSTER.copy(deep=True)

    _table()

    assert_frame_equal(HISTORY, panel_before)
    assert_frame_equal(ROSTER, roster_before)


def test_the_result_is_deterministic() -> None:
    assert_frame_equal(_table(), _table())


def test_a_thin_history_falls_back_rather_than_reporting_noise() -> None:
    thin = _panel([("2025-26", 1, 101, 20, 2)])

    table = build_opening_projection_table(
        thin, ROSTER, season=UPCOMING, cross_season=CrossSeasonConfig(min_minutes=270)
    ).set_index("player_id")

    assert table.loc[101, "expected_points"] == DEFAULT_OPENING_EXPECTED_POINTS
    assert bool(table.loc[101, "has_prior_record"]) is False


# --- guards -----------------------------------------------------------------


def test_a_roster_missing_columns_is_reported() -> None:
    with pytest.raises(PredictionConfigurationError, match="roster is missing columns"):
        build_opening_projection_table(HISTORY, ROSTER.drop(columns=["now_cost"]), season=UPCOMING)


def test_duplicate_roster_identifiers_are_refused() -> None:
    duplicated = pd.concat([ROSTER, ROSTER.iloc[[0]]], ignore_index=True)

    with pytest.raises(PredictionConfigurationError, match="duplicate player identifiers"):
        build_opening_projection_table(HISTORY, duplicated, season=UPCOMING)


def test_an_empty_roster_is_refused() -> None:
    with pytest.raises(PredictionConfigurationError, match="at least one player"):
        build_opening_projection_table(HISTORY, ROSTER.iloc[:0], season=UPCOMING)


def test_a_non_dataframe_roster_is_refused() -> None:
    with pytest.raises(PredictionConfigurationError, match="pandas DataFrame"):
        build_opening_projection_table(HISTORY, [{"code": 1}], season=UPCOMING)  # type: ignore[arg-type]


def test_an_unknown_roster_position_is_refused() -> None:
    broken = _roster([(101, "Known", 3, "WING", 75)])

    with pytest.raises(Exception, match="Unsupported position value"):
        build_opening_projection_table(broken.pipe(lambda f: f), broken, season=UPCOMING)


def test_a_fractional_price_is_refused() -> None:
    """Built as text from the start: a roster read from CSV arrives that way."""

    broken = _roster([(101, "Known", 3, "MID", 75)]).astype({"now_cost": str})
    broken.loc[0, "now_cost"] = "7.5"

    with pytest.raises(PredictionConfigurationError, match="must be integral"):
        build_opening_projection_table(HISTORY, broken, season=UPCOMING)
