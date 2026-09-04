"""Tests for the fixture-group conformal calibration.

Synthetic residuals whose spread doubles on double gameweeks: the position-only
calibration must undercover the doubles and overcover the singles, the fixture-group
calibration must cover both near nominal, and the split must be chronological.
"""

import random

import pandas as pd
import pytest

from squadopt.uncertainty import (
    FixtureGroupConformalConfig,
    UncertaintyConfigurationError,
    UncertaintyValidationError,
    fit_and_evaluate_fixture_group_conformal,
    fixture_group,
    fixture_group_conformal_to_dict,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")


def _table(
    *, seasons: int = 2, gameweeks: int = 20, players_per_position: int = 12
) -> pd.DataFrame:
    """Residuals with unit spread on singles, double spread on doubles, and a few blanks."""

    generator = random.Random(7)
    rows: list[dict[str, object]] = []
    for season_index in range(seasons):
        season = f"20{21 + season_index}-{22 + season_index}"
        for gameweek in range(2, 2 + gameweeks):
            double_week = gameweek % 3 == 0
            blank_week = gameweek % 7 == 0
            player = 100
            for position in POSITIONS:
                for index in range(players_per_position):
                    player += 1
                    if blank_week and index == 0:
                        count = 0
                    elif double_week and index < 6:
                        count = 2
                    else:
                        count = 1
                    scale = 0.0 if count == 0 else (2.0 if count == 2 else 1.0)
                    rows.append(
                        {
                            "fold_id": f"{season}-gw{gameweek:02d}",
                            "season": season,
                            "gameweek": gameweek,
                            "player_id": player,
                            "position": position,
                            "residual": generator.gauss(0.0, scale),
                            "fixture_count": count,
                        }
                    )
    return pd.DataFrame(rows)


def test_fixture_group_names_the_calendar() -> None:
    assert fixture_group(0) == "blank"
    assert fixture_group(1) == "single"
    assert fixture_group(2) == "double_plus"
    assert fixture_group(3) == "double_plus"


def test_the_fixture_axis_repairs_double_gameweek_coverage() -> None:
    result = fit_and_evaluate_fixture_group_conformal(_table())

    position_only = result.position_metrics
    with_fixture = result.fixture_metrics
    # Position-only: one radius per position, fitted mostly on singles, so doubles
    # (twice the spread) are undercovered and singles slightly overcovered.
    assert position_only["double_plus"].empirical_coverage < 0.80
    assert position_only["single"].empirical_coverage > 0.88
    # Position by fixture group: both groups near the nominal 0.90.
    assert abs(with_fixture["double_plus"].empirical_coverage - 0.90) < 0.06
    assert abs(with_fixture["single"].empirical_coverage - 0.90) < 0.04
    # And the double radius is wider than the single one for every position.
    for position in POSITIONS:
        single = result.fixture_cells[(position, "single")].interval_radius
        double = result.fixture_cells[(position, "double_plus")].interval_radius
        assert double > single
        assert result.fixture_cells[(position, "single")].source == "position_fixture_group"
    assert (
        with_fixture["double_plus"].mean_interval_width
        > position_only["double_plus"].mean_interval_width
    )


def test_the_split_is_chronological_and_blanks_are_excluded() -> None:
    result = fit_and_evaluate_fixture_group_conformal(
        _table(), FixtureGroupConformalConfig(calibration_fold_fraction=0.5)
    )

    assert len(result.calibration_folds) == 20 and len(result.evaluation_folds) == 20
    assert all(fold.startswith("2021-22") for fold in result.calibration_folds)
    assert all(fold.startswith("2022-23") for fold in result.evaluation_folds)
    assert result.diagnostics["blank_rows_excluded"] > 0
    assert (
        result.diagnostics["calibration_rows"] + result.diagnostics["evaluation_rows"]
        == result.diagnostics["rows_total"] - result.diagnostics["blank_rows_excluded"]
    )
    document = fixture_group_conformal_to_dict(result)
    assert document["contract_version"] == "fixture_group_conformal_v1"
    assert "MID/double_plus" in document["held_out"]["position_fixture_group"]  # type: ignore[index]
    assert document["fingerprint"] == result.fingerprint


def test_a_small_cell_falls_back_to_its_position() -> None:
    table = _table()
    # Strip nearly every GK double so its cell falls under the floor.
    doubles = (table["position"] == "GK") & (table["fixture_count"] == 2)
    keep = table.index[~doubles].tolist() + table.index[doubles].tolist()[:3]
    result = fit_and_evaluate_fixture_group_conformal(
        table.loc[sorted(keep)], FixtureGroupConformalConfig(min_group_observations=30)
    )
    cell = result.fixture_cells[("GK", "double_plus")]
    assert cell.source == "position_fallback"
    assert cell.interval_radius == result.position_cells["GK"].interval_radius


def test_the_result_is_deterministic() -> None:
    first = fit_and_evaluate_fixture_group_conformal(_table())
    second = fit_and_evaluate_fixture_group_conformal(_table())
    assert first.fingerprint == second.fingerprint
    assert fixture_group_conformal_to_dict(first) == fixture_group_conformal_to_dict(second)


@pytest.mark.parametrize(
    "overrides",
    [{"confidence_level": 1.0}, {"calibration_fold_fraction": 0.0}, {"min_group_observations": 0}],
)
def test_invalid_config_is_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(UncertaintyConfigurationError):
        FixtureGroupConformalConfig(**overrides)  # type: ignore[arg-type]


def test_malformed_tables_are_refused() -> None:
    table = _table()
    with pytest.raises(UncertaintyValidationError, match="missing columns"):
        fit_and_evaluate_fixture_group_conformal(table.drop(columns="fixture_count"))
    with pytest.raises(UncertaintyValidationError, match="Unknown positions"):
        fit_and_evaluate_fixture_group_conformal(table.assign(position="WING"))
    one_fold = table.loc[table["fold_id"] == table["fold_id"].iloc[0]]
    with pytest.raises(UncertaintyValidationError, match="chronological split"):
        fit_and_evaluate_fixture_group_conformal(one_fold)
