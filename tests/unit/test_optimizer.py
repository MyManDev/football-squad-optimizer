"""Tests for the baseline CP-SAT optimizer."""

from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_players import make_full_size_players

from squadopt import (
    InvalidPlayerDataError,
    OptimizationConfig,
    OptimizationResult,
    SolverExecutionError,
    SolverStatus,
    optimize_squad,
)
from squadopt.live.report import live_optimization_config
from squadopt.optimization.optimizer import (
    _map_solver_status,
    _scale_bench_coefficient,
    _scale_expected_points,
    wall_clock_stopped_the_search,
)


def _ids(frame: pd.DataFrame) -> set[object]:
    return set(frame["player_id"].tolist())


def test_selects_exact_squad_size(baseline_result: OptimizationResult) -> None:
    assert len(baseline_result.selected_squad) == 15


def test_respects_squad_position_quotas(baseline_result: OptimizationResult) -> None:
    assert baseline_result.selected_squad["position"].value_counts().to_dict() == {
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
        "GK": 2,
    }


def test_respects_binding_budget_constraint(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    players = known_optimum_players.copy(deep=True)
    players.loc[players["player_id"] == "MID_A", "price_tenths"] = 100

    result = optimize_squad(players, small_config)

    assert result.total_cost_tenths == 200
    assert "MID_A" not in _ids(result.selected_squad)
    assert "MID_B" in _ids(result.selected_squad)


def test_respects_binding_team_limit(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    players = known_optimum_players.copy(deep=True)
    players.loc[players["player_id"].str.endswith("_A"), "team_id"] = "DOMINANT"
    config = OptimizationConfig(
        budget_tenths=small_config.budget_tenths,
        squad_size=small_config.squad_size,
        squad_position_limits=small_config.squad_position_limits,
        starting_size=small_config.starting_size,
        starting_position_min=small_config.starting_position_min,
        starting_position_max=small_config.starting_position_max,
        max_players_per_team=3,
    )

    result = optimize_squad(players, config)

    assert int((result.selected_squad["team_id"] == "DOMINANT").sum()) == 3


def test_selects_exact_starting_size(baseline_result: OptimizationResult) -> None:
    assert len(baseline_result.starting_xi) == 11


def test_starting_xi_has_exactly_one_goalkeeper(
    baseline_result: OptimizationResult,
) -> None:
    assert int((baseline_result.starting_xi["position"] == "GK").sum()) == 1


def test_respects_formation_bounds(baseline_result: OptimizationResult) -> None:
    counts = baseline_result.starting_xi["position"].value_counts()

    assert 3 <= counts["DEF"] <= 5
    assert 2 <= counts["MID"] <= 5
    assert 1 <= counts["FWD"] <= 3


def test_selects_exactly_one_captain(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None


def test_captain_is_in_starting_xi(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None
    assert baseline_result.captain["player_id"] in _ids(baseline_result.starting_xi)


def test_all_starters_are_in_selected_squad(baseline_result: OptimizationResult) -> None:
    assert _ids(baseline_result.starting_xi) <= _ids(baseline_result.selected_squad)


def test_reports_infeasible_problem(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    config = OptimizationConfig(
        budget_tenths=0,
        squad_size=small_config.squad_size,
        squad_position_limits=small_config.squad_position_limits,
        starting_size=small_config.starting_size,
        starting_position_min=small_config.starting_position_min,
        starting_position_max=small_config.starting_position_max,
        max_players_per_team=small_config.max_players_per_team,
    )

    result = optimize_squad(known_optimum_players, config)

    assert result.solver_status is SolverStatus.INFEASIBLE
    assert not result.has_solution
    assert result.selected_squad.empty
    assert list(result.selected_squad.columns) == list(known_optimum_players.columns)
    assert result.captain is None
    assert result.total_cost_tenths is None
    assert result.objective_value is None


def test_does_not_mutate_input_dataframe(baseline_players: pd.DataFrame) -> None:
    original = baseline_players.copy(deep=True)

    optimize_squad(baseline_players, OptimizationConfig())

    assert_frame_equal(baseline_players, original)


def test_finds_known_small_optimum(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_squad(known_optimum_players, small_config)

    assert result.solver_status is SolverStatus.OPTIMAL
    assert _ids(result.selected_squad) == {"GK_A", "DEF_A", "MID_A", "FWD_A"}
    assert _ids(result.starting_xi) == {"GK_A", "MID_A", "FWD_A"}
    assert _ids(result.bench) == {"DEF_A"}
    assert result.captain is not None
    assert result.captain["player_id"] == "MID_A"
    assert result.total_cost_tenths == 200
    assert result.projected_score == pytest.approx(31.0)
    assert result.objective_value == pytest.approx(31.4)


def test_tie_breaking_is_deterministic(
    tied_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    first = optimize_squad(tied_players.sample(frac=1, random_state=11), small_config)
    second = optimize_squad(tied_players.sample(frac=1, random_state=42), small_config)

    assert first.diagnostics["tiebreak_completed"] is True
    assert _ids(first.selected_squad) == _ids(second.selected_squad)
    assert _ids(first.starting_xi) == _ids(second.starting_xi)
    assert first.captain is not None and second.captain is not None
    assert first.captain["player_id"] == second.captain["player_id"]


def test_deterministic_work_budget_is_shared_by_primary_and_tiebreak(
    tied_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    config = replace(
        small_config,
        solver_time_limit_seconds=5.0,
        solver_deterministic_time_limit=0.1,
    )

    first = optimize_squad(tied_players.sample(frac=1, random_state=11), config)
    second = optimize_squad(tied_players.sample(frac=1, random_state=42), config)

    assert first.solver_status is SolverStatus.OPTIMAL
    assert first.diagnostics["solver_deterministic_time_limit"] == 0.1
    primary = float(first.diagnostics["primary_deterministic_time"])
    tiebreak_limit = float(first.diagnostics["tiebreak_deterministic_time_limit"])
    tiebreak = float(first.diagnostics["tiebreak_deterministic_time"])
    total = float(first.diagnostics["deterministic_time_used"])
    assert tiebreak_limit == pytest.approx(max(0.0, 0.1 - primary))
    assert total == pytest.approx(primary + tiebreak)
    assert total > 0.0
    assert _ids(first.selected_squad) == _ids(second.selected_squad)
    assert _ids(first.starting_xi) == _ids(second.starting_xi)
    assert first.captain is not None and second.captain is not None
    assert first.captain["player_id"] == second.captain["player_id"]


def test_integer_price_handling(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_squad(known_optimum_players, small_config)
    assert isinstance(result.total_cost_tenths, int)

    invalid = known_optimum_players.copy(deep=True)
    invalid["price_tenths"] = invalid["price_tenths"].astype(float)
    with pytest.raises(InvalidPlayerDataError):
        optimize_squad(invalid, small_config)


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (6.2374, 1000, 6237),
        (6.2375, 1000, 6238),
        (6.2376, 1000, 6238),
        (0.0005, 1000, 1),
        (2.675, 100, 268),
        (5.12345, 10_000, 51_235),
    ],
)
def test_expected_points_scaling_precision(value: float, scale: int, expected: int) -> None:
    assert _scale_expected_points(value, scale) == expected


def test_bench_coefficient_uses_round_half_up() -> None:
    assert _scale_bench_coefficient(6238, 0.1) == 624


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        (cp_model.OPTIMAL, SolverStatus.OPTIMAL),
        (cp_model.FEASIBLE, SolverStatus.FEASIBLE),
        (cp_model.INFEASIBLE, SolverStatus.INFEASIBLE),
        (cp_model.UNKNOWN, SolverStatus.UNKNOWN),
    ],
)
def test_maps_solver_statuses(raw_status: int, expected: SolverStatus) -> None:
    assert _map_solver_status(raw_status) is expected


def test_model_invalid_status_is_an_execution_error() -> None:
    with pytest.raises(SolverExecutionError):
        _map_solver_status(cp_model.MODEL_INVALID)


def test_preserves_extra_input_columns(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    known_optimum_players["source_note"] = "synthetic"

    result = optimize_squad(known_optimum_players, small_config)

    assert "source_note" in result.selected_squad.columns
    assert set(result.selected_squad["source_note"]) == {"synthetic"}


def test_bench_is_ordered_keeper_first_then_by_descending_expectation(
    baseline_result: OptimizationResult,
) -> None:
    """The bench is an ordered decision: automatic substitutions walk it top to bottom."""

    bench = baseline_result.bench
    assert len(bench) == 4
    assert bench.iloc[0]["position"] == "GK"
    outfield_points = [float(v) for v in bench.iloc[1:]["expected_points"]]
    assert outfield_points == sorted(outfield_points, reverse=True)


def test_the_tiebreak_is_attempted_and_completes_on_the_baseline(
    baseline_players: pd.DataFrame,
) -> None:
    """The tie-break runs and proves itself on the 24-player baseline.

    This is a smoke check on the plumbing, not the #192 pin it used to call itself. The
    baseline pool solves in milliseconds, so ``tiebreak_completed`` is true here whatever
    the budget is: reverting either half of the #192 fix — the tie-break's own budget and
    the primary-solution hint — leaves this test green. The pin that can notice a budget
    too small for the pool the live path actually gets is
    ``test_the_tiebreak_completes_within_the_live_budget_on_a_full_size_pool``.
    """

    result = optimize_squad(baseline_players, OptimizationConfig())
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.diagnostics["tiebreak_attempted"] is True
    assert result.diagnostics["tiebreak_completed"] is True


# Measured on the full-size fixture at ``live_optimization_config()``: the primary spends
# 1.171 deterministic units and the tie-break 4.183, 5.354 in total, identically on three
# consecutive runs and in separate processes. The recorded opening-gameweek pool costs
# 3.512 at the same settings, so the fixture is the harder of the two.
#
# The ceiling is 1.31x the measurement, and it is chosen against a number rather than for
# comfort: dropping the #192 hint (``optimizer.py``, the primary solution handed to the
# tie-break as a start) costs this pool 8.034 units instead of 5.354, so a ceiling of 7.0
# fails when that hint goes and 12.0 would not have. Deterministic time is reproducible by
# construction -- one search worker, a fixed seed -- so the only thing that legitimately
# moves these numbers is a CP-SAT version change, and a version change should re-measure
# and re-pin them rather than find the gate already loosened to accommodate it.
FULL_SIZE_TIEBREAK_UNITS = 5.354
FULL_SIZE_TIEBREAK_UNITS_WITHOUT_THE_HINT = 8.034
FULL_SIZE_TIEBREAK_UNITS_CEILING = 7.0


def test_the_tiebreak_completes_within_the_live_budget_on_a_full_size_pool() -> None:
    """The live budget proves the tie-break on a pool the size of the one it really gets.

    The tie-break exists to pick a canonical member of the primal-optimal set. Cut short it
    returns whichever member it was holding, while ``solver_status`` still reports the
    primary's ``OPTIMAL`` — so an unproven pick would be recorded as the proven answer. The
    only assertion that can notice the live budget stopping being enough is one made on a
    pool of the real size: the 24-player baseline above completes whatever the budget is.
    """

    pool = make_full_size_players()
    assert len(pool) == 600, "a pin on a small pool cannot notice the real one failing"
    # The ceiling is between what the tie-break costs and what it costs without the #192
    # hint, so this test is the pin on that hint as well as on the budget.
    assert (
        FULL_SIZE_TIEBREAK_UNITS
        < FULL_SIZE_TIEBREAK_UNITS_CEILING
        < FULL_SIZE_TIEBREAK_UNITS_WITHOUT_THE_HINT
    )

    result = optimize_squad(pool, live_optimization_config())

    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.diagnostics["tiebreak_attempted"] is True
    assert result.diagnostics["tiebreak_completed"] is True
    assert wall_clock_stopped_the_search(result.solver_status, result.diagnostics) is False
    assert result.diagnostics["deterministic_time_budget_exhausted"] is False
    spent = float(str(result.diagnostics["deterministic_time_used"]))
    assert spent < FULL_SIZE_TIEBREAK_UNITS_CEILING, (
        f"the tie-break spent {spent} deterministic units against a measured "
        f"{FULL_SIZE_TIEBREAK_UNITS}; the live budget is sized from that measurement"
    )


def test_a_budget_below_the_full_size_pool_stops_it_deterministically() -> None:
    """The pin above can fail, and when the budget is what stops the search it says so.

    A guard nobody has watched fail is not evidence. Halving the measured need leaves the
    tie-break unfinished — and because a deterministic budget, not a clock, is what ran
    out, both the stopping point and this test's outcome are the same on every machine.
    """

    starved = replace(
        OptimizationConfig(),
        solver_time_limit_seconds=600.0,
        solver_deterministic_time_limit=FULL_SIZE_TIEBREAK_UNITS / 2.0,
    )

    result = optimize_squad(make_full_size_players(), starved)

    assert result.solver_status is SolverStatus.OPTIMAL  # the primary still proves itself
    assert result.diagnostics["tiebreak_attempted"] is True
    assert result.diagnostics["tiebreak_completed"] is False
    assert result.diagnostics["deterministic_time_budget_exhausted"] is True
    # The budget ran out, not the clock, so a second run stops in the same place.
    assert wall_clock_stopped_the_search(result.solver_status, result.diagnostics) is False


def test_two_solves_agree_on_the_full_squad_identity(baseline_players: pd.DataFrame) -> None:
    """The replay guarantee at solution identity, not only objective value.

    Two solves at the same limit on the same 24-player pool, which agree even when the
    answer is clock-dependent, so this cannot show that identity replays under load. What
    can is the pair above: the identity a cut tie-break leaves to the machine, and the
    budget that keeps it from being cut.
    """

    first = optimize_squad(baseline_players, OptimizationConfig())
    second = optimize_squad(baseline_players, OptimizationConfig())
    assert [int(v) for v in first.selected_squad["player_id"]] == [
        int(v) for v in second.selected_squad["player_id"]
    ]
    assert [int(v) for v in first.bench["player_id"]] == [int(v) for v in second.bench["player_id"]]
    assert int(first.captain["player_id"]) == int(second.captain["player_id"])
