"""Frozen utility arithmetic, official scoring and fail-closed candidate selection."""

from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_component_decision_scoring import _draw, _optimization_result

from squadopt.application.phase_e import PHASE_E_CALIBRATED_VERSIONS
from squadopt.evaluation import EvaluationValidationError
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.scenarios import selection
from squadopt.scenarios.components import ComponentScenarioDraw, _component_fingerprint
from squadopt.scenarios.models import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioValidationError,
    _scenario_fingerprint,
)
from squadopt.scenarios.selection import (
    PhaseESelectionStatus,
    integer_mean_cvar,
    select_phase_e_candidate,
)


def _candidates() -> tuple[OptimizationResult, ...]:
    challenger = replace(_optimization_result(), objective_value=99.0)
    control = replace(
        challenger,
        captain=challenger.selected_squad.loc[challenger.selected_squad["player_id"].eq(14)]
        .iloc[0]
        .copy(),
        objective_value=100.0,
    )
    return control, challenger


def _full_draw(
    *, missing: int | None = None, config: ScenarioConfig | None = None
) -> ComponentScenarioDraw:
    """Repeat the existing hand-checked two-scenario autosub fixture 500 times."""
    result = _optimization_result()
    ids = tuple(player_id for player_id in range(1, 16) if player_id != missing)
    original = _draw(result, player_ids=ids)
    settings = config or ScenarioConfig()
    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(settings.scenario_count))
    sources = tuple(
        original.scenarios.source_fold_ids[index % 2] for index in range(len(scenario_ids))
    )

    def repeat(frame: pd.DataFrame) -> pd.DataFrame:
        expanded = (
            pd.concat([frame] * ((len(scenario_ids) + 1) // 2), ignore_index=True)
            .iloc[: len(scenario_ids)]
            .copy()
        )
        expanded.index = pd.Index(scenario_ids, name="scenario_id")
        return expanded

    points = repeat(original.scenarios.scenario_points)
    appearances = repeat(original.sampled_appearances)
    minutes = repeat(original.sampled_minutes)
    inputs = replace(
        original.inputs,
        provenance=replace(
            original.inputs.provenance,
            model_version=original.scenarios.projections.provenance.model_version,
        ),
    )
    scenarios = ScenarioSet(
        projections=original.scenarios.projections,
        target=original.scenarios.target,
        config=settings,
        scenario_ids=scenario_ids,
        source_fold_ids=sources,
        scenario_points=points,
        scenario_fingerprint=_scenario_fingerprint(
            original.scenarios.projections,
            original.scenarios.target,
            settings,
            scenario_ids,
            sources,
            points,
        ),
        diagnostics={},
    )
    return ComponentScenarioDraw(
        scenarios=scenarios,
        inputs=inputs,
        sampled_minutes=minutes,
        sampled_appearances=appearances,
        component_fingerprint=_component_fingerprint(scenarios, inputs, minutes, appearances),
    )


def _select(
    candidates: tuple[OptimizationResult, ...],
    draw: ComponentScenarioDraw | None,
    *,
    complete: bool = True,
    pinned: bool = True,
):
    pins = (
        ((draw.inputs.provenance.model_version, draw.inputs.contract_version),)
        if draw and pinned
        else ()
    )
    return select_phase_e_candidate(
        candidates,
        draw,
        candidate_count_requested=4,
        candidate_set_complete=complete,
        calibrated_versions=pins,
    )


def test_integer_utility_matches_hand_computation_and_can_prefer_a_lower_mean() -> None:
    risky = integer_mean_cvar([10.0] * 900 + [-10.0] * 100)
    steady = integer_mean_cvar([4.0] * 1000)
    assert (risky.mean, risky.cvar, risky.utility_int) == (8.0, -10.0, 350_000_000_000)
    assert steady.mean < risky.mean
    assert steady.utility_int == 400_000_000_000 > risky.utility_int


@pytest.mark.parametrize(
    "value, rounded, expected",
    [(1.0005, 1.001, 100_100_000_000), (-1.0005, -1.001, -100_100_000_000)],
)
def test_round_half_up_applies_before_both_readings(
    value: float, rounded: float, expected: int
) -> None:
    utility = integer_mean_cvar([value] * 1000)
    assert utility.mean == utility.cvar == rounded
    assert utility.utility_int == expected


def test_utility_uses_python_integers_beyond_int64() -> None:
    utility = integer_mean_cvar([10_000_000_000.0] * 1000)
    assert type(utility.utility_int) is int
    assert utility.utility_int == 10**21


@pytest.mark.parametrize(
    "scores", [[], [1.0] * 999, [float("nan")] * 1000, [float("inf")] * 1000, [True] * 1000]
)
def test_utility_rejects_unfrozen_or_invalid_scores(scores: list[float]) -> None:
    with pytest.raises(ScenarioValidationError):
        integer_mean_cvar(scores)


def test_real_official_scorer_selects_challenger_with_shared_draw_and_no_mutation() -> None:
    candidates = _candidates()
    draw = _full_draw()
    before = draw.scenarios.scenario_points.copy(deep=True)
    squad_before = candidates[0].selected_squad.copy(deep=True)
    selected = _select(candidates, draw)
    assert selected.selection_status is PhaseESelectionStatus.SELECTED
    assert selected.selected_result is candidates[1]
    assert selected.control_result is candidates[0]
    assert selected.selected_candidate_rank == 1
    assert selected.candidate_count_requested == 4
    assert selected.candidate_count_proven == selected.candidate_count_scored == 2
    assert selected.scenario_fingerprint == draw.scenarios.scenario_fingerprint
    assert selected.component_fingerprint == draw.component_fingerprint
    # Original fixture totals: captain 14 gives (12,21); captain 13 gives (12,27),
    # with autosubs and vice-captain 8 handling the captain's non-appearance.
    assert [(row.mean, row.cvar, row.utility_int) for row in selected.diagnostics] == [
        (16.5, 12.0, 1_537_500_000_000),
        (19.5, 12.0, 1_762_500_000_000),
    ]
    assert selected.diagnostics[1].deterministic_gap == 1.0
    assert_frame_equal(before, draw.scenarios.scenario_points)
    assert_frame_equal(squad_before, candidates[0].selected_squad)


def test_calibration_pin_is_empty_and_unknown_versions_fall_back_without_scores() -> None:
    assert PHASE_E_CALIBRATED_VERSIONS == ()
    candidates = _candidates()
    draw = _full_draw()
    result = _select(candidates, draw, pinned=False)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.selected_result is candidates[0]
    assert result.candidate_count_scored == 0
    assert result.component_fingerprint == draw.component_fingerprint
    result = _select(candidates, None)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.scenario_fingerprint is result.component_fingerprint is None


def test_incomplete_and_feasible_candidates_do_not_consult_a_draw() -> None:
    candidates = _candidates()
    for pool, complete in [
        (candidates, False),
        ((replace(candidates[0], solver_status=SolverStatus.FEASIBLE),), True),
    ]:
        result = _select(pool, None, complete=complete)
        assert result.selection_status is PhaseESelectionStatus.FALLBACK_INCOMPLETE_CANDIDATES
        assert result.selected_result is pool[0]
        assert result.component_fingerprint is None


def test_unknown_alternative_returns_control_instead_of_completing_an_empty_decision() -> None:
    control, challenger = _candidates()
    unknown = replace(
        challenger,
        solver_status=SolverStatus.UNKNOWN,
        captain=None,
        objective_value=None,
        selected_squad=challenger.selected_squad.iloc[:0],
        starting_xi=challenger.starting_xi.iloc[:0],
        bench=challenger.bench.iloc[:0],
    )
    result = _select((control, unknown), None)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_INCOMPLETE_CANDIDATES
    assert result.selected_result is control
    assert result.candidate_count_proven == 1
    assert result.candidate_count_scored == 0
    assert len(result.diagnostics) == 1


@pytest.mark.parametrize(
    "config",
    [
        ScenarioConfig(scenario_count=999),
        ScenarioConfig(player_location_shrinkage=0.0),
        ScenarioConfig(deterministic_seed=5),
    ],
)
def test_unapproved_sampler_settings_cannot_use_a_version_pin(config: ScenarioConfig) -> None:
    result = _select(_candidates(), _full_draw(config=config))
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.candidate_count_scored == 0


def test_uncovered_control_falls_back_without_inventing_player_outcomes() -> None:
    candidates = _candidates()
    draw = _full_draw(missing=15)
    result = _select(candidates, draw)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_SCENARIO_COVERAGE
    assert result.selected_result is candidates[0]
    assert result.candidate_count_scored == 0
    assert all(record.covered is False for record in result.diagnostics)


def test_duplicate_or_unordered_candidates_are_rejected() -> None:
    candidates = _candidates()
    with pytest.raises(ScenarioValidationError, match="unique"):
        _select((candidates[0], candidates[0]), None)
    with pytest.raises(ScenarioValidationError, match="decreasing"):
        _select(tuple(reversed(candidates)), None)


def test_unsolved_control_preserves_the_existing_completion_error() -> None:
    control = replace(_candidates()[0], solver_status=SolverStatus.UNKNOWN, captain=None)
    with pytest.raises(EvaluationValidationError, match="OPTIMAL or FEASIBLE"):
        _select((control,), None)


def test_equal_utility_prefers_control_and_every_candidate_receives_the_same_draw(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ComponentScenarioDraw] = []

    def score(candidate: OptimizationResult, draw: ComponentScenarioDraw) -> SimpleNamespace:
        seen.append(draw)
        return SimpleNamespace(total_points=(7.0,) * 1000)

    monkeypatch.setattr(selection, "score_component_scenario_decision", score)
    candidates = _candidates()
    draw = _full_draw()
    first = _select(candidates, draw)
    second = _select(candidates, draw)
    assert first.selected_candidate_rank == second.selected_candidate_rank == 0
    assert first.selected_result is second.selected_result is candidates[0]
    assert first.diagnostics == second.diagnostics
    assert len(seen) == 4
    assert seen[0] is seen[1]
    assert seen[2] is seen[3]
    assert all(item.component_fingerprint == draw.component_fingerprint for item in seen)


@pytest.mark.parametrize("keep_challenger", [False, True])
def test_uncovered_alternative_is_eliminated_and_two_covered_candidates_are_required(
    monkeypatch: pytest.MonkeyPatch, keep_challenger: bool
) -> None:
    monkeypatch.setattr(
        selection,
        "score_component_scenario_decision",
        lambda candidate, draw: SimpleNamespace(total_points=(7.0,) * 1000),
    )
    control, challenger = _candidates()

    def rename(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.assign(player_id=frame["player_id"].replace({15: 99}))

    uncovered = replace(
        challenger,
        selected_squad=rename(challenger.selected_squad),
        starting_xi=rename(challenger.starting_xi),
        bench=rename(challenger.bench),
        objective_value=98.0,
    )
    pool = (control, challenger, uncovered) if keep_challenger else (control, uncovered)
    result = _select(pool, _full_draw())
    assert result.diagnostics[-1].covered is False
    assert result.diagnostics[-1].utility_int is None
    assert result.candidate_count_scored == (2 if keep_challenger else 1)
    assert result.selected_result is control
    assert result.selection_status is (
        PhaseESelectionStatus.SELECTED
        if keep_challenger
        else PhaseESelectionStatus.FALLBACK_SCENARIO_COVERAGE
    )


def test_inconsistent_model_provenance_does_not_receive_calibration_by_assertion() -> None:
    draw = _full_draw()
    inputs = replace(draw.inputs, provenance=replace(draw.inputs.provenance, model_version="other"))
    mismatched = replace(
        draw,
        inputs=inputs,
        component_fingerprint=_component_fingerprint(
            draw.scenarios, inputs, draw.sampled_minutes, draw.sampled_appearances
        ),
    )
    result = _select(_candidates(), mismatched)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.candidate_count_scored == 0
