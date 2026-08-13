"""Tests for leakage-safe player-adaptive uncertainty calibration."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    PlayerAdaptiveUncertaintyConfig,
    UncertaintyConfigurationError,
    UncertaintyValidationError,
    apply_player_adaptive_uncertainty,
    evaluate_player_adaptive_uncertainty,
    fit_player_adaptive_uncertainty,
)


def _fold(
    season: str,
    gameweek: int,
    rows: list[tuple[object, str, float]],
) -> EvaluationFold:
    projections = pd.DataFrame(
        {
            "player_id": [row[0] for row in rows],
            "name": [f"P{row[0]}" for row in rows],
            "team_id": list(range(1, len(rows) + 1)),
            "position": [row[1] for row in rows],
            "price_tenths": [50] * len(rows),
            "expected_points": [10.0] * len(rows),
        }
    )
    realized = pd.DataFrame(
        {
            "player_id": [row[0] for row in rows],
            "total_points": [10.0 + row[2] for row in rows],
        }
    )
    return EvaluationFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        projections=projections,
        realized_points=realized,
        metadata={"season": season, "gameweek": gameweek},
    )


CONFIG = PlayerAdaptiveUncertaintyConfig(
    confidence_level=0.60,
    development_seasons=("d1", "d2"),
    holdout_season="h1",
    scale_training_fraction=0.50,
    min_pooled_observations=2,
    min_position_observations=2,
    min_player_observations=2,
    shrinkage_observations=1.0,
    minimum_scale=0.10,
)
DEVELOPMENT = (
    _fold("d1", 2, [(1, "MID", 1.0), (2, "MID", 8.0)]),
    _fold("d1", 3, [(1, "MID", -1.0), (2, "MID", -8.0)]),
    _fold("d2", 2, [(1, "MID", 1.0), (2, "MID", 8.0)]),
    _fold("d2", 3, [(1, "MID", -1.0), (2, "MID", -8.0)]),
)
HOLDOUT = (_fold("h1", 2, [(1, "MID", 0.5), (2, "MID", 4.0), (3, "FWD", 2.0)]),)


def test_chronological_scale_and_conformal_subsets_are_disjoint() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)

    assert calibration.scale_training_fold_ids == ("d1-gw02", "d1-gw03")
    assert calibration.conformal_calibration_fold_ids == ("d2-gw02", "d2-gw03")
    assert not (
        set(calibration.scale_training_fold_ids) & set(calibration.conformal_calibration_fold_ids)
    )
    assert calibration.diagnostics["calibration_split"] == "chronological-disjoint-folds"


def test_player_with_volatile_history_receives_a_wider_interval() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)

    result = apply_player_adaptive_uncertainty(HOLDOUT[0].projections, calibration).table
    stable = result.loc[result["player_id"].eq(1)].iloc[0]
    volatile = result.loc[result["player_id"].eq(2)].iloc[0]

    assert volatile[UNCERTAINTY_STDDEV_COLUMN] > stable[UNCERTAINTY_STDDEV_COLUMN]
    assert (
        volatile[INTERVAL_UPPER_COLUMN] - volatile[INTERVAL_LOWER_COLUMN]
        > stable[INTERVAL_UPPER_COLUMN] - stable[INTERVAL_LOWER_COLUMN]
    )
    assert stable[UNCERTAINTY_SOURCE_COLUMN] == "player_shrunk"
    assert volatile[UNCERTAINTY_SOURCE_COLUMN] == "player_shrunk"
    assert stable[PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN] == 2


def test_unseen_player_uses_deterministic_position_or_pooled_fallback() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    target = pd.concat(
        [
            HOLDOUT[0].projections,
            pd.DataFrame(
                {
                    "player_id": [4],
                    "name": ["P4"],
                    "team_id": [4],
                    "position": ["MID"],
                    "price_tenths": [50],
                    "expected_points": [10.0],
                }
            ),
        ],
        ignore_index=True,
    )

    result = apply_player_adaptive_uncertainty(target, calibration).table.set_index("player_id")

    assert result.loc[4, UNCERTAINTY_SOURCE_COLUMN] == "position_fallback"
    assert result.loc[3, UNCERTAINTY_SOURCE_COLUMN] == "pooled_fallback"
    assert result.loc[4, PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN] == 0
    assert result.loc[3, PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN] == 0
    assert result.loc[4, UNCERTAINTY_OBSERVATIONS_COLUMN] >= 2
    assert result.loc[3, UNCERTAINTY_OBSERVATIONS_COLUMN] >= 2


def test_application_does_not_mutate_inputs_or_point_predictions() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    projections = HOLDOUT[0].projections.copy(deep=True)
    before = projections.copy(deep=True)

    result = apply_player_adaptive_uncertainty(projections, calibration)

    assert_frame_equal(projections, before)
    assert result.table["expected_points"].tolist() == before["expected_points"].tolist()
    assert result.diagnostics["point_projection_changed"] is False


def test_holdout_outcomes_cannot_change_frozen_intervals() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    mutated = (_fold("h1", 2, [(1, "MID", 100.0), (2, "MID", -100.0), (3, "FWD", 50.0)]),)

    first = evaluate_player_adaptive_uncertainty(HOLDOUT, calibration)
    second = evaluate_player_adaptive_uncertainty(mutated, calibration)
    columns = ["player_id", INTERVAL_LOWER_COLUMN, INTERVAL_UPPER_COLUMN]

    assert_frame_equal(
        first.folds[0].scored_players.loc[:, columns],
        second.folds[0].scored_players.loc[:, columns],
    )
    assert first.metrics != second.metrics


def test_disjoint_conformal_outcomes_change_multiplier_but_not_scale_state() -> None:
    changed_fold = _fold("d2", 3, [(1, "MID", -4.0), (2, "MID", -16.0)])
    changed = (*DEVELOPMENT[:3], changed_fold)

    baseline = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    recalibrated = fit_player_adaptive_uncertainty(changed, CONFIG)

    assert baseline.pooled_scale == recalibrated.pooled_scale
    assert baseline.players == recalibrated.players
    assert baseline.groups["MID"].position_scale == recalibrated.groups["MID"].position_scale
    assert baseline.groups["MID"].conformal_multiplier != (
        recalibrated.groups["MID"].conformal_multiplier
    )


def test_calibration_is_order_deterministic_and_tampering_is_rejected() -> None:
    first = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    reordered = tuple(
        replace(
            fold,
            projections=fold.projections.iloc[::-1].reset_index(drop=True),
            realized_points=fold.realized_points.iloc[::-1].reset_index(drop=True),
        )
        for fold in reversed(DEVELOPMENT)
    )
    second = fit_player_adaptive_uncertainty(reordered, CONFIG)

    assert first.calibration_fingerprint == second.calibration_fingerprint
    tampered = replace(first, calibration_fingerprint="f" * 64)
    with pytest.raises(UncertaintyValidationError, match="fingerprint"):
        apply_player_adaptive_uncertainty(HOLDOUT[0].projections, tampered)


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
def test_adaptive_config_rejects_invalid_controls(field: str, value: object) -> None:
    with pytest.raises(UncertaintyConfigurationError):
        replace(CONFIG, **{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence_level", 0.7),
        ("scale_training_fraction", 0.6),
        ("min_pooled_observations", 3),
        ("min_position_observations", 3),
        ("min_player_observations", 3),
        ("shrinkage_observations", 2.0),
        ("minimum_scale", 0.2),
    ],
)
def test_every_adaptive_control_changes_the_config_fingerprint(
    field: str,
    value: object,
) -> None:
    assert replace(CONFIG, **{field: value}).configuration_fingerprint != (
        CONFIG.configuration_fingerprint
    )


def test_at_least_two_chronological_folds_are_required() -> None:
    config = replace(CONFIG, development_seasons=("d1",))

    with pytest.raises(UncertaintyValidationError, match="at least two"):
        fit_player_adaptive_uncertainty(DEVELOPMENT[:1], config)


def test_application_rejects_a_different_player_id_type() -> None:
    calibration = fit_player_adaptive_uncertainty(DEVELOPMENT, CONFIG)
    projections = HOLDOUT[0].projections.copy(deep=True)
    projections["player_id"] = projections["player_id"].astype("string")

    with pytest.raises(UncertaintyValidationError, match="same player_id type"):
        apply_player_adaptive_uncertainty(projections, calibration)
