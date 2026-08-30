"""Is the squad tail failure the captain's second copy, or the rest of the squad?

The Phase 2 squad calibration failed S2; the tail diagnostic that followed ruled out a
global dispersion scale and found the common weekly shock explained little. What did
separate the failing folds was the captain's realized error. The scoring policy counts
the captain twice, so this removes **only that second copy** — from the scenario side and
the realized side alike — and asks whether the tail failure survives it.

``captain_bonus_removed`` never means the captain leaves the squad. He stays in the
starting XI with his ordinary points on both sides, and nothing is reoptimized: one
decision and one scenario matrix are read twice.

**No scoring arithmetic is re-implemented.** The full score comes from the canonical
``evaluate_fixed_decision``; the extra copy is the captain's own column of the canonical
``ScenarioSet`` on one side and his realized points on the other. At the pre-registered
dispersion of exactly 1.0 the evaluator collapses to ``score = raw + shift``, so
subtracting that column from the evaluated scores *is* the ablation rather than an
approximation of it — and the study refuses any other dispersion instead of guessing. The
quantile and the PIT are read with the evaluator's own expressions, and the full arm
proves the derivation against the canonical metrics rather than asking to be trusted.

The frozen shift was fitted for the full score, so applying it unchanged to the ablated
distribution over-corrects and biases the reading toward the captain. Each distribution is
therefore read twice — under the frozen shift and under none — and the classification
refuses to answer when the two conventions disagree.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation.scoring import score_realized_squad_points
from squadopt.experiments.shadow_squad_calibration import (
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
    _require,
    _scenario_config,
)
from squadopt.experiments.tail_diagnostic import (
    BOUND_TOLERANCE,
    CONTROL_SCALE,
    FROZEN_SHIFT_POINTS,
    S1_PIT_BOUNDS,
    S2_TAIL_BOUNDS,
    _evaluation_config,
    optimize_squad_once,
)
from squadopt.optimization import OptimizationResult
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioEvaluationResult,
    ScenarioSet,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)

CAPTAIN_ATTRIBUTION_CONTRACT_VERSION: Final = "phase2_captain_attribution_v1"

FULL: Final = "full"
ABLATED: Final = "captain_bonus_removed"
FULL_UNSHIFTED: Final = "full_unshifted"
ABLATED_UNSHIFTED: Final = "captain_bonus_removed_unshifted"
ARMS: Final = (FULL, ABLATED, FULL_UNSHIFTED, ABLATED_UNSHIFTED)

CAPTAIN_CONCENTRATED: Final = "captain_component_concentrated"
SHARED_TAIL_FAILURE: Final = "shared_tail_failure"
INCONCLUSIVE: Final = "inconclusive"

#: The identity check's tolerance. The decomposition is exact in real arithmetic; this
#: only absorbs the last bits of a float sum.
DECOMPOSITION_TOLERANCE: Final = 1e-9


@dataclass(frozen=True, slots=True)
class CaptainReading:
    """One fold, read as a full squad and again without the captain's second copy."""

    fold_id: str
    season: str
    pit: Mapping[str, float]
    below_lower_quantile: Mapping[str, bool]
    captain_scenario_mean_bonus: float
    captain_realized_bonus: float
    full_scenario_mean_score: float
    full_realized_score: float
    ablated_scenario_mean_score: float
    ablated_realized_score: float
    decomposition_holds: bool

    @property
    def captain_bonus_error(self) -> float:
        """What the captain's second copy returned, against what it promised."""

        return self.captain_realized_bonus - self.captain_scenario_mean_bonus

    @property
    def full_score_error(self) -> float:
        """Mechanically contains the captain's error twice: as starter and as bonus."""

        return self.full_realized_score - self.full_scenario_mean_score

    @property
    def ablated_score_error(self) -> float:
        """The same error with the captain present only as a starter."""

        return self.ablated_realized_score - self.ablated_scenario_mean_score


def _pit(scores: np.ndarray, realized: float) -> float:
    """The evaluator's own reading: the fraction of scenarios at or below the outcome."""

    return float((scores <= realized).mean())


def _below(scores: np.ndarray, realized: float, quantile: float) -> bool:
    """The evaluator's own quantile rule, and its own strict comparison."""

    return bool(realized < float(np.quantile(scores, quantile, method="linear")))


def read_fold(
    fold: SquadFold,
    residuals: pd.DataFrame,
    history_fold_ids: Sequence[str],
    provenance: PredictionProvenance,
    config: SquadShadowConfig,
) -> CaptainReading:
    """Score one fold four ways from one decision and one scenario matrix."""

    _require(
        config.dispersion_scale == CONTROL_SCALE,
        "the captain ablation is defined only at the pre-registered dispersion of "
        f"{CONTROL_SCALE}; at any other value the evaluated scores are not the raw scores "
        "plus a constant and the second copy is not separable from them.",
    )
    decision = optimize_squad_once(fold, config)
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

    captain = decision.captain
    _require(captain is not None, f"{fold.fold_id}: the decision names no captain.")
    assert captain is not None
    captain_id = captain["player_id"]
    _require(
        captain_id in set(scenarios.scenario_points.columns),
        f"{fold.fold_id}: the scenario matrix carries no column for the captain.",
    )
    captain_scenario = scenarios.scenario_points[captain_id].to_numpy(dtype="float64")

    realized_row = fold.realized_points.loc[
        fold.realized_points["player_id"] == captain_id, "total_points"
    ]
    _require(
        not realized_row.empty,
        f"{fold.fold_id}: the fold reports no realized points for its captain; a missing "
        "bonus is refused, never read as zero.",
    )
    captain_realized = float(realized_row.iloc[0])
    _require(
        math.isfinite(captain_realized),
        f"{fold.fold_id}: a non-finite captain bonus cannot enter an attribution.",
    )

    full_scores = np.asarray(evaluated.scenario_scores, dtype="float64")
    ablated_scores = full_scores - captain_scenario
    full_realized = score_realized_squad_points(decision, fold.realized_points)
    ablated_realized = full_realized - captain_realized
    pairs: dict[str, tuple[np.ndarray, float]] = {
        FULL: (full_scores, full_realized),
        ABLATED: (ablated_scores, ablated_realized),
        FULL_UNSHIFTED: (full_scores - FROZEN_SHIFT_POINTS, full_realized),
        ABLATED_UNSHIFTED: (ablated_scores - FROZEN_SHIFT_POINTS, ablated_realized),
    }

    holds = _decomposition_holds(
        fold,
        decision,
        scenarios,
        evaluated,
        config,
        captain_id=captain_id,
        full_scores=full_scores,
        ablated_scores=ablated_scores,
        ablated_realized=ablated_realized,
    )
    return CaptainReading(
        fold_id=fold.fold_id,
        season=fold.season,
        pit={name: _pit(scores, realized) for name, (scores, realized) in pairs.items()},
        below_lower_quantile={
            name: _below(scores, realized, config.lower_quantile)
            for name, (scores, realized) in pairs.items()
        },
        captain_scenario_mean_bonus=float(captain_scenario.mean()),
        captain_realized_bonus=captain_realized,
        full_scenario_mean_score=float(evaluated.metrics.mean_score),
        full_realized_score=full_realized,
        ablated_scenario_mean_score=float(ablated_scores.mean()),
        ablated_realized_score=ablated_realized,
        decomposition_holds=holds,
    )


def _decomposition_holds(
    fold: SquadFold,
    decision: OptimizationResult,
    scenarios: ScenarioSet,
    evaluated: ScenarioEvaluationResult,
    config: SquadShadowConfig,
    *,
    captain_id: int,
    full_scores: np.ndarray,
    ablated_scores: np.ndarray,
    ablated_realized: float,
) -> bool:
    """Does the ablated score really equal the squad without the captain's second copy?

    Checked against the canonical scenario matrix and the fold's own realized frame,
    not against the arrays this module just built from each other. Re-summing the
    starting XI here is a check on the decomposition, never the source of a reported
    number: every number the study publishes comes from the canonical evaluator.

    The captain must be a member of the starting XI. Without that, removing "his second
    copy" would be removing him, and the whole framing would be a different study.
    """

    starters = [int(player_id) for player_id in decision.starting_xi["player_id"]]
    if int(captain_id) not in starters:
        return False

    matrix = scenarios.scenario_points
    starter_scenario = matrix[starters].to_numpy(dtype="float64").sum(axis=1)
    realized = dict(
        zip(
            fold.realized_points["player_id"].tolist(),
            fold.realized_points["total_points"].tolist(),
            strict=True,
        )
    )
    if any(player_id not in realized for player_id in starters):
        return False
    starter_realized = float(sum(float(realized[player_id]) for player_id in starters))

    metrics = evaluated.metrics
    return bool(
        float(np.abs(ablated_scores - (starter_scenario + FROZEN_SHIFT_POINTS)).max())
        <= DECOMPOSITION_TOLERANCE
        and abs(ablated_realized - starter_realized) <= DECOMPOSITION_TOLERANCE
        # And the study's own readers reproduce the evaluator's, so the full arm is the
        # canonical measurement rather than a second implementation of it.
        and abs(
            float(np.quantile(full_scores, config.lower_quantile, method="linear"))
            - float(metrics.lower_quantile_score)
        )
        <= DECOMPOSITION_TOLERANCE
        and abs(float(full_scores.mean()) - float(metrics.mean_score)) <= DECOMPOSITION_TOLERANCE
    )


def _gates(pit: Sequence[float], below: Sequence[bool]) -> dict[str, float | bool]:
    """One arm's S1 and S2, read exactly as the Phase 2 protocol reads them."""

    _require(bool(pit), "a summary needs at least one fold.")
    mean_pit = float(np.mean(pit))
    events = int(sum(1 for flag in below if flag))
    rate = events / len(below)
    return {
        "fold_count": float(len(pit)),
        "mean_probability_integral_transform": mean_pit,
        "below_lower_quantile_folds": float(events),
        "below_lower_quantile_rate": rate,
        "s1_within_band": bool(
            S1_PIT_BOUNDS[0] - BOUND_TOLERANCE <= mean_pit <= S1_PIT_BOUNDS[1] + BOUND_TOLERANCE
        ),
        "s2_within_band": bool(
            S2_TAIL_BOUNDS[0] - BOUND_TOLERANCE <= rate <= S2_TAIL_BOUNDS[1] + BOUND_TOLERANCE
        ),
        "s2_fails_above_band": bool(rate > S2_TAIL_BOUNDS[1] + BOUND_TOLERANCE),
    }


def summarise(readings: Sequence[CaptainReading]) -> dict[str, dict[str, float | bool]]:
    """The four arms: two distributions, each under two location conventions."""

    return {
        arm: _gates(
            [reading.pit[arm] for reading in readings],
            [reading.below_lower_quantile[arm] for reading in readings],
        )
        for arm in ARMS
    }


def captain_component(readings: Sequence[CaptainReading]) -> dict[str, object]:
    """What the captain's second copy promised, and what it returned."""

    _require(bool(readings), "the captain component needs at least one fold.")
    errors = np.asarray([reading.captain_bonus_error for reading in readings], dtype="float64")
    full_errors = np.asarray([reading.full_score_error for reading in readings], dtype="float64")
    ablated_errors = np.asarray(
        [reading.ablated_score_error for reading in readings], dtype="float64"
    )

    def correlation(against: np.ndarray) -> float | None:
        if errors.std() <= 0.0 or against.std() <= 0.0:
            return None
        return float(np.corrcoef(errors, against)[0, 1])

    def group(selected: Sequence[CaptainReading]) -> dict[str, float | None]:
        values = [entry.captain_bonus_error for entry in selected]
        return {
            "fold_count": float(len(values)),
            "mean": float(np.mean(values)) if values else None,
            "median": float(np.median(values)) if values else None,
        }

    return {
        "fold_count": len(readings),
        "mean_scenario_bonus": float(
            np.mean([reading.captain_scenario_mean_bonus for reading in readings])
        ),
        "mean_realized_bonus": float(
            np.mean([reading.captain_realized_bonus for reading in readings])
        ),
        "mean_bonus_error": float(errors.mean()),
        "negative_bonus_error_folds": int((errors < 0.0).sum()),
        # The full-score error contains the captain's error twice — as starter and as
        # bonus — so this is partly an autocorrelation and is not evidence on its own.
        # The ablated error contains him only as a starter.
        "pearson_correlation_with_full_score_error": correlation(full_errors),
        "pearson_correlation_with_captain_bonus_removed_score_error": correlation(ablated_errors),
        "on_full_score_tail_failures": group(
            [reading for reading in readings if reading.below_lower_quantile[FULL]]
        ),
        "elsewhere": group(
            [reading for reading in readings if not reading.below_lower_quantile[FULL]]
        ),
        "decomposition_holds_folds": int(
            sum(1 for reading in readings if reading.decomposition_holds)
        ),
    }


def classify(arms: Mapping[str, Mapping[str, float | bool]]) -> tuple[str, tuple[str, ...]]:
    """One of three words, from the existing S2 band and nothing invented.

    The companion convention is a veto rather than a second opinion: when the two
    location conventions disagree about the ablated arm, this study will not claim a
    localization that depends on which one was chosen.
    """

    if not arms[FULL]["s2_fails_above_band"]:
        return INCONCLUSIVE, (
            "the full-squad S2 does not fail above the upper bound on this population, so "
            "there is no failure here to attribute.",
        )
    primary = _tail_position(arms[ABLATED])
    companion = _tail_position(arms[ABLATED_UNSHIFTED])
    if primary != companion:
        return INCONCLUSIVE, (
            f"the frozen-shift convention puts the captain-bonus-removed S2 {primary} and "
            f"the unshifted convention puts it {companion}, so the reading would depend on "
            "a choice this study declared it would not make.",
        )
    if primary == "inside the band":
        return CAPTAIN_CONCENTRATED, ()
    if primary == "above the band":
        return SHARED_TAIL_FAILURE, ()
    return INCONCLUSIVE, (
        "the captain-bonus-removed S2 is below the floor rather than inside the band or "
        "above it, so the two arms do not separate the failure.",
    )


def _tail_position(gates: Mapping[str, float | bool]) -> str:
    """Where one arm's S2 sits: the three-state verdict the veto compares."""

    if gates["s2_within_band"]:
        return "inside the band"
    return "above the band" if gates["s2_fails_above_band"] else "below the floor"


def refuse_unexpected_folds(readings: Sequence[CaptainReading]) -> None:
    """No fold twice, and a decomposition that does not hold is not a decomposition."""

    identifiers = [reading.fold_id for reading in readings]
    _require(bool(identifiers), "the attribution needs at least one fold.")
    _require(
        len(set(identifiers)) == len(identifiers),
        "the population repeats a fold; an attribution counts distinct measurements.",
    )
    broken = [reading.fold_id for reading in readings if not reading.decomposition_holds]
    if broken:
        raise SquadShadowError(
            f"the decomposition identity does not hold on folds {broken[:5]!r}; the ablation "
            "is not a decomposition of the score it claims to decompose."
        )
