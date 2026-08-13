"""The Sprint 0 end-to-end chain, from a local file to a squad, XI, and captain.

This is the acceptance test for the whole skeleton: local synthetic data becomes a
canonical dataset, leakage-safe features, baseline projections, and finally a real
CP-SAT solution. Nothing here touches the network.

The optimizer is a required project dependency, so it is exercised directly rather
than skipped: if it were missing, the package would be broken anyway.
"""

from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import SAMPLE_ADAPTER, SEASON

from squadopt import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.data import build_canonical_dataset, load_csv
from squadopt.features import build_feature_dataset
from squadopt.prediction import build_projection_table

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "sample" / "raw_player_gameweeks.csv"
TARGET_GAMEWEEK = 6


def _run(gameweek: int = TARGET_GAMEWEEK):  # type: ignore[no-untyped-def]
    canonical = build_canonical_dataset(load_csv(SAMPLE_FILE), adapter=SAMPLE_ADAPTER)
    features = build_feature_dataset(canonical)
    projections = build_projection_table(features, season=SEASON, gameweek=gameweek)
    return projections, optimize_squad(projections, OptimizationConfig())


def test_the_chain_produces_a_solved_squad() -> None:
    _, result = _run()

    assert result.has_solution
    assert result.solver_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}


def test_the_squad_satisfies_the_configured_shape() -> None:
    _, result = _run()
    config = OptimizationConfig()

    assert len(result.selected_squad) == config.squad_size
    assert len(result.starting_xi) == config.starting_size
    assert len(result.bench) == config.squad_size - config.starting_size
    assert result.captain is not None


def test_positional_quotas_and_team_limit_hold() -> None:
    _, result = _run()
    config = OptimizationConfig()

    counts = result.selected_squad["position"].value_counts()
    for position, required in config.squad_position_limits.items():
        assert int(counts.get(position, 0)) == required

    per_team = result.selected_squad["team_id"].value_counts()
    assert int(per_team.max()) <= config.max_players_per_team


def test_the_squad_stays_within_budget() -> None:
    _, result = _run()

    assert result.total_cost_tenths is not None
    assert result.total_cost_tenths <= OptimizationConfig().budget_tenths


def test_the_captain_starts() -> None:
    _, result = _run()

    assert result.captain is not None
    assert result.captain["player_id"] in set(result.starting_xi["player_id"])


def test_prices_stay_integral_all_the_way_through() -> None:
    """A float price anywhere upstream would break the budget constraint."""

    projections, result = _run()

    assert str(projections["price_tenths"].dtype) == "int64"
    assert str(result.selected_squad["price_tenths"].dtype) == "int64"


def test_the_whole_chain_is_deterministic() -> None:
    first_projections, first_result = _run()
    second_projections, second_result = _run()

    assert_frame_equal(first_projections, second_projections)
    assert_frame_equal(
        first_result.selected_squad.reset_index(drop=True),
        second_result.selected_squad.reset_index(drop=True),
    )
    assert first_result.objective_value == second_result.objective_value


@pytest.mark.parametrize("gameweek", [2, 4, 6, 8])
def test_every_gameweek_with_history_is_solvable(gameweek: int) -> None:
    _, result = _run(gameweek)

    assert result.has_solution


def test_the_opening_gameweek_is_solvable_and_price_informative() -> None:
    """The fitted deadline-price prior ranks players before form exists."""

    projections, result = _run(1)

    assert result.has_solution
    assert projections["expected_points"].nunique() > 1
