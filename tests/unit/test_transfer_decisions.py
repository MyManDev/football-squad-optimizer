"""Member transfer candidates on one shared draw: rules, one hit, identities, named fallbacks.

The 15-player official-scoring fixture and the 1000-scenario draw of the Phase E tests are
reused. The member holds players 1 to 13 plus 16 and 17, so every candidate that reaches the
draw must move 16 and 17 out and 14 and 15 in: two transfers, one of them paid.
"""

import json
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from tests.unit.test_component_decision_scoring import TARGET, _optimization_result
from tests.unit.test_phase_e_selection import _full_draw

from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioValidationError,
    TransferDecisionCandidate,
    TransferSelectionStatus,
    TransferStartState,
    evaluate_transfer_candidates,
    integer_mean_cvar,
    score_component_scenario_decision,
    selection_record,
    transfer_candidate_from_plan,
)
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ComponentScenarioDraw,
    _component_fingerprint,
)

HELD = (*range(1, 14), 16, 17)
START = TransferStartState(
    season=TARGET.season,
    gameweek=TARGET.gameweek,
    squad_player_ids=HELD,
    bank_tenths=25,
    free_transfers=1,
)
HIT = 4.0


def _with_captain(result: OptimizationResult, player_id: int) -> OptimizationResult:
    squad = result.selected_squad
    return replace(result, captain=squad.loc[squad["player_id"].eq(player_id)].iloc[0].copy())


def _candidate(
    label: str,
    decision: OptimizationResult,
    *,
    ins: tuple[int, ...] = (14, 15),
    outs: tuple[int, ...] = (16, 17),
    chip: str | None = None,
    hit: float | None = None,
    free: int = 1,
    bank: int = 25,
    horizon: str | None = "horizon-a",
    gameweek: int = START.gameweek,
) -> TransferDecisionCandidate:
    paid = 0 if chip in ("wildcard", "freehit") else max(0, len(ins) - free)
    return TransferDecisionCandidate(
        label=label,
        gameweek=gameweek,
        decision=decision,
        transfers_in=ins,
        transfers_out=outs,
        free_transfers_before=free,
        paid_transfer_count=paid,
        transfer_hit_points=paid * HIT if hit is None else hit,
        bank_before_tenths=bank,
        bank_after_tenths=bank,
        chip=chip,
        planner_status="OPTIMAL",
        planner_objective=100.0,
        horizon_fingerprint=horizon,
    )


def _pin(draw: ComponentScenarioDraw) -> tuple[tuple[str, str], ...]:
    return ((draw.inputs.provenance.model_version, draw.inputs.contract_version),)


def _raw_mean(decision: OptimizationResult, draw: ComponentScenarioDraw) -> float:
    scores = score_component_scenario_decision(decision, draw)
    return integer_mean_cvar([float(score.total_points) for score in scores.scores]).mean


def test_candidates_share_one_draw_and_pay_the_hit_exactly_once() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    # Captain 14 scores 1 in both scenarios, so the challenger forgoes the vice-captain's 7 the
    # control collects when captain 13 is absent: (27 - 21) / 2 = 3.0 points of mean, same tail.
    challenger = _candidate("captain-14", _with_captain(_optimization_result(), 14))

    selection = evaluate_transfer_candidates(
        (control, challenger), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.SELECTED
    assert selection.candidate_count == 2 and selection.candidate_count_scored == 2
    assert selection.control is control
    assert selection.scenario_fingerprint == draw.scenarios.scenario_fingerprint
    assert selection.component_fingerprint == draw.component_fingerprint
    assert selection.sampler_contract_version == COMPONENT_SCENARIO_CONTRACT_VERSION
    assert selection.start_state_fingerprint == START.fingerprint
    first, second = selection.diagnostics
    assert first.covered and second.covered and first.same_captain and not second.same_captain
    assert first.squad_overlap == 15 and first.transfer_hit_points == HIT
    assert first.transfers_in == (14, 15) and first.transfers_out == (16, 17)
    # Net of the hit, once: the mean moves by exactly the planner's hit, never twice.
    assert first.mean == pytest.approx(_raw_mean(control.decision, draw) - HIT)
    assert second.mean == pytest.approx(_raw_mean(challenger.decision, draw) - HIT)
    scores = score_component_scenario_decision(control.decision, draw)
    net = integer_mean_cvar([float(score.total_points) - HIT for score in scores.scores])
    assert first.utility_int == net.utility_int and first.cvar == pytest.approx(net.cvar)
    assert second.mean == pytest.approx(first.mean - 3.0)
    assert second.cvar == pytest.approx(first.cvar)
    assert first.utility_int is not None and second.utility_int is not None
    assert first.utility_int > second.utility_int
    assert selection.selected_rank == 0 and selection.selected is control
    assert "control has the highest net utility" in selection.reason
    record = selection_record(selection)
    json.dumps(record, allow_nan=False)
    assert record["status"] == "SELECTED" and len(record["candidates"]) == 2
    assert record["candidates"][0]["mean_net_of_hit"] == pytest.approx(first.mean)


def test_a_wildcard_pays_no_hit_and_a_misreported_hit_is_refused() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    wildcard = _candidate("wildcard", _with_captain(_optimization_result(), 8), chip="wildcard")
    assert wildcard.paid_transfer_count == 0 and wildcard.transfer_hit_points == 0.0

    selection = evaluate_transfer_candidates(
        (control, wildcard), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.SELECTED
    _, second = selection.diagnostics
    assert second.mean == pytest.approx(_raw_mean(wildcard.decision, draw))
    assert second.chip == "wildcard" and second.transfer_hit_points == 0.0

    wrong_hit = _candidate("wrong", _with_captain(_optimization_result(), 8), hit=8.0)
    with pytest.raises(ScenarioValidationError, match="hit points"):
        evaluate_transfer_candidates((control, wrong_hit), draw, start_state=START)
    free_claimed = replace(
        _candidate("free", _with_captain(_optimization_result(), 8)),
        paid_transfer_count=0,
        transfer_hit_points=0.0,
    )
    with pytest.raises(ScenarioValidationError, match="hit points"):
        evaluate_transfer_candidates((control, free_claimed), draw, start_state=START)


@pytest.mark.parametrize(
    "mutation",
    [
        "unpaired_transfers",
        "squad_not_from_transfers",
        "bank",
        "free_transfers",
        "duplicate_signature",
        "duplicate_label",
        "horizon",
        "draw_target",
        "empty",
    ],
)
def test_candidates_outside_the_start_state_or_rules_are_refused(mutation: str) -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    other = _candidate("captain-8", _with_captain(_optimization_result(), 8))
    start = START
    candidates: tuple[TransferDecisionCandidate, ...] = (control, other)
    if mutation == "unpaired_transfers":
        candidates = (control, replace(other, transfers_in=(14,)))
    elif mutation == "squad_not_from_transfers":
        candidates = (control, replace(other, transfers_in=(14, 15), transfers_out=(16, 13)))
    elif mutation == "bank":
        candidates = (control, replace(other, bank_before_tenths=30))
    elif mutation == "free_transfers":
        candidates = (control, replace(other, free_transfers_before=2))
    elif mutation == "duplicate_signature":
        candidates = (control, _candidate("same", _optimization_result()))
    elif mutation == "duplicate_label":
        candidates = (control, replace(other, label="control"))
    elif mutation == "horizon":
        candidates = (control, replace(other, horizon_fingerprint="horizon-b"))
    elif mutation == "draw_target":
        start = replace(START, gameweek=START.gameweek + 1)
    else:
        candidates = ()
    with pytest.raises(ScenarioValidationError):
        evaluate_transfer_candidates(
            candidates, draw, start_state=start, calibrated_versions=_pin(draw)
        )


def test_unknown_chips_and_unsolved_decisions_are_refused_at_construction() -> None:
    with pytest.raises(ScenarioValidationError, match="chip"):
        _candidate("x", _optimization_result(), chip="mystery")
    unsolved = replace(_optimization_result(), solver_status=SolverStatus.INFEASIBLE)
    with pytest.raises(ScenarioValidationError, match="solved"):
        evaluate_transfer_candidates((_candidate("x", unsolved),), None, start_state=START)


def test_unsupported_chips_keep_the_control_or_drop_the_candidate_with_a_reason() -> None:
    draw = _full_draw()
    boosted_control = _candidate("control", _optimization_result(), chip="bboost")
    other = _candidate("captain-8", _with_captain(_optimization_result(), 8))

    selection = evaluate_transfer_candidates(
        (boosted_control, other), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.FALLBACK_UNSUPPORTED_CHIP
    assert selection.selected is boosted_control and selection.selected_rank == 0
    assert selection.candidate_count_scored == 0 and "bboost" in selection.reason
    assert selection.scenario_fingerprint is None and selection.diagnostics[0].supported is False

    control = _candidate("control", _optimization_result())
    triple = _candidate("triple", _with_captain(_optimization_result(), 8), chip="3xc")
    only_pair = evaluate_transfer_candidates(
        (control, triple), draw, start_state=START, calibrated_versions=_pin(draw)
    )
    assert only_pair.status is TransferSelectionStatus.FALLBACK_SCENARIO_COVERAGE
    assert only_pair.selected is control and only_pair.candidate_count_scored == 1
    assert only_pair.diagnostics[1].supported is False and only_pair.diagnostics[1].covered is None
    assert "3xc" in (only_pair.diagnostics[1].reason or "")

    third = _candidate("captain-14", _with_captain(_optimization_result(), 14))
    with_third = evaluate_transfer_candidates(
        (control, triple, third), draw, start_state=START, calibrated_versions=_pin(draw)
    )
    assert with_third.status is TransferSelectionStatus.SELECTED
    assert with_third.candidate_count_scored == 2 and with_third.selected_rank == 0


def test_a_missing_or_unpinned_draw_keeps_the_control_with_its_reason() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    other = _candidate("captain-8", _with_captain(_optimization_result(), 8))

    none = evaluate_transfer_candidates((control, other), None, start_state=START)
    assert none.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert none.selected is control and none.scenario_fingerprint is None
    assert "no component scenario draw" in none.reason

    unpinned = evaluate_transfer_candidates((control, other), draw, start_state=START)
    assert unpinned.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert unpinned.scenario_fingerprint == draw.scenarios.scenario_fingerprint
    assert unpinned.candidate_count_scored == 0 and unpinned.selected is control

    conditional = replace(
        draw,
        scenarios=replace(
            draw.scenarios,
            diagnostics={
                "component_sampler_contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION
            },
        ),
    )
    foundation_pin = evaluate_transfer_candidates(
        (control, other), conditional, start_state=START, calibrated_versions=_pin(draw)
    )
    assert foundation_pin.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert foundation_pin.sampler_contract_version == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    conditional_pin = (
        (draw.inputs.provenance.model_version, CONDITIONAL_RESIDUAL_CONTRACT_VERSION),
    )
    pinned = evaluate_transfer_candidates(
        (control, other), conditional, start_state=START, calibrated_versions=conditional_pin
    )
    assert pinned.status is TransferSelectionStatus.SELECTED

    reseeded = _full_draw(config=ScenarioConfig(deterministic_seed=1))
    seeded = evaluate_transfer_candidates(
        (control, other), reseeded, start_state=START, calibrated_versions=_pin(reseeded)
    )
    assert seeded.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED


def test_an_uncovered_control_or_a_single_covered_candidate_keeps_the_control() -> None:
    draw = _full_draw(missing=15)
    control = _candidate("control", _optimization_result())
    other = _candidate("captain-8", _with_captain(_optimization_result(), 8))

    selection = evaluate_transfer_candidates(
        (control, other), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.FALLBACK_SCENARIO_COVERAGE
    assert selection.selected is control and selection.candidate_count_scored == 0
    assert selection.diagnostics[0].covered is False
    assert "not covered" in selection.reason


def test_the_adapter_reads_only_the_first_week_of_a_plan() -> None:
    result = _optimization_result()
    week = SimpleNamespace(
        gameweek=TARGET.gameweek,
        selected_squad=result.selected_squad,
        starting_xi=result.starting_xi,
        bench=result.bench,
        captain=result.captain,
        transfers_in=pd.DataFrame({"player_id": [15, 14], "name": ["P15", "P14"]}),
        transfers_out=pd.DataFrame({"player_id": [17, 16], "name": ["P17", "P16"]}),
        bank_before_tenths=25,
        bank_after_tenths=25,
        free_transfers_before=1,
        paid_transfer_count=1,
        transfer_hit_points=4.0,
        projected_score=50.0,
        chip=None,
    )
    later = SimpleNamespace(**{**vars(week), "chip": "bboost", "transfer_hit_points": 0.0})
    plan = SimpleNamespace(
        solver_status=SolverStatus.OPTIMAL,
        weeks=(week, later),
        horizon_fingerprint="horizon-a",
        objective_value=46.0,
    )

    candidate = transfer_candidate_from_plan(plan, label="planner")

    assert candidate.gameweek == TARGET.gameweek
    assert candidate.transfers_in == (14, 15) and candidate.transfers_out == (16, 17)
    assert candidate.transfer_count == 2 and candidate.paid_transfer_count == 1
    assert candidate.transfer_hit_points == 4.0 and candidate.chip is None
    assert candidate.planner_status == "OPTIMAL" and candidate.planner_objective == 46.0
    assert candidate.horizon_fingerprint == "horizon-a" and candidate.projected_score == 50.0
    assert candidate.decision.solver_status is SolverStatus.OPTIMAL
    assert candidate.decision.objective_value == 46.0 and candidate.decision.projected_score == 50.0
    assert candidate.signature()[2] == 13
    draw = _full_draw()
    selection = evaluate_transfer_candidates(
        (candidate, _candidate("captain-8", _with_captain(result, 8))),
        draw,
        start_state=START,
        calibrated_versions=_pin(draw),
    )
    assert selection.status is TransferSelectionStatus.SELECTED
    with pytest.raises(ScenarioValidationError, match="planned week"):
        transfer_candidate_from_plan(SimpleNamespace(**{**vars(plan), "weeks": ()}), label="empty")


def test_a_plan_for_another_week_is_never_evaluated_against_this_start_state() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    next_week = _candidate(
        "next-week", _with_captain(_optimization_result(), 8), gameweek=START.gameweek + 1
    )
    with pytest.raises(ScenarioValidationError, match="gameweek"):
        evaluate_transfer_candidates(
            (control, next_week), draw, start_state=START, calibrated_versions=_pin(draw)
        )
    with pytest.raises(ScenarioValidationError, match="gameweek"):
        evaluate_transfer_candidates(
            (control,), None, start_state=replace(START, gameweek=START.gameweek + 1)
        )

    result = _optimization_result()
    week = SimpleNamespace(
        gameweek=START.gameweek + 1,
        selected_squad=result.selected_squad,
        starting_xi=result.starting_xi,
        bench=result.bench,
        captain=result.captain,
        transfers_in=pd.DataFrame({"player_id": [14, 15]}),
        transfers_out=pd.DataFrame({"player_id": [16, 17]}),
        bank_before_tenths=25,
        bank_after_tenths=25,
        free_transfers_before=1,
        paid_transfer_count=1,
        transfer_hit_points=4.0,
        projected_score=50.0,
        chip=None,
    )
    plan = SimpleNamespace(
        solver_status=SolverStatus.OPTIMAL,
        weeks=(week,),
        horizon_fingerprint="horizon-a",
        objective_value=46.0,
    )
    with pytest.raises(ScenarioValidationError, match="first week is gameweek"):
        transfer_candidate_from_plan(plan, label="planner", gameweek=START.gameweek)
    adapted = transfer_candidate_from_plan(plan, label="planner")
    assert adapted.gameweek == START.gameweek + 1
    with pytest.raises(ScenarioValidationError, match="gameweek"):
        evaluate_transfer_candidates((adapted,), None, start_state=START)


def test_the_same_decision_under_another_chip_is_a_distinct_candidate() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    wildcard = _candidate("wildcard", _optimization_result(), chip="wildcard")
    assert control.signature() == wildcard.signature()
    assert control.identity() != wildcard.identity()

    selection = evaluate_transfer_candidates(
        (control, wildcard), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.SELECTED
    first, second = selection.diagnostics
    assert first.transfer_hit_points == HIT and second.transfer_hit_points == 0.0
    assert second.mean == pytest.approx(first.mean + HIT)
    assert selection.selected_rank == 1 and selection.selected is wildcard
    assert "wildcard has the highest net utility" in selection.reason

    same_chip = _candidate("same", _optimization_result())
    with pytest.raises(ScenarioValidationError, match="distinct"):
        evaluate_transfer_candidates((control, same_chip), draw, start_state=START)


def test_an_exact_tie_on_the_shared_draw_keeps_the_control() -> None:
    draw = _full_draw()
    control = _candidate("control", _optimization_result())
    # Captain 8 doubles the same 7 the control's vice-captain doubles: identical scores.
    tie = _candidate("captain-8", _with_captain(_optimization_result(), 8))

    selection = evaluate_transfer_candidates(
        (control, tie), draw, start_state=START, calibrated_versions=_pin(draw)
    )

    first, second = selection.diagnostics
    assert first.utility_int == second.utility_int
    assert first.mean == pytest.approx(second.mean)
    assert selection.status is TransferSelectionStatus.SELECTED
    assert selection.selected_rank == 0 and selection.selected is control


def test_a_draw_for_another_deadline_is_refused_even_when_candidates_agree_with_the_start() -> None:
    draw = _full_draw()
    later = replace(START, gameweek=START.gameweek + 1)
    control = _candidate("control", _optimization_result(), gameweek=later.gameweek)
    other = _candidate(
        "captain-14", _with_captain(_optimization_result(), 14), gameweek=later.gameweek
    )

    with pytest.raises(ScenarioValidationError, match="simulates"):
        evaluate_transfer_candidates(
            (control, other), draw, start_state=later, calibrated_versions=_pin(draw)
        )


def test_hit_arithmetic_follows_free_transfers_and_the_seasons_hit_cost() -> None:
    draw = _full_draw()
    two_free = replace(START, free_transfers=2)
    banked = _candidate("banked", _optimization_result(), free=2)
    assert banked.paid_transfer_count == 0 and banked.transfer_hit_points == 0.0
    other = _candidate("captain-14", _with_captain(_optimization_result(), 14), free=2)

    selection = evaluate_transfer_candidates(
        (banked, other), draw, start_state=two_free, calibrated_versions=_pin(draw)
    )

    assert selection.status is TransferSelectionStatus.SELECTED
    assert selection.diagnostics[0].transfer_hit_points == 0.0
    assert selection.diagnostics[0].mean == pytest.approx(_raw_mean(banked.decision, draw))
    overcharged = replace(banked, paid_transfer_count=1, transfer_hit_points=HIT)
    with pytest.raises(ScenarioValidationError, match="hit points"):
        evaluate_transfer_candidates((overcharged,), None, start_state=two_free)

    three_start = TransferStartState(
        season=START.season,
        gameweek=START.gameweek,
        squad_player_ids=(*range(1, 13), 16, 17, 18),
        bank_tenths=25,
        free_transfers=1,
    )
    triple = _candidate("three", _optimization_result(), ins=(13, 14, 15), outs=(16, 17, 18))
    assert triple.paid_transfer_count == 2 and triple.transfer_hit_points == 2 * HIT
    unpinned = evaluate_transfer_candidates((triple,), None, start_state=three_start)
    assert unpinned.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    with pytest.raises(ScenarioValidationError, match=r"5\.0 points per hit"):
        evaluate_transfer_candidates(
            (triple,), None, start_state=three_start, transfer_hit_cost_points=5.0
        )
    priced = replace(triple, transfer_hit_points=10.0)
    assert (
        evaluate_transfer_candidates(
            (priced,), None, start_state=three_start, transfer_hit_cost_points=5.0
        ).status
        is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    )

    held = TransferStartState(
        season=START.season,
        gameweek=START.gameweek,
        squad_player_ids=tuple(range(1, 16)),
        bank_tenths=25,
        free_transfers=1,
    )
    roll = _candidate("roll", _optimization_result(), ins=(), outs=())
    assert roll.transfer_count == 0 and roll.transfer_hit_points == 0.0
    rolled = evaluate_transfer_candidates(
        (roll,), draw, start_state=held, calibrated_versions=_pin(draw)
    )
    assert rolled.status is TransferSelectionStatus.FALLBACK_SCENARIO_COVERAGE
    assert rolled.diagnostics[0].covered is True and "fewer than two" in rolled.reason


def test_bank_fields_must_be_non_negative_integers() -> None:
    candidate = _candidate("control", _optimization_result())
    for name, value in (
        ("bank_before_tenths", True),
        ("bank_after_tenths", -40),
        ("bank_after_tenths", None),
        ("bank_before_tenths", 2.5),
    ):
        with pytest.raises(ScenarioValidationError, match=name):
            replace(candidate, **{name: value})


def test_a_draw_whose_inputs_disagree_with_its_projections_is_not_calibrated() -> None:
    draw = _full_draw()
    inputs = replace(
        draw.inputs, provenance=replace(draw.inputs.provenance, model_version="other-model")
    )
    foreign = ComponentScenarioDraw(
        scenarios=draw.scenarios,
        inputs=inputs,
        sampled_minutes=draw.sampled_minutes,
        sampled_appearances=draw.sampled_appearances,
        component_fingerprint=_component_fingerprint(
            draw.scenarios, inputs, draw.sampled_minutes, draw.sampled_appearances
        ),
    )
    control = _candidate("control", _optimization_result())
    other = _candidate("captain-14", _with_captain(_optimization_result(), 14))

    selection = evaluate_transfer_candidates(
        (control, other),
        foreign,
        start_state=START,
        calibrated_versions=(("other-model", COMPONENT_SCENARIO_CONTRACT_VERSION),),
    )

    assert selection.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert selection.candidate_count_scored == 0
