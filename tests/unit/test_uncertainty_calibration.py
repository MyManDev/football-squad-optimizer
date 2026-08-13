"""Synthetic acceptance tests for leakage-safe conformal uncertainty calibration."""

import dataclasses
from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    ProjectionUncertaintyCalibration,
    UncertaintyConfig,
    UncertaintyValidationError,
    apply_projection_uncertainty,
    evaluate_projection_uncertainty,
    fit_projection_uncertainty,
)


def _fold(
    season: str,
    gameweek: int,
    rows: list[tuple[object, str, float, float]],
) -> EvaluationFold:
    """Build one fold from (player_id, position, expected, realized)."""

    projections = pd.DataFrame(
        {
            "player_id": [row[0] for row in rows],
            "name": [f"P{row[0]}" for row in rows],
            "team_id": list(range(1, len(rows) + 1)),
            "position": [row[1] for row in rows],
            "price_tenths": [50] * len(rows),
            "expected_points": [row[2] for row in rows],
        }
    )
    realized = pd.DataFrame(
        {
            "player_id": [row[0] for row in rows],
            "total_points": [row[3] for row in rows],
        }
    )
    return EvaluationFold(
        fold_id=f"{season}-gw{gameweek:02d}",
        projections=projections,
        realized_points=realized,
        metadata={"season": season, "gameweek": gameweek},
    )


CONFIG = UncertaintyConfig(
    confidence_level=0.6,
    development_seasons=("d1",),
    holdout_season="h1",
    min_pooled_observations=2,
    min_group_observations=3,
)
DEVELOPMENT = (
    _fold(
        "d1",
        2,
        [
            (1, "GK", 2.0, 2.0),  # residual  0
            (2, "DEF", 2.0, 3.0),  # residual  1
            (3, "MID", 2.0, 0.0),  # residual -2
            (4, "FWD", 2.0, 5.0),  # residual  3
        ],
    ),
)
HOLDOUT = (
    _fold(
        "h1",
        2,
        [
            (11, "MID", 1.0, 2.0),  # covered residual 1
            (12, "FWD", 1.0, 4.0),  # uncovered residual 3
        ],
    ),
)


def test_hand_computed_finite_sample_quantile_and_pooled_fallback() -> None:
    """n=4, confidence=.6 gives ceil((4+1)*.6)=3: abs residual radius 2."""

    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)

    assert calibration.pooled_observations == 4
    for position, group in calibration.groups.items():
        assert group.position == position
        assert group.source == "pooled_fallback"
        assert group.group_observations == 1
        assert group.calibration_observations == 4
        assert group.conformal_rank == 3
        assert group.interval_radius == 2.0
        assert group.residual_mean == 0.5
        assert group.residual_stddev == pytest.approx(3.25**0.5)


def test_position_group_is_used_when_it_has_enough_observations() -> None:
    development = (
        _fold(
            "d1",
            2,
            [
                (1, "MID", 2.0, 3.0),
                (2, "MID", 3.0, 4.0),
                (3, "FWD", 1.0, 4.0),
            ],
        ),
    )
    config = replace(CONFIG, confidence_level=0.5, min_group_observations=2)

    calibration = fit_projection_uncertainty(development, config)

    assert calibration.groups["MID"].source == "position"
    assert calibration.groups["MID"].calibration_observations == 2
    assert calibration.groups["MID"].interval_radius == 1.0
    assert calibration.groups["FWD"].source == "pooled_fallback"


def test_application_preserves_point_projection_and_extra_columns() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    projections = HOLDOUT[0].projections.copy(deep=True)
    projections.index = [20, 21]
    before = projections.copy(deep=True)

    result = apply_projection_uncertainty(projections, calibration)

    assert_frame_equal(projections, before)
    assert result.table.index.tolist() == [20, 21]
    assert result.table["expected_points"].tolist() == projections["expected_points"].tolist()
    assert result.table["name"].tolist() == projections["name"].tolist()
    assert result.table[INTERVAL_LOWER_COLUMN].tolist() == [-1.0, -1.0]
    assert result.table[INTERVAL_UPPER_COLUMN].tolist() == [3.0, 3.0]
    assert result.table[UNCERTAINTY_GROUP_COLUMN].tolist() == ["MID", "FWD"]
    assert result.table[UNCERTAINTY_SOURCE_COLUMN].tolist() == [
        "pooled_fallback",
        "pooled_fallback",
    ]
    assert result.table[UNCERTAINTY_OBSERVATIONS_COLUMN].tolist() == [4, 4]
    assert result.table[UNCERTAINTY_STDDEV_COLUMN].tolist() == pytest.approx([3.25**0.5, 3.25**0.5])


def test_holdout_metrics_match_hand_computation() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)

    result = evaluate_projection_uncertainty(HOLDOUT, calibration)

    assert result.metrics.observations == 2
    assert result.metrics.empirical_coverage == 0.5
    assert result.metrics.mean_interval_width == 4.0
    assert result.metrics.mean_absolute_error == 2.0
    assert result.metrics.root_mean_squared_error == pytest.approx(5**0.5)
    assert result.metrics.mean_error == 2.0
    assert result.folds[0].scored_players["interval_covered"].tolist() == [True, False]
    assert set(result.group_metrics) == {"MID", "FWD"}
    assert result.diagnostics["holdout_refit"] is False


def test_negative_realized_outcomes_and_negative_lower_bounds_are_allowed() -> None:
    holdout = (_fold("h1", 2, [(11, "MID", 0.5, -1.0)]),)
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)

    result = evaluate_projection_uncertainty(holdout, calibration)

    assert result.folds[0].scored_players.loc[0, INTERVAL_LOWER_COLUMN] == -1.5
    assert result.folds[0].scored_players.loc[0, "total_points"] == -1.0


def test_holdout_outcome_mutation_cannot_change_the_frozen_intervals() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    mutated = (_fold("h1", 2, [(11, "MID", 1.0, 200.0), (12, "FWD", 1.0, -50.0)]),)

    baseline = evaluate_projection_uncertainty(HOLDOUT, calibration)
    rebuilt = evaluate_projection_uncertainty(mutated, calibration)
    interval_columns = [
        "player_id",
        "expected_points",
        INTERVAL_LOWER_COLUMN,
        INTERVAL_UPPER_COLUMN,
    ]

    assert calibration.calibration_fingerprint == rebuilt.calibration.calibration_fingerprint
    assert_frame_equal(
        baseline.folds[0].scored_players.loc[:, interval_columns],
        rebuilt.folds[0].scored_players.loc[:, interval_columns],
    )
    assert baseline.metrics != rebuilt.metrics


def test_fitting_is_deterministic_and_does_not_mutate_fold_frames() -> None:
    projections_before = DEVELOPMENT[0].projections.copy(deep=True)
    realized_before = DEVELOPMENT[0].realized_points.copy(deep=True)

    first = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    second = fit_projection_uncertainty(DEVELOPMENT, CONFIG)

    assert first.calibration_fingerprint == second.calibration_fingerprint
    assert first.groups == second.groups
    assert_frame_equal(DEVELOPMENT[0].projections, projections_before)
    assert_frame_equal(DEVELOPMENT[0].realized_points, realized_before)


def test_result_tables_are_independent_copies() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    result = apply_projection_uncertainty(HOLDOUT[0].projections, calibration)
    original_expected = HOLDOUT[0].projections["expected_points"].tolist()

    result.table.loc[:, "expected_points"] = 999.0

    assert HOLDOUT[0].projections["expected_points"].tolist() == original_expected
    assert calibration.groups["MID"].interval_radius == 2.0

    with pytest.raises(dataclasses.FrozenInstanceError):
        calibration.pooled_observations = 0  # type: ignore[misc]


def test_holdout_fold_is_refused_by_the_fit_path() -> None:
    with pytest.raises(UncertaintyValidationError, match="cannot be used to fit"):
        fit_projection_uncertainty(HOLDOUT, CONFIG)


def test_development_fold_is_refused_by_the_holdout_path() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)

    with pytest.raises(UncertaintyValidationError, match="outside the configured holdout"):
        evaluate_projection_uncertainty(DEVELOPMENT, calibration)


def test_opening_gameweeks_are_refused() -> None:
    opening = (_fold("d1", 1, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)]),)

    with pytest.raises(UncertaintyValidationError, match="Opening gameweeks"):
        fit_projection_uncertainty(opening, CONFIG)


def test_exact_player_alignment_is_required() -> None:
    broken = _fold("d1", 2, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)])
    realized = broken.realized_points.iloc[[0]].copy(deep=True)
    broken = replace(broken, realized_points=realized)

    with pytest.raises(UncertaintyValidationError, match="exact player_id alignment"):
        fit_projection_uncertainty((broken,), CONFIG)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("position", "WING", "invalid positions"),
        ("expected_points", float("nan"), "missing values"),
        ("expected_points", float("inf"), "finite and non-negative"),
        ("expected_points", -1.0, "finite and non-negative"),
    ],
)
def test_invalid_projection_values_are_domain_errors(
    column: str,
    value: object,
    message: str,
) -> None:
    fold = _fold("d1", 2, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)])
    projections = fold.projections.copy(deep=True)
    projections.loc[0, column] = value
    fold = replace(fold, projections=projections)

    with pytest.raises(UncertaintyValidationError, match=message):
        fit_projection_uncertainty((fold,), CONFIG)


def test_duplicate_and_inconsistent_identifiers_are_rejected() -> None:
    duplicate = _fold("d1", 2, [(1, "MID", 2.0, 3.0), (1, "FWD", 2.0, 1.0)])
    with pytest.raises(UncertaintyValidationError, match="duplicate player_id"):
        fit_projection_uncertainty((duplicate,), CONFIG)

    mixed = _fold("d1", 2, [(1, "MID", 2.0, 3.0), ("2", "FWD", 2.0, 1.0)])
    with pytest.raises(UncertaintyValidationError, match="consistent ID type"):
        fit_projection_uncertainty((mixed,), CONFIG)


def test_identifier_type_must_remain_consistent_across_folds() -> None:
    integer_fold = _fold("d1", 2, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)])
    string_fold = _fold("d1", 3, [("1", "MID", 2.0, 3.0), ("2", "FWD", 2.0, 1.0)])

    with pytest.raises(UncertaintyValidationError, match="across development folds"):
        fit_projection_uncertainty((integer_fold, string_fold), CONFIG)


def test_identifier_type_must_remain_consistent_across_holdout_folds() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    integer_fold = _fold("h1", 2, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)])
    string_fold = _fold("h1", 3, [("1", "MID", 2.0, 3.0), ("2", "FWD", 2.0, 1.0)])

    with pytest.raises(UncertaintyValidationError, match="across holdout folds"):
        evaluate_projection_uncertainty((integer_fold, string_fold), calibration)


def test_malformed_public_calibration_is_a_domain_error() -> None:
    fitted = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    malformed = ProjectionUncertaintyCalibration(
        config=fitted.config,
        pooled_observations=fitted.pooled_observations,
        groups={},
        calibration_fingerprint=fitted.calibration_fingerprint,
        diagnostics=fitted.diagnostics,
    )

    with pytest.raises(UncertaintyValidationError, match="every canonical position"):
        apply_projection_uncertainty(HOLDOUT[0].projections, malformed)


def test_tampered_calibration_fingerprint_is_a_domain_error() -> None:
    fitted = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    tampered = replace(fitted, calibration_fingerprint="0" * 64)

    with pytest.raises(UncertaintyValidationError, match="fingerprint"):
        apply_projection_uncertainty(HOLDOUT[0].projections, tampered)


def test_non_finite_realized_points_are_rejected() -> None:
    fold = _fold("d1", 2, [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)])
    realized = fold.realized_points.copy(deep=True)
    realized.loc[0, "total_points"] = float("inf")
    fold = replace(fold, realized_points=realized)

    with pytest.raises(UncertaintyValidationError, match="total_points values must be finite"):
        fit_projection_uncertainty((fold,), CONFIG)


def test_overflowing_input_and_derived_residual_are_domain_errors() -> None:
    overflowing_input = _fold(
        "d1",
        2,
        [(1, "MID", 2.0, 3.0), (2, "FWD", 2.0, 1.0)],
    )
    projections = overflowing_input.projections.copy(deep=True)
    projections["expected_points"] = pd.Series([10**1000, 2], dtype="object")
    overflowing_input = replace(overflowing_input, projections=projections)
    with pytest.raises(UncertaintyValidationError, match="finite and non-negative"):
        fit_projection_uncertainty((overflowing_input,), CONFIG)

    overflowing_residual = _fold(
        "d1",
        2,
        [(1, "MID", 1e308, -1e308), (2, "FWD", 2.0, 1.0)],
    )
    with pytest.raises(UncertaintyValidationError, match="derived residuals must be finite"):
        fit_projection_uncertainty((overflowing_residual,), CONFIG)


def test_non_finite_derived_interval_is_a_domain_error() -> None:
    extreme_development = (
        _fold(
            "d1",
            2,
            [
                (1, "GK", 0.0, 1e308),
                (2, "DEF", 1e308, 0.0),
                (3, "MID", 0.0, 1e308),
                (4, "FWD", 1e308, 0.0),
            ],
        ),
    )
    calibration = fit_projection_uncertainty(extreme_development, CONFIG)
    projections = _fold("h1", 2, [(11, "MID", 1e308, 0.0)]).projections

    with pytest.raises(UncertaintyValidationError, match="non-finite prediction interval"):
        apply_projection_uncertainty(projections, calibration)


def test_overflowing_derived_metric_is_a_domain_error() -> None:
    calibration = fit_projection_uncertainty(DEVELOPMENT, CONFIG)
    holdout = (_fold("h1", 2, [(11, "MID", 1.0, 1e200)]),)

    with pytest.raises(UncertaintyValidationError, match="metrics cannot be represented"):
        evaluate_projection_uncertainty(holdout, calibration)


def test_duplicate_columns_are_rejected() -> None:
    fold = DEVELOPMENT[0]
    projections = fold.projections.copy(deep=True)
    projections.insert(2, "position_copy", projections["position"])
    projections.columns = [
        "position" if column == "position_copy" else column for column in projections.columns
    ]
    fold = replace(fold, projections=projections)

    with pytest.raises(UncertaintyValidationError, match="duplicate columns"):
        fit_projection_uncertainty((fold,), CONFIG)


def test_missing_contract_columns_are_reported() -> None:
    fold = DEVELOPMENT[0]
    broken = replace(fold, projections=fold.projections.drop(columns=["position"]))

    with pytest.raises(UncertaintyValidationError, match="missing columns"):
        fit_projection_uncertainty((broken,), CONFIG)
