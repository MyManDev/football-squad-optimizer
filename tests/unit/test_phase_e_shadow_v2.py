"""Named C v2 scope enables 2025-26 official scoring without changing the v1 boundary."""

from dataclasses import replace

import pandas as pd
import pytest
from tests.unit.test_phase_e_selection import _candidates, _full_draw, _select

from squadopt.evaluation.component_handoff import DEVELOPMENT_OOF_CONTRACT_VERSION
from squadopt.experiments.phase_e_shadow import (
    PHASE_E_SHADOW_CONTRACT,
    PHASE_E_SHADOW_DEVELOPMENT_V2_CONTRACT,
    PhaseEShadowError,
    PhaseEShadowFold,
    evaluate_phase_e_shadow,
    score_phase_e_shadow_fold,
)


@pytest.fixture(scope="module")
def selected():
    candidates = _candidates()
    # Reuse the hand-checked selection fixture; this unit tests realized scoring after it.
    return candidates, _select(candidates, _full_draw())


def _outcomes(extra_control_points: int = 0) -> pd.DataFrame:
    outcomes = pd.DataFrame(
        {"player_id": range(1, 16), "total_points": range(1, 16), "minutes": 90}
    )
    outcomes.loc[outcomes.player_id.eq(14), "total_points"] += extra_control_points
    return outcomes


def test_v2_official_realized_scoring_admits_2025_26_and_preserves_outcomes(selected) -> None:
    candidates, selection = selected
    outcomes = _outcomes()
    before = outcomes.copy(deep=True)
    record = score_phase_e_shadow_fold(
        "2025-26-gw10",
        candidates,
        selection,
        outcomes,
        candidate_set_complete=True,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    assert record.fold_id == "2025-26-gw10"
    assert record.selected_rank == 1 and record.captain_changed
    assert record.difference == -1.0
    assert record.candidates[1].utility_difference == 2.25
    pd.testing.assert_frame_equal(outcomes, before)


def test_v2_aggregate_accepts_the_scored_season_and_keeps_the_fixed_gates(selected) -> None:
    candidates, selection = selected
    records = [
        score_phase_e_shadow_fold(
            f"2025-26-gw{index + 1:02d}",
            candidates,
            selection,
            _outcomes(index),
            candidate_set_complete=True,
            development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        )
        for index in range(4)
    ]
    report = evaluate_phase_e_shadow(
        records,
        expected_fold_ids=[fold.fold_id for fold in records],
        phase_d_status="calibrated_internal",
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    assert report["contract_version"] == PHASE_E_SHADOW_DEVELOPMENT_V2_CONTRACT
    assert report["fold_count"] == 4 and report["error_count"] == 0
    assert report["mean_difference"] == -2.5
    assert report["season_mean_differences"] == {"2025-26": -2.5}
    assert report["gates"]["A"] is False and report["status"] == "harmful"

    # The same scored observations retain identical gates in the original four-season scope.
    old = [replace(fold, fold_id=fold.fold_id.replace("2025-26", "2024-25")) for fold in records]
    original = evaluate_phase_e_shadow(
        old, expected_fold_ids=[fold.fold_id for fold in old], phase_d_status="calibrated_internal"
    )
    assert original["contract_version"] == PHASE_E_SHADOW_CONTRACT
    assert original["gates"] == report["gates"]
    assert original["mean_difference"] == report["mean_difference"]


@pytest.mark.parametrize("contract", [None, "unknown-development-contract"])
def test_scoring_and_aggregate_refuse_2025_26_without_the_named_contract(
    selected, contract
) -> None:
    candidates, selection = selected
    with pytest.raises(PhaseEShadowError):
        score_phase_e_shadow_fold(
            "2025-26-gw01",
            candidates,
            selection,
            _outcomes(),
            candidate_set_complete=True,
            development_contract=contract,
        )
    error = PhaseEShadowFold("2025-26-gw01", "ERROR", False, error="synthetic solver failure")
    with pytest.raises(PhaseEShadowError):
        evaluate_phase_e_shadow(
            [error],
            expected_fold_ids=[error.fold_id],
            phase_d_status="calibrated_internal",
            development_contract=contract,
        )


@pytest.mark.parametrize("fold_id", ["2026-27-gw01", "2025-26-gw39"])
def test_named_v2_scope_remains_limited_to_its_five_seasons_and_valid_gameweeks(
    selected,
    fold_id: str,
) -> None:
    candidates, selection = selected
    with pytest.raises(PhaseEShadowError, match="development-season"):
        score_phase_e_shadow_fold(
            fold_id,
            candidates,
            selection,
            _outcomes(),
            candidate_set_complete=True,
            development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        )


def test_unknown_contract_is_rejected_even_for_a_v1_season() -> None:
    error = PhaseEShadowFold("2024-25-gw01", "ERROR", False, error="synthetic solver failure")
    with pytest.raises(PhaseEShadowError, match="Unsupported"):
        evaluate_phase_e_shadow(
            [error],
            expected_fold_ids=[error.fold_id],
            phase_d_status="calibrated_internal",
            development_contract="unknown-development-contract",
        )
