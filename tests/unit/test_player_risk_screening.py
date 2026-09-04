"""Tests for expanding-season player-adaptive risk screening."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationFold
from squadopt.optimization import OptimizationConfig
from squadopt.risk import (
    PLAYER_RISK_SCREENING_CONTRACT_VERSION,
    PlayerRiskScreeningConfig,
    RiskConfigurationError,
    RiskScreeningConfig,
    run_player_risk_screening,
)
from squadopt.uncertainty import PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION

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
            "player_id": [
                "GK_A",
                "GK_B",
                "DEF_A",
                "DEF_B",
                "MID_A",
                "MID_B",
                "FWD_A",
                "FWD_B",
            ],
            "name": ["GK A", "GK B", "DEF A", "DEF B", "MID A", "MID B", "FWD A", "FWD B"],
            "team_id": ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"],
            "position": ["GK", "GK", "DEF", "DEF", "MID", "MID", "FWD", "FWD"],
            "price_tenths": [50] * 8,
            "expected_points": [5.0, 1.0, 4.0, 1.0, 10.0, 1.0, 6.0, 1.0],
        }
    )
    if target:
        realized = [5.0, 0.0, 6.0, 0.0, -5.0, 0.0, 7.0, 0.0]
    elif gameweek % 2 == 0:
        realized = [6.0, 0.0, 5.0, 0.0, 20.0, -9.0, 7.0, 0.0]
    else:
        realized = [4.0, 2.0, 3.0, 2.0, 0.0, 11.0, 5.0, 2.0]
    return EvaluationFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        projections=players,
        realized_points=pd.DataFrame({"player_id": players["player_id"], "total_points": realized}),
        metadata={"season": season, "gameweek": gameweek},
    )


def _folds() -> tuple[EvaluationFold, ...]:
    return (
        _fold("s1", 2, target=False),
        _fold("s1", 3, target=False),
        _fold("s2", 2, target=True),
        _fold("s2", 3, target=True),
        _fold("s3", 2, target=True),
        _fold("s3", 3, target=True),
    )


def _config() -> PlayerRiskScreeningConfig:
    return PlayerRiskScreeningConfig(
        season_order=("s1", "s2", "s3"),
        risk_aversion_levels=(0.0, 1.0),
        downside_quantile=0.5,
        uncertainty_confidence_level=0.5,
        min_pooled_observations=2,
        min_group_observations=2,
        min_player_observations=2,
        shrinkage_observations=1.0,
        minimum_scale=0.1,
        optimization_config=SMALL_CONFIG,
    )


def test_screening_uses_expanding_completed_seasons_and_adaptive_contract() -> None:
    result = run_player_risk_screening(_folds(), _config())
    control, risk_averse = result.candidates

    assert [fold.calibration_seasons for fold in control.folds] == [
        ("s1",),
        ("s1",),
        ("s1", "s2"),
        ("s1", "s2"),
    ]
    assert result.diagnostics["contract_version"] == PLAYER_RISK_SCREENING_CONTRACT_VERSION
    assert (
        result.diagnostics["uncertainty_contract_version"]
        == PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION
    )
    assert result.diagnostics["holdout_accessed"] is False
    assert result.diagnostics["promotion_performed"] is False
    assert result.diagnostics["player_specific_uncertainty"] is True
    assert control.comparison.mean_difference == 0.0
    assert risk_averse.comparison.comparable_folds == 4
    assert all(
        fold.result.diagnostics["uncertainty_contract_version"]
        == PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION
        for fold in risk_averse.folds
    )


def test_target_outcomes_do_not_change_same_season_decisions() -> None:
    folds = _folds()
    changed = folds[2].realized_points.copy(deep=True)
    changed.loc[:, "total_points"] = [100.0, -50.0, 75.0, -25.0, 60.0, -10.0, 90.0, -5.0]
    mutated = (*folds[:2], replace(folds[2], realized_points=changed), *folds[3:])

    baseline = run_player_risk_screening(folds, _config())
    rebuilt = run_player_risk_screening(mutated, _config())

    for baseline_candidate, rebuilt_candidate in zip(
        baseline.candidates,
        rebuilt.candidates,
        strict=True,
    ):
        for baseline_fold, rebuilt_fold in zip(
            baseline_candidate.folds[:2],
            rebuilt_candidate.folds[:2],
            strict=True,
        ):
            assert baseline_fold.result.calibration_fingerprint == (
                rebuilt_fold.result.calibration_fingerprint
            )
            assert (
                baseline_fold.result.optimization_result.starting_xi["player_id"].tolist()
                == rebuilt_fold.result.optimization_result.starting_xi["player_id"].tolist()
            )


def test_screening_is_order_deterministic_and_does_not_mutate_folds() -> None:
    folds = _folds()
    projection_before = folds[0].projections.copy(deep=True)
    realized_before = folds[0].realized_points.copy(deep=True)

    ordered = run_player_risk_screening(folds, _config())
    shuffled = run_player_risk_screening(tuple(reversed(folds)), _config())

    assert ordered.diagnostics["evaluation_fold_ids"] == shuffled.diagnostics["evaluation_fold_ids"]
    for first, second in zip(ordered.candidates, shuffled.candidates, strict=True):
        assert first.metrics == second.metrics
        assert first.comparison == second.comparison
    assert_frame_equal(folds[0].projections, projection_before)
    assert_frame_equal(folds[0].realized_points, realized_before)


def test_player_screening_has_a_separate_fingerprint_from_legacy_screening() -> None:
    adaptive = _config()
    legacy = RiskScreeningConfig(
        season_order=adaptive.season_order,
        risk_aversion_levels=adaptive.risk_aversion_levels,
        downside_quantile=adaptive.downside_quantile,
        uncertainty_confidence_level=adaptive.uncertainty_confidence_level,
        min_pooled_observations=adaptive.min_pooled_observations,
        min_group_observations=adaptive.min_group_observations,
        optimization_config=adaptive.optimization_config,
    )

    assert adaptive.configuration_fingerprint != legacy.configuration_fingerprint


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scale_training_fraction", 0.0),
        ("scale_training_fraction", 1.0),
        ("min_player_observations", 1),
        ("shrinkage_observations", 0.0),
        ("minimum_scale", 0.0),
    ],
)
def test_player_screening_rejects_invalid_adaptive_controls(
    field: str,
    value: object,
) -> None:
    with pytest.raises(RiskConfigurationError):
        replace(_config(), **{field: value})
