"""Banded candidate generation: constrained plans, honest menus, measured price tags."""

import pandas as pd
import pytest
from tests.unit.test_transfer_planning import OPTIMAL_INITIAL, _horizon_table

from squadopt.application.strategies import (
    CandidateConstraints,
    EvidenceStatus,
    RankingCriterion,
    Strategy,
    StrategyConfigurationError,
    solve_strategy_plan,
    strategy,
)
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    FirstWeekOverlap,
    PlanningHorizon,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)


def _one_week(known_optimum_players: pd.DataFrame) -> PlanningHorizon:
    return PlanningHorizon(_horizon_table(known_optimum_players, (1,)))


def _rival_ids(known_optimum_players: pd.DataFrame, count: int) -> frozenset[str]:
    # The known world's optimum picks the strong player per position (the _A set); a
    # rival holding the weak end (_B) means an unconstrained solve overlaps with none
    # of it, so a floor visibly bends the squad.
    ids = [str(v) for v in known_optimum_players["player_id"].tolist()]
    weak = [player for player in ids if player.endswith("_B")]
    return frozenset(weak[:count])


# --- the solver-level band ----------------------------------------------------------


def test_the_band_is_validated() -> None:
    with pytest.raises(TransferPlanningValidationError, match="at least one player"):
        FirstWeekOverlap(player_ids=frozenset())
    with pytest.raises(TransferPlanningValidationError, match="at least one bound"):
        FirstWeekOverlap(player_ids=frozenset({"A"}))
    with pytest.raises(TransferPlanningValidationError, match="may not exceed"):
        FirstWeekOverlap(player_ids=frozenset({"A"}), minimum=3, maximum=1)


def test_a_floor_forces_the_overlap_and_costs_expected_points(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    """Rising floors: overlap rises monotonically, expected points fall monotonically."""

    horizon = _one_week(known_optimum_players)
    rival = _rival_ids(known_optimum_players, 4)
    free = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)
    assert free.solver_status is SolverStatus.OPTIMAL

    overlaps: list[int] = []
    scores: list[float] = []
    for floor in (1, 2, 3):
        banded = optimize_transfer_plan(
            horizon,
            OPTIMAL_INITIAL,
            small_config,
            first_week_overlap=FirstWeekOverlap(player_ids=rival, minimum=floor),
        )
        assert banded.solver_status is SolverStatus.OPTIMAL
        held = {str(v) for v in banded.weeks[0].selected_squad["player_id"].tolist()}
        overlap = len(held & {str(p) for p in rival})
        assert overlap >= floor
        overlaps.append(overlap)
        assert banded.total_projected_score is not None
        scores.append(float(banded.total_projected_score))
    assert overlaps == sorted(overlaps)
    assert scores == sorted(scores, reverse=True)
    assert free.total_projected_score is not None
    assert all(score <= float(free.total_projected_score) for score in scores)


def test_a_ceiling_caps_the_overlap(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    # Cap against the strong players the unconstrained optimum would hold.
    strong = frozenset(
        str(v) for v in known_optimum_players["player_id"].tolist() if str(v).endswith("_A")
    )
    banded = optimize_transfer_plan(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        first_week_overlap=FirstWeekOverlap(player_ids=strong, maximum=2),  # type: ignore[arg-type]
    )
    assert banded.solver_status is SolverStatus.OPTIMAL
    held = {str(v) for v in banded.weeks[0].selected_squad["player_id"].tolist()}
    assert len(held & strong) <= 2


def test_an_impossible_floor_is_infeasible_not_arbitrary(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    """A floor above what the horizon carries: INFEASIBLE, deterministically."""

    horizon = _one_week(known_optimum_players)
    result = optimize_transfer_plan(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        first_week_overlap=FirstWeekOverlap(player_ids=frozenset({"NOT_IN_WORLD"}), minimum=1),
    )
    assert result.solver_status is SolverStatus.INFEASIBLE
    assert result.weeks == ()


def test_no_band_is_todays_planner_bit_for_bit(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    plain = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)
    with_none = optimize_transfer_plan(
        horizon, OPTIMAL_INITIAL, small_config, first_week_overlap=None
    )
    assert [week.selected_squad["player_id"].tolist() for week in plain.weeks] == [
        week.selected_squad["player_id"].tolist() for week in with_none.weeks
    ]
    assert plain.objective_value == with_none.objective_value


# --- the strategy-level generator ---------------------------------------------------


def _overlap_strategy(floor: int) -> Strategy:
    return Strategy(
        slug="ortak-koru",
        constraints=CandidateConstraints(overlap_floor=floor),
        ranks_by=RankingCriterion.EXPECTED_GAP_VS_RIVAL,
        publishes=frozenset({"moves", "expected_points_cost", "overlap_count"}),
        evidence=EvidenceStatus.PREREG_OPEN,
        rival_required=True,
    )


def test_a_strategy_plan_carries_overlap_and_a_measured_price(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    rival = _rival_ids(known_optimum_players, 4)
    control = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)

    result = solve_strategy_plan(
        _overlap_strategy(2),
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        rival_player_ids=rival,  # type: ignore[arg-type]
        control_plan=control,
    )

    assert result is not None
    assert result.overlap_count is not None and result.overlap_count >= 2
    # The price is the control's expected points minus the banded plan's: the banded
    # plan cannot beat the control, so the tag is non-negative and measured, not typed.
    assert result.expected_points_cost >= 0.0
    assert control.total_projected_score is not None
    assert result.plan.total_projected_score is not None
    assert result.expected_points_cost == pytest.approx(
        float(control.total_projected_score) - float(result.plan.total_projected_score)
    )


def test_an_impossible_band_shortens_the_menu_instead_of_lying(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    result = solve_strategy_plan(
        _overlap_strategy(1),
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        rival_player_ids=frozenset({"NOT_IN_WORLD"}),  # type: ignore[arg-type]
    )
    assert result is None  # no unproven or impossible entry is produced


def test_the_control_strategy_is_the_plain_planner(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    plain = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)
    result = solve_strategy_plan(strategy("saf-puan"), horizon, OPTIMAL_INITIAL, small_config)
    assert result is not None
    assert result.expected_points_cost == 0.0
    assert result.overlap_count is None
    assert [w.selected_squad["player_id"].tolist() for w in result.plan.weeks] == [
        w.selected_squad["player_id"].tolist() for w in plain.weeks
    ]


def test_knobs_move_only_the_declared_space(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    rival = _rival_ids(known_optimum_players, 4)
    with pytest.raises(StrategyConfigurationError, match="declared space"):
        solve_strategy_plan(
            _overlap_strategy(2),
            horizon,
            OPTIMAL_INITIAL,
            small_config,
            rival_player_ids=rival,  # type: ignore[arg-type]
            knob_values={"surprise_knob": 3},
        )


def test_a_rival_relative_strategy_without_a_rival_is_refused(
    known_optimum_players: pd.DataFrame, small_config: OptimizationConfig
) -> None:
    horizon = _one_week(known_optimum_players)
    with pytest.raises(StrategyConfigurationError, match="requires a rival"):
        solve_strategy_plan(_overlap_strategy(2), horizon, OPTIMAL_INITIAL, small_config)
