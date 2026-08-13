"""JSON-compatible records and concise Markdown reports for experiment artifacts."""

from collections.abc import Mapping
from dataclasses import asdict

from squadopt.experiments.config import (
    SCREENING_EXPERIMENT_CONTRACT_VERSION,
    ExperimentCandidate,
    FrozenCandidateError,
)
from squadopt.experiments.models import (
    CandidateAssessment,
    FrozenCandidate,
    HoldoutEvaluationResult,
    ScreeningExperimentResult,
)


def _candidate_record(candidate: ExperimentCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "form_window": candidate.form_window,
        "bench_weight": candidate.bench_weight,
    }


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    return value


def frozen_candidate_to_dict(candidate: FrozenCandidate) -> dict[str, object]:
    """Return the portable artifact required by the holdout command."""

    return {
        "candidate": _candidate_record(candidate.candidate),
        "control": _candidate_record(candidate.control),
        "screening_fingerprint": candidate.screening_fingerprint,
        "configuration_fingerprint": candidate.configuration_fingerprint,
        "experiment_contract_version": candidate.experiment_contract_version,
    }


def _candidate_from_record(value: object, name: str) -> ExperimentCandidate:
    if not isinstance(value, Mapping):
        raise FrozenCandidateError(f"{name} must be a mapping.")
    if "form_window" not in value or "bench_weight" not in value:
        raise FrozenCandidateError(f"{name} must contain form_window and bench_weight.")
    return ExperimentCandidate(
        form_window=value["form_window"],
        bench_weight=value["bench_weight"],
    )


def frozen_candidate_from_dict(value: object) -> FrozenCandidate:
    """Validate and reconstruct a frozen candidate from a JSON-decoded object."""

    if not isinstance(value, Mapping):
        raise FrozenCandidateError("Frozen candidate artifact must be a mapping.")
    required = (
        "candidate",
        "control",
        "screening_fingerprint",
        "configuration_fingerprint",
        "experiment_contract_version",
    )
    missing = [name for name in required if name not in value]
    if missing:
        raise FrozenCandidateError(f"Frozen candidate artifact is missing {missing!r}.")
    strings = {
        name: value[name]
        for name in (
            "screening_fingerprint",
            "configuration_fingerprint",
            "experiment_contract_version",
        )
    }
    if any(not isinstance(item, str) for item in strings.values()):
        raise FrozenCandidateError("Frozen candidate digest and version fields must be strings.")
    return FrozenCandidate(
        candidate=_candidate_from_record(value["candidate"], "candidate"),
        control=_candidate_from_record(value["control"], "control"),
        screening_fingerprint=strings["screening_fingerprint"],
        configuration_fingerprint=strings["configuration_fingerprint"],
        experiment_contract_version=strings["experiment_contract_version"],
    )


def _fold_records(assessment: CandidateAssessment) -> list[dict[str, object]]:
    return [
        {
            "fold_id": fold.fold_id,
            "season": fold.metadata.get("season"),
            "gameweek": fold.metadata.get("gameweek"),
            "solver_status": fold.optimization_result.solver_status.value,
            "realized_squad_points": fold.realized_squad_points,
            "projected_objective_value": fold.optimization_result.objective_value,
            "solver_runtime_seconds": fold.optimization_result.diagnostics.get(
                "solve_time_seconds"
            ),
            "squad_turnover": fold.squad_turnover,
            "solve_reused": fold.optimization_result.diagnostics.get("solve_reused", False),
        }
        for fold in assessment.evaluation.folds
    ]


def _assessment_record(assessment: CandidateAssessment) -> dict[str, object]:
    summary = asdict(assessment.evaluation.summary)
    comparison = assessment.comparison
    return {
        **_candidate_record(assessment.candidate),
        "coefficient_signature": assessment.coefficient_signature,
        "coefficient_equivalent_to": assessment.equivalent_to,
        "summary": summary,
        "paired_comparison": {
            "control_id": comparison.control_id,
            "comparable_folds": comparison.comparable_folds,
            "mean_difference": comparison.mean_difference,
            "confidence_interval_lower": comparison.confidence_interval_lower,
            "confidence_interval_upper": comparison.confidence_interval_upper,
            "season_mean_differences": dict(comparison.season_mean_differences),
            "passes_feasibility": comparison.passes_feasibility,
            "passes_mean_improvement": comparison.passes_mean_improvement,
            "passes_confidence_interval": comparison.passes_confidence_interval,
            "eligible": comparison.eligible,
        },
        "folds": _fold_records(assessment),
    }


def _configuration_record(result: ScreeningExperimentResult) -> dict[str, object]:
    config = result.config
    optimization = config.optimization_config
    policy = config.promotion_policy
    return {
        "configuration_fingerprint": config.configuration_fingerprint,
        "development_seasons": list(config.development_seasons),
        "holdout_seasons": list(config.holdout_seasons),
        "form_windows": list(config.form_windows),
        "bench_weights": list(config.bench_weights),
        "control": _candidate_record(config.control),
        "scoring_policy": result.assessments[0].evaluation.config.scoring_policy.value,
        "min_prior_gameweeks_in_season": config.min_prior_gameweeks_in_season,
        "parallel_candidate_jobs": config.parallel_candidate_jobs,
        "cross_season": {
            "decay": config.cross_season_config.decay,
            "min_minutes": config.cross_season_config.min_minutes,
        },
        "optimization": {
            "budget_tenths": optimization.budget_tenths,
            "squad_size": optimization.squad_size,
            "squad_position_limits": dict(optimization.squad_position_limits),
            "starting_size": optimization.starting_size,
            "starting_position_min": dict(optimization.starting_position_min),
            "starting_position_max": dict(optimization.starting_position_max),
            "max_players_per_team": optimization.max_players_per_team,
            "expected_points_scale": optimization.expected_points_scale,
            "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
            "deterministic_seed": optimization.deterministic_seed,
            "solver_workers": 1,
        },
        "promotion_policy": {
            "min_mean_improvement": policy.min_mean_improvement,
            "confidence_level": policy.confidence_level,
            "bootstrap_resamples": policy.bootstrap_resamples,
            "moving_block_length": policy.moving_block_length,
            "deterministic_seed": policy.deterministic_seed,
        },
        "run_metadata": _json_value(config.run_metadata),
    }


def screening_result_to_dict(result: ScreeningExperimentResult) -> dict[str, object]:
    """Serialize the complete development-only experiment result."""

    return {
        "artifact_type": "screening_experiment",
        "experiment_contract_version": SCREENING_EXPERIMENT_CONTRACT_VERSION,
        "screening_fingerprint": result.screening_fingerprint,
        "configuration": _configuration_record(result),
        "selection": {
            **_candidate_record(result.selected_candidate),
            "selected_is_control": result.selected_is_control,
            "reason": result.selection_reason,
        },
        "frozen_candidate": frozen_candidate_to_dict(
            FrozenCandidate(
                candidate=result.selected_candidate,
                control=result.config.control,
                screening_fingerprint=result.screening_fingerprint,
                configuration_fingerprint=result.config.configuration_fingerprint,
            )
        ),
        "main_effects": [asdict(effect) for effect in result.main_effects],
        "interactions": [asdict(effect) for effect in result.interactions],
        "candidates": [_assessment_record(item) for item in result.assessments],
        "diagnostics": dict(result.diagnostics),
    }


def screening_result_to_markdown(result: ScreeningExperimentResult) -> str:
    """Render the screening decision and aggregate candidate table."""

    lines = [
        "# Sprint 2 screening DoE",
        "",
        f"Screening fingerprint: `{result.screening_fingerprint}`",
        f"Development seasons: `{', '.join(result.config.development_seasons)}`",
        "The locked holdout was not accessed by this run.",
        "",
        "## Candidate responses",
        "",
        "| Candidate | Mean realized | Paired delta | "
        f"{result.config.promotion_policy.confidence_level * 100:g}% CI | "
        "Feasibility | Eligible |",
        "| --- | ---: | ---: | --- | ---: | --- |",
    ]
    for item in result.assessments:
        summary = item.evaluation.summary
        comparison = item.comparison
        interval = (
            "n/a"
            if comparison.confidence_interval_lower is None
            else f"[{comparison.confidence_interval_lower:.3f}, "
            f"{comparison.confidence_interval_upper:.3f}]"
        )
        mean = summary.mean_realized_squad_points
        difference = comparison.mean_difference
        lines.append(
            f"| `{item.candidate.candidate_id}` | "
            f"{'n/a' if mean is None else f'{mean:.3f}'} | "
            f"{'n/a' if difference is None else f'{difference:.3f}'} | {interval} | "
            f"{summary.feasibility_rate:.3f} | {str(comparison.eligible).lower()} |"
        )

    lines.extend(
        [
            "",
            "## Frozen development decision",
            "",
            f"Selected candidate: `{result.selected_candidate.candidate_id}`",
            "",
            result.selection_reason,
            "",
            "## Main effects",
            "",
            "| Factor | Level | Marginal mean | Effect from control level |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for effect in result.main_effects:
        rendered_mean = "n/a" if effect.marginal_mean is None else f"{effect.marginal_mean:.3f}"
        rendered_delta = (
            "n/a"
            if effect.effect_from_control_level is None
            else f"{effect.effect_from_control_level:.3f}"
        )
        lines.append(f"| {effect.factor} | {effect.level} | {rendered_mean} | {rendered_delta} |")
    return "\n".join(lines) + "\n"


def holdout_result_to_dict(result: HoldoutEvaluationResult) -> dict[str, object]:
    """Serialize the locked-holdout decision and both compared candidates."""

    return {
        "artifact_type": "locked_holdout_evaluation",
        "frozen_candidate": frozen_candidate_to_dict(result.frozen_candidate),
        "promoted": result.promoted,
        "decision_reason": result.decision_reason,
        "candidate": _assessment_record(result.candidate_assessment),
        "control": _assessment_record(result.control_assessment),
        "diagnostics": dict(result.diagnostics),
    }


def holdout_result_to_markdown(result: HoldoutEvaluationResult) -> str:
    """Render the final holdout gate in a compact human-readable report."""

    comparison = result.candidate_assessment.comparison
    interval = (
        "n/a"
        if comparison.confidence_interval_lower is None
        else f"[{comparison.confidence_interval_lower:.3f}, "
        f"{comparison.confidence_interval_upper:.3f}]"
    )
    return "\n".join(
        [
            "# Sprint 2 locked holdout",
            "",
            f"Frozen screening fingerprint: `{result.frozen_candidate.screening_fingerprint}`",
            f"Candidate: `{result.frozen_candidate.candidate.candidate_id}`",
            f"Control: `{result.frozen_candidate.control.candidate_id}`",
            f"Paired mean difference: `{comparison.mean_difference}`",
            f"Confidence interval: `{interval}`",
            f"Promoted: `{str(result.promoted).lower()}`",
            "",
            result.decision_reason,
            "",
        ]
    )
