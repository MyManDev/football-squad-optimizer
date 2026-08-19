"""JSON-compatible and Markdown views of scenario generation and evaluation."""

from collections.abc import Mapping
from dataclasses import asdict

from squadopt.scenarios.models import (
    ScenarioEvaluationResult,
    ScenarioSet,
    ScenarioValidationError,
)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def scenario_result_to_dict(
    scenarios: ScenarioSet,
    evaluation: ScenarioEvaluationResult,
) -> dict[str, object]:
    """Serialize scenario provenance and fixed-decision risk metrics."""

    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    if not isinstance(evaluation, ScenarioEvaluationResult):
        raise ScenarioValidationError("evaluation must be a ScenarioEvaluationResult.")
    verified = scenarios.validated_copy()
    if evaluation.scenario_fingerprint != verified.scenario_fingerprint:
        raise ScenarioValidationError("evaluation and scenarios must have the same fingerprint.")
    return {
        "artifact_type": "fixed_decision_scenario_evaluation",
        "scenario_contract_version": verified.contract_version,
        "evaluation_contract_version": evaluation.contract_version,
        "scenario_fingerprint": verified.scenario_fingerprint,
        "prediction": {
            "prediction_fingerprint": verified.projections.prediction_fingerprint,
            "model_name": verified.projections.provenance.model_name,
            "model_version": verified.projections.provenance.model_version,
            "training_cutoff": verified.projections.provenance.training_cutoff,
            "training_data_fingerprint": (
                verified.projections.provenance.training_data_fingerprint
            ),
        },
        "target": {
            "fold_id": verified.target.fold_id,
            "season": verified.target.season,
            "gameweek": verified.target.gameweek,
        },
        "configuration": {
            "scenario_count": verified.config.scenario_count,
            "deterministic_seed": verified.config.deterministic_seed,
            "min_history_folds": verified.config.min_history_folds,
            "min_player_observations": verified.config.min_player_observations,
            "player_scale_shrinkage": verified.config.player_scale_shrinkage,
        },
        "history": {
            "rows": verified.diagnostics["history_rows"],
            "folds": verified.diagnostics["history_folds"],
            "first_fold": verified.diagnostics["history_first_fold"],
            "last_fold": verified.diagnostics["history_last_fold"],
            "sampled_source_fold_counts": {
                fold_id: verified.source_fold_ids.count(fold_id)
                for fold_id in sorted(set(verified.source_fold_ids))
            },
        },
        "generation_diagnostics": _json_value(verified.diagnostics),
        "fixed_decision_metrics": asdict(evaluation.metrics),
        "evaluation_diagnostics": _json_value(evaluation.diagnostics),
        "limitations": [
            "The empirical residual process is not a claim of future stationarity.",
            "The evaluated squad decision is fixed and is not reoptimized by scenario.",
            "No CVaR or other scenario-aware optimizer objective is implemented.",
            "Fixture, availability, transfers, chips, and multi-gameweek state are excluded.",
        ],
    }


def scenario_result_to_markdown(
    scenarios: ScenarioSet,
    evaluation: ScenarioEvaluationResult,
) -> str:
    """Render the scenario risk evidence for review."""

    report = scenario_result_to_dict(scenarios, evaluation)
    target = report["target"]
    history = report["history"]
    metrics = report["fixed_decision_metrics"]
    assert isinstance(target, dict)
    assert isinstance(history, dict)
    assert isinstance(metrics, dict)
    lines = [
        "# Monte Carlo scenario evaluation",
        "",
        f"Scenario fingerprint: `{report['scenario_fingerprint']}`",
        f"Target: `{target['fold_id']}`",
        "The squad, starting XI, and captain are fixed; no scenario reoptimization occurs.",
        "",
        "## Historical residual input",
        "",
        f"- Rows: `{history['rows']}`",
        f"- Folds: `{history['folds']}`",
        f"- Range: `{history['first_fold']}` through `{history['last_fold']}`",
        "",
        "## Fixed-decision distribution",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Scenarios | {metrics['scenario_count']} |",
        f"| Point-projection score | {metrics['point_projection_score']} |",
        f"| Mean score | {metrics['mean_score']} |",
        f"| Population standard deviation | {metrics['score_standard_deviation']} |",
        (
            f"| Lower {float(metrics['lower_quantile_probability']) * 100:g}% quantile | "
            f"{metrics['lower_quantile_score']} |"
        ),
        (
            f"| Mean worst {float(metrics['worst_fraction']) * 100:g}% | "
            f"{metrics['mean_worst_fraction_score']} |"
        ),
        f"| Minimum | {metrics['minimum_score']} |",
        (
            f"| P(score < {metrics['points_threshold']}) | "
            f"{metrics['probability_below_threshold']} |"
        ),
        "",
        "## Limitations",
        "",
    ]
    limitations = report["limitations"]
    assert isinstance(limitations, list)
    lines.extend(f"- {item}" for item in limitations)
    return "\n".join(lines) + "\n"
