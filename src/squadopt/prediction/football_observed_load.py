"""A standalone observed-record tilt of a complete native weekly minute law."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import logsumexp

from squadopt.features.football_load_inputs import POSITIONS
from squadopt.features.football_observed_load import (
    COVERAGE_KIND,
    FEATURE_NAMES,
    FEATURE_VERSION,
    MINUTE_DEFINITION,
    ObservedLoadOutcome,
    ObservedLoadWeek,
    observed_load_digest,
    observed_load_features,
    validate_observed_load_header,
    validate_observed_load_outcome,
    validate_observed_load_week,
    validate_targets,
)
from squadopt.features.football_observed_load import (
    parse_observed_load_clock as _clock,
)

MODEL_VERSION = "football_observed_non_pl_load_v1"
FloatArray = NDArray[np.float64]
HEADS = (
    "weekly_appearance",
    "start_short",
    "start60",
    "start90",
    "cameo_short",
    "cameo60",
    "cameo90",
)
CONTEXT_NAMES = (
    "intercept",
    *(name + ending for name in FEATURE_NAMES for ending in ("", "_missing")),
    *("position_" + p for p in POSITIONS),
)
DESIGN_NAMES = tuple(head + ":" + name for head in HEADS for name in CONTEXT_NAMES)


@dataclass(frozen=True, slots=True)
class ObservedLoadTransform:
    means: tuple[float, ...]
    scales: tuple[float, ...]
    known_counts: tuple[int, ...]


@dataclass(frozen=True)
class ObservedLoadExample:
    context: FloatArray
    counts: FloatArray
    native: FloatArray
    observed_index: int


@dataclass(frozen=True, slots=True)
class ObservedLoadMetadata:
    model_version: str
    feature_version: str
    coverage_kind: str
    minute_definition: str
    feature_names: tuple[str, ...]
    design_names: tuple[str, ...]
    cutoff: str
    target_season: str
    target_gameweeks: tuple[int, ...]
    training_seasons: tuple[str, ...]
    allow_released_2025_26: bool
    transform: ObservedLoadTransform
    coefficients: tuple[float, ...]
    training_receipts: tuple[tuple[str, str, str], ...]
    observed_competition_scopes: tuple[tuple[str, ...], ...]
    l2: float
    max_iterations: int
    optimizer_iterations: int
    objective: float
    gradient_max_abs: float
    native_mass_policy: str = "normalize_once_after_1e-12_validation_preserve_structural_zeros"
    eligibility_policy: str = "not_applied"
    chronology: str = "all_population_headers_before_labels"


@dataclass(frozen=True, slots=True)
class ObservedLoadPrediction:
    week: ObservedLoadWeek
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    weekly_appearance: float
    fixture_probabilities: tuple[tuple[float, ...], ...]
    model_sha256: str
    input_sha256: str


@dataclass(frozen=True)
class _Fitted:
    coefficients: FloatArray
    metadata: ObservedLoadMetadata
    encoded: str
    sha256: str


def _encode(value: Any) -> str:
    return json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _finite(value: float, name: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Observed load {name} must be finite and nonnegative.")
    return float(value)


def _transform(weeks: tuple[ObservedLoadWeek, ...]) -> ObservedLoadTransform:
    values = tuple(observed_load_features(week) for week in weeks)
    means, scales, counts = [], [], []
    for index in range(len(FEATURE_NAMES)):
        known = [float(value) for row in values if (value := row[index]) is not None]
        mean = math.fsum(known) / len(known) if known else 0.0
        scale = math.sqrt(math.fsum((v - mean) ** 2 for v in known) / len(known)) if known else 1.0
        means.append(mean)
        scales.append(scale or 1.0)
        counts.append(len(known))
    return ObservedLoadTransform(tuple(means), tuple(scales), tuple(counts))


def _context(week: ObservedLoadWeek, transform: ObservedLoadTransform) -> FloatArray:
    values: list[float] = [1.0]
    for index, value in enumerate(observed_load_features(week)):
        if value is not None and transform.known_counts[index] == 0:
            raise ValueError("Observed load feature has no observed training support.")
        values.extend(
            (
                0.0
                if value is None
                else (value - transform.means[index]) / transform.scales[index],
                float(value is None),
            )
        )
    values.extend(float(week.position == position) for position in POSITIONS)
    result = np.asarray(values, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Observed load context must be finite.")
    return result


def _example(
    week: ObservedLoadWeek, transform: ObservedLoadTransform, observed: int = 0
) -> ObservedLoadExample:
    counts = np.asarray(
        [
            (float(any(state)), *(float(state.count(i)) for i in range(1, 7)))
            for state in week.native.states
        ]
    )
    native = np.asarray(week.native.probabilities, dtype=float)
    native /= math.fsum(float(value) for value in native)
    return ObservedLoadExample(_context(week, transform), counts, native, observed)


def _scores(example: ObservedLoadExample, coefficients: FloatArray) -> FloatArray:
    return example.counts @ (coefficients.reshape(7, len(example.context)) @ example.context)


def objective_gradient(
    coefficients: FloatArray, examples: Sequence[ObservedLoadExample], l2: float
) -> tuple[float, FloatArray]:
    """Exact categorical log likelihood over supplied weekly states plus ridge."""
    penalty = _finite(l2, "l2")
    if coefficients.ndim != 1 or not np.isfinite(coefficients).all() or not examples:
        raise ValueError("Observed load objective requires finite coefficients and examples.")
    loss = 0.5 * penalty * float(coefficients @ coefficients)
    gradient = penalty * coefficients.copy()
    for example in examples:
        native, context, counts = example.native, example.context, example.counts
        observed = example.observed_index
        if (
            native.ndim != 1
            or context.ndim != 1
            or counts.shape != (len(native), 7)
            or coefficients.shape != (7 * len(context),)
            or not np.isfinite(native).all()
            or not np.isfinite(context).all()
            or not np.isfinite(counts).all()
            or np.any(native < 0)
            or not math.isclose(math.fsum(float(p) for p in native), 1, rel_tol=0, abs_tol=1e-12)
            or type(observed) is not int
            or not 0 <= observed < len(native)
            or native[observed] <= 0
        ):
            raise ValueError("Observed load objective has invalid shape, mass or label support.")
        scores = _scores(example, coefficients)
        support = native > 0
        logits = np.log(native[support]) + scores[support]
        normalizer = float(logsumexp(logits))
        weights = np.exp(logits - normalizer)
        loss += normalizer - math.log(float(native[observed])) - float(scores[observed])
        residual = weights @ counts[support] - counts[observed]
        gradient += np.outer(residual, context).ravel()
    if not math.isfinite(loss) or not np.isfinite(gradient).all():
        raise ValueError("Observed load likelihood produced nonfinite values.")
    return loss, gradient


def _tilt(example: ObservedLoadExample, coefficients: FloatArray) -> FloatArray:
    support = example.native > 0
    logits = np.log(example.native[support]) + _scores(example, coefficients)[support]
    normalizer = float(logsumexp(logits))
    positive = np.exp(logits - normalizer)
    if not math.isfinite(normalizer) or not np.isfinite(positive).all() or np.any(positive <= 0):
        raise ValueError("Observed load tilt cannot erase positive native support.")
    result = np.zeros_like(example.native)
    result[support] = positive / math.fsum(float(p) for p in positive)
    return result


def _verify(fitted: _Fitted) -> None:
    if (
        _encode(fitted.metadata) != fitted.encoded
        or hashlib.sha256(fitted.encoded.encode()).hexdigest() != fitted.sha256
        or tuple(float(v) for v in fitted.coefficients) != fitted.metadata.coefficients
        or fitted.metadata.model_version != MODEL_VERSION
        or fitted.metadata.feature_version != FEATURE_VERSION
        or fitted.metadata.feature_names != FEATURE_NAMES
        or fitted.metadata.design_names != DESIGN_NAMES
    ):
        raise ValueError("Observed load fitted parameter/receipt integrity mismatch.")


def _optimizer_coefficients(result: Any, max_iterations: int) -> tuple[FloatArray, int]:
    success = getattr(result, "success", None)
    status = getattr(result, "status", None)
    iterations = getattr(result, "nit", None)
    if (
        type(success) is not bool
        or not success
        or type(status) is not int
        or status != 0
        or type(iterations) is not int
        or not 0 <= iterations <= max_iterations
    ):
        raise ValueError("Observed load optimizer has no valid successful termination receipt.")
    try:
        values = np.asarray(getattr(result, "x", None), dtype=object)
        if values.shape != (len(DESIGN_NAMES),) or any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, float, np.integer, np.floating))
            for value in values
        ):
            raise ValueError("Invalid coefficient shape or scalar type.")
        coefficients = values.astype(np.float64)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Observed load optimizer returned invalid real coefficients.") from error
    if not np.isfinite(coefficients).all() or np.any(np.abs(coefficients) > 20):
        raise ValueError("Observed load optimizer coefficients must be finite and bounded.")
    return coefficients, iterations


class ObservedLoadModel:
    def __init__(self) -> None:
        self._fitted: _Fitted | None = None

    def _require(self) -> _Fitted:
        if self._fitted is None:
            raise ValueError("Observed load model has not been fitted.")
        _verify(self._fitted)
        return self._fitted

    @property
    def metadata(self) -> ObservedLoadMetadata:
        return self._require().metadata

    @property
    def metadata_json(self) -> str:
        return self._require().encoded

    @property
    def model_sha256(self) -> str:
        return self._require().sha256

    def fit(
        self,
        observations: Sequence[ObservedLoadOutcome],
        *,
        cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
        l2: float = 1.0,
        max_iterations: int = 1000,
        allow_released_2025_26: bool = False,
    ) -> ObservedLoadModel:
        validate_targets(target_season, target_gameweeks)
        penalty = _finite(l2, "l2")
        if type(max_iterations) is not int or not 1 <= max_iterations <= 1000:
            raise ValueError("Observed load max_iterations must be in 1..1000.")
        if type(allow_released_2025_26) is not bool:
            raise ValueError("Observed load released-season option must be Boolean.")
        cutoff = _clock(cutoff, "fit cutoff").isoformat().replace("+00:00", "Z")
        rows = tuple(observations)
        if not rows:
            raise ValueError("Observed load fit requires training observations.")
        clocks: dict[tuple[str, int], datetime] = {}
        identities: set[tuple[str, int, int]] = set()
        for row in rows:
            validate_observed_load_header(
                row,
                cutoff=cutoff,
                target_season=target_season,
                target_gameweeks=target_gameweeks,
                allow_released_2025_26=allow_released_2025_26,
            )
            key = row.week.season, row.week.gameweek
            clock = _clock(row.week.decision_at, "decision")
            if key in clocks and clocks[key] != clock:
                raise ValueError("Observed load gameweek requires one original decision clock.")
            clocks[key] = clock
            identity = (*key, row.week.player_code)
            if identity in identities:
                raise ValueError("Duplicate observed load training player/week.")
            identities.add(identity)
        for row in rows:
            validate_observed_load_outcome(row)
        weeks = tuple(row.week for row in rows)
        transform = _transform(weeks)
        examples = tuple(
            _example(row.week, transform, row.week.native.states.index(row.observed_states))
            for row in rows
        )
        initial = np.zeros(len(DESIGN_NAMES))
        result: Any = minimize(
            lambda values: objective_gradient(values, examples, penalty),
            initial,
            method="L-BFGS-B",
            jac=True,
            bounds=[(-20.0, 20.0)] * len(initial),
            options={"maxiter": max_iterations, "ftol": 1e-12, "gtol": 1e-7},
        )
        coefficients, iterations = _optimizer_coefficients(result, max_iterations)
        loss, gradient = objective_gradient(coefficients, examples, penalty)
        for example in examples:
            _tilt(example, coefficients)
        metadata = ObservedLoadMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            COVERAGE_KIND,
            MINUTE_DEFINITION,
            FEATURE_NAMES,
            DESIGN_NAMES,
            cutoff,
            target_season,
            target_gameweeks,
            tuple(sorted({w.season for w in weeks})),
            allow_released_2025_26,
            transform,
            tuple(float(v) for v in coefficients),
            tuple(
                (
                    observed_load_digest(r.week),
                    r.source_sha256,
                    hashlib.sha256(_encode(r).encode()).hexdigest(),
                )
                for r in rows
            ),
            tuple(sorted({tuple(sorted(w.competitions)) for w in weeks})),
            penalty,
            max_iterations,
            iterations,
            loss,
            float(np.max(np.abs(gradient))),
        )
        encoded = _encode(metadata)
        fitted = _Fitted(
            np.frombuffer(coefficients.tobytes(), dtype=np.float64),
            metadata,
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
        )
        _verify(fitted)
        self._fitted = fitted
        return self

    def predict(
        self, week: ObservedLoadWeek, *, zero_coefficients: bool = False
    ) -> ObservedLoadPrediction:
        if type(zero_coefficients) is not bool:
            raise ValueError("Observed load zero-coefficient option must be Boolean.")
        fitted = self._require()
        validate_observed_load_week(
            week, allow_released_2025_26=fitted.metadata.allow_released_2025_26
        )
        if week.provenance.kind != "prospective":
            raise ValueError("Observed load prediction requires a prospective source.")
        if (
            week.season != fitted.metadata.target_season
            or week.gameweek not in fitted.metadata.target_gameweeks
            or _clock(week.decision_at, "decision") < _clock(fitted.metadata.cutoff, "fit cutoff")
        ):
            raise ValueError("Observed load prediction is outside its fitted target.")
        if tuple(sorted(week.competitions)) not in fitted.metadata.observed_competition_scopes:
            raise ValueError("Observed load prediction changes its trained competition scope.")
        if zero_coefficients:
            probabilities = np.asarray(week.native.probabilities, dtype=float)
            probabilities /= math.fsum(float(p) for p in probabilities)
        else:
            example = _example(week, fitted.metadata.transform)
            probabilities = _tilt(example, fitted.coefficients)
        states = week.native.states
        marginal = tuple(
            tuple(
                math.fsum(
                    float(probabilities[i]) for i, state in enumerate(states) if state[j] == k
                )
                for k in range(7)
            )
            for j in range(len(week.native.fixtures))
        )
        appearance = math.fsum(
            float(probabilities[i]) for i, state in enumerate(states) if any(state)
        )
        return ObservedLoadPrediction(
            week,
            states,
            tuple(float(p) for p in probabilities),
            appearance,
            marginal,
            fitted.sha256,
            observed_load_digest(week),
        )
