"""The member advice control can be inspected internally without promoting a transfer."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from tests.unit.test_component_decision_scoring import TARGET, _optimization_result
from tests.unit.test_phase_e_selection import _full_draw

from squadopt.application import advice, phase_e
from squadopt.application.entries import EntryPicks
from squadopt.evaluation import DEVELOPMENT_OOF_CONTRACT_VERSION
from squadopt.live.transfers import HeldSquad
from squadopt.optimization import SolverStatus
from squadopt.planning import PlanningWeekResult, TransferPlanningConfig, TransferPlanResult
from squadopt.scenarios.components import _component_fingerprint
from squadopt.scenarios.models import ScenarioValidationError
from squadopt.scenarios.transfer_decisions import TransferSelectionStatus, selection_record

HELD = (*range(1, 14), 16, 17)


def _held() -> HeldSquad:
    return HeldSquad(
        season=TARGET.season,
        decided_gameweek=TARGET.gameweek - 1,
        squad_player_ids=HELD,
        purchase_prices={player_id: 50 for player_id in HELD},
        bank_tenths=25,
        free_transfers=1,
        chips_used={},
    )


def _plan(*, hit: float = 4.0, chip: str | None = None) -> TransferPlanResult:
    decision = _optimization_result()
    paid = 0 if chip == "wildcard" else 1
    week = PlanningWeekResult(
        gameweek=TARGET.gameweek,
        selected_squad=decision.selected_squad,
        starting_xi=decision.starting_xi,
        bench=decision.bench,
        captain=decision.captain,
        transfers_in=pd.DataFrame({"player_id": [14, 15]}),
        transfers_out=pd.DataFrame({"player_id": [16, 17]}),
        bank_before_tenths=25,
        bank_after_tenths=25,
        free_transfers_before=1,
        free_transfers_unused=0,
        free_transfers_for_next_gameweek=1,
        transfer_count=2,
        paid_transfer_count=paid,
        transfer_hit_points=paid * hit,
        projected_score=40.0,
        projected_bench_points=5.0,
        discounted_objective_contribution=40.0,
        chip=chip,
    )
    return TransferPlanResult(
        solver_status=SolverStatus.OPTIMAL,
        weeks=(week,),
        horizon_fingerprint="a" * 64,
        total_projected_score=40.0,
        total_projected_bench_points=5.0,
        total_transfer_hit_points=paid * hit,
        objective_value=40.0,
        diagnostics={},
    )


def _run(plan, diagnostic):
    phase_e.run_transfer_advice_diagnostic(
        plan,
        _held(),
        gameweek=TARGET.gameweek,
        transfer_hit_cost_points=4.0,
        diagnostic=diagnostic,
    )


def test_empty_production_pin_skips_adaptation_menu_draw_and_evaluation(monkeypatch):
    assert phase_e.PHASE_E_CALIBRATED_VERSIONS == ()
    unexpected = Mock(side_effect=AssertionError("no extra work with an empty pin"))
    monkeypatch.setattr(phase_e, "transfer_candidate_from_plan", unexpected)
    monkeypatch.setattr(phase_e, "evaluate_transfer_candidates", unexpected)

    _run(_plan(), unexpected)

    unexpected.assert_not_called()


def test_no_hook_skips_adaptation_even_with_a_calibration_pin(monkeypatch):
    monkeypatch.setattr(phase_e, "PHASE_E_CALIBRATED_VERSIONS", (("model", "sampler"),))
    unexpected = Mock(side_effect=AssertionError("no diagnostic was requested"))
    monkeypatch.setattr(phase_e, "transfer_candidate_from_plan", unexpected)

    _run(_plan(), None)

    unexpected.assert_not_called()


@pytest.mark.parametrize("hit", [4.0, 6.0])
def test_advice_keeps_control_bytes_and_compute_counts_while_recording_a_better_candidate(
    monkeypatch, hit
):
    """One prepared plan/provider call per request; the diagnostic is an accessible sink."""
    control_plan = _plan(hit=hit)
    challenger = _plan(hit=hit, chip="wildcard")
    draw = _full_draw()
    held = _held()
    picks = EntryPicks(
        entry_id=101,
        season=held.season,
        gameweek=held.decided_gameweek,
        squad=HELD,
        starting_xi=HELD[:11],
        captain=HELD[0],
        vice_captain=HELD[1],
        bank_tenths=held.bank_tenths,
        # Fifteen bought at today's price: no profit, so no sell-on fee to withhold.
        squad_sell_value_tenths=sum(held.purchase_prices.values()),
        free_transfers=held.free_transfers,
        source_snapshot_id="capture-a",
    )
    provider = Mock()
    provider.picks.return_value = picks
    pool = control_plan.weeks[0].selected_squad
    extra = pool.iloc[:2].copy()
    extra["player_id"] = [16, 17]
    pool = pd.concat((pool, extra), ignore_index=True)
    inputs = SimpleNamespace(
        season=TARGET.season,
        snapshot_id="capture-a",
        deadline=SimpleNamespace(gameweek=TARGET.gameweek),
        players=pool,
    )
    projection = SimpleNamespace(table=pool)
    rules = SimpleNamespace(season=TARGET.season, source_snapshot_id="capture-a")
    decision = SimpleNamespace(
        as_record=lambda: {
            "transfers_in": [14, 15],
            "transfers_out": [16, 17],
            "transfer_hit_points": hit,
        }
    )
    # The planner's own cost is a caution margin and must not reach the diagnostic; what
    # the game charges is what a plan's hit points are counted at, so that is the number
    # the candidates are scored on.
    solve = Mock(
        return_value=(
            control_plan,
            decision,
            TransferPlanningConfig(transfer_hit_cost_points=8.0, hit_points_charged=hit),
        )
    )
    monkeypatch.setattr(advice, "plan_transfers", solve)
    records = []
    loader = Mock(return_value=((challenger,), draw))

    def diagnostic(control, start_state, evaluate):
        assert control.gameweek == TARGET.gameweek == start_state.gameweek
        assert (
            start_state.squad_player_ids
            == phase_e.TransferStartState(
                TARGET.season, TARGET.gameweek, HELD, 25, 1
            ).squad_player_ids
        )
        records.append(selection_record(evaluate(*loader())))

    request = advice.AdviseEntryRequest(TARGET.season, TARGET.gameweek, 352490, 101)

    def call(hook=None):
        return advice.advise_entry(
            request,
            provider=provider,
            inputs=inputs,
            projection=projection,
            rules=rules,
            phase_e_diagnostic=hook,
        )

    baseline = call()
    assert call(diagnostic) == baseline
    loader.assert_not_called()
    assert not records
    assert provider.picks.call_count == solve.call_count == 2

    monkeypatch.setattr(
        phase_e,
        "PHASE_E_CALIBRATED_VERSIONS",
        ((draw.inputs.provenance.model_version, draw.inputs.contract_version),),
    )
    observed = call(diagnostic)

    assert json.dumps(observed, sort_keys=True) == json.dumps(baseline, sort_keys=True)
    assert observed["mode"] == "saf-puan" and observed["window"] == 1
    assert observed["transfer_hit_points"] == hit
    assert provider.picks.call_count == solve.call_count == 3
    loader.assert_called_once_with()
    record = records[0]
    assert record["status"] == TransferSelectionStatus.SELECTED
    assert record["selected_rank"] == 1  # Internal winner never replaces member advice.
    assert record["candidates"][0]["transfer_hit_points"] == hit
    assert (
        record["candidates"][1]["mean_net_of_hit"] - record["candidates"][0]["mean_net_of_hit"]
        == hit
    )
    failed_hook = Mock(side_effect=RuntimeError("diagnostic store unavailable"))
    assert call(failed_hook) == baseline
    failed_hook.assert_called_once()


@pytest.mark.parametrize("wrong_plan", ["control", "alternative"])
def test_the_adaptor_rejects_a_plan_for_another_deadline(monkeypatch, wrong_plan):
    monkeypatch.setattr(phase_e, "PHASE_E_CALIBRATED_VERSIONS", (("model", "sampler"),))
    plan = _plan()
    wrong = replace(plan, weeks=(replace(plan.weeks[0], gameweek=TARGET.gameweek + 1),))
    hook = Mock(side_effect=lambda control, start, evaluate: evaluate((wrong,), None))

    with pytest.raises(ScenarioValidationError, match="first week is gameweek"):
        _run(wrong if wrong_plan == "control" else plan, hook)
    if wrong_plan == "control":
        hook.assert_not_called()


def test_development_draw_is_refused_before_the_transfer_evaluator(monkeypatch):
    draw = _full_draw()
    inputs = replace(
        draw.inputs,
        provenance=replace(
            draw.inputs.provenance, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        ),
    )
    development = replace(
        draw,
        inputs=inputs,
        component_fingerprint=_component_fingerprint(
            draw.scenarios, inputs, draw.sampled_minutes, draw.sampled_appearances
        ),
    )
    monkeypatch.setattr(
        phase_e,
        "PHASE_E_CALIBRATED_VERSIONS",
        ((draw.inputs.provenance.model_version, draw.inputs.contract_version),),
    )
    unexpected = Mock(side_effect=AssertionError("development draw must not reach scoring"))
    monkeypatch.setattr(phase_e, "evaluate_transfer_candidates", unexpected)

    with pytest.raises(ScenarioValidationError, match="Development draws"):
        _run(_plan(), lambda control, start, evaluate: evaluate((), development))

    unexpected.assert_not_called()
