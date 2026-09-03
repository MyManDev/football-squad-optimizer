"""Compact internal reporting for descriptive Phase C ablations."""

from collections.abc import Mapping

from squadopt.evaluation import BinaryMetrics, ComponentMetricSet, ErrorMetrics
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.phase_c_ablation import (
    PhaseCAblationEvaluation,
    PhaseCArmEvaluation,
)


def _binary(metrics: BinaryMetrics) -> dict[str, object]:
    return {
        "observations": metrics.observations,
        "brier_score": metrics.brier_score,
        "log_loss": metrics.log_loss,
        "mean_prediction": metrics.mean_prediction,
        "event_rate": metrics.event_rate,
        "mean_calibration_bias": metrics.mean_calibration_bias,
        "reliability_bins": [
            {
                "index": item.index,
                "lower_bound": item.lower_bound,
                "upper_bound": item.upper_bound,
                "observations": item.observations,
                "mean_probability": item.mean_probability,
                "event_rate": item.appearance_rate,
            }
            for item in metrics.reliability_bins
        ],
    }


def _errors(metrics: ErrorMetrics) -> dict[str, object]:
    return {
        "observations": metrics.observations,
        "mean_absolute_error": metrics.mean_absolute_error,
        "root_mean_squared_error": metrics.root_mean_squared_error,
        "mean_error": metrics.mean_error,
    }


def _metric_set(metrics: ComponentMetricSet) -> dict[str, object]:
    return {
        "population_rows": metrics.population_rows,
        "blank_rows": metrics.blank_rows,
        "missing_appearance_target_rows": metrics.missing_appearance_target_rows,
        "missing_appearance_prediction_rows": metrics.missing_appearance_prediction_rows,
        "missing_start_label_rows": metrics.missing_start_label_rows,
        "missing_start_prediction_rows": metrics.missing_start_prediction_rows,
        "missing_minutes_target_rows": metrics.missing_minutes_target_rows,
        "missing_minutes_prediction_rows": metrics.missing_minutes_prediction_rows,
        "missing_points_target_rows": metrics.missing_points_target_rows,
        "missing_points_prediction_rows": metrics.missing_points_prediction_rows,
        "appearance": _binary(metrics.appearance),
        "start": _binary(metrics.start),
        "start_given_appearance": _binary(metrics.start_given_appearance),
        "minutes": _errors(metrics.minutes),
        "minutes_if_appearance": _errors(metrics.minutes_if_appearance),
        "points": _errors(metrics.points),
        "points_if_appearance": _errors(metrics.points_if_appearance),
    }


def _slices(values: Mapping[str, ComponentMetricSet]) -> dict[str, object]:
    return {name: _metric_set(item) for name, item in values.items()}


def _arm(item: PhaseCArmEvaluation) -> dict[str, object]:
    declaration = item.declaration
    metrics = item.metrics
    return {
        "declaration": {
            "arm_id": declaration.arm_id,
            "evidence_family": declaration.evidence_family,
            "model_version": declaration.model_version,
            "feature_contract_version": declaration.feature_contract_version,
            "target_contract_version": declaration.target_contract_version,
            "evaluation_rows_sha256": declaration.evaluation_rows_sha256,
        },
        "metrics": {
            "contract_version": metrics.contract_version,
            "overall": _metric_set(metrics.overall),
            "by_season": _slices(metrics.by_season),
            "by_position": _slices(metrics.by_position),
            "by_fixture_group": _slices(metrics.by_fixture_group),
        },
    }


def phase_c_ablation_to_dict(result: PhaseCAblationEvaluation) -> dict[str, object]:
    """Serialize diagnostics while explicitly withholding any promotion decision."""

    if not isinstance(result, PhaseCAblationEvaluation):
        raise ExperimentExecutionError("result must be a PhaseCAblationEvaluation.")
    return {
        "artifact_type": "phase_c_component_ablation",
        "contract_version": result.contract_version,
        "comparison_fingerprint": result.comparison_fingerprint,
        "paired_rows": result.paired_rows,
        "promotion_decision": "not_evaluated",
        "base": _arm(result.base),
        "candidates": [_arm(item) for item in result.candidates],
    }


__all__ = ["phase_c_ablation_to_dict"]
