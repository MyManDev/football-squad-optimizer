"""Compact internal reporting for descriptive Phase C ablations."""

from collections.abc import Mapping

from squadopt.evaluation import (
    BinaryMetrics,
    ComponentMetricSet,
    ErrorMetrics,
    EvaluationResult,
    PhaseCDecisionComparison,
)
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.phase_c_ablation import (
    PhaseCAblationEvaluation,
    PhaseCArmEvaluation,
)

PHASE_C_DECISION_REPORT_VERSION = "phase_c_decision_comparison_v1"


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


def _decision_summary(result: EvaluationResult) -> dict[str, object]:
    summary = result.summary
    return {
        "attempted_folds": summary.attempted_folds,
        "feasible_folds": summary.feasible_folds,
        "scored_folds": summary.scored_folds,
        "mean_realized_squad_points": summary.mean_realized_squad_points,
    }


def phase_c_decision_comparison_to_dict(
    result: PhaseCDecisionComparison,
) -> dict[str, object]:
    """Serialize one descriptive paired decision comparison without promoting an arm."""

    if not isinstance(result, PhaseCDecisionComparison):
        raise ExperimentExecutionError("result must be a PhaseCDecisionComparison.")
    control_folds = result.control.folds
    candidate_folds = result.component_base.folds
    if [item.fold_id for item in control_folds] != [item.fold_id for item in candidate_folds]:
        raise ExperimentExecutionError("Phase C decision result fold orders differ.")
    table_digests = {item.metadata.get("phase_c_table_sha256") for item in candidate_folds}
    roster_digests = {item.metadata.get("phase_c_roster_sha256") for item in candidate_folds}
    if (
        len(table_digests) != 1
        or len(roster_digests) != 1
        or not all(isinstance(value, str) and len(value) == 64 for value in table_digests)
        or not all(isinstance(value, str) and len(value) == 64 for value in roster_digests)
    ):
        raise ExperimentExecutionError("Phase C decision result has inconsistent source digests.")

    paired: list[dict[str, object]] = []
    for control, candidate in zip(control_folds, candidate_folds, strict=True):
        control_score = control.realized_squad_points
        candidate_score = candidate.realized_squad_points
        paired.append(
            {
                "fold_id": control.fold_id,
                "control_solver_status": control.optimization_result.solver_status.value,
                "component_solver_status": candidate.optimization_result.solver_status.value,
                "control_realized_score": control_score,
                "component_realized_score": candidate_score,
                "difference": (
                    None
                    if control_score is None or candidate_score is None
                    else candidate_score - control_score
                ),
            }
        )
    diagnostics = result.diagnostics
    return {
        "artifact_type": "phase_c_decision_comparison",
        "contract_version": PHASE_C_DECISION_REPORT_VERSION,
        "promotion_decision": "not_evaluated",
        "scoring_policy": result.control.config.scoring_policy.value,
        "source": {
            "table_sha256": next(iter(table_digests)),
            "roster_sha256": next(iter(roster_digests)),
        },
        "control": _decision_summary(result.control),
        "component_base": _decision_summary(result.component_base),
        "diagnostics": {
            "attempted_folds": diagnostics.attempted_folds,
            "comparable_folds": diagnostics.comparable_folds,
            "candidate_wins": diagnostics.candidate_wins,
            "ties": diagnostics.ties,
            "candidate_losses": diagnostics.candidate_losses,
            "mean_difference": diagnostics.mean_difference,
            "median_difference": diagnostics.median_difference,
            "season_mean_differences": dict(diagnostics.season_mean_differences),
            "candidate_zero_minute_starters": diagnostics.candidate_zero_minute_starters,
            "control_zero_minute_starters": diagnostics.control_zero_minute_starters,
            "candidate_autosub_points": diagnostics.candidate_autosub_points,
            "control_autosub_points": diagnostics.control_autosub_points,
            "candidate_vice_captain_recoveries": (diagnostics.candidate_vice_captain_recoveries),
            "control_vice_captain_recoveries": diagnostics.control_vice_captain_recoveries,
        },
        "folds": paired,
    }


__all__ = [
    "PHASE_C_DECISION_REPORT_VERSION",
    "phase_c_ablation_to_dict",
    "phase_c_decision_comparison_to_dict",
]
