"""Why the squad distribution's lower tail is thin — one scale sweep, two descriptions.

The Phase 2 squad calibration recorded a failed verdict whose two gates disagree in an
informative way: S1 passed, so after the frozen shift the realized squad score sits in
the middle of its own scenario distribution, while S2 failed because that score fell
below the distribution's tenth percentile in 8 of 37 folds instead of 2 to 5. Centred,
and too thin below.

This module diagnoses that on development data. It fixes nothing, promotes nothing and
fits nothing: the only quantity that varies between its arms is ``dispersion_scale``,
an evaluation parameter that already exists, and the levels it takes are declared in
``docs/phase2_tail_diagnostic_prereg.md`` before any of them was measured.

**Nothing here is a new model.** The squad comes from ``optimize_squad``, the scenarios
from ``generate_scenarios``, the summaries from ``evaluate_fixed_decision``, the realized
score from ``score_realized_squad_points``, the residual decomposition from the
generator's own ``decompose_residual_components``, and the interval from the canonical
bootstrap. What is new is only the comparison, and the discipline that makes it fair:
each fold is optimized once and its scenarios are generated once, so the four arms share
their random numbers by construction rather than by an assertion after the fact.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation.scoring import score_realized_squad_points
from squadopt.experiments.shadow_calibration import (
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    bootstrap_interval,
)

# The pinned knobs are read from the Phase 2 configuration rather than restated here:
# two lists of the same pre-registered controls are two lists that can drift apart.
# ``_scenario_config`` and ``_optimizer_config`` are that configuration's own
# translations of it, and are reused for the same reason.
from squadopt.experiments.shadow_squad_calibration import (
    EVALUATION_SEASON,
    MIN_EVALUATION_FOLDS,
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
    _optimizer_config,
    _require,
    _scenario_config,
)
from squadopt.optimization import OptimizationResult, optimize_squad
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioEvaluationConfig,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)
from squadopt.scenarios.decomposition import decompose_residual_components

TAIL_DIAGNOSTIC_CONTRACT_VERSION: Final = "phase2_tail_diagnostic_v1"

#: The declared arms. Constants, not parameters: a level added after a result is a level
#: chosen by the result.
SCALE_LEVELS: Final = (1.00, 1.15, 1.30, 1.45)
CONTROL_SCALE: Final = 1.00

#: The declared split. 2024-25's result was seen before this study was written, so it is
#: labelled development sensitivity — never a confirmation set — and 2025-26 is absent.
SCREENING_SEASONS: Final = ("2021-22", "2022-23")
VALIDATION_SEASON: Final = "2023-24"
SENSITIVITY_SEASON: Final = EVALUATION_SEASON
STUDY_SEASONS: Final = (*SCREENING_SEASONS, VALIDATION_SEASON, SENSITIVITY_SEASON)

#: The shift the Phase 2 run froze, applied unchanged to every arm. Scaling multiplies
#: each scenario score's deviation from the raw mean and the shift is added afterwards,
#: so no arm can move the mean this corrects; refitting per arm would be a second free
#: parameter chosen after the failure was seen.
FROZEN_SHIFT_POINTS: Final = -7.430702271879578

#: What the control arm has to reproduce, from the recorded artifact.
RECORDED_MEAN_PIT: Final = 0.4921621621621622
RECORDED_BELOW_QUANTILE_RATE: Final = 0.21621621621621623
REPLAY_TOLERANCE: Final = 1e-12

#: The bands the Phase 2 protocol pre-registered. Read, never moved.
S1_PIT_BOUNDS: Final = (0.43, 0.57)
S2_TAIL_BOUNDS: Final = (0.04, 0.16)
BOUND_TOLERANCE: Final = 1e-9
BOOTSTRAP_RESAMPLES: Final = 5000

SCALE_SUFFICIENT: Final = "scale_sufficient_candidate"
SCALE_NOT_SUFFICIENT: Final = "scale_not_sufficient"
INCONCLUSIVE: Final = "diagnostic_inconclusive"


@dataclass(frozen=True, slots=True)
class ArmReading:
    """One fold read at one scale."""

    fold_id: str
    season: str
    scale: float
    probability_integral_transform: float
    below_lower_quantile: bool
    scenario_mean_score: float
    realized_score: float
    tail_width: float


@dataclass(frozen=True, slots=True)
class FoldFacts:
    """What one fold contributes to the descriptive readings, at the control arm."""

    fold_id: str
    season: str
    realized_score: float
    scenario_mean_score: float
    below_lower_quantile: bool
    #: None when the decision names no captain. Missing, never zero.
    captain_realized_error: float | None


def _evaluation_config(config: SquadShadowConfig, *, scale: float) -> ScenarioEvaluationConfig:
    """The Phase 2 evaluation, with the arm's scale and nothing else changed."""

    return ScenarioEvaluationConfig(
        lower_quantile=config.lower_quantile,
        worst_fraction=config.worst_fraction,
        points_threshold=config.points_threshold,
        location_shift_points=FROZEN_SHIFT_POINTS,
        dispersion_scale=scale,
    )


def _captain_error(fold: SquadFold, decision: OptimizationResult) -> float | None:
    """The captain's realized points minus the captain's projected points.

    ``None`` when the decision names no captain or the fold does not report that
    player: an absent number is missing, and this study never reads it as zero.
    """

    captain = decision.captain
    if captain is None:
        return None
    player_id = captain["player_id"]
    realized = fold.realized_points.loc[
        fold.realized_points["player_id"] == player_id, "total_points"
    ]
    projected = fold.projections.loc[fold.projections["player_id"] == player_id, "expected_points"]
    if realized.empty or projected.empty:
        return None
    return float(realized.iloc[0]) - float(projected.iloc[0])


def read_fold_at_every_scale(
    fold: SquadFold,
    residuals: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
    *,
    scales: Sequence[float] = SCALE_LEVELS,
) -> tuple[tuple[ArmReading, ...], FoldFacts]:
    """Optimize once, generate once, evaluate at every arm.

    The single generation is the point: the arms differ in what is read off one
    scenario matrix, so they cannot differ in the draws underneath it.
    """

    decision = optimize_squad_once(fold, config)
    snapshot = prepare_optimizer_projection(
        fold.projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        fold.projections.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    history = residuals.loc[residuals["fold_id"].astype(str).isin(set(history_fold_ids))]
    scenarios = generate_scenarios(
        snapshot,
        history,
        ScenarioTarget(fold.season, fold.gameweek),
        _scenario_config(config),
    )
    realized_score = score_realized_squad_points(decision, fold.realized_points)
    _require(
        math.isfinite(realized_score),
        f"{fold.fold_id}: a non-finite realized score cannot enter a diagnostic.",
    )

    readings: list[ArmReading] = []
    control: ArmReading | None = None
    for scale in scales:
        evaluated = evaluate_fixed_decision(
            decision, scenarios, _evaluation_config(config, scale=float(scale))
        )
        scores = np.asarray(evaluated.scenario_scores, dtype="float64")
        lower = float(evaluated.metrics.lower_quantile_score)
        mean_score = float(evaluated.metrics.mean_score)
        reading = ArmReading(
            fold_id=fold.fold_id,
            season=fold.season,
            scale=float(scale),
            probability_integral_transform=float((scores <= realized_score).mean()),
            below_lower_quantile=bool(realized_score < lower),
            scenario_mean_score=mean_score,
            realized_score=realized_score,
            tail_width=mean_score - lower,
        )
        readings.append(reading)
        if float(scale) == CONTROL_SCALE:
            control = reading

    _require(control is not None, "the control arm is not among the declared scales.")
    assert control is not None
    facts = FoldFacts(
        fold_id=fold.fold_id,
        season=fold.season,
        realized_score=realized_score,
        scenario_mean_score=control.scenario_mean_score,
        below_lower_quantile=control.below_lower_quantile,
        captain_realized_error=_captain_error(fold, decision),
    )
    return tuple(readings), facts


def optimize_squad_once(fold: SquadFold, config: SquadShadowConfig) -> OptimizationResult:
    """The Phase 2 decision for this fold, at the pinned optimizer settings."""

    decision = optimize_squad(fold.projections, _optimizer_config(config))
    _require(
        decision.has_solution,
        f"{fold.fold_id}: no feasible decision; the fold is refused rather than scored "
        "on a partial squad.",
    )
    return decision


def summarise_arm(readings: Sequence[ArmReading]) -> dict[str, float | None]:
    """The declared metrics for one season and one scale, and nothing invented."""

    _require(bool(readings), "an arm summary needs at least one fold.")
    pit = [reading.probability_integral_transform for reading in readings]
    tail = [1.0 if reading.below_lower_quantile else 0.0 for reading in readings]
    events = int(sum(tail))
    summary: dict[str, float | None] = {
        "fold_count": float(len(readings)),
        "mean_probability_integral_transform": float(np.mean(pit)),
        "below_lower_quantile_folds": float(events),
        "below_lower_quantile_rate": float(np.mean(tail)),
        "mean_scenario_score": float(np.mean([r.scenario_mean_score for r in readings])),
        "mean_realized_score": float(np.mean([r.realized_score for r in readings])),
        "mean_tail_width": float(np.mean([r.tail_width for r in readings])),
    }
    # Diagnostic only: no classification reads these.
    for name, series in (("mean_pit", pit), ("below_lower_quantile_rate", tail)):
        low, high = bootstrap_interval(
            series,
            resamples=BOOTSTRAP_RESAMPLES,
            seed=BOOTSTRAP_SEED,
            confidence_level=CONFIDENCE_LEVEL,
        )
        summary[f"{name}_bootstrap_low"] = low
        summary[f"{name}_bootstrap_high"] = high
    return summary


def _within(value: float, bounds: tuple[float, float]) -> bool:
    low, high = bounds
    return low - BOUND_TOLERANCE <= value <= high + BOUND_TOLERANCE


def satisfies_both_gates(summary: Mapping[str, float | None]) -> bool:
    """Both pre-registered bands, read exactly as the Phase 2 protocol reads them."""

    pit = summary["mean_probability_integral_transform"]
    rate = summary["below_lower_quantile_rate"]
    if pit is None or rate is None:
        return False
    return _within(float(pit), S1_PIT_BOUNDS) and _within(float(rate), S2_TAIL_BOUNDS)


def classify(
    validation: Mapping[float, Mapping[str, float | None]],
) -> tuple[str, tuple[float, ...]]:
    """The study's only decision: one of three words, from validation alone.

    No winner is chosen when more than one arm qualifies, and the smallest is not
    promoted by default. The eligible set is the whole answer.
    """

    if not validation:
        return INCONCLUSIVE, ()
    folds = {float(summary["fold_count"] or 0.0) for summary in validation.values()}
    if not folds or min(folds) < MIN_EVALUATION_FOLDS:
        return INCONCLUSIVE, ()
    eligible = tuple(
        sorted(scale for scale, summary in validation.items() if satisfies_both_gates(summary))
    )
    return (SCALE_SUFFICIENT if eligible else SCALE_NOT_SUFFICIENT), eligible


def control_replay(sensitivity: Mapping[str, float | None]) -> dict[str, float | bool | None]:
    """Does the control arm reproduce the recorded measurement?

    A comparison whose baseline has drifted is not a comparison. The caller stops the
    study when this says so, rather than reporting arms against a moved control.
    """

    pit = sensitivity["mean_probability_integral_transform"]
    rate = sensitivity["below_lower_quantile_rate"]
    reproduced = (
        pit is not None
        and rate is not None
        and abs(float(pit) - RECORDED_MEAN_PIT) <= REPLAY_TOLERANCE
        and abs(float(rate) - RECORDED_BELOW_QUANTILE_RATE) <= REPLAY_TOLERANCE
    )
    return {
        "recorded_mean_probability_integral_transform": RECORDED_MEAN_PIT,
        "measured_mean_probability_integral_transform": pit,
        "recorded_below_lower_quantile_rate": RECORDED_BELOW_QUANTILE_RATE,
        "measured_below_lower_quantile_rate": rate,
        "tolerance": REPLAY_TOLERANCE,
        "reproduced": bool(reproduced),
    }


def common_shock_description(
    facts: Sequence[FoldFacts], residuals: pd.DataFrame
) -> dict[str, object]:
    """H2, descriptive: does the squad's error move with the gameweek's common residual?

    The decomposition is the generator's own, so the "common component" here is the
    quantity the scenarios are built from rather than a second definition of it. This
    describes co-movement. It is not a causal claim and it is not a gate.
    """

    required = {"fold_id", "team_id", "residual"}
    missing = sorted(required - set(residuals.columns))
    if missing:
        return {
            "measurable": False,
            "reason": (
                f"team-shock diagnostic not measurable from this artifact: the residual "
                f"export carries no {missing!r}."
            ),
        }

    decomposed = decompose_residual_components(residuals)
    by_fold = decomposed.groupby("fold_id", sort=False)
    common = by_fold["common_component"].first()
    team_spread = by_fold["team_component"].std(ddof=0)

    paired = [
        (float(common.loc[fact.fold_id]), fact.realized_score - fact.scenario_mean_score, fact)
        for fact in facts
        if fact.fold_id in common.index
    ]
    unmatched = tuple(fact.fold_id for fact in facts if fact.fold_id not in common.index)
    if len(paired) < 2:
        return {
            "measurable": False,
            "reason": "fewer than two folds carry both a squad gap and a common component.",
            "folds_without_residual_rows": list(unmatched),
        }

    commons = np.asarray([entry[0] for entry in paired], dtype="float64")
    gaps = np.asarray([entry[1] for entry in paired], dtype="float64")
    agreeing = int(np.sum(np.sign(commons) == np.sign(gaps)))
    correlation = (
        float(np.corrcoef(commons, gaps)[0, 1])
        if commons.std() > 0.0 and gaps.std() > 0.0
        else None
    )
    below = [entry for entry in paired if entry[2].below_lower_quantile]
    rest = [entry for entry in paired if not entry[2].below_lower_quantile]
    return {
        "measurable": True,
        "fold_count": len(paired),
        "folds_without_residual_rows": list(unmatched),
        "sign_agreement_rate": agreeing / len(paired),
        "pearson_correlation": correlation,
        "mean_common_component": float(commons.mean()),
        "mean_common_component_below_lower_quantile": (
            float(np.mean([entry[0] for entry in below])) if below else None
        ),
        "mean_common_component_elsewhere": (
            float(np.mean([entry[0] for entry in rest])) if rest else None
        ),
        "mean_squad_gap_below_lower_quantile": (
            float(np.mean([entry[1] for entry in below])) if below else None
        ),
        "mean_squad_gap_elsewhere": (
            float(np.mean([entry[1] for entry in rest])) if rest else None
        ),
        "mean_team_component_dispersion": float(team_spread.mean()),
    }


def captain_description(facts: Sequence[FoldFacts]) -> dict[str, object]:
    """H3, descriptive: do the below-q10 events sit where the captain missed?"""

    measured = [fact for fact in facts if fact.captain_realized_error is not None]
    if not measured:
        return {
            "measurable": False,
            "reason": "no fold's decision names a captain this study can read.",
            "folds_without_captain": len(facts),
        }
    errors = [
        fact.captain_realized_error for fact in measured if fact.captain_realized_error is not None
    ]
    below = [
        fact.captain_realized_error
        for fact in measured
        if fact.below_lower_quantile and fact.captain_realized_error is not None
    ]
    rest = [
        fact.captain_realized_error
        for fact in measured
        if not fact.below_lower_quantile and fact.captain_realized_error is not None
    ]
    return {
        "measurable": True,
        "fold_count": len(measured),
        # Missing is not zero: a fold with no captain is counted here, not averaged in.
        "folds_without_captain": len(facts) - len(measured),
        "mean_captain_realized_error": float(np.mean(errors)),
        "mean_captain_realized_error_below_lower_quantile": (
            float(np.mean(below)) if below else None
        ),
        "mean_captain_realized_error_elsewhere": float(np.mean(rest)) if rest else None,
        "worst_captain_realized_error": float(min(errors)),
    }


def eligible_development_folds(
    folds: Sequence[SquadFold], config: SquadShadowConfig
) -> tuple[SquadFold, ...]:
    """The development chain minus its burn-in, by the third amendment's own rule.

    A fold with less history than ``min_history_folds`` is one the generator refuses;
    the Phase 2 shift fit excludes exactly these, and so does this study.
    """

    return tuple(
        fold for fold in folds if len(set(fold.prior_fold_ids)) >= config.min_history_folds
    )


def refuse_the_holdout(seasons: Sequence[str]) -> None:
    """The locked season never reaches a loader through this study."""

    from squadopt.experiments.shadow_squad_calibration import LOCKED_HOLDOUT_SEASON

    if LOCKED_HOLDOUT_SEASON in set(seasons):
        raise SquadShadowError(
            f"{LOCKED_HOLDOUT_SEASON} is the locked confirmation holdout and may not be "
            "read by a development diagnostic."
        )
