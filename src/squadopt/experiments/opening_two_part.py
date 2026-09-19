"""The two-part opening projection, as ``docs/opening_two_part_prereg.md`` fixed it.

The protocol was written on 2026-08-26 and committed before anything here was fitted. Every
choice below is its choice: the population, both parts, the fitters, the three clauses of the
gate and the tolerance in the restated ordering clause. Nothing in this module decides anything
the document left open, and nothing in it may be changed to make a number come out.

The shape::

    expected points = P(plays | ownership, price, position) x E[points | plays, price, position]

The predecessor (``opening_newcomer_study``) fitted one additive price line over every newcomer,
two thirds of whom never appear, so the slope was flattened by rows that scored nothing and
ownership then fixed the level while breaking the order. Here the two questions are separated:
the first factor prices whether he plays, the second prices how well he does when he does.

**What the first factor's label is, and is not.** Its target is ``minutes > 0`` at the opening
gameweek, which is a **play** label. It is not an availability label: the archive carries no
``status``, ``news`` or ``chance_of_playing`` at gameweek one, so no availability label exists to
fit. A gate cleared here says the product orders and levels the opening prior better; it says
nothing about whether the factor has learned who was available.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from squadopt.experiments.opening_newcomers import (
    POSITIONS,
    OpeningStudyConfig,
    _fit_through_origin,
    _paired_bootstrap,
    _rank_correlation,
    control_prediction,
)
from squadopt.experiments.team_rating import _fit_logistic

OPENING_TWO_PART_CONTRACT_VERSION: Final = "opening_two_part_v1"

#: The design of part one, in the protocol's order: an intercept, ownership, price, and the
#: four positions as indicators with ``GK`` as the reference level.
PART_ONE_DESIGN: Final[tuple[str, ...]] = (
    "intercept",
    "ownership_share",
    "price_m",
    "DEF",
    "MID",
    "FWD",
)
#: The restated ordering clause's tolerance. Chosen in the protocol on the predecessor's own
#: committed measurements, and fixed there: identical ordering differed by under 0.001, and the
#: candidates that genuinely worsened it did so by at least 0.032.
ORDERING_TOLERANCE: Final = 0.010
#: How many deciles the reported calibration of part one uses.
CALIBRATION_DECILES: Final = 10


@dataclass(frozen=True, slots=True)
class TwoPartCoefficients:
    """What one walk-forward fit produced, both parts together."""

    part_one: tuple[float, ...]
    """The logistic's coefficients, in ``PART_ONE_DESIGN`` order."""
    part_two: tuple[tuple[str, float], ...]
    """Per position, the through-origin slope on price, fitted on played rows only. A position
    with no played training row has no slope and is absent rather than zero."""

    def slope(self, position: str) -> float | None:
        for name, value in self.part_two:
            if name == position:
                return value
        return None

    def as_record(self) -> dict[str, object]:
        return {
            "part_one": dict(zip(PART_ONE_DESIGN, self.part_one, strict=True)),
            "part_two_price_slope_by_position": dict(self.part_two),
        }


def part_one_design(rows: pd.DataFrame) -> np.ndarray:
    """The design matrix of part one, with ``GK`` as the reference level."""

    position = rows["position"].astype(str)
    return np.column_stack(
        [
            np.ones(len(rows), dtype="float64"),
            rows["ownership_share"].to_numpy(dtype="float64"),
            rows["price_m"].to_numpy(dtype="float64"),
            (position == "DEF").to_numpy(dtype="float64"),
            (position == "MID").to_numpy(dtype="float64"),
            (position == "FWD").to_numpy(dtype="float64"),
        ]
    )


def played(rows: pd.DataFrame) -> np.ndarray:
    """The protocol's target for part one: he took the field at the opening gameweek."""

    return (rows["minutes"].to_numpy(dtype="float64") > 0.0).astype("float64")


def fit_two_part(training: pd.DataFrame) -> TwoPartCoefficients:
    """Fit both parts on rows from strictly earlier seasons.

    Part one is the protocol's logistic over every training row. Part two is the predecessor's
    least squares through the origin on price, per position, **fitted on played rows only**:
    that restriction is the whole structural difference from the candidate that failed, which
    absorbed the two thirds who never appear into one slope.
    """

    theta = _fit_logistic(part_one_design(training), played(training))
    slopes: list[tuple[str, float]] = []
    for position in POSITIONS:
        block = training.loc[
            (training["position"].astype(str) == position) & (training["minutes"] > 0)
        ]
        if block.empty:
            continue
        design = block["price_m"].to_numpy(dtype="float64").reshape(-1, 1)
        target = block["total_points"].to_numpy(dtype="float64")
        slopes.append((position, float(_fit_through_origin(design, target)[0])))
    return TwoPartCoefficients(
        part_one=tuple(float(value) for value in theta), part_two=tuple(slopes)
    )


def play_probability(rows: pd.DataFrame, coefficients: TwoPartCoefficients) -> np.ndarray:
    """Part one alone, which the record reports the calibration of and does not gate."""

    linear = part_one_design(rows) @ np.asarray(coefficients.part_one, dtype="float64")
    return np.asarray(1.0 / (1.0 + np.exp(-np.clip(linear, -30.0, 30.0))), dtype="float64")


def predict_two_part(rows: pd.DataFrame, coefficients: TwoPartCoefficients) -> np.ndarray:
    """The product, clipped at zero as the shipped prior is.

    A position the training rows never played has no slope, so it has no second factor and
    predicts nothing rather than predicting zero; with the archive's four positions always
    present in a season this does not arise, and it is written this way so that it could not
    pass silently if it did.
    """

    probability = play_probability(rows, coefficients)
    price = rows["price_m"].to_numpy(dtype="float64")
    position = rows["position"].astype(str).to_numpy()
    rate = np.array([coefficients.slope(str(name)) or 0.0 for name in position], dtype="float64")
    return np.asarray(np.clip(probability * price * rate, 0.0, None), dtype="float64")


@dataclass(frozen=True, slots=True)
class SeasonReading:
    """One judged season, for the two clauses that are read per season."""

    season: str
    rows: int
    training_rows: int
    rows_without_published_ownership: int
    control_mae: float
    candidate_mae: float
    control_rank: float
    candidate_rank: float
    played_rows: int
    candidate_bias_on_played: float
    candidate_mae_on_played: float
    calibration: tuple[dict[str, object], ...]
    coefficients: dict[str, object]

    @property
    def mae_improvement(self) -> float:
        return self.control_mae - self.candidate_mae

    @property
    def rank_shortfall(self) -> float:
        """How far the candidate's ordering falls below the control's; negative is better."""

        return self.control_rank - self.candidate_rank


def calibration_by_decile(
    probability: np.ndarray, outcome: np.ndarray, *, deciles: int = CALIBRATION_DECILES
) -> tuple[dict[str, object], ...]:
    """Predicted against realized play rate, by decile of the predicted probability.

    Reported and not gated, because a first factor that orders well and is systematically
    over-confident leaves the product's level wrong for a reason the accuracy clause alone
    would not name.
    """

    if probability.size == 0:
        return ()
    order = np.argsort(probability, kind="stable")
    buckets = np.array_split(order, min(deciles, probability.size))
    readings: list[dict[str, object]] = []
    for index, bucket in enumerate(buckets, start=1):
        if bucket.size == 0:
            continue
        readings.append(
            {
                "decile": index,
                "rows": int(bucket.size),
                "mean_predicted": float(probability[bucket].mean()),
                "realized_play_rate": float(outcome[bucket].mean()),
            }
        )
    return tuple(readings)


def evaluate_two_part(
    rows: pd.DataFrame, config: OpeningStudyConfig
) -> tuple[tuple[SeasonReading, ...], dict[str, object]]:
    """Walk forward over the judged seasons and read the two clauses that are read per row."""

    newcomers = rows.loc[~rows["has_prior_record"]]
    readings: list[SeasonReading] = []
    differences: list[float] = []
    for season in config.evaluated_seasons:
        training = newcomers.loc[newcomers["season"] < season]
        block = newcomers.loc[newcomers["season"] == season]
        if len(training) < config.minimum_training_rows or block.empty:
            continue
        coefficients = fit_two_part(training)
        candidate = predict_two_part(block, coefficients)
        control = control_prediction(block)
        realized = block["total_points"].to_numpy(dtype="float64")
        control_errors = np.abs(control - realized)
        candidate_errors = np.abs(candidate - realized)
        differences.extend((control_errors - candidate_errors).tolist())
        appeared = block["minutes"].to_numpy(dtype="float64") > 0.0
        readings.append(
            SeasonReading(
                season=season,
                rows=len(block),
                training_rows=len(training),
                rows_without_published_ownership=int(
                    (block["ownership_share"].to_numpy(dtype="float64") == 0.0).sum()
                ),
                control_mae=float(control_errors.mean()),
                candidate_mae=float(candidate_errors.mean()),
                control_rank=_rank_correlation(block, control),
                candidate_rank=_rank_correlation(block, candidate),
                played_rows=int(appeared.sum()),
                candidate_bias_on_played=(
                    float((realized[appeared] - candidate[appeared]).mean())
                    if appeared.any()
                    else 0.0
                ),
                candidate_mae_on_played=(
                    float(candidate_errors[appeared].mean()) if appeared.any() else 0.0
                ),
                calibration=calibration_by_decile(
                    play_probability(block, coefficients), appeared.astype("float64")
                ),
                coefficients=coefficients.as_record(),
            )
        )
    pooled = np.asarray(differences, dtype="float64")
    low, high = _paired_bootstrap(
        pooled, resamples=config.bootstrap_resamples, seed=config.deterministic_seed
    )
    pooled_rows = newcomers.loc[newcomers["season"].isin([r.season for r in readings])]
    summary = {
        "pooled_rows": int(pooled.size),
        "pooled_mae_improvement": float(pooled.mean()) if pooled.size else 0.0,
        "interval_90": [low, high],
        "interval_excludes_zero": bool(low > 0.0),
        "improves_every_season": all(r.mae_improvement > 0.0 for r in readings),
        "pooled_control_rank": _rank_correlation(pooled_rows, control_prediction(pooled_rows)),
    }
    return tuple(readings), summary


def two_part_gate(
    readings: tuple[SeasonReading, ...],
    summary: dict[str, object],
    pooled_rank_shortfall: float,
    decision_differences: tuple[float, ...],
) -> dict[str, object]:
    """The three clauses, exactly as the protocol fixed them, applied by code.

    Clause 2 is the restated one. The predecessor failed a candidate for ordering *identical*
    to the control, which is not a worsening; the protocol restates it as a tolerance and
    fixes the number at 0.010 before any of this ran.
    """

    accuracy = bool(summary["improves_every_season"] and summary["interval_excludes_zero"])
    per_season = all(r.rank_shortfall <= ORDERING_TOLERANCE for r in readings)
    ordering = bool(per_season and pooled_rank_shortfall <= ORDERING_TOLERANCE)
    losses = sum(1 for value in decision_differences if value < 0.0)
    mean_difference = float(np.mean(decision_differences)) if decision_differences else 0.0
    decision = bool(decision_differences) and mean_difference >= 0.0 and losses <= 1
    return {
        "accuracy_passes": accuracy,
        "ordering_passes": ordering,
        "ordering_tolerance": ORDERING_TOLERANCE,
        "worst_season_rank_shortfall": (
            max(r.rank_shortfall for r in readings) if readings else 0.0
        ),
        "pooled_rank_shortfall": pooled_rank_shortfall,
        "decision_passes": decision,
        "mean_decision_difference": mean_difference,
        "decision_losses": losses,
        "passes": bool(accuracy and ordering and decision),
    }


__all__ = [
    "CALIBRATION_DECILES",
    "OPENING_TWO_PART_CONTRACT_VERSION",
    "ORDERING_TOLERANCE",
    "PART_ONE_DESIGN",
    "SeasonReading",
    "TwoPartCoefficients",
    "calibration_by_decile",
    "evaluate_two_part",
    "fit_two_part",
    "part_one_design",
    "play_probability",
    "played",
    "predict_two_part",
    "two_part_gate",
]
