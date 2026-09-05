"""The Phase E candidate generator: control unchanged, exact cuts, proven order.

Every pool is synthetic. The brute-force tests enumerate every legal complete decision of a
small pool by hand and check the generator against that list, so the exact no-good and the
exhaustion rule are tested against the truth rather than against the solver's own answer.
"""

from dataclasses import replace
from decimal import Decimal
from itertools import combinations, product

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from pandas.testing import assert_frame_equal

from squadopt.optimization import (
    InvalidConfigurationError,
    OptimizationConfig,
    OptimizationResult,
    SolverStatus,
    SquadCandidateSet,
    decision_signature,
    generate_squad_candidates,
    optimize_squad,
)
from squadopt.optimization import optimizer as optimizer_module
from squadopt.optimization.coefficients import objective_coefficients

TIMING_KEYS = {
    "solve_time_seconds",
    "primary_deterministic_time",
    "tiebreak_deterministic_time",
    "tiebreak_deterministic_time_limit",
    "deterministic_time_used",
    "deterministic_time_budget_exhausted",
}


def _ids(frame: pd.DataFrame) -> set[object]:
    return set(frame["player_id"].tolist())


def _assert_legal(
    result: OptimizationResult, players: pd.DataFrame, config: OptimizationConfig
) -> None:
    squad = result.selected_squad
    eleven = result.starting_xi
    assert result.captain is not None
    assert len(squad) == config.squad_size
    assert len(eleven) == config.starting_size
    assert _ids(eleven) <= _ids(squad)
    assert result.captain["player_id"] in _ids(eleven)
    assert _ids(squad) <= _ids(players)
    assert int(squad["price_tenths"].sum()) <= config.budget_tenths
    assert int(squad["team_id"].value_counts().max()) <= config.max_players_per_team
    for position, limit in config.squad_position_limits.items():
        assert int((squad["position"] == position).sum()) == limit
        started = int((eleven["position"] == position).sum())
        assert config.starting_position_min[position] <= started
        assert started <= config.starting_position_max[position]


def _enumerate_decisions(
    players: pd.DataFrame, config: OptimizationConfig
) -> list[tuple[Decimal, tuple[object, ...], tuple[object, ...], object]]:
    """Every legal complete decision with its exact deterministic objective, best first."""

    rows = players.to_dict("records")
    coefficients = dict(
        zip(
            players["player_id"].tolist(),
            objective_coefficients(players["expected_points"].tolist(), config),
            strict=True,
        )
    )
    by_position = {
        position: [row for row in rows if row["position"] == position]
        for position in config.squad_position_limits
    }
    decisions = []
    for chosen in product(
        *(
            combinations(by_position[position], config.squad_position_limits[position])
            for position in config.squad_position_limits
        )
    ):
        squad = [row for group in chosen for row in group]
        if sum(int(row["price_tenths"]) for row in squad) > config.budget_tenths:
            continue
        teams = pd.Series([row["team_id"] for row in squad]).value_counts()
        if int(teams.max()) > config.max_players_per_team:
            continue
        for eleven in combinations(squad, config.starting_size):
            counts = {position: 0 for position in config.squad_position_limits}
            for row in eleven:
                counts[row["position"]] += 1
            if any(
                not config.starting_position_min[position]
                <= counts[position]
                <= config.starting_position_max[position]
                for position in counts
            ):
                continue
            bench = [row for row in squad if row not in eleven]
            for captain in eleven:
                objective = (
                    sum(coefficients[row["player_id"]][2] for row in eleven)
                    + coefficients[captain["player_id"]][2]
                    + sum(coefficients[row["player_id"]][0] for row in bench)
                )
                decisions.append(
                    (
                        Decimal(objective) / config.expected_points_scale,
                        tuple(sorted(str(row["player_id"]) for row in squad)),
                        tuple(sorted(str(row["player_id"]) for row in eleven)),
                        captain["player_id"],
                    )
                )
    decisions.sort(key=lambda item: item[0], reverse=True)
    return decisions


def _stringified(
    signature: tuple[tuple[object, ...], tuple[object, ...], object],
) -> tuple[object, ...]:
    squad, eleven, captain = signature
    return (tuple(sorted(str(v) for v in squad)), tuple(sorted(str(v) for v in eleven)), captain)


def test_the_control_is_the_unchanged_optimize_squad_result(
    baseline_players: pd.DataFrame,
) -> None:
    config = OptimizationConfig()
    expected = optimize_squad(baseline_players, config)

    generated = generate_squad_candidates(baseline_players, config, candidate_count=4)

    control = generated.control
    assert_frame_equal(control.selected_squad, expected.selected_squad)
    assert_frame_equal(control.starting_xi, expected.starting_xi)
    assert_frame_equal(control.bench, expected.bench)
    assert control.captain is not None and expected.captain is not None
    assert control.captain["player_id"] == expected.captain["player_id"]
    assert control.objective_value == expected.objective_value
    assert control.solver_status is SolverStatus.OPTIMAL
    assert {k: v for k, v in control.diagnostics.items() if k not in TIMING_KEYS} == {
        k: v for k, v in expected.diagnostics.items() if k not in TIMING_KEYS
    }


def test_candidates_are_distinct_legal_and_ordered_by_objective(
    baseline_players: pd.DataFrame,
) -> None:
    config = OptimizationConfig()

    generated = generate_squad_candidates(baseline_players, config, candidate_count=4)

    assert generated.complete
    assert generated.termination_status is SolverStatus.OPTIMAL
    assert len(generated.candidates) == 4
    signatures = [decision_signature(candidate) for candidate in generated.candidates]
    assert len(set(signatures)) == 4
    objectives = [candidate.objective_value for candidate in generated.candidates]
    assert all(value is not None for value in objectives)
    assert objectives == sorted(objectives, reverse=True)  # type: ignore[type-var]
    for candidate in generated.candidates:
        assert candidate.solver_status is SolverStatus.OPTIMAL
        _assert_legal(candidate, baseline_players, config)


def test_the_top_k_matches_a_brute_force_enumeration_and_exhausts_the_space(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    truth = _enumerate_decisions(known_optimum_players, small_config)
    assert 6 < len(truth) < 200, "the pool must be small enough to enumerate by hand"

    generated = generate_squad_candidates(
        known_optimum_players, small_config, candidate_count=len(truth) + 5
    )

    assert generated.complete
    assert generated.termination_status is SolverStatus.INFEASIBLE
    assert len(generated.candidates) == len(truth)
    produced = [
        (Decimal(str(candidate.objective_value)), *_stringified(decision_signature(candidate)))
        for candidate in generated.candidates
    ]
    assert [item[0] for item in produced] == [item[0] for item in truth]
    assert sorted(produced) == sorted(truth), "every legal decision appears exactly once"


def test_a_bench_only_difference_is_a_distinct_candidate(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    """A second copy of the benched defender ties the control on a bench-only swap."""

    players = known_optimum_players.copy(deep=True)
    twin = players.loc[players["player_id"] == "DEF_A"].copy()
    twin["player_id"] = "DEF_A2"
    twin["team_id"] = "T9"
    players = pd.concat([players, twin], ignore_index=True)

    generated = generate_squad_candidates(players, small_config, candidate_count=2)

    control, second = generated.candidates
    control_squad, control_eleven, control_captain = decision_signature(control)
    second_squad, second_eleven, second_captain = decision_signature(second)
    assert control_squad != second_squad
    assert control_eleven == second_eleven
    assert control_captain == second_captain
    assert second.objective_value == control.objective_value
    assert {"DEF_A", "DEF_A2"} == set(control_squad) ^ set(second_squad)


def test_generation_is_deterministic_and_leaves_the_pool_untouched(
    baseline_players: pd.DataFrame,
) -> None:
    before = baseline_players.copy(deep=True)

    first = generate_squad_candidates(baseline_players, candidate_count=4)
    second = generate_squad_candidates(baseline_players, candidate_count=4)

    assert_frame_equal(baseline_players, before)
    assert [decision_signature(c) for c in first.candidates] == [
        decision_signature(c) for c in second.candidates
    ]
    assert [c.objective_value for c in first.candidates] == [
        c.objective_value for c in second.candidates
    ]


def test_required_players_hold_for_every_candidate(baseline_players: pd.DataFrame) -> None:
    generated = generate_squad_candidates(
        baseline_players, candidate_count=3, required_player_ids=(1, 24)
    )

    assert generated.complete
    for candidate in generated.candidates:
        assert {1, 24} <= _ids(candidate.selected_squad)


def test_an_unsolved_control_is_returned_alone_and_incomplete(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    config = replace(small_config, budget_tenths=0)

    generated = generate_squad_candidates(known_optimum_players, config, candidate_count=4)

    assert generated.candidates == (generated.control,)
    assert not generated.complete
    assert generated.termination_status is SolverStatus.INFEASIBLE
    assert generated.control.solver_status is SolverStatus.INFEASIBLE
    assert generated.control.selected_squad.empty
    assert generated.control.captain is None


@pytest.mark.parametrize("injected", [cp_model.FEASIBLE, cp_model.UNKNOWN])
def test_an_unproven_alternative_stops_the_search_and_is_not_kept(
    baseline_players: pd.DataFrame,
    monkeypatch: pytest.MonkeyPatch,
    injected: int,
) -> None:
    """The control solves normally; the first alternative's primary solve is unproven."""

    real_solve = optimizer_module._solve
    calls: list[int] = []

    def fake_solve(model: cp_model.CpModel, solver: cp_model.CpSolver) -> int:
        calls.append(len(calls))
        if len(calls) == 3:  # control primary, control tie-break, then the alternative
            if injected == cp_model.UNKNOWN:
                return int(cp_model.UNKNOWN)
            real_solve(model, solver)
            return int(cp_model.FEASIBLE)
        return real_solve(model, solver)

    monkeypatch.setattr(optimizer_module, "_solve", fake_solve)

    generated = generate_squad_candidates(baseline_players, candidate_count=4)

    assert len(calls) == 3, "the search stops at the first unproven solve"
    assert generated.candidates == (generated.control,)
    assert not generated.complete
    assert generated.termination_status is optimizer_module._map_solver_status(injected)
    assert generated.control.solver_status is SolverStatus.OPTIMAL


@pytest.mark.parametrize("count", [0, -1, True, "4", 2.0])
def test_the_candidate_count_must_be_a_positive_integer(
    baseline_players: pd.DataFrame, count: object
) -> None:
    with pytest.raises(InvalidConfigurationError):
        generate_squad_candidates(baseline_players, candidate_count=count)  # type: ignore[arg-type]


def test_the_candidate_set_validates_its_shape(baseline_result: OptimizationResult) -> None:
    with pytest.raises(InvalidConfigurationError):
        SquadCandidateSet(
            candidates=(baseline_result, baseline_result),
            candidate_count_requested=1,
            complete=True,
            termination_status=SolverStatus.OPTIMAL,
        )
    with pytest.raises(InvalidConfigurationError):
        SquadCandidateSet(
            candidates=(),
            candidate_count_requested=1,
            complete=True,
            termination_status=SolverStatus.OPTIMAL,
        )


def test_excluding_a_decision_returns_the_next_best_and_refuses_foreign_ones(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    truth = _enumerate_decisions(known_optimum_players, small_config)
    control = optimize_squad(known_optimum_players, small_config)

    alternative = optimize_squad(known_optimum_players, small_config, excluded_decisions=(control,))

    assert decision_signature(alternative) != decision_signature(control)
    assert Decimal(str(alternative.objective_value)) == truth[1][0]

    foreign = known_optimum_players.copy(deep=True)
    foreign.loc[foreign["player_id"] == "MID_A", "player_id"] = "MID_Z"
    with pytest.raises(InvalidConfigurationError):
        optimize_squad(foreign, small_config, excluded_decisions=(control,))
    with pytest.raises(InvalidConfigurationError):
        optimize_squad(
            known_optimum_players,
            small_config,
            excluded_decisions=(replace(control, captain=None),),
        )
