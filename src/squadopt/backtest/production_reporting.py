"""Serialise a judging run, including the environment that produced it.

The environment is recorded because leaving it out already cost something. The Ridge
reference's recorded figure and a fresh measurement of the same configuration disagree —
56.8912 against 56.9456 in mean realized points — while the deterministic baseline
reproduces to the digit. The baseline is arithmetic; Ridge is a least-squares solve, and
a solve is sensitive to the numerical libraries underneath it in a way arithmetic is not.
The recorded run states Python 3.13.5 and does not state numpy or scikit-learn at all, so
the cause cannot be confirmed from what was written down. This module writes down enough
that the same question has an answer next time.

The deeper consequence is why a judging run compares all three candidates in one pass. If
Ridge's number moves with the environment, then a gate phrased as "match Ridge" has an
environment-dependent threshold, and comparing a fresh candidate against a recorded
reference measures the machines as much as the models.
"""

import platform
from collections.abc import Mapping
from typing import Final

import numpy as np
import pandas as pd
import sklearn  # type: ignore[import-untyped]

from squadopt.backtest.production_benchmark import (
    PRODUCTION_BENCHMARK_CONTRACT_VERSION,
    ProductionBenchmarkResult,
)

ARTIFACT_TYPE: Final = "production_gate_judgement"


def _library_versions() -> Mapping[str, str]:
    """Record every library whose numerics can move a result.

    scikit-learn and numpy are here because their absence from the earlier artifact is
    exactly what made a discrepancy unexplainable.
    """

    try:
        import ortools

        ortools_version = getattr(ortools, "__version__", "unknown")
    except ImportError:  # pragma: no cover - ortools is a hard dependency
        ortools_version = "missing"

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or "unknown",
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
        "ortools": ortools_version,
    }


def judgement_to_dict(result: ProductionBenchmarkResult) -> dict[str, object]:
    """Render a judging run as a serialisable document."""

    return {
        "artifact_type": ARTIFACT_TYPE,
        "benchmark_contract_version": PRODUCTION_BENCHMARK_CONTRACT_VERSION,
        "environment": dict(_library_versions()),
        "metadata": dict(result.metadata),
        "candidate_declaration": {
            "contract_version": result.candidate_declaration.contract_version,
            "candidate_id": result.candidate_declaration.candidate_id,
            "model_name": result.candidate_declaration.model_name,
            "model_version": result.candidate_declaration.model_version,
            "feature_contract_version": (result.candidate_declaration.feature_contract_version),
            "changed_component": result.candidate_declaration.changed_component,
            "change_summary": result.candidate_declaration.change_summary,
            "frozen_components": list(result.candidate_declaration.frozen_components),
            "evaluation_objective": result.candidate_declaration.evaluation_objective,
            "source_reference": result.candidate_declaration.source_reference,
            "declaration_fingerprint": (result.candidate_declaration.declaration_fingerprint),
            "benchmark_configuration_fingerprint": (result.config.configuration_fingerprint),
        },
        "configuration": {
            "seasons": list(result.config.seasons),
            "min_prior_gameweeks_in_season": result.config.min_prior_gameweeks_in_season,
            "rate_window": result.config.production_config.rate_window,
            "appearance_window": result.config.production_config.minutes.window,
            "carry_over_rate_weight": result.config.production_config.carry_over_rate_weight,
            "carry_over_minutes_weight": result.config.production_config.minutes.carry_over_weight,
            "opening_price_coefficient": (
                result.config.production_config.opening_price_coefficient
            ),
            "ridge_form_window": result.config.ridge_config.form_window,
            "ridge_alpha": result.config.ridge_config.alpha,
            "optimization": {
                "solver_time_limit_seconds": (
                    result.config.evaluation_config.optimization_config.solver_time_limit_seconds
                ),
                "solver_deterministic_time_limit": (
                    result.config.evaluation_config.optimization_config.solver_deterministic_time_limit
                ),
                "deterministic_seed": (
                    result.config.evaluation_config.optimization_config.deterministic_seed
                ),
                "solver_workers": 1,
                "stopping_rule": "deterministic_work_with_wall_clock_safety_cap",
            },
            "policy": {
                field: getattr(result.config.policy, field)
                for field in result.config.policy.__dataclass_fields__
            },
        },
        "folds": result.fold_count,
        "feasible_folds": dict(result.feasible_folds),
        "solver_statuses": {
            label: dict(counts) for label, counts in sorted(result.solver_statuses.items())
        },
        "truncated_candidates": list(result.truncated_candidates),
        "route_counts": {
            label: dict(counts) for label, counts in sorted(result.route_counts.items())
        },
        "mean_realized_points": dict(result.mean_realized_points),
        "prediction_metrics": {
            label: {
                "observations": metrics.observations,
                "mean_absolute_error": metrics.mean_absolute_error,
                "root_mean_squared_error": metrics.root_mean_squared_error,
                "mean_error": metrics.mean_error,
                "by_position": [
                    {
                        "position": entry.position,
                        "observations": entry.observations,
                        "mean_absolute_error": entry.mean_absolute_error,
                        "root_mean_squared_error": entry.root_mean_squared_error,
                        "mean_error": entry.mean_error,
                    }
                    for entry in metrics.by_position
                ],
            }
            for label, metrics in sorted(result.prediction_metrics.items())
        },
        "comparisons": [
            {
                "candidate": comparison.candidate,
                "reference": comparison.reference,
                "comparable_folds": comparison.comparable_folds,
                "mean_difference": comparison.mean_difference,
                "median_difference": comparison.median_difference,
                "difference_stdev": comparison.difference_stdev,
                "confidence_interval_lower": comparison.confidence_interval_lower,
                "confidence_interval_upper": comparison.confidence_interval_upper,
                "candidate_wins": comparison.candidate_wins,
                "ties": comparison.ties,
                "candidate_losses": comparison.candidate_losses,
                "season_mean_differences": dict(comparison.season_mean_differences),
            }
            for comparison in result.comparisons
        ],
        "gates": [
            {
                "name": gate.name,
                "requirement": gate.requirement,
                "measured": gate.measured,
                "passed": gate.passed,
            }
            for gate in result.gates
        ],
        "gates_all_passed": result.all_gates_passed,
        "verdict": result.verdict,
        "residual_history": {
            "columns": list(result.residuals.columns),
            "definition": "realized_points_minus_predicted_points",
            "rows": len(result.residuals),
        },
        "limitations": [
            "A development gate verdict is not an operational promotion; clearing these "
            "gates makes a candidate eligible for the locked holdout protocol and nothing "
            "more.",
            "The 2025-26 holdout is not read by this run.",
            "A candidate listed under truncated_candidates had at least one fold the "
            "solver did not prove optimal. This adds search noise of unknown direction to "
            "realized points, because realized points are not the solver objective. The "
            "deterministic work budget makes the selected incumbent reproducible; the "
            "wall-clock limit is only a safety cap.",
            "Ridge is measured in this run rather than read from an earlier artifact, "
            "because its figure moves with the numerical environment while the "
            "deterministic baseline does not.",
            "Per-fold squad scores are not published; the aggregates are the claim and "
            "fold-level scores are a derived product of third-party data.",
        ],
    }


def _gate_rows(document: Mapping[str, object]) -> list[str]:
    gates = document["gates"]
    assert isinstance(gates, list)
    rows = ["| Condition | Required | Measured | Verdict |", "| --- | --- | ---: | --- |"]
    for gate in gates:
        assert isinstance(gate, dict)
        verdict = "pass" if gate["passed"] else "**fail**"
        measured = float(str(gate["measured"]))
        rows.append(f"| `{gate['name']}` | {gate['requirement']} | {measured:+.4f} | {verdict} |")
    return rows


def judgement_to_markdown(result: ProductionBenchmarkResult) -> str:
    """Render a judging run as a report a reader can check without running anything."""

    document = judgement_to_dict(result)
    environment = document["environment"]
    assert isinstance(environment, dict)

    lines = [
        "# Production gate judgement",
        "",
        "A **development gate verdict**, not an operational promotion. Clearing these gates "
        "makes a candidate eligible for the locked holdout protocol; it does not by itself "
        "put anything into production.",
        "",
        f"Verdict: **{document['verdict']}**",
        "",
        "## Frozen candidate declaration",
        "",
        f"- Candidate: `{result.candidate_declaration.candidate_id}`",
        f"- Declared change: `{result.candidate_declaration.changed_component}` — "
        f"{result.candidate_declaration.change_summary}",
        f"- Evaluation objective: `{result.candidate_declaration.evaluation_objective}`",
        f"- Declaration fingerprint: `{result.candidate_declaration.declaration_fingerprint}`",
        f"- Benchmark configuration fingerprint: `{result.config.configuration_fingerprint}`",
        "- Frozen components: "
        + ", ".join(f"`{item}`" for item in result.candidate_declaration.frozen_components),
        "",
        "## Fold set",
        "",
        f"- Seasons: `{', '.join(result.config.seasons)}`",
        f"- Folds: `{result.fold_count}`",
        "- Feasible folds: "
        + ", ".join(f"{label} `{count}`" for label, count in sorted(result.feasible_folds.items())),
        "- The 2025-26 holdout is untouched.",
        "- Solver stopping rule: deterministic work budget "
        f"`{result.config.evaluation_config.optimization_config.solver_deterministic_time_limit}` "
        "with wall-clock safety cap "
        f"`{result.config.evaluation_config.optimization_config.solver_time_limit_seconds}s`.",
        "",
        "## Mean realized squad points",
        "",
        "| Candidate | Mean realized |",
        "| --- | ---: |",
    ]
    for label, value in sorted(result.mean_realized_points.items()):
        lines.append(f"| {label} | {value:.4f} |")

    lines += [
        "",
        "## Paired comparisons",
        "",
        "| Candidate | Reference | Mean | 90% interval | Stdev | W/T/L |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for comparison in result.comparisons:
        lines.append(
            f"| {comparison.candidate} | {comparison.reference} | "
            f"{comparison.mean_difference:+.4f} | "
            f"`[{comparison.confidence_interval_lower:+.4f}, "
            f"{comparison.confidence_interval_upper:+.4f}]` | "
            f"{comparison.difference_stdev:.4f} | "
            f"{comparison.candidate_wins}/{comparison.ties}/{comparison.candidate_losses} |"
        )

    if result.route_counts:
        lines += [
            "",
            "## Projection ladder",
            "",
            "Rows each candidate routed down each rung, summed over folds. A score alone "
            "cannot distinguish a candidate that used its changed stage everywhere from one "
            "that fell through to a fallback on a large share of its rows.",
            "",
        ]
        for label, counts in sorted(result.route_counts.items()):
            if not counts:
                continue
            total = sum(counts.values())
            lines += [f"**{label}**", "", "| Rung | Rows | Share |", "| --- | ---: | ---: |"]
            for rung, value in counts.items():
                share = value / total if total else 0.0
                lines.append(f"| `{rung}` | {value:,} | {share:.1%} |")
            lines.append("")

    lines += [
        "",
        "## Prediction metrics",
        "",
        "| Candidate | Observations | MAE | RMSE | Bias |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for label, metrics in sorted(result.prediction_metrics.items()):
        lines.append(
            f"| {label} | {metrics.observations:,} | {metrics.mean_absolute_error:.4f} | "
            f"{metrics.root_mean_squared_error:.4f} | {metrics.mean_error:+.4f} |"
        )

    lines += [
        "",
        "### Production, by position",
        "",
        "Reported per position rather than pooled, because pooling is what hides a "
        "systematic skew.",
        "",
        "| Position | Observations | MAE | RMSE | Bias |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for entry in result.prediction_metrics["production"].by_position:
        lines.append(
            f"| {entry.position} | {entry.observations:,} | {entry.mean_absolute_error:.4f} | "
            f"{entry.root_mean_squared_error:.4f} | {entry.mean_error:+.4f} |"
        )

    lines += ["", "## Pre-registered gates", "", *_gate_rows(document)]
    if result.truncated_candidates:
        listed = ", ".join(result.truncated_candidates)
        lines += [
            "",
            "## Solver truncation",
            "",
            f"**{listed} did not solve every fold to optimality.** Those folds returned "
            "the incumbent selected after the same deterministic amount of CP-SAT work. "
            "Their realized points therefore contain search noise of unknown direction, "
            "not a known downward bias. The wall-clock limit is only a safety cap; the run "
            "is rejected if that cap binds first.",
            "",
            "| Candidate | Solver outcomes |",
            "| --- | --- |",
        ]
        for label, counts in sorted(result.solver_statuses.items()):
            rendered = ", ".join(f"{status} {count}" for status, count in sorted(counts.items()))
            lines.append(f"| {label} | {rendered} |")

    lines += [
        "",
        "## Environment",
        "",
        "Recorded because a numerical solve is sensitive to the libraries underneath it. "
        "The Ridge reference is measured in this run rather than read from an earlier "
        "artifact, since comparing against a figure recorded on another machine would "
        "measure the machines as much as the models.",
        "",
    ]
    lines += [f"- {name}: `{value}`" for name, value in sorted(environment.items())]
    return "\n".join(lines) + "\n"
