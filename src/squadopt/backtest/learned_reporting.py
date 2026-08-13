"""Portable JSON and Markdown views of the paired learned benchmark."""

from dataclasses import asdict

from squadopt.backtest.learned import LearnedBenchmarkResult, PredictionMetrics
from squadopt.backtest.splits import BacktestConfigurationError


def _prediction_record(metrics: PredictionMetrics) -> dict[str, object]:
    return {
        "observations": metrics.observations,
        "mean_absolute_error": metrics.mean_absolute_error,
        "root_mean_squared_error": metrics.root_mean_squared_error,
        "mean_error": metrics.mean_error,
        "by_position": [asdict(item) for item in metrics.by_position],
    }


def learned_benchmark_to_dict(result: LearnedBenchmarkResult) -> dict[str, object]:
    """Serialize the complete paired result without embedding every residual row."""

    if not isinstance(result, LearnedBenchmarkResult):
        raise BacktestConfigurationError("result must be a LearnedBenchmarkResult.")
    ridge = result.config.ridge_config
    cross_season = result.config.cross_season_config
    optimization = result.config.optimization_config
    folds: list[dict[str, object]] = []
    for baseline, learned in zip(result.baseline.folds, result.learned.folds, strict=True):
        folds.append(
            {
                "fold_id": baseline.fold_id,
                "season": learned.metadata["season"],
                "gameweek": learned.metadata["gameweek"],
                "baseline_solver_status": baseline.optimization_result.solver_status.value,
                "learned_solver_status": learned.optimization_result.solver_status.value,
                "baseline_realized_squad_points": baseline.realized_squad_points,
                "learned_realized_squad_points": learned.realized_squad_points,
                "realized_squad_points_difference": (
                    None
                    if baseline.realized_squad_points is None
                    or learned.realized_squad_points is None
                    else learned.realized_squad_points - baseline.realized_squad_points
                ),
                "prediction_fingerprint": learned.metadata.get("prediction_fingerprint"),
                "model_fingerprint": learned.metadata.get("prediction_model_fingerprint"),
                "training_cutoff": learned.metadata.get("prediction_training_cutoff"),
                "training_rows": learned.metadata.get("prediction_training_rows"),
            }
        )
    return {
        "artifact_type": "learned_prediction_benchmark",
        "benchmark_contract_version": result.diagnostics["benchmark_contract_version"],
        "configuration": {
            "evaluation_seasons": list(result.config.seasons),
            "locked_holdout_season": "2025-26",
            "min_prior_gameweeks_in_season": result.config.min_prior_gameweeks_in_season,
            "ridge": {
                "model": "squadopt-ridge-reference",
                "model_version": "ridge-reference-v1",
                "form_window": ridge.form_window,
                "alpha": ridge.alpha,
                "min_training_rows": ridge.min_training_rows,
                "feature_names": list(ridge.feature_names),
                "imputation": "training_median_else_zero",
                "prediction_floor": 0.0,
            },
            "cross_season": {
                "decay": cross_season.decay,
                "min_minutes": cross_season.min_minutes,
            },
            "optimization": {
                "budget_tenths": optimization.budget_tenths,
                "bench_weight": optimization.bench_weight,
                "expected_points_scale": optimization.expected_points_scale,
                "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
                "deterministic_seed": optimization.deterministic_seed,
                "solver_workers": 1,
            },
            "run_metadata": dict(result.config.run_metadata),
        },
        "prediction_metrics": {
            "baseline": _prediction_record(result.baseline_prediction_metrics),
            "learned": _prediction_record(result.learned_prediction_metrics),
        },
        "decision_metrics": asdict(result.decision_metrics),
        "folds": folds,
        "residual_history": {
            "rows": len(result.residuals),
            "columns": list(result.residuals.columns),
            "definition": result.diagnostics["residual_definition"],
        },
        "decision": {
            "automatic_promotion": False,
            "holdout_accessed": False,
            "reason": (
                "This is a development benchmark. Review prediction and decision metrics "
                "before defining a separate promotion gate."
            ),
        },
        "limitations": [
            "The Ridge model is an integration reference, not Ibrahim's production model.",
            "Opening gameweeks and the locked 2025-26 holdout are not evaluated.",
            "Fixture, availability, transfer, chip, and multi-gameweek effects are excluded.",
            "Residual scenarios and scenario-aware optimization are outside Sprint 6.",
        ],
    }


def learned_benchmark_to_markdown(result: LearnedBenchmarkResult) -> str:
    """Render the paired development evidence in a concise reviewable form."""

    report = learned_benchmark_to_dict(result)
    prediction = report["prediction_metrics"]
    decision = report["decision_metrics"]
    configuration = report["configuration"]
    assert isinstance(prediction, dict)
    assert isinstance(decision, dict)
    assert isinstance(configuration, dict)
    baseline = prediction["baseline"]
    learned = prediction["learned"]
    assert isinstance(baseline, dict)
    assert isinstance(learned, dict)
    lines = [
        "# Learned prediction benchmark",
        "",
        "Development-only paired comparison; the locked holdout was not accessed.",
        "",
        "## Configuration",
        "",
        f"- Evaluation seasons: `{', '.join(configuration['evaluation_seasons'])}`",
        "- Model: `squadopt-ridge-reference@ridge-reference-v1`",
        f"- Form window: `{result.config.ridge_config.form_window}`",
        f"- Ridge alpha: `{result.config.ridge_config.alpha}`",
        "- Missing values: training median, or zero if a training column is entirely missing",
        "- Negative point predictions: floored at zero",
        "",
        "## Player-gameweek prediction metrics",
        "",
        "| Model | Observations | MAE | RMSE | Mean error |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| Baseline | {baseline['observations']} | "
            f"{float(baseline['mean_absolute_error']):.6f} | "
            f"{float(baseline['root_mean_squared_error']):.6f} | "
            f"{float(baseline['mean_error']):.6f} |"
        ),
        (
            f"| Ridge | {learned['observations']} | "
            f"{float(learned['mean_absolute_error']):.6f} | "
            f"{float(learned['root_mean_squared_error']):.6f} | "
            f"{float(learned['mean_error']):.6f} |"
        ),
        "",
        "## Optimized-decision comparison",
        "",
        f"- Comparable scored folds: `{decision['comparable_scored_folds']}`",
        f"- Baseline mean realized points: `{decision['baseline_mean_realized_points']}`",
        f"- Ridge mean realized points: `{decision['learned_mean_realized_points']}`",
        f"- Mean paired difference: `{decision['mean_realized_points_difference']}`",
        (
            "- Ridge win/tie/loss folds: "
            f"`{decision['learned_wins']}/{decision['ties']}/{decision['learned_losses']}`"
        ),
        f"- Squad changed folds: `{decision['squad_changed_folds']}`",
        f"- Starting XI changed folds: `{decision['starting_xi_changed_folds']}`",
        f"- Captain changed folds: `{decision['captain_changed_folds']}`",
        "",
        "## Decision",
        "",
        "No automatic promotion. This reference must be reviewed and can later be replaced "
        "through the same prediction contract by Ibrahim's model.",
        "",
        "## Limitations",
        "",
    ]
    limitations = report["limitations"]
    assert isinstance(limitations, list)
    lines.extend(f"- {item}" for item in limitations)
    return "\n".join(lines) + "\n"
