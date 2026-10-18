"""Proper scoring of the Phase C conditional predictive distributions, arm against arm.

The out-of-fold table carries one mean per conditional component; the v2 development export
writes beside it a distribution sidecar with what the mean hides (``DISTRIBUTION_COLUMNS`` in
:mod:`squadopt.prediction.component_models`): a single Gaussian for the linear control, a gated
two-expert mixture for the mixture candidate. This module scores those distributions on the
rows that appeared, as declared in ``docs/research/moe_mixture_prereg.md``:

* **log score** of the realized integer target under the discretised distribution,
  ``log(F(y + 0.5) - F(y - 0.5))`` with the probability floored, higher is better;
* **PIT** at the mid-point ``(F(y - 0.5) + F(y + 0.5)) / 2``, whose mean sits near 0.5 and
  whose tails (below 0.05, at or above 0.95) each hold near five per cent of the rows when the
  distribution is calibrated.

Both are computed per row, averaged per fold, and the per-fold mean log score of the candidate
minus the control's is the paired statistic the interval helper summarises. Nothing here enters
the points-MAE rule; it is the reading recorded beside it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import norm

from squadopt.evaluation import EvaluationValidationError
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.prediction.component_models import DISTRIBUTION_COLUMNS

SCORING_CONTRACT_VERSION: Final = "phase_c_component_distribution_scoring_v1"
KEY_COLUMNS: Final = ("season", "target_gameweek", "fold_id", "player_id")
COMPONENTS: Final = ("points", "minutes")
#: The discretised probability is floored before the log so one impossible row cannot sink a
#: fold's mean; the floor is a constant of the declaration.
PROBABILITY_FLOOR: Final = 1e-12
LOWER_TAIL: Final = 0.05
UPPER_TAIL: Final = 0.95
#: The paired-inference policy at its declared defaults, as the v2 comparison uses it.
POLICY: Final = PromotionPolicy(
    confidence_level=0.90, bootstrap_resamples=5000, moving_block_length=4, deterministic_seed=0
)


def _mixture_cdf(
    value: npt.NDArray[np.float64],
    *,
    gate: npt.NDArray[np.float64],
    mean_low: npt.NDArray[np.float64],
    mean_high: npt.NDArray[np.float64],
    scale_low: npt.NDArray[np.float64],
    scale_high: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """The CDF of ``gate N(high) + (1 - gate) N(low)`` at ``value``, row by row.

    A missing high slot (the single-Gaussian family) carries gate 0, so its term is dropped
    rather than evaluated on a missing mean.
    """

    low_cdf = np.asarray(norm.cdf((value - mean_low) / scale_low), dtype="float64")
    high_mean = np.where(np.isfinite(mean_high), mean_high, 0.0)
    high_scale = np.where(np.isfinite(scale_high) & (scale_high > 0), scale_high, 1.0)
    high_cdf = np.asarray(norm.cdf((value - high_mean) / high_scale), dtype="float64")
    weight = np.where(np.isfinite(gate), gate, 0.0)
    cdf: npt.NDArray[np.float64] = weight * high_cdf + (1.0 - weight) * low_cdf
    return cdf


def score_rows(sidecar: pd.DataFrame, *, component: str) -> pd.DataFrame:
    """Per-row discretised log score and mid-point PIT of ``<component>_target`` under the arm.

    ``sidecar`` carries the key columns, the sidecar columns and the realized target column
    ``<component>_target``. Returns the key columns with ``log_score`` and ``pit``.
    """

    if component not in COMPONENTS:
        raise EvaluationValidationError(f"Unknown component {component!r}.")
    target_column = f"{component}_target"
    needed = (*KEY_COLUMNS, target_column, *DISTRIBUTION_COLUMNS)
    missing = [column for column in needed if column not in sidecar.columns]
    if missing:
        raise EvaluationValidationError(f"Sidecar rows are missing columns {missing!r}.")
    target = pd.to_numeric(sidecar[target_column], errors="raise").to_numpy(dtype="float64")
    if not bool(np.isfinite(target).all()):
        raise EvaluationValidationError(f"Every scored row needs a realized {target_column}.")

    def column(name: str) -> npt.NDArray[np.float64]:
        return pd.to_numeric(sidecar[f"{component}_{name}"], errors="coerce").to_numpy(
            dtype="float64"
        )

    parameters = {
        "gate": column("gate"),
        "mean_low": column("mean_low"),
        "mean_high": column("mean_high"),
        "scale_low": column("scale_low"),
        "scale_high": column("scale_high"),
    }
    if not bool(np.isfinite(parameters["mean_low"]).all()) or bool(
        (parameters["scale_low"] <= 0).any()
    ):
        raise EvaluationValidationError("Every scored row needs a finite low mean and scale.")
    upper = _mixture_cdf(target + 0.5, **parameters)
    lower = _mixture_cdf(target - 0.5, **parameters)
    probability = np.clip(upper - lower, PROBABILITY_FLOOR, 1.0)
    scored = sidecar.loc[:, list(KEY_COLUMNS)].copy(deep=True)
    scored["log_score"] = np.log(probability)
    scored["pit"] = (upper + lower) / 2.0
    return scored


@dataclass(frozen=True, slots=True)
class ScoreSummary:
    """The pooled reading of one arm's distribution on one row set."""

    rows: int
    mean_log_score: float
    mean_pit: float
    lower_tail_rate: float
    upper_tail_rate: float

    def as_record(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "mean_log_score": self.mean_log_score,
            "mean_pit": self.mean_pit,
            "lower_tail_rate": self.lower_tail_rate,
            "upper_tail_rate": self.upper_tail_rate,
        }


def summarize(scored: pd.DataFrame) -> ScoreSummary:
    """Pool the per-row scores of one arm."""

    if scored.empty:
        raise EvaluationValidationError("No row to summarize.")
    pit = scored["pit"].to_numpy(dtype="float64")
    return ScoreSummary(
        rows=len(scored),
        mean_log_score=float(scored["log_score"].mean()),
        mean_pit=float(pit.mean()),
        lower_tail_rate=float((pit < LOWER_TAIL).mean()),
        upper_tail_rate=float((pit >= UPPER_TAIL).mean()),
    )


@dataclass(frozen=True, slots=True)
class PairedSeasonReading:
    """The paired per-fold log-score difference (candidate minus control) in one season."""

    season: str
    folds: int
    mean_difference: float
    interval_low: float
    interval_high: float
    wins: int
    ties: int
    losses: int

    def as_record(self) -> dict[str, object]:
        return {
            "season": self.season,
            "folds": self.folds,
            "mean_difference": self.mean_difference,
            "interval_low": self.interval_low,
            "interval_high": self.interval_high,
            "wins": self.wins,
            "ties": self.ties,
            "losses": self.losses,
        }


def paired_fold_reading(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    season: str,
    candidate_id: str,
    policy: PromotionPolicy = POLICY,
) -> PairedSeasonReading:
    """Per-fold mean log score, candidate minus control, with the season-aware interval."""

    control_folds = control.loc[control["season"].astype("string") == season]
    candidate_folds = candidate.loc[candidate["season"].astype("string") == season]
    control_mean = control_folds.groupby("fold_id", sort=True)["log_score"].mean()
    candidate_mean = candidate_folds.groupby("fold_id", sort=True)["log_score"].mean()
    if not control_mean.index.equals(candidate_mean.index):
        raise EvaluationValidationError(
            f"The two arms score different folds in {season}; this is not one paired reading."
        )
    if control_mean.empty:
        raise EvaluationValidationError(f"No scored fold in {season}.")
    differences = [
        (season, float(candidate_mean.loc[fold] - control_mean.loc[fold]))
        for fold in control_mean.index
    ]
    low, high = season_aware_moving_block_interval(
        differences, policy=policy, candidate_id=candidate_id
    )
    values = [value for _, value in differences]
    return PairedSeasonReading(
        season=season,
        folds=len(values),
        mean_difference=statistics.fmean(values),
        interval_low=float(low),
        interval_high=float(high),
        wins=sum(value > 0 for value in values),
        ties=sum(value == 0 for value in values),
        losses=sum(value < 0 for value in values),
    )


def declared_reading(primary: PairedSeasonReading, control_era: PairedSeasonReading) -> str:
    """The pre-registered reading: sharper, worse or undecided."""

    if primary.interval_low > 0 and control_era.interval_high >= 0:
        return "sharper"
    if primary.interval_high < 0:
        return "worse"
    return "undecided"


def score_arms(
    control: pd.DataFrame,
    candidate: pd.DataFrame,
    *,
    primary_season: str,
    control_era_season: str,
    candidate_id: str,
    policy: PromotionPolicy = POLICY,
) -> dict[str, object]:
    """The whole reading for two joined sidecars carrying the realized targets.

    Both frames carry the key columns, the sidecar columns and ``points_target`` and
    ``minutes_target``; they must hold the same keys, which is what makes the reading paired.
    """

    for frame, name in ((control, "control"), (candidate, "candidate")):
        if frame.empty:
            raise EvaluationValidationError(f"The {name} arm has no row to score.")
    control_keys = control.loc[:, list(KEY_COLUMNS)].sort_values(list(KEY_COLUMNS))
    candidate_keys = candidate.loc[:, list(KEY_COLUMNS)].sort_values(list(KEY_COLUMNS))
    if not control_keys.reset_index(drop=True).equals(candidate_keys.reset_index(drop=True)):
        raise EvaluationValidationError("The two arms do not score the same rows.")

    report: dict[str, object] = {
        "contract_version": SCORING_CONTRACT_VERSION,
        "rows": len(control),
        "probability_floor": PROBABILITY_FLOOR,
        "tails": {"lower_below": LOWER_TAIL, "upper_at_or_above": UPPER_TAIL},
        "components": {},
    }
    components: dict[str, object] = {}
    for component in COMPONENTS:
        control_scores = score_rows(control, component=component)
        candidate_scores = score_rows(candidate, component=component)
        seasons = sorted(set(control["season"].astype("string")))
        by_season: dict[str, Mapping[str, object]] = {}
        for season in seasons:
            mask_control = control_scores["season"].astype("string") == season
            mask_candidate = candidate_scores["season"].astype("string") == season
            by_season[season] = {
                "control": summarize(control_scores.loc[mask_control]).as_record(),
                "candidate": summarize(candidate_scores.loc[mask_candidate]).as_record(),
            }
        primary = paired_fold_reading(
            control_scores,
            candidate_scores,
            season=primary_season,
            candidate_id=f"{candidate_id}_{component}",
            policy=policy,
        )
        control_era = paired_fold_reading(
            control_scores,
            candidate_scores,
            season=control_era_season,
            candidate_id=f"{candidate_id}_{component}",
            policy=policy,
        )
        components[component] = {
            "pooled": {
                "control": summarize(control_scores).as_record(),
                "candidate": summarize(candidate_scores).as_record(),
            },
            "by_season": by_season,
            "primary_season": primary.as_record(),
            "control_era_season": control_era.as_record(),
            "reading": declared_reading(primary, control_era),
        }
    report["components"] = components
    return report


def render_markdown(
    report: Mapping[str, object], *, title: str, lines_before: Sequence[str]
) -> str:
    """A short readout of :func:`score_arms`, every number taken from the report."""

    components = report["components"]
    if not isinstance(components, Mapping):
        raise EvaluationValidationError("report['components'] must be a mapping.")
    lines = [f"# {title}", "", *lines_before, ""]
    for component, block in components.items():
        if not isinstance(block, Mapping):
            raise EvaluationValidationError("Each component block must be a mapping.")
        primary = block["primary_season"]
        control_era = block["control_era_season"]
        if not isinstance(primary, Mapping) or not isinstance(control_era, Mapping):
            raise EvaluationValidationError("Season readings must be mappings.")
        lines += [
            f"## {component} given an appearance: reading `{block['reading']}`",
            "",
            f"Per-fold mean log score, candidate minus control: {primary['season']} mean "
            f"{float(primary['mean_difference']):+.5f}, 90% interval "
            f"[{float(primary['interval_low']):+.5f}, {float(primary['interval_high']):+.5f}], "
            f"wins / ties / losses {primary['wins']} / {primary['ties']} / {primary['losses']} "
            f"({primary['folds']} folds); {control_era['season']} mean "
            f"{float(control_era['mean_difference']):+.5f}, interval "
            f"[{float(control_era['interval_low']):+.5f}, "
            f"{float(control_era['interval_high']):+.5f}], "
            f"{control_era['wins']} / {control_era['ties']} / {control_era['losses']}.",
            "",
            "| season | rows | log score (control) | candidate | mean PIT (control) | candidate "
            "| lower tail (control) | candidate | upper tail (control) | candidate |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        pooled = block["pooled"]
        by_season = block["by_season"]
        if not isinstance(pooled, Mapping) or not isinstance(by_season, Mapping):
            raise EvaluationValidationError("Pooled and by-season blocks must be mappings.")
        for season, pair in (("pooled", pooled), *sorted(by_season.items())):
            if not isinstance(pair, Mapping):
                raise EvaluationValidationError("A season pair must be a mapping.")
            control = pair["control"]
            candidate = pair["candidate"]
            if not isinstance(control, Mapping) or not isinstance(candidate, Mapping):
                raise EvaluationValidationError("Arm summaries must be mappings.")
            lines.append(
                f"| {season} | {control['rows']} | {float(control['mean_log_score']):.5f} | "
                f"{float(candidate['mean_log_score']):.5f} | {float(control['mean_pit']):.4f} | "
                f"{float(candidate['mean_pit']):.4f} | {float(control['lower_tail_rate']):.4f} | "
                f"{float(candidate['lower_tail_rate']):.4f} | "
                f"{float(control['upper_tail_rate']):.4f} | "
                f"{float(candidate['upper_tail_rate']):.4f} |"
            )
        lines.append("")
    return "\n".join(lines)


def log_density_sanity(value: float, mean: float, scale: float) -> float:
    """The discretised single-Gaussian probability at ``value``, for tests and hand checks."""

    if scale <= 0 or not math.isfinite(scale):
        raise EvaluationValidationError("scale must be a positive finite number.")
    upper = float(norm.cdf((value + 0.5 - mean) / scale))
    lower = float(norm.cdf((value - 0.5 - mean) / scale))
    return max(upper - lower, PROBABILITY_FLOOR)
