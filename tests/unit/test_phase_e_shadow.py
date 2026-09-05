"""Paired shadow gates, whole-fold uncertainty and official realized scoring."""

import hashlib
import json
import random
from dataclasses import asdict, replace
from statistics import fmean

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_phase_e_selection import _candidates, _full_draw, _select

from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.phase_e_shadow import (
    PhaseEShadowCandidate,
    PhaseEShadowError,
    PhaseEShadowFold,
    evaluate_phase_e_shadow,
    score_phase_e_shadow_fold,
)
from squadopt.experiments.statistics import (
    _percentile,
    season_aware_moving_block_indices,
    season_aware_moving_block_interval,
)


def _fold(index: int, *, difference: float = 1.0, disagree: bool = True) -> PhaseEShadowFold:
    return PhaseEShadowFold(
        fold_id=f"2023-24-gw{index + 1:02d}",
        status="SELECTED",
        candidate_set_complete=True,
        selected_rank=1 if disagree else 0,
        control_points=50.0,
        selected_points=50.0 + difference if disagree else 50.0,
        squad_changed=disagree,
        candidates=(
            PhaseEShadowCandidate(0, 50.0, 0.0),
            PhaseEShadowCandidate(1, 50.0 + difference, float(index)),
        ),
    )


def _evaluate(folds: list[PhaseEShadowFold], status: str = "calibrated_internal"):
    return evaluate_phase_e_shadow(
        folds, expected_fold_ids=[fold.fold_id for fold in folds], phase_d_status=status
    )


def test_bootstrap_extraction_preserves_the_existing_rng_and_interpolated_interval() -> None:
    differences = [("2022-23", float(i * i)) for i in range(9)] + [
        ("2023-24", float(i - 10)) for i in range(3)
    ]
    policy = PromotionPolicy(bootstrap_resamples=2000)
    candidate_id = "phase_e_vs_phase_c"
    rng = random.Random(int(hashlib.sha256(candidate_id.encode()).hexdigest()[:8], 16))
    # Independent pre-extraction reference, including a season shorter than one block.
    means = []
    for _ in range(2000):
        sample = []
        for values in ([float(i * i) for i in range(9)], [-10.0, -9.0, -8.0]):
            block = min(4, len(values))
            selected = []
            while len(selected) < len(values):
                start = rng.randrange(len(values) - block + 1)
                selected.extend(values[start : start + block])
            sample.extend(selected[: len(values)])
        means.append(fmean(sample))
    assert season_aware_moving_block_interval(
        differences, policy=policy, candidate_id=candidate_id
    ) == (_percentile(means, (1 - 0.9) / 2), _percentile(means, 1 - (1 - 0.9) / 2))
    for indices in season_aware_moving_block_indices(
        [season for season, _ in differences], policy=policy, candidate_id=candidate_id
    ):
        assert len(indices) == 12
        assert all(index < 9 for index in indices[:9])
        assert indices[9:] == (9, 10, 11)


def test_official_realized_scoring_happens_after_selection_and_preserves_inputs() -> None:
    candidates = _candidates()
    selection = _select(candidates, _full_draw())
    outcomes = pd.DataFrame(
        {"player_id": range(1, 16), "total_points": range(1, 16), "minutes": 90}
    )
    before = outcomes.copy(deep=True)
    record = score_phase_e_shadow_fold(
        "2023-24-gw10", candidates, selection, outcomes, candidate_set_complete=True
    )
    assert record.selected_rank == 1
    assert record.difference == -1.0  # Captain 13 replaces captain 14, all players appear.
    assert record.captain_changed and not record.squad_changed and not record.eleven_changed
    assert record.candidates[1].utility_difference == 2.25
    pd.testing.assert_frame_equal(outcomes, before)
    fallback = _select(candidates, _full_draw(), complete=False)
    record = score_phase_e_shadow_fold(
        "2023-24-gw10", candidates, fallback, outcomes, candidate_set_complete=False
    )
    assert record.difference == 0.0 and record.selected_rank == 0
    assert not record.candidate_set_complete and len(record.candidates) == 1


def test_fallback_zeros_stay_in_the_mean_and_in_the_usefulness_denominator() -> None:
    records = [_fold(i, difference=2.0, disagree=i < 4) for i in range(20)]
    for i in range(4, 20):
        records[i] = replace(records[i], status="FALLBACK_PHASE_D_NOT_CALIBRATED")
    result = _evaluate(records)
    assert result["mean_difference"] == 0.4
    assert result["disagreement_mean"] == 2.0
    assert result["disagreement_count"] == 4
    assert result["change_counts"]["bench_only"] == 4
    assert result["gates"] == {"A": True, "R": True, "U": True, "S": False}
    assert result["status"] == "shadow_eligible"


@pytest.mark.parametrize("phase_d", ["failed", "abstained"])
def test_phase_d_failure_has_verdict_precedence(phase_d: str) -> None:
    result = _evaluate([_fold(i, difference=-5) for i in range(5)], phase_d)
    assert result["gates"]["A"] is False
    assert result["status"] == "technical_only"


def test_harm_threshold_is_strict_and_precedes_reliability() -> None:
    records = [replace(_fold(i, difference=-1), candidate_set_complete=False) for i in range(5)]
    result = _evaluate(records)
    assert result["mean_difference_interval"] == (-1.0, -1.0)
    assert result["status"] == "harmful"


def test_reliability_and_usefulness_boundaries_and_inert_verdict() -> None:
    records = [_fold(i, disagree=i < 4) for i in range(20)]
    records[0] = replace(records[0], candidate_set_complete=False)
    assert _evaluate(records)["status"] == "shadow_eligible"  # 95% complete, 20% disagree.
    records[1] = replace(records[1], candidate_set_complete=False)
    assert _evaluate(records)["status"] == "technical_only"
    assert _evaluate([_fold(i, disagree=False) for i in range(5)])["status"] == "inert"


def test_signal_resamples_whole_folds_and_is_descriptive_only() -> None:
    records = [_fold(i, difference=float(i)) for i in range(8)]
    result = _evaluate(records)
    assert result["spearman"] == pytest.approx(1)
    assert result["spearman_interval"] == pytest.approx((1, 1))
    assert result["signal"] is True
    # Reverse every utility difference, leaving realized choices unchanged.
    reversed_signal = [
        replace(
            fold,
            candidates=tuple(
                replace(candidate, utility_difference=-candidate.utility_difference)
                for candidate in fold.candidates
            ),
        )
        for fold in records
    ]
    other = _evaluate(reversed_signal)
    assert other["signal"] is False
    assert other["status"] == result["status"] == "shadow_eligible"
    assert _evaluate(list(reversed(records))) == result


def test_undefined_correlations_and_disagreement_intervals_are_unavailable() -> None:
    result = _evaluate([_fold(i, disagree=False) for i in range(5)])
    assert result["spearman"] is None and result["spearman_interval"] is None
    assert result["disagreement_mean"] is None and result["disagreement_interval"] is None
    assert result["signal"] is False


def test_error_fold_is_retained_without_inventing_a_zero_difference() -> None:
    records = [_fold(i) for i in range(5)]
    records[2] = PhaseEShadowFold(records[2].fold_id, "ERROR", False, error="solver failed")
    result = _evaluate(records)
    assert result["fold_count"] == 5 and result["error_count"] == 1
    assert result["mean_difference"] is None and result["gates"]["A"] is None
    assert result["gates"]["R"] is False and result["status"] == "technical_only"


def test_population_mismatch_or_forged_fallback_is_rejected() -> None:
    records = [_fold(0)]
    with pytest.raises(PhaseEShadowError, match="population"):
        evaluate_phase_e_shadow(
            records,
            expected_fold_ids=[records[0].fold_id, "2023-24-gw02"],
            phase_d_status="calibrated_internal",
        )
    with pytest.raises(PhaseEShadowError, match="fallback"):
        _evaluate([replace(records[0], status="FALLBACK_SCENARIO_COVERAGE")])
    with pytest.raises(PhaseEShadowError, match="development-season"):
        _evaluate([replace(records[0], fold_id="2025-26-gw01")])
    with pytest.raises(PhaseEShadowError, match="binding"):
        _evaluate(records, "passed")


def test_failed_calibration_still_scores_technical_pairs_without_changing_selection() -> None:
    candidates = _candidates()
    draw = _full_draw()
    selection = _select(candidates, draw, pinned=False)
    outcomes = pd.DataFrame(
        {"player_id": range(1, 16), "total_points": range(1, 16), "minutes": 90}
    )
    record = score_phase_e_shadow_fold(
        "2023-24-gw10",
        candidates,
        selection,
        outcomes,
        candidate_set_complete=True,
        draw=draw,
    )
    assert record.status == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    assert record.difference == 0 and record.selected_rank == 0
    assert len(record.candidates) == 2
    assert record.candidates[1].utility_difference == 2.25
    assert record.scenario_fingerprint == draw.scenarios.scenario_fingerprint
    assert record.component_fingerprint == draw.component_fingerprint
    assert _evaluate([record], "failed")["status"] == "technical_only"


def test_error_records_cannot_leak_fabricated_disagreements_into_gates() -> None:
    record = PhaseEShadowFold("2023-24-gw01", "ERROR", False, error="failed", squad_changed=True)
    with pytest.raises(PhaseEShadowError, match="Error folds"):
        _evaluate([record])


def test_bootstrap_signal_keeps_both_candidates_of_each_sampled_fold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from squadopt.experiments import phase_e_shadow as module

    records = [
        replace(
            _fold(i, difference=float(i)),
            candidates=(
                PhaseEShadowCandidate(0, 50.0, 0.0),
                PhaseEShadowCandidate(1, 50.0 + i, float(2 * i)),
                PhaseEShadowCandidate(2, 70.0 + i, float(2 * i + 1)),
            ),
        )
        for i in range(5)
    ]
    original = module.spearmanr
    calls = 0

    def check_pairs(left, right):
        nonlocal calls
        calls += 1
        assert len(left) == len(right) == 10
        for start in range(0, 10, 2):
            assert left[start] % 2 == 0 and left[start + 1] == left[start] + 1
            assert right[start + 1] - right[start] == 20
        return original(left, right)

    monkeypatch.setattr(module, "spearmanr", check_pairs)
    _evaluate(records)
    assert calls == 2001


def test_shadow_artifact_uses_plain_json_scalars_for_numpy_optimizer_identifiers() -> None:
    candidates = []
    for candidate in _candidates():
        captain = candidate.captain.copy()
        captain["player_id"] = np.int64(captain["player_id"])
        candidates.append(replace(candidate, captain=captain))
    draw = _full_draw()
    selection = _select(tuple(candidates), draw)
    outcomes = pd.DataFrame(
        {"player_id": range(1, 16), "total_points": range(1, 16), "minutes": 90}
    )
    record = score_phase_e_shadow_fold(
        "2023-24-gw10", candidates, selection, outcomes, candidate_set_complete=True
    )
    json.dumps(asdict(record), allow_nan=False)
    assert type(record.captain_changed) is bool
    assert all(type(candidate.captain_id) is int for candidate in record.candidates)
