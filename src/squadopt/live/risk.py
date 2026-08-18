"""Structured risk evidence for one already-optimized live recommendation."""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.optimization import OptimizationResult
from squadopt.prediction import (
    PredictionError,
    PredictionProvenance,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    RESIDUAL_HISTORY_COLUMNS,
    RivalSquad,
    ScenarioComparisonResult,
    ScenarioConfig,
    ScenarioError,
    ScenarioEvaluationConfig,
    ScenarioRiskMetrics,
    ScenarioTarget,
    compare_fixed_decisions,
    evaluate_fixed_decision,
    generate_scenarios,
)

LIVE_RISK_CONTRACT_VERSION: Final = "live_recommendation_risk_v1"


class LiveRiskValidationError(DataError):
    """Raised when supplied live-risk evidence violates its contract."""


class LiveRiskStatus(StrEnum):
    """Whether distributional diagnostics could be supported by evidence."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"


class LiveRiskBlocker(StrEnum):
    """Specific reasons a requested live-risk calculation was refused."""

    MODEL_MISMATCH = "model_mismatch"
    UNSUPPORTED_OPENING_GAMEWEEK = "unsupported_opening_gameweek"
    INSUFFICIENT_HISTORY = "insufficient_history"


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveRiskValidationError(f"{name} must be non-empty text.")
    return value.strip()


def _residual_fingerprint(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values(["season", "gameweek", "fold_id", "player_id"], kind="stable")
    return hashlib.sha256(ordered.to_csv(index=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LiveResidualHistory:
    """Out-of-sample residual rows plus the model identity that produced them."""

    table: pd.DataFrame
    model_name: str
    model_version: str
    feature_contract_version: str
    post_processing_contract_version: str
    source_id: str
    residual_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.table, pd.DataFrame):
            raise LiveRiskValidationError("table must be a pandas DataFrame.")
        duplicated = self.table.columns[self.table.columns.duplicated()].tolist()
        if duplicated:
            raise LiveRiskValidationError(
                f"Residual history contains duplicate columns: {duplicated!r}."
            )
        missing = [
            column for column in RESIDUAL_HISTORY_COLUMNS if column not in self.table.columns
        ]
        if missing:
            raise LiveRiskValidationError(f"Residual history is missing columns: {missing!r}.")
        table = self.table.loc[:, list(RESIDUAL_HISTORY_COLUMNS)].copy(deep=True)
        if table.empty:
            raise LiveRiskValidationError("Residual history must contain at least one row.")
        for name in (
            "model_name",
            "model_version",
            "feature_contract_version",
            "post_processing_contract_version",
            "source_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "residual_fingerprint", _residual_fingerprint(table))


@dataclass(frozen=True, slots=True)
class LiveRiskDiagnostics:
    """Available risk summaries or explicit reasons they are unavailable."""

    status: LiveRiskStatus
    reason: str
    blockers: tuple[LiveRiskBlocker, ...] = ()
    metrics: ScenarioRiskMetrics | None = None
    scenario_fingerprint: str | None = None
    residual_provenance: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = LIVE_RISK_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != LIVE_RISK_CONTRACT_VERSION:
            raise LiveRiskValidationError("Unsupported live-risk contract version.")
        if not isinstance(self.status, LiveRiskStatus):
            raise LiveRiskValidationError("status must be a LiveRiskStatus.")
        object.__setattr__(self, "reason", _text(self.reason, "reason"))
        if any(not isinstance(blocker, LiveRiskBlocker) for blocker in self.blockers):
            raise LiveRiskValidationError("blockers must contain LiveRiskBlocker values.")
        if self.status is LiveRiskStatus.AVAILABLE:
            if self.blockers or self.metrics is None or self.scenario_fingerprint is None:
                raise LiveRiskValidationError(
                    "Available live risk requires metrics and a scenario fingerprint."
                )
        elif self.metrics is not None or self.scenario_fingerprint is not None:
            raise LiveRiskValidationError(
                "Unavailable live risk cannot carry scenario metrics or a fingerprint."
            )
        if self.status is LiveRiskStatus.UNAVAILABLE and not self.blockers:
            raise LiveRiskValidationError("Unavailable live risk must name at least one blocker.")
        if self.status is LiveRiskStatus.NOT_REQUESTED and self.blockers:
            raise LiveRiskValidationError("Not-requested live risk cannot carry evidence blockers.")
        object.__setattr__(
            self,
            "residual_provenance",
            MappingProxyType(dict(self.residual_provenance)),
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def is_available(self) -> bool:
        """Return whether every requested distributional metric is supported."""

        return self.status is LiveRiskStatus.AVAILABLE


# Limits of the evidence behind an available lower tail, stated with it rather than
# left silent. The calendar limit is measured: the position-only calibration undercovers
# double gameweeks (docs/fixture_group_conformal_note.md), and the residual history a
# live evaluation resamples carries the same blindness unless the caller supplies the
# calendar and a double-gameweek scale.
CALENDAR_BLIND_LIMIT: Final = (
    "The residual history is calendar-blind: on a double gameweek the lower tail is "
    "optimistic by roughly the measured undercoverage (0.85 against nominal 0.90; "
    "docs/fixture_group_conformal_note.md)."
)
LIVE_RISK_STATED_LIMITS: Final = (CALENDAR_BLIND_LIMIT,)


@dataclass(frozen=True, slots=True)
class SelectionOptimism:
    """The winner's curse the scenarios must be shifted by for a *selected* squad.

    Scenarios are centred on the projections; the projections of the players an
    optimizer selects are optimistic by construction. `selection_optimism_profile_v1`
    measured it on the control over 147 development folds: -2.951 points per starter,
    -3.863 for the captain (once more, doubled in the score). The squad-level shift is
    what the scenario audit found uncorrected (+34.5) and corrected (-4.4 with the
    decision-side shrinkage stand-in). Stated as data so a later measurement (the live
    ledger, a promoted model's own profile) replaces it explicitly.
    """

    per_starter_points: float
    captain_points: float
    source: str

    def location_shift(self, starters: int = 11) -> float:
        return -(starters * self.per_starter_points + self.captain_points)


DEVELOPMENT_SELECTION_OPTIMISM: Final = SelectionOptimism(
    per_starter_points=2.951,
    captain_points=3.863,
    source="selection_optimism_profile_v1 (control, 147 development folds, fw06)",
)


def risk_not_requested() -> LiveRiskDiagnostics:
    """Return the honest default when no residual evidence was supplied."""

    return LiveRiskDiagnostics(
        status=LiveRiskStatus.NOT_REQUESTED,
        reason="No residual history was supplied; distributional risk was not evaluated.",
    )


def _provenance(
    history: LiveResidualHistory,
    eligible: pd.DataFrame,
    *,
    target_gameweek: int,
) -> dict[str, object]:
    fold_ids = tuple(
        eligible.loc[:, ["season", "gameweek", "fold_id"]]
        .drop_duplicates()
        .sort_values(["season", "gameweek", "fold_id"], kind="stable")["fold_id"]
        .tolist()
    )
    return {
        "source_id": history.source_id,
        "residual_fingerprint": history.residual_fingerprint,
        "eligible_residual_fingerprint": (
            _residual_fingerprint(eligible) if not eligible.empty else None
        ),
        "model_name": history.model_name,
        "model_version": history.model_version,
        "feature_contract_version": history.feature_contract_version,
        "post_processing_contract_version": history.post_processing_contract_version,
        "input_rows": len(history.table),
        "eligible_rows": len(eligible),
        "eligible_fold_ids": fold_ids,
        "target_gameweek": target_gameweek,
        "opening_policy": "historical_gw1_rows_only",
        "residual_definition": "realized_points_minus_predicted_points",
    }


def evaluate_live_risk(
    inputs: RecommendationInputs,
    projection: Projection,
    optimization_result: OptimizationResult,
    residual_history: LiveResidualHistory,
    *,
    scenario_config: ScenarioConfig | None = None,
    evaluation_config: ScenarioEvaluationConfig | None = None,
    selection_optimism: SelectionOptimism | None = DEVELOPMENT_SELECTION_OPTIMISM,
    fixture_counts: Mapping[int, int] | None = None,
    rivals: Sequence[RivalSquad] = (),
) -> LiveRiskDiagnostics:
    """Evaluate a fixed live decision only when model and target evidence match.

    ``selection_optimism`` shifts the chosen squad's scenario scores by the measured
    winner's curse (None or a zero shift leaves them uncorrected, and says so).
    ``fixture_counts`` (player code → fixtures this gameweek) lets the scenario config's
    ``double_gameweek_scale`` widen doubles; without it the calendar-blind limit is
    stated. ``rivals`` are scored in the same scenarios and the difference is reported.
    """

    if not isinstance(residual_history, LiveResidualHistory):
        raise LiveRiskValidationError("residual_history must be a LiveResidualHistory instance.")
    scenarios = ScenarioConfig() if scenario_config is None else scenario_config
    evaluation = ScenarioEvaluationConfig() if evaluation_config is None else evaluation_config
    if selection_optimism is not None and evaluation.location_shift_points == 0.0:
        evaluation = replace(
            evaluation,
            location_shift_points=selection_optimism.location_shift(
                len(optimization_result.starting_xi)
            ),
        )
    if scenarios.double_gameweek_scale != 1.0 and fixture_counts is None:
        raise LiveRiskValidationError(
            "scenario_config.double_gameweek_scale differs from one; fixture_counts are "
            "required to apply it."
        )
    if not isinstance(scenarios, ScenarioConfig):
        raise LiveRiskValidationError("scenario_config must be a ScenarioConfig.")
    if not isinstance(evaluation, ScenarioEvaluationConfig):
        raise LiveRiskValidationError("evaluation_config must be a ScenarioEvaluationConfig.")

    expected_identity = (
        str(projection.diagnostics.get("model_name", "")),
        str(projection.diagnostics.get("model_version", "")),
        str(projection.diagnostics.get("feature_contract_version", "")),
        str(projection.diagnostics.get("availability_contract_version", "")),
    )
    observed_identity = (
        residual_history.model_name,
        residual_history.model_version,
        residual_history.feature_contract_version,
        residual_history.post_processing_contract_version,
    )
    blockers: list[LiveRiskBlocker] = []
    if observed_identity != expected_identity:
        blockers.append(LiveRiskBlocker.MODEL_MISMATCH)

    eligible = residual_history.table
    if inputs.deadline.gameweek == 1:
        eligible = eligible.loc[eligible["gameweek"] == 1].copy(deep=True)
        if eligible.empty:
            blockers.append(LiveRiskBlocker.UNSUPPORTED_OPENING_GAMEWEEK)
    provenance = _provenance(residual_history, eligible, target_gameweek=inputs.deadline.gameweek)
    eligible_folds = int(eligible["fold_id"].nunique()) if not eligible.empty else 0
    if eligible_folds < scenarios.min_history_folds:
        blockers.append(LiveRiskBlocker.INSUFFICIENT_HISTORY)

    if blockers:
        unique_blockers = tuple(dict.fromkeys(blockers))
        explanations = {
            LiveRiskBlocker.MODEL_MISMATCH: (
                "Residual history was produced by a different model contract."
            ),
            LiveRiskBlocker.UNSUPPORTED_OPENING_GAMEWEEK: (
                "Midseason residuals do not support opening-gameweek risk."
            ),
            LiveRiskBlocker.INSUFFICIENT_HISTORY: (
                f"Eligible history has {eligible_folds} folds; "
                f"{scenarios.min_history_folds} are required."
            ),
        }
        return LiveRiskDiagnostics(
            status=LiveRiskStatus.UNAVAILABLE,
            reason=" ".join(explanations[blocker] for blocker in unique_blockers),
            blockers=unique_blockers,
            residual_provenance=provenance,
            diagnostics={
                "metrics_fabricated": False,
                "decision_reoptimized_per_scenario": False,
                "scenario_count": scenarios.scenario_count,
                "deterministic_seed": scenarios.deterministic_seed,
                "min_history_folds": scenarios.min_history_folds,
                "lower_quantile": evaluation.lower_quantile,
                "worst_fraction": evaluation.worst_fraction,
                "points_threshold": evaluation.points_threshold,
            },
        )

    training_cutoff = projection.diagnostics.get("training_cutoff")
    training_fingerprint = projection.diagnostics.get("training_data_fingerprint")
    if not isinstance(training_cutoff, str) or not training_cutoff:
        raise LiveRiskValidationError("Projection diagnostics lack training_cutoff.")
    if not isinstance(training_fingerprint, str):
        raise LiveRiskValidationError("Projection diagnostics lack training_data_fingerprint.")
    prediction_provenance = PredictionProvenance(
        model_name=expected_identity[0],
        model_version=expected_identity[1],
        feature_contract_version=expected_identity[2],
        training_cutoff=training_cutoff,
        training_data_fingerprint=training_fingerprint,
    )
    snapshot = prepare_optimizer_projection(
        projection.table.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        projection.table.loc[:, ["player_id", "expected_points"]],
        prediction_provenance,
    )
    try:
        scenario_set = generate_scenarios(
            snapshot,
            eligible,
            ScenarioTarget(inputs.season, inputs.deadline.gameweek),
            scenarios,
            fixture_counts=(None if fixture_counts is None else dict(fixture_counts.items())),
        )
        result = evaluate_fixed_decision(optimization_result, scenario_set, evaluation)
        comparisons: list[ScenarioComparisonResult] = [
            compare_fixed_decisions(optimization_result, rival, scenario_set, evaluation)
            for rival in rivals
        ]
    except (PredictionError, ScenarioError) as error:
        raise LiveRiskValidationError(
            f"Live-risk evidence could not be evaluated: {error}"
        ) from error
    return LiveRiskDiagnostics(
        status=LiveRiskStatus.AVAILABLE,
        reason="Risk metrics are supported by matched historical residual evidence.",
        metrics=result.metrics,
        scenario_fingerprint=result.scenario_fingerprint,
        residual_provenance=provenance,
        diagnostics={
            **dict(result.diagnostics),
            "metrics_fabricated": False,
            "scenario_count": scenarios.scenario_count,
            "deterministic_seed": scenarios.deterministic_seed,
            "min_history_folds": scenarios.min_history_folds,
            "lower_quantile": evaluation.lower_quantile,
            "worst_fraction": evaluation.worst_fraction,
            "points_threshold": evaluation.points_threshold,
            "location_shift_points": evaluation.location_shift_points,
            "selection_optimism_source": (
                None if selection_optimism is None else selection_optimism.source
            ),
            "double_gameweek_scale": scenarios.double_gameweek_scale,
            "double_gameweek_players": scenario_set.diagnostics.get("double_gameweek_players"),
            "probability_below_threshold_interval": result.diagnostics.get(
                "probability_below_threshold_interval"
            ),
            "rival_comparisons": [
                {
                    "rival": comparison.rival_label,
                    "probability_ahead": comparison.probability_ahead,
                    "probability_ahead_interval": list(comparison.probability_ahead_interval),
                    "mean_difference": comparison.mean_difference,
                    "difference_quantiles": dict(comparison.difference_quantiles),
                    "shared_starters": comparison.shared_starters,
                }
                for comparison in comparisons
            ],
            "stated_limits": _stated_limits(evaluation, scenarios, fixture_counts),
        },
    )


def _stated_limits(
    evaluation: ScenarioEvaluationConfig,
    scenarios: ScenarioConfig,
    fixture_counts: Mapping[int, int] | None,
) -> list[str]:
    limits: list[str] = []
    if evaluation.location_shift_points == 0.0:
        limits.append(
            "No selection-optimism correction was applied: the chosen squad's scenario "
            "scores are centred on projections that are optimistic by construction "
            "(about +34 points at squad level in the scenario audit)."
        )
    else:
        limits.append(
            f"The lower tail is shifted by {evaluation.location_shift_points:+.1f} points for "
            "selection optimism measured on development folds, not yet on this season's "
            "ledger."
        )
    if evaluation.dispersion_scale == 1.0:
        limits.append(
            "The squad-level spread is the raw scenario spread: the audit measured it about "
            "15% narrow (PIT tails 0.14 against 0.10 on 37 folds, intervals including "
            "nominal), so the lower tail is if anything slightly optimistic."
        )
    else:
        limits.append(
            f"The squad-level spread is widened by {evaluation.dispersion_scale:g} around its "
            "centre (scenario audit, online root-mean-square of standardized gaps); the "
            "evidence is 37 folds and the tails' intervals include nominal both ways."
        )
    if fixture_counts is None or scenarios.double_gameweek_scale == 1.0:
        limits.append(CALENDAR_BLIND_LIMIT)
    else:
        limits.append(
            f"Double-gameweek players' spread is widened by {scenarios.double_gameweek_scale:g} "
            "(fixture-group conformal ratio); the shift is not calendar-specific."
        )
    return limits
