"""A learned scoring rate, fitted only on history the decision point can see.

This is the single component Issue #43 changes: ``expected_points_rate``. Everything
around it stays as measured — the expected-minutes stage, the cold-start ladder, the
two-stage product, the availability rule, the feature windows, and the opening-price
prior.

What changes, precisely: the current stage reads the shifted rolling points-per-90
feature and uses it as the rate. This stage keeps that feature as an input and learns a
rate from it together with the calendar and appearance signals the declaration permits —
fixture count, home fixture count, appearance rate, and minutes per appearance.

Three properties are deliberate.

**The ladder shape does not move.** The learned rate replaces only the value on the
in-season rung. A row without in-season history still falls to the shrunk carry-over
rung, and a row with neither still returns missing rather than a fabricated rate, for
the same reason as before: a price prior estimates points, not a rate, and inventing one
would put a made-up number inside a product.

**A row is scored only where every declared input is present.** Imputing a missing input
would let the model answer confidently from a value nobody measured, and it would also
quietly move the ladder — a row that used to fall through would now be scored.

**The fit is closed-form ridge on standardised inputs, solved with numpy.** There is no
randomness, no iteration count, and no solver choice to drift between environments. That
matters here more than usual: the benchmark's Ridge reference already showed that a
number which moves with the numerical environment makes a gate threshold move with it.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.features.config import (
    MINUTES_PER_FULL_MATCH,
    minutes_per_appearance_feature_name,
    per_90_feature_name,
    rolling_feature_name,
)
from squadopt.prediction.config import PredictionConfigurationError

LEARNED_RATE_MODEL_NAME: Final = "squadopt-learned-rate"
LEARNED_RATE_MODEL_VERSION: Final = "learned-rate-v2"
LEARNED_RATE_FEATURE_CONTRACT_VERSION: Final = "learned-rate-calendar-appearance-v1"
LEARNED_RATE_TRAINING_CONTRACT_VERSION: Final = "expanding_window_minutes_weighted_ridge_rate_v1"

# Calendar inputs the declaration permits. Named here rather than derived, because the
# declaration names an exact list and a silently widened one is a different candidate.
CALENDAR_INPUT_COLUMNS: Final = ("fixture_count", "home_fixture_count")

RATE_FROM_LEARNED_MODEL: Final = "learned_model"


def rate_input_columns(window: int) -> tuple[str, ...]:
    """Return the declared learned-rate inputs for one frozen feature window."""

    return (
        per_90_feature_name(window),
        rolling_feature_name("appeared", window),
        minutes_per_appearance_feature_name(window),
        *CALENDAR_INPUT_COLUMNS,
    )


@dataclass(frozen=True, slots=True)
class LearnedRateConfig:
    """Controls for the learned rate stage.

    ``window`` must equal the projection's rate window, so the model reads the same
    frozen feature the stage it replaces read.
    """

    window: int = 6
    ridge_alpha: float = 1.0
    min_training_rows: int = 500

    def __post_init__(self) -> None:
        for name in ("window", "min_training_rows"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
                raise PredictionConfigurationError(f"{name} must be a positive integer.")
            object.__setattr__(self, name, int(value))
        alpha = self.ridge_alpha
        if isinstance(alpha, bool) or not isinstance(alpha, Real):
            raise PredictionConfigurationError("ridge_alpha must be a finite number.")
        alpha = float(alpha)
        if not math.isfinite(alpha) or alpha <= 0.0:
            raise PredictionConfigurationError("ridge_alpha must be finite and positive.")
        object.__setattr__(self, "ridge_alpha", alpha)

    @property
    def input_columns(self) -> tuple[str, ...]:
        """Return the declared inputs this configuration reads."""

        return rate_input_columns(self.window)


@dataclass(frozen=True, slots=True)
class LearnedRateModel:
    """One fitted rate model and the identity of the history that produced it."""

    input_columns: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    training_rows: int
    ridge_alpha: float
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        width = len(self.input_columns)
        if width == 0:
            raise PredictionConfigurationError("input_columns must be non-empty.")
        for name in ("means", "scales", "coefficients"):
            values = getattr(self, name)
            if len(values) != width:
                raise PredictionConfigurationError(f"{name} must carry one value per input column.")
        if any(scale <= 0.0 for scale in self.scales):
            raise PredictionConfigurationError("scales must be positive.")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def model_fingerprint(self) -> str:
        """Fingerprint the fitted state, so two folds' models are distinguishable."""

        payload = {
            "input_columns": list(self.input_columns),
            "means": [float(value) for value in self.means],
            "scales": [float(value) for value in self.scales],
            "coefficients": [float(value) for value in self.coefficients],
            "intercept": float(self.intercept),
            "ridge_alpha": float(self.ridge_alpha),
            "training_rows": int(self.training_rows),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def predict(self, inputs: pd.DataFrame) -> pd.Series:
        """Return the modelled rate for rows carrying every declared input."""

        matrix = _matrix(inputs, self.input_columns)
        standardised = (matrix - np.asarray(self.means)) / np.asarray(self.scales)
        predicted = standardised @ np.asarray(self.coefficients) + float(self.intercept)
        return pd.Series(predicted, index=inputs.index, dtype="float64")


def _matrix(frame: pd.DataFrame, columns: Sequence[str]) -> np.ndarray:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise PredictionConfigurationError(
            f"The learned rate stage requires columns {missing!r}, which the feature "
            "dataset does not carry."
        )
    values = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    matrix: np.ndarray = np.asarray(values.to_numpy(), dtype="float64")
    return matrix


def realized_points_per_90(frame: pd.DataFrame) -> pd.Series:
    """Return each row's own realized scoring rate, missing where nobody played.

    A rate is undefined without minutes, and filling those rows with zero would teach
    the model that not playing means scoring at zero per 90 — which is a statement
    about selection, not about scoring. Whether a player features is the expected
    minutes stage's question, and it stays there.
    """

    for column in ("minutes", "total_points"):
        if column not in frame.columns:
            raise PredictionConfigurationError(
                f"Training rows must carry {column!r} to derive a realized rate."
            )
    minutes = pd.to_numeric(frame["minutes"], errors="coerce").astype("float64")
    points = pd.to_numeric(frame["total_points"], errors="coerce").astype("float64")
    played = minutes.notna() & minutes.gt(0.0) & points.notna()
    rate = pd.Series(float("nan"), index=frame.index, dtype="float64")
    rate = rate.mask(played, points.div(minutes).mul(float(MINUTES_PER_FULL_MATCH)))
    return rate


def fit_learned_rate(
    training: pd.DataFrame,
    *,
    config: LearnedRateConfig | None = None,
) -> LearnedRateModel:
    """Fit the rate model on rows visible before a decision point.

    ``training`` must already be restricted to history the decision point can see.
    This function does not filter by time, because a filter here would be a second
    place where leakage could be got wrong; the caller holds that responsibility and
    the walk-forward contract already enforces it.

    **Rows are weighted by their minutes**, which is what makes the fitted quantity a
    rate at all. An unweighted fit treats a five-minute cameo and a full match as equal
    evidence about scoring per 90, and the cameo's denominator is tiny: measured on the
    development seasons, appearances under ten minutes average 44.0 points per 90 against
    3.4 for full matches, and 15% of rows fall under twenty minutes. That pulls the
    unweighted mean to 7.2 when the minutes-weighted rate is about 3.5, so an unweighted
    intercept alone over-predicts every player by roughly half a point once multiplied
    back by expected minutes.

    Weighting by minutes is not a robustness patch bolted on afterwards. It is the same
    quantity the frozen rolling feature computes — a ratio of sums, not a mean of
    ratios — so the learned rate and the feature it reads describe the same thing.
    """

    settings = LearnedRateConfig() if config is None else config
    if not isinstance(settings, LearnedRateConfig):
        raise PredictionConfigurationError("config must be a LearnedRateConfig.")
    if not isinstance(training, pd.DataFrame):
        raise PredictionConfigurationError("training must be a pandas DataFrame.")

    columns = settings.input_columns
    matrix = _matrix(training, columns)
    target = realized_points_per_90(training).to_numpy(dtype="float64")
    minutes = pd.to_numeric(training["minutes"], errors="coerce").to_numpy(dtype="float64")

    usable = (
        np.isfinite(matrix).all(axis=1)
        & np.isfinite(target)
        & np.isfinite(minutes)
        & (minutes > 0.0)
    )
    rows = int(usable.sum())
    if rows < settings.min_training_rows:
        raise PredictionConfigurationError(
            f"The learned rate stage needs at least {settings.min_training_rows} complete "
            f"training rows and found {rows}. A model fitted on less would be reported "
            "with the same confidence as one fitted on a season."
        )

    design = matrix[usable]
    outcome = target[usable]
    weights = minutes[usable]
    total_weight = float(weights.sum())

    means = (weights @ design) / total_weight
    centred = design - means
    scales = np.sqrt((weights @ np.square(centred)) / total_weight)
    # A constant input carries no information; scaling it by zero would divide by zero,
    # so it is neutralised rather than dropped, which keeps the column layout stable
    # across folds and therefore keeps two folds' models comparable.
    scales = np.where(scales > 0.0, scales, 1.0)
    standardised = centred / scales

    intercept = float((weights @ outcome) / total_weight)
    weighted = standardised * weights[:, None]
    width = standardised.shape[1]
    gram = standardised.T @ weighted + settings.ridge_alpha * np.eye(width)
    coefficients = np.linalg.solve(gram, weighted.T @ (outcome - intercept))

    deviation = outcome - intercept
    variance = float((weights @ np.square(deviation)) / total_weight)

    return LearnedRateModel(
        input_columns=tuple(columns),
        means=tuple(float(value) for value in means),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=intercept,
        training_rows=rows,
        ridge_alpha=settings.ridge_alpha,
        diagnostics={
            "training_rows_offered": len(training),
            "training_rows_complete": rows,
            "training_weight_minutes": total_weight,
            "target_weighted_mean": intercept,
            "target_weighted_stdev": math.sqrt(variance),
            "target_unweighted_mean": float(outcome.mean()),
        },
    )


def learned_points_per_90(
    features: pd.DataFrame,
    model: LearnedRateModel,
    *,
    config: LearnedRateConfig | None = None,
    carry_over_rate_weight: float,
    prior_rate_column: str,
) -> tuple[pd.Series, pd.Series]:
    """Project the scoring rate, reporting where each value came from.

    The ladder matches the stage this replaces rung for rung. Only the in-season rung's
    value differs: modelled rather than read straight from the rolling feature.
    """

    settings = LearnedRateConfig() if config is None else config
    if not isinstance(settings, LearnedRateConfig):
        raise PredictionConfigurationError("config must be a LearnedRateConfig.")
    if not isinstance(model, LearnedRateModel):
        raise PredictionConfigurationError("model must be a LearnedRateModel.")
    if tuple(model.input_columns) != settings.input_columns:
        raise PredictionConfigurationError(
            "The fitted model reads different inputs than this configuration declares: "
            f"{list(model.input_columns)!r} against {list(settings.input_columns)!r}."
        )

    in_season = pd.to_numeric(
        features[per_90_feature_name(settings.window)], errors="coerce"
    ).astype("float64")
    carried = (
        pd.to_numeric(features[prior_rate_column], errors="coerce").astype("float64")
        if prior_rate_column in features.columns
        else pd.Series(float("nan"), index=features.index, dtype="float64")
    )

    values = pd.Series(float("nan"), index=features.index, dtype="float64")
    source = pd.Series("unknown", index=features.index, dtype="object")

    usable_carry = carried.notna()
    values = values.mask(usable_carry, carried.mul(carry_over_rate_weight))
    source = source.mask(usable_carry, "carry_over")

    complete = pd.Series(
        np.isfinite(_matrix(features, settings.input_columns)).all(axis=1),
        index=features.index,
    )
    modelled = in_season.notna() & complete
    values = values.mask(modelled, model.predict(features))
    source = source.mask(modelled, RATE_FROM_LEARNED_MODEL)

    return values.clip(lower=0.0).astype("float64"), source.astype("string")
