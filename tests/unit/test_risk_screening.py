"""Tests for expanding-season, development-only risk screening."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationFold
from squadopt.optimization import OptimizationConfig
from squadopt.risk import RiskScreeningConfig, RiskValidationError, run_risk_screening

SMALL_CONFIG = OptimizationConfig(
    budget_tenths=200,
    squad_size=4,
    squad_position_limits={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
    starting_size=3,
    starting_position_min={"GK": 1, "DEF": 0, "MID": 0, "FWD": 1},
    starting_position_max={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
    max_players_per_team=4,
)


def _fold(season: str, gameweek: int, *, target: bool) -> EvaluationFold:
    players = pd.DataFrame(
        {
            "player_id": ["GK_A", "GK_B", "DEF_A", "DEF_B", "MID_A", "MID_B", "FWD_A", "FWD_B"],
            "name": ["GK A", "GK B", "DEF A", "DEF B", "MID A", "MID B", "FWD A", "FWD B"],
            "team_id": ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"],
            "position": ["GK", "GK", "DEF", "DEF", "MID", "MID", "FWD", "FWD"],
            "price_tenths": [50] * 8,
            "expected_points": [5.0, 1.0, 4.0, 1.0, 10.0, 1.0, 6.0, 1.0],
        }
    )
    if target:
        realized = [5.0, 0.0, 6.0, 0.0, -5.0, 0.0, 7.0, 0.0]
    else:
        realized = [6.0, 0.0, 5.0, 0.0, 20.0, -9.0, 7.0, 0.0]
    return EvaluationFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        projections=players,
        realized_points=pd.DataFrame({"player_id": players["player_id"], "total_points": realized}),
        metadata={"season": season, "gameweek": gameweek},
    )


def _folds() -> tuple[EvaluationFold, ...]:
    return (
        _fold("s1", 2, target=False),
        _fold("s2", 2, target=True),
        _fold("s3", 2, target=True),
    )


def _config() -> RiskScreeningConfig:
    return RiskScreeningConfig(
        season_order=("s1", "s2", "s3"),
        risk_aversion_levels=(0.0, 1.0),
        downside_quantile=0.5,
        uncertainty_confidence_level=0.5,
        min_pooled_observations=2,
        min_group_observations=2,
        optimization_config=SMALL_CONFIG,
    )


def test_screening_uses_only_completed_seasons_for_each_calibration() -> None:
    result = run_risk_screening(_folds(), _config())

    control, risk_averse = result.candidates
    assert [fold.calibration_seasons for fold in control.folds] == [
        ("s1",),
        ("s1", "s2"),
    ]
    assert [fold.season for fold in control.folds] == ["s2", "s3"]
    assert result.diagnostics["holdout_accessed"] is False
    assert result.diagnostics["promotion_performed"] is False
    assert control.comparison.mean_difference == 0.0
    assert control.comparison.squad_changed_folds == 0
    assert risk_averse.comparison.comparable_folds == 2
    assert risk_averse.comparison.starting_xi_changed_folds == 2
    assert risk_averse.comparison.captain_changed_folds == 2
    assert risk_averse.metrics.feasibility_rate == 1.0


def test_known_downside_metrics_and_paired_difference_are_reported() -> None:
    result = run_risk_screening(_folds(), _config())
    control, risk_averse = result.candidates

    assert control.metrics.mean_realized_squad_points == 2.0
    assert control.metrics.downside_quantile_score == 2.0
    assert control.metrics.mean_worst_fraction_score == 2.0
    assert risk_averse.metrics.mean_realized_squad_points == 25.0
    assert risk_averse.metrics.minimum_realized_squad_points == 25.0
    assert risk_averse.comparison.mean_difference == 23.0
    assert risk_averse.comparison.mean_worst_fraction_difference == 23.0


def test_target_outcome_mutation_cannot_change_same_season_decisions() -> None:
    baseline_folds = _folds()
    mutated_fold = baseline_folds[1]
    mutated_realized = mutated_fold.realized_points.copy(deep=True)
    mutated_realized.loc[:, "total_points"] = [100.0, -50.0, 75.0, -25.0, 60.0, -10.0, 90.0, -5.0]
    mutated = (
        baseline_folds[0],
        replace(mutated_fold, realized_points=mutated_realized),
        baseline_folds[2],
    )

    baseline = run_risk_screening(baseline_folds, _config())
    rebuilt = run_risk_screening(mutated, _config())

    for baseline_candidate, rebuilt_candidate in zip(
        baseline.candidates,
        rebuilt.candidates,
        strict=True,
    ):
        baseline_s2 = baseline_candidate.folds[0].result
        rebuilt_s2 = rebuilt_candidate.folds[0].result
        assert baseline_s2.calibration_fingerprint == rebuilt_s2.calibration_fingerprint
        assert (
            baseline_s2.optimization_result.selected_squad["player_id"].tolist()
            == rebuilt_s2.optimization_result.selected_squad["player_id"].tolist()
        )
        assert (
            baseline_s2.optimization_result.starting_xi["player_id"].tolist()
            == rebuilt_s2.optimization_result.starting_xi["player_id"].tolist()
        )


def test_screening_is_order_deterministic_and_does_not_mutate_folds() -> None:
    folds = _folds()
    projection_before = folds[0].projections.copy(deep=True)
    realized_before = folds[0].realized_points.copy(deep=True)

    ordered = run_risk_screening(folds, _config())
    shuffled = run_risk_screening(tuple(reversed(folds)), _config())

    assert ordered.diagnostics["evaluation_fold_ids"] == shuffled.diagnostics["evaluation_fold_ids"]
    for first, second in zip(ordered.candidates, shuffled.candidates, strict=True):
        assert first.metrics == second.metrics
        assert first.comparison == second.comparison
    assert_frame_equal(folds[0].projections, projection_before)
    assert_frame_equal(folds[0].realized_points, realized_before)


def test_missing_configured_season_is_rejected() -> None:
    with pytest.raises(RiskValidationError, match="do not cover"):
        run_risk_screening(_folds()[:-1], _config())


def test_target_fold_requires_exact_projection_and_outcome_alignment() -> None:
    folds = _folds()
    broken_target = replace(
        folds[1],
        realized_points=folds[1].realized_points.iloc[:-1].copy(deep=True),
    )

    with pytest.raises(RiskValidationError, match="exact player_id alignment"):
        run_risk_screening((folds[0], broken_target, folds[2]), _config())


def test_invalid_unselected_target_outcome_is_rejected_before_scoring() -> None:
    folds = _folds()
    target = folds[1]
    broken_outcomes = target.realized_points.copy(deep=True)
    broken_outcomes.loc[broken_outcomes["player_id"].eq("GK_B"), "total_points"] = float("nan")
    broken_target = replace(target, realized_points=broken_outcomes)

    with pytest.raises(RiskValidationError, match="realized-point columns contain missing values"):
        run_risk_screening((folds[0], broken_target, folds[2]), _config())
