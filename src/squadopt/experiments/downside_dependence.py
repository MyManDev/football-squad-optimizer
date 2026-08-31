"""Measure selected-XI downside co-movement without changing scenario generation."""

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
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    MIN_EVALUATION_FOLDS,
    SquadFold,
    SquadShadowConfig,
    _require,
    _scenario_config,
)
from squadopt.experiments.tail_diagnostic import (
    CONTROL_SCALE,
    _evaluation_config,
    optimize_squad_once,
)
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioTarget, evaluate_fixed_decision, generate_scenarios

DOWNSIDE_DEPENDENCE_CONTRACT_VERSION: Final = "phase2_downside_dependence_v1"
DOWNSIDE_QUANTILE: Final = 0.25
COUNT_UPPER_QUANTILE: Final = 0.90
STARTER_COUNT: Final = 11
PAIR_COUNT: Final = math.comb(STARTER_COUNT, 2)

JOINT_UNDERREPRESENTED: Final = "joint_downside_underrepresented"
MARGINAL_AND_JOINT_MISS: Final = "marginal_and_joint_downside_miss"
NO_JOINT_EVIDENCE: Final = "no_joint_downside_evidence"
INCONCLUSIVE: Final = "diagnostic_inconclusive"


@dataclass(frozen=True, slots=True)
class DownsideReading:
    """One fixed XI's realized downside and its canonical scenario expectation."""

    fold_id: str
    season: str
    realized_marginal_rate: float
    expected_marginal_rate: float
    realized_joint_rate: float
    expected_joint_rate: float
    realized_same_team_joint_rate: float | None
    expected_same_team_joint_rate: float | None
    realized_different_team_joint_rate: float
    expected_different_team_joint_rate: float
    realized_downside_count: int
    count_mid_pit: float
    count_above_q90: bool
    covariance_contribution: float
    full_score_pit: float
    full_score_below_q10: bool

    @property
    def marginal_gap(self) -> float:
        return self.realized_marginal_rate - self.expected_marginal_rate

    @property
    def joint_gap(self) -> float:
        return self.realized_joint_rate - self.expected_joint_rate

    @property
    def same_team_joint_gap(self) -> float | None:
        if self.realized_same_team_joint_rate is None or self.expected_same_team_joint_rate is None:
            return None
        return self.realized_same_team_joint_rate - self.expected_same_team_joint_rate

    @property
    def different_team_joint_gap(self) -> float:
        return self.realized_different_team_joint_rate - self.expected_different_team_joint_rate


def _pair_rates(
    events: np.ndarray, teams: Sequence[object]
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray]:
    """Return all-, same-team and different-team pair rates for each row."""

    left, right = np.triu_indices(STARTER_COUNT, k=1)
    joint = events[:, left] & events[:, right]
    same_mask: np.ndarray = np.array(
        [teams[int(a)] == teams[int(b)] for a, b in zip(left, right, strict=True)],
        dtype=np.bool_,
    )
    different_mask = ~same_mask
    all_rates = joint.mean(axis=1)
    same_rates = joint[:, same_mask].mean(axis=1) if bool(same_mask.any()) else None
    different_rates = joint[:, different_mask].mean(axis=1)
    return all_rates, same_rates, different_rates


def read_fold(
    fold: SquadFold,
    residuals: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
) -> DownsideReading:
    """Read simultaneous starter downside from one unchanged decision and scenario set."""

    _require(
        config.dispersion_scale == CONTROL_SCALE,
        "the downside diagnostic is defined only at the recorded control dispersion.",
    )
    decision = optimize_squad_once(fold, config)
    starters = decision.starting_xi["player_id"].tolist()
    _require(
        len(starters) == STARTER_COUNT and len(set(starters)) == STARTER_COUNT,
        f"{fold.fold_id}: the diagnostic requires exactly eleven distinct starters.",
    )
    snapshot = prepare_optimizer_projection(
        fold.projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        fold.projections.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    history = residuals.loc[residuals["fold_id"].astype(str).isin(set(history_fold_ids))]
    scenarios = generate_scenarios(
        snapshot, history, ScenarioTarget(fold.season, fold.gameweek), _scenario_config(config)
    )
    evaluated = evaluate_fixed_decision(
        decision, scenarios, _evaluation_config(config, scale=CONTROL_SCALE)
    )

    projection_rows = snapshot.table.set_index("player_id")
    _require(
        all(player_id in projection_rows.index for player_id in starters),
        f"{fold.fold_id}: a starter is absent from the projection snapshot.",
    )
    scenario_rows = scenarios.scenario_points.loc[:, starters].to_numpy(dtype="float64")
    expected = projection_rows.loc[starters, "expected_points"].to_numpy(dtype="float64")
    scenario_residuals = scenario_rows - expected[None, :]
    thresholds = np.quantile(scenario_residuals, DOWNSIDE_QUANTILE, axis=0, method="linear")
    scenario_events = scenario_residuals < thresholds[None, :]

    realized_rows = fold.realized_points.set_index("player_id")
    _require(
        realized_rows.index.is_unique
        and all(player_id in realized_rows.index for player_id in starters),
        f"{fold.fold_id}: realized points must cover each starter exactly once.",
    )
    realized = realized_rows.loc[starters, "total_points"].to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(realized).all()),
        f"{fold.fold_id}: starter outcomes must be finite.",
    )
    realized_events = (realized - expected) < thresholds
    teams = projection_rows.loc[starters, "team_id"].tolist()
    scenario_all, scenario_same, scenario_different = _pair_rates(scenario_events, teams)
    realized_all, realized_same, realized_different = _pair_rates(realized_events[None, :], teams)

    scenario_counts = scenario_events.sum(axis=1)
    realized_count = int(realized_events.sum())
    count_mid_pit = float(
        ((scenario_counts < realized_count).sum() + 0.5 * (scenario_counts == realized_count).sum())
        / len(scenario_counts)
    )
    count_q90 = float(np.quantile(scenario_counts, COUNT_UPPER_QUANTILE, method="linear"))
    covariance_contribution = float(
        scenario_residuals.sum(axis=1).var(ddof=0) - scenario_residuals.var(axis=0, ddof=0).sum()
    )

    full_scores = np.asarray(evaluated.scenario_scores, dtype="float64")
    full_realized = score_realized_squad_points(decision, fold.realized_points)
    return DownsideReading(
        fold_id=fold.fold_id,
        season=fold.season,
        realized_marginal_rate=realized_count / STARTER_COUNT,
        expected_marginal_rate=float(scenario_events.mean()),
        realized_joint_rate=float(realized_all[0]),
        expected_joint_rate=float(scenario_all.mean()),
        realized_same_team_joint_rate=(
            float(realized_same[0]) if realized_same is not None else None
        ),
        expected_same_team_joint_rate=(
            float(scenario_same.mean()) if scenario_same is not None else None
        ),
        realized_different_team_joint_rate=float(realized_different[0]),
        expected_different_team_joint_rate=float(scenario_different.mean()),
        realized_downside_count=realized_count,
        count_mid_pit=count_mid_pit,
        count_above_q90=realized_count > count_q90,
        covariance_contribution=covariance_contribution,
        full_score_pit=float((full_scores <= full_realized).mean()),
        full_score_below_q10=bool(
            full_realized < float(np.quantile(full_scores, config.lower_quantile, method="linear"))
        ),
    )


def _gap_summary(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a downside gap summary requires at least one fold.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def summarise(readings: Sequence[DownsideReading]) -> dict[str, object]:
    """Summarise one declared fold population without inventing a composite score."""

    _require(bool(readings), "a downside summary requires at least one fold.")
    same_gaps = [
        value for reading in readings if (value := reading.same_team_joint_gap) is not None
    ]
    return {
        "fold_count": len(readings),
        "marginal_downside_rate": {
            "realized": float(np.mean([r.realized_marginal_rate for r in readings])),
            "scenario_expected": float(np.mean([r.expected_marginal_rate for r in readings])),
            "gap": _gap_summary([r.marginal_gap for r in readings]),
        },
        "all_pair_joint_downside_rate": {
            "realized": float(np.mean([r.realized_joint_rate for r in readings])),
            "scenario_expected": float(np.mean([r.expected_joint_rate for r in readings])),
            "gap": _gap_summary([r.joint_gap for r in readings]),
        },
        "same_team_joint_downside_gap": _gap_summary(same_gaps) if same_gaps else None,
        "different_team_joint_downside_gap": _gap_summary(
            [r.different_team_joint_gap for r in readings]
        ),
        "mean_count_mid_pit": float(np.mean([r.count_mid_pit for r in readings])),
        "count_above_scenario_q90_folds": sum(r.count_above_q90 for r in readings),
        "mean_realized_downside_count": float(
            np.mean([r.realized_downside_count for r in readings])
        ),
        "mean_scenario_covariance_contribution": float(
            np.mean([r.covariance_contribution for r in readings])
        ),
        "full_score_below_q10_folds": sum(r.full_score_below_q10 for r in readings),
    }


def classify(summary: Mapping[str, object]) -> str:
    """Classify validation only under the pre-registered descriptive rule."""

    fold_count = summary.get("fold_count")
    if type(fold_count) is not int or fold_count < MIN_EVALUATION_FOLDS:
        return INCONCLUSIVE
    marginal = summary.get("marginal_downside_rate")
    joint = summary.get("all_pair_joint_downside_rate")
    if not isinstance(marginal, Mapping) or not isinstance(joint, Mapping):
        return INCONCLUSIVE
    marginal_gap = marginal.get("gap")
    joint_gap = joint.get("gap")
    if not isinstance(marginal_gap, Mapping) or not isinstance(joint_gap, Mapping):
        return INCONCLUSIVE
    marginal_low = float(marginal_gap["bootstrap_low"])
    marginal_high = float(marginal_gap["bootstrap_high"])
    joint_mean = float(joint_gap["mean"])
    joint_low = float(joint_gap["bootstrap_low"])
    if joint_low > 0.0 and marginal_low <= 0.0 <= marginal_high:
        return JOINT_UNDERREPRESENTED
    if joint_mean > 0.0 and not (marginal_low <= 0.0 <= marginal_high):
        return MARGINAL_AND_JOINT_MISS
    return NO_JOINT_EVIDENCE
