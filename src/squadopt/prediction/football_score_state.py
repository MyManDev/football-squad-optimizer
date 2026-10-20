"""Private paired score process with fitted predictable lead/trail intensities.

Six shared coefficients describe leading and trailing in three fixed thirds of
the original forecast clock. The internal chain retains the full goal
difference. Player intervals are supplied facts or predecision projections;
this module neither learns substitutions nor applies FPL minute eligibility.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.sparse import bmat, csc_matrix, diags, eye

from squadopt.features.football_score_replay import (
    REPLAY_FIT_VERSION,
    ScoreReplayBasis,
    ScoreReplayObservation,
    ScoreReplayProvenance,
    canonical_score_replay_basis,
    canonical_score_replay_observation,
    score_replay_basis_digest,
    validate_score_replay_header,
    validate_score_replay_observation,
)
from squadopt.features.football_score_state_inputs import (
    PhysicalGoal,
    ScoreFixture,
    TrainingScoreFixture,
    score_input_digest,
    validate_score_fixture,
    validate_training_score_fixture,
    validate_training_score_header,
)

MODEL_VERSION = "football_score_state_v1"
FEATURE_VERSION = "causal_score_state_thirds_v1"
FEATURE_NAMES = tuple(
    f"{state}_forecast_third_{phase + 1}" for phase in range(3) for state in ("leading", "trailing")
)
COEFFICIENT_BOUND = 6.0
MAX_ITERATIONS = 1000
DEFAULT_NUMERICAL_TOLERANCE = 1e-11
DEFAULT_MAX_DIFFERENCE = 256
ROUNDING_BOUND = 256 * np.finfo(float).eps


@dataclass(frozen=True)
class ScoreTrainingExample:
    """An independently inspectable predictable-state likelihood design."""

    exposure_masses: tuple[float, ...]
    exposure_features: tuple[tuple[float, ...], ...]
    event_log_offsets: tuple[float, ...]
    event_features: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class ScoreStateMetadata:
    model_version: str
    feature_version: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    cutoff: str
    target_season: str
    target_gameweeks: tuple[int, ...]
    allowed_seasons: tuple[str, ...]
    l2: float
    max_iterations: int
    optimizer_iterations: int
    objective: float
    gradient_max_abs: float
    numerical_tolerance: float
    max_difference: int
    training_receipts: tuple[tuple[str, str, str, str], ...]
    chronology: str = "all_headers_before_labels_target_and_later_gameweeks_excluded"
    native_offset: str = "original_whole_fixture_goals_divided_by_forecast_physical_duration"
    playing_interval_policy: str = "frozen_predecision_normal_exit_no_learned_substitution"
    numerical_method: str = "sparse_piecewise_uniformization_exact_difference_poisson_tail_bound"


@dataclass(frozen=True)
class ScoreReplayMetadata(ScoreStateMetadata):
    fit_contract: str = REPLAY_FIT_VERSION
    allow_released_2025_26: bool = False
    replay_receipts: tuple[tuple[str, ScoreReplayProvenance], ...] = ()


@dataclass(frozen=True)
class ScoreSolverReceipt:
    original_status: int
    original_iterations: int
    coordinate_iterations: tuple[int, ...]
    projected_gradient_max_abs: float
    method: str = "separable_bounded_derivative_bisection_v1"
    original_method: str = "L-BFGS-B"
    kkt_tolerance: float = 1e-8


@dataclass(frozen=True, kw_only=True)
class ScoreSolvedMetadata(ScoreStateMetadata):
    solver_receipt: ScoreSolverReceipt


@dataclass(frozen=True, kw_only=True)
class ScoreSolvedReplayMetadata(ScoreReplayMetadata):
    solver_receipt: ScoreSolverReceipt


@dataclass(frozen=True)
class PlayerCleanSheet:
    player_code: int
    club_code: int
    survival: tuple[float, ...]


@dataclass(frozen=True)
class ScoreStatePrediction:
    fixture: ScoreFixture
    home_physical_goals: float
    away_physical_goals: float
    player_survival: tuple[PlayerCleanSheet, ...]
    difference_states: tuple[int, ...]
    difference_probabilities: tuple[float, ...]
    overflow_mass: float
    mass_error_bound: float
    goal_moment_error_bound: float
    model_sha256: str
    input_sha256: str
    zero_coefficients: bool
    dominating_goal_mean: float
    unique_intervals: int
    matrix_exponentials: int


@dataclass(frozen=True)
class _Fitted:
    coefficients: NDArray[np.float64]
    metadata: ScoreStateMetadata
    metadata_json: str
    sha256: str


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("score model clock must be an aware ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("score model clock must be an aware ISO timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("score model clock must be an aware ISO timestamp")
    return result.astimezone(UTC)


def _season(value: str) -> int:
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        raise ValueError("score model season must be YYYY-YY")
    try:
        year = int(value[:4])
        end = int(value[5:])
    except ValueError as error:
        raise ValueError("score model season must be YYYY-YY") from error
    if year < 2000 or end != (year + 1) % 100:
        raise ValueError("score model season must be consecutive YYYY-YY")
    return year


def _targets(season: str, gameweeks: tuple[int, ...]) -> None:
    _season(season)
    if (
        not isinstance(gameweeks, tuple)
        or not gameweeks
        or any(type(gw) is not int or not 1 <= gw <= 38 for gw in gameweeks)
        or tuple(sorted(set(gameweeks))) != gameweeks
    ):
        raise ValueError("score model target gameweeks must be distinct ordered integers in 1..38")


def _features(difference: int, phase: int) -> tuple[float, ...]:
    vector = [0.0] * 6
    if difference:
        vector[2 * phase + (0 if difference > 0 else 1)] = 1.0
    return tuple(vector)


def _phase(elapsed: float, horizon: float) -> int:
    return min(2, int(3 * elapsed / horizon))


def _breaks(start: float, end: float, horizon: float) -> tuple[float, ...]:
    return (start, *(point for point in (horizon / 3, 2 * horizon / 3) if start < point < end), end)


def training_design(row: TrainingScoreFixture | ScoreReplayObservation) -> ScoreTrainingExample:
    """Build the event likelihood after its source has been fully validated."""
    basis = row.basis if isinstance(row, ScoreReplayObservation) else row.input
    return _training_design(
        basis.native_home_goals,
        basis.native_away_goals,
        basis.forecast_duration,
        basis.home_club_code,
        row.actual_duration,
        row.goals,
    )


def _training_design(
    native_home_goals: float,
    native_away_goals: float,
    horizon: float,
    home_club_code: int,
    actual_duration: float,
    goals: tuple[PhysicalGoal, ...],
) -> ScoreTrainingExample:
    home_rate = native_home_goals / horizon
    away_rate = native_away_goals / horizon
    masses: list[float] = []
    exposure: list[tuple[float, ...]] = []
    offsets: list[float] = []
    events: list[tuple[float, ...]] = []
    difference = 0
    previous = 0.0
    for goal in (*goals, None):
        elapsed = actual_duration if goal is None else goal.elapsed
        points = _breaks(previous, elapsed, horizon)
        for left, right in pairwise(points):
            phase = _phase((left + right) / 2, horizon)
            for rate, sign in ((home_rate, difference), (away_rate, -difference)):
                masses.append(rate * (right - left))
                exposure.append(_features(sign, phase))
        if goal is None:
            break
        is_home = goal.beneficiary_club_code == home_club_code
        rate = home_rate if is_home else away_rate
        if rate <= 0:
            raise ValueError("historical physical goal has no native intensity support")
        offsets.append(math.log(rate))
        events.append(_features(difference if is_home else -difference, _phase(elapsed, horizon)))
        difference += 1 if is_home else -1
        previous = elapsed
    return ScoreTrainingExample(tuple(masses), tuple(exposure), tuple(offsets), tuple(events))


def _training_basis(
    row: TrainingScoreFixture | ScoreReplayObservation,
) -> ScoreFixture | ScoreReplayBasis:
    if type(row) is ScoreReplayObservation and type(row.basis) is ScoreReplayBasis:
        return row.basis
    if type(row) is TrainingScoreFixture and type(row.input) is ScoreFixture:
        return row.input
    raise ValueError("score training requires declared source types")


def _basis_digest(
    row: TrainingScoreFixture | ScoreReplayObservation, allow_released_2025_26: bool
) -> str:
    if isinstance(row, ScoreReplayObservation):
        return score_replay_basis_digest(row.basis, allow_released_2025_26=allow_released_2025_26)
    return score_input_digest(row.input)


def objective_gradient(
    coefficients: NDArray[np.float64], examples: Sequence[ScoreTrainingExample], l2: float
) -> tuple[float, NDArray[np.float64]]:
    """Negative complete-history event log likelihood and analytic gradient."""
    if coefficients.shape != (6,) or not np.isfinite(coefficients).all():
        raise ValueError("score coefficients must contain six finite values")
    loss = 0.5 * l2 * float(coefficients @ coefficients)
    gradient = l2 * coefficients.copy()
    for example in examples:
        design = np.asarray(example.exposure_features, dtype=float).reshape(-1, 6)
        masses = np.asarray(example.exposure_masses, dtype=float)
        weighted = masses * np.exp(design @ coefficients)
        event_design = np.asarray(example.event_features, dtype=float).reshape(-1, 6)
        loss += float(weighted.sum() - event_design.sum(axis=0) @ coefficients)
        loss -= math.fsum(example.event_log_offsets)
        gradient += design.T @ weighted - event_design.sum(axis=0)
    if not math.isfinite(loss) or not np.isfinite(gradient).all():
        raise ValueError("score likelihood produced nonfinite values")
    return loss, gradient


def _immutable(values: NDArray[np.float64]) -> NDArray[np.float64]:
    return np.frombuffer(values.astype(np.float64).tobytes(), dtype=np.float64)


def _separable_solution(
    examples: Sequence[ScoreTrainingExample], l2: float
) -> tuple[NDArray[np.float64], tuple[int, ...]]:
    """Solve the unchanged bounded objective only for exact zero/one-hot designs."""
    if isinstance(l2, bool) or not isinstance(l2, (int, float)) or not math.isfinite(l2) or l2 < 0:
        raise ValueError("Separable score fitting requires finite nonnegative l2.")
    masses: list[list[float]] = [[] for _ in range(6)]
    counts = [0] * 6
    for example in examples:
        for values, vectors, is_event in (
            (example.exposure_masses, example.exposure_features, False),
            (example.event_log_offsets, example.event_features, True),
        ):
            if len(values) != len(vectors):
                raise ValueError("Separable score design lengths differ.")
            for value, vector in zip(values, vectors, strict=True):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or (not is_event and value < 0)
                    or len(vector) != 6
                    or any(
                        isinstance(item, bool)
                        or not isinstance(item, (int, float))
                        or item not in (0.0, 1.0)
                        for item in vector
                    )
                    or sum(vector) > 1
                ):
                    raise ValueError("Separable score design must be finite zero/one-hot rows.")
                if 1.0 in vector:
                    index = vector.index(1.0)
                    if is_event:
                        counts[index] += 1
                    else:
                        masses[index].append(float(value))
    coefficients = np.zeros(6, dtype=float)
    iterations = []
    for index in range(6):
        try:
            mass = math.fsum(masses[index])
        except OverflowError as error:
            raise ValueError("Separable score exposure exceeds finite support.") from error

        def derivative(value: float, mass: float = mass, count: int = counts[index]) -> float:
            gradient = mass * math.exp(value) - count + l2 * value
            if not math.isfinite(gradient):
                raise ValueError("Separable score derivative exceeds finite support.")
            return gradient

        lower, upper = -COEFFICIENT_BOUND, COEFFICIENT_BOUND
        steps = 0
        if mass == counts[index] == l2 == 0:
            optimum = 0.0
        elif derivative(lower) >= 0:
            optimum = lower
        elif derivative(upper) <= 0:
            optimum = upper
        else:
            for _ in range(128):
                steps += 1
                middle = lower + (upper - lower) / 2
                gradient = derivative(middle)
                if gradient == 0 or middle in (lower, upper):
                    break
                if gradient < 0:
                    lower = middle
                else:
                    upper = middle
            optimum = min((lower, middle, upper), key=lambda value: (abs(derivative(value)), value))
        coefficients[index] = optimum
        iterations.append(steps)
    return coefficients, tuple(iterations)


def _projected_gradient(coefficients: NDArray[np.float64], gradient: NDArray[np.float64]) -> float:
    if coefficients.shape != (6,) or gradient.shape != (6,) or not np.isfinite(gradient).all():
        raise ValueError("Score KKT certification requires six finite gradients.")
    residual = np.where(
        coefficients == -COEFFICIENT_BOUND,
        np.minimum(gradient, 0),
        np.where(coefficients == COEFFICIENT_BOUND, np.maximum(gradient, 0), gradient),
    )
    return float(np.max(np.abs(residual)))


def _verify(fitted: _Fitted) -> None:
    canonical = json.dumps(
        asdict(fitted.metadata), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    if (
        canonical != fitted.metadata_json
        or hashlib.sha256(canonical.encode()).hexdigest() != fitted.sha256
        or tuple(float(value) for value in fitted.coefficients) != fitted.metadata.coefficients
        or fitted.metadata.model_version != MODEL_VERSION
        or fitted.metadata.feature_version != FEATURE_VERSION
        or fitted.metadata.feature_names != FEATURE_NAMES
    ):
        raise ValueError("score fitted parameter and metadata receipt mismatch")


def _poisson_upper(mean: float, threshold: int) -> float:
    """Chernoff upper bound on P(Poisson(mean)>=threshold), rounded outward."""
    if mean == 0:
        return 0.0
    if threshold <= mean:
        return 1.0
    exponent = -mean + threshold * (1 + math.log(mean) - math.log(threshold))
    bound = math.exp(exponent) if exponent > -740 else float(np.nextafter(0.0, 1.0))
    return min(1.0, math.nextafter(bound, math.inf))


def _radius(mean: float, tolerance: float, maximum: int) -> tuple[int, float, float]:
    for radius in range(1, maximum + 1):
        mass = _poisson_upper(mean, radius + 1)
        moment = mean * _poisson_upper(mean, radius)
        if mass + ROUNDING_BOUND <= tolerance and moment + ROUNDING_BOUND * (1 + mean) <= tolerance:
            return radius, mass + ROUNDING_BOUND, moment + ROUNDING_BOUND * (1 + mean)
    raise ValueError("score process exceeds declared grid and numerical tail tolerance")


def _rates(
    fixture: ScoreFixture, coefficients: NDArray[np.float64], phase: int, states: NDArray[np.int64]
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    leading, trailing = (
        math.exp(float(coefficients[2 * phase])),
        math.exp(float(coefficients[2 * phase + 1])),
    )
    home = (
        fixture.native_home_goals
        / fixture.forecast_duration
        * np.where(states > 0, leading, np.where(states < 0, trailing, 1.0))
    )
    away = (
        fixture.native_away_goals
        / fixture.forecast_duration
        * np.where(states < 0, leading, np.where(states > 0, trailing, 1.0))
    )
    return np.asarray(home, dtype=float), np.asarray(away, dtype=float)


def _generator(home: NDArray[np.float64], away: NDArray[np.float64]) -> csc_matrix:
    n = len(home)
    matrix = diags((home[:-1], -(home + away), away[1:]), (-1, 0, 1), shape=(n, n), format="csc")
    return matrix


class _Process:
    def __init__(
        self,
        fixture: ScoreFixture,
        coefficients: NDArray[np.float64],
        tolerance: float,
        maximum: int,
    ) -> None:
        self.fixture = fixture
        self.coefficients = coefficients
        self.exponentials = 0
        mean = 0.0
        for phase in range(3):
            home, away = _rates(
                fixture, coefficients, phase, np.asarray([-1, 0, 1], dtype=np.int64)
            )
            mean += float(np.max(home + away)) * fixture.forecast_duration / 3
        self.mean = mean
        self.radius, grid_mass, grid_moment = _radius(mean, tolerance / 2, maximum)
        self.series_tolerance = tolerance / (32 * (1 + mean))
        self.mass_bound = grid_mass + 6 * self.series_tolerance
        self.moment_bound = grid_moment + 3 * self.series_tolerance * (1 + mean)
        self.states = np.arange(-self.radius, self.radius + 1, dtype=np.int64)
        self.rates = tuple(_rates(fixture, coefficients, phase, self.states) for phase in range(3))
        self.generators = tuple(_generator(home, away) for home, away in self.rates)
        self.initial = np.zeros(len(self.states), dtype=float)
        self.initial[self.radius] = 1.0
        self.entries: dict[float, NDArray[np.float64]] = {0.0: self.initial}
        self.intervals: dict[tuple[int, float, float], float] = {}

    def _advance(
        self, matrix: csc_matrix, vector: NDArray[np.float64], duration: float
    ) -> NDArray[np.float64]:
        if duration == 0:
            return vector.copy()
        self.exponentials += 1
        rate = float(np.max(-matrix.diagonal()))
        if rate == 0:
            return vector.copy()
        mean = rate * duration
        transition = eye(matrix.shape[0], format="csc") + matrix / rate
        weight = math.exp(-mean)
        if weight == 0:
            raise ValueError("score uniformization native support underflows")
        power = vector.copy()
        result = weight * power
        for count in range(1, 4097):
            power = np.asarray(transition @ power, dtype=float)
            weight *= mean / count
            result += weight * power
            if (
                _poisson_upper(mean, count + 1) <= self.series_tolerance
                and mean * _poisson_upper(mean, count) <= self.series_tolerance
            ):
                break
        else:
            raise ValueError("score uniformization exceeds declared numerical work bound")
        if not np.isfinite(result).all() or float(np.min(result)) < -ROUNDING_BOUND:
            raise ValueError("score matrix exponential produced invalid numerical mass")
        return np.maximum(result, 0.0)

    def entry(self, elapsed: float) -> NDArray[np.float64]:
        if elapsed not in self.entries:
            value = self.initial.copy()
            points = _breaks(0.0, elapsed, self.fixture.forecast_duration)
            for left, right in pairwise(points):
                phase = _phase((left + right) / 2, self.fixture.forecast_duration)
                value = self._advance(self.generators[phase], value, right - left)
            self.entries[elapsed] = value
        return self.entries[elapsed]

    def goals(self) -> tuple[float, float]:
        n = len(self.states)
        vector = np.concatenate((self.initial, np.zeros(2)))
        for phase in range(3):
            home, away = self.rates[phase]
            matrix = bmat(
                [
                    [self.generators[phase], csc_matrix((n, 2))],
                    [csc_matrix(np.vstack((home, away))), csc_matrix((2, 2))],
                ],
                format="csc",
            )
            vector = self._advance(matrix, vector, self.fixture.forecast_duration / 3)
        self.entries[self.fixture.forecast_duration] = vector[:n]
        return float(vector[n]), float(vector[n + 1])

    def survival(self, club: int, start: float, end: float) -> float:
        key = (club, start, end)
        if key not in self.intervals:
            value = self.entry(start).copy()
            points = _breaks(start, end, self.fixture.forecast_duration)
            for left, right in pairwise(points):
                phase = _phase((left + right) / 2, self.fixture.forecast_duration)
                home, away = self.rates[phase]
                own = home if club == self.fixture.home_club_code else away
                offset = -1 if club == self.fixture.home_club_code else 1
                diagonal = own[:-1] if offset == -1 else own[1:]
                killed = diags(
                    (diagonal, -(home + away)),
                    (offset, 0),
                    shape=(len(self.states), len(self.states)),
                    format="csc",
                )
                value = self._advance(killed, value, right - left)
            probability = float(value.sum())
            if probability > 1 + ROUNDING_BOUND:
                raise ValueError("score clean-sheet survival exceeds one")
            self.intervals[key] = probability
        return self.intervals[key]


class ScoreStateModel:
    def __init__(
        self,
        *,
        numerical_tolerance: float = DEFAULT_NUMERICAL_TOLERANCE,
        max_difference: int = DEFAULT_MAX_DIFFERENCE,
    ) -> None:
        if (
            not isinstance(numerical_tolerance, (int, float))
            or isinstance(numerical_tolerance, bool)
            or not math.isfinite(numerical_tolerance)
            or not 1e-12 <= numerical_tolerance <= 1e-6
        ):
            raise ValueError("score numerical tolerance must be finite in 1e-12..1e-6")
        if type(max_difference) is not int or not 1 <= max_difference <= 512:
            raise ValueError("score max difference must be an integer in 1..512")
        self.numerical_tolerance = float(numerical_tolerance)
        self.max_difference = max_difference
        self._fitted: _Fitted | None = None

    def _require(self) -> _Fitted:
        if self._fitted is None:
            raise ValueError("score model has not been fitted")
        _verify(self._fitted)
        return self._fitted

    @property
    def metadata(self) -> ScoreStateMetadata:
        return self._require().metadata

    @property
    def metadata_json(self) -> str:
        return self._require().metadata_json

    @property
    def model_sha256(self) -> str:
        return self._require().sha256

    def fit(
        self,
        observations: Sequence[TrainingScoreFixture | ScoreReplayObservation],
        *,
        cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
        allowed_seasons: tuple[str, ...],
        l2: float = 1.0,
        max_iterations: int = MAX_ITERATIONS,
        allow_released_2025_26: bool = False,
    ) -> ScoreStateModel:
        _targets(target_season, target_gameweeks)
        if type(allow_released_2025_26) is not bool:
            raise ValueError("score released-season selection must be Boolean")
        fit_time = _utc(cutoff)
        canonical_cutoff = fit_time.isoformat().replace("+00:00", "Z")
        if (
            not isinstance(allowed_seasons, tuple)
            or not allowed_seasons
            or len(set(allowed_seasons)) != len(allowed_seasons)
        ):
            raise ValueError("score allowed seasons must be a nonempty unique tuple")
        for season in allowed_seasons:
            _season(season)
            if (season == "2025-26" and not allow_released_2025_26) or _season(season) > _season(
                target_season
            ):
                raise ValueError("score allowed season is protected or future")
        if (
            not isinstance(l2, (int, float))
            or isinstance(l2, bool)
            or not math.isfinite(l2)
            or l2 < 0
        ):
            raise ValueError("score l2 must be finite and nonnegative")
        if type(max_iterations) is not int or not 1 <= max_iterations <= MAX_ITERATIONS:
            raise ValueError("score max iterations must be an integer in 1..1000")
        rows = tuple(observations)
        if not rows:
            raise ValueError("score training observations must not be empty")
        clocks: dict[tuple[str, int], datetime] = {}
        identities: set[tuple[str, int]] = set()
        for row in rows:
            basis = _training_basis(row)
            season = basis.season
            if (
                (season == "2025-26" and not allow_released_2025_26)
                or season not in allowed_seasons
                or _season(season) > _season(target_season)
                or (season == target_season and basis.gameweek >= min(target_gameweeks))
            ):
                raise ValueError("score causal training season or gameweek is excluded")
            if isinstance(row, ScoreReplayObservation):
                validate_score_replay_header(
                    row,
                    fit_cutoff=canonical_cutoff,
                    target_season=target_season,
                    target_gameweeks=target_gameweeks,
                    allow_released_2025_26=allow_released_2025_26,
                )
            else:
                validate_training_score_header(
                    row,
                    fit_cutoff=canonical_cutoff,
                    target_season=target_season,
                    target_gameweeks=target_gameweeks,
                )
            key = (season, basis.gameweek)
            decision = _utc(basis.decision_at)
            if key in clocks and clocks[key] != decision:
                raise ValueError("score historical gameweek requires one original decision clock")
            clocks[key] = decision
            identity = (season, basis.fixture_id)
            if identity in identities:
                raise ValueError("score training fixture identity is duplicated")
            identities.add(identity)
        for row in rows:
            if isinstance(row, ScoreReplayObservation):
                validate_score_replay_observation(
                    row,
                    fit_cutoff=canonical_cutoff,
                    target_season=target_season,
                    target_gameweeks=target_gameweeks,
                    allow_released_2025_26=allow_released_2025_26,
                )
            else:
                validate_training_score_fixture(
                    row,
                    fit_cutoff=canonical_cutoff,
                    target_season=target_season,
                    target_gameweeks=target_gameweeks,
                )
        rows = tuple(
            canonical_score_replay_observation(row, allow_released_2025_26=allow_released_2025_26)
            if isinstance(row, ScoreReplayObservation)
            else row
            for row in rows
        )
        examples = tuple(training_design(row) for row in rows)

        def objective(values: NDArray[np.float64]) -> tuple[float, NDArray[np.float64]]:
            return objective_gradient(values, examples, float(l2))

        result: Any = minimize(
            objective,
            np.zeros(6),
            method="L-BFGS-B",
            jac=True,
            bounds=[(-COEFFICIENT_BOUND, COEFFICIENT_BOUND)] * 6,
            options={"maxiter": max_iterations, "ftol": 1e-13, "gtol": 1e-8},
        )
        try:
            raw_coefficients = np.asarray(getattr(result, "x", ()))
            if raw_coefficients.dtype.kind not in "fiu":
                raise ValueError("optimizer coefficients must be real numeric values")
            coefficients = raw_coefficients.astype(float)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("score intensity optimizer did not converge finitely") from error
        iterations = getattr(result, "nit", None)
        success = getattr(result, "success", None)
        status = getattr(result, "status", None)
        if (
            not isinstance(success, (bool, np.bool_))
            or type(status) is not int
            or (success and status != 0)
            or isinstance(iterations, bool)
            or not isinstance(iterations, (int, np.integer))
            or not 0 <= iterations <= max_iterations
            or coefficients.shape != (6,)
            or not np.isfinite(coefficients).all()
            or np.any(np.abs(coefficients) > COEFFICIENT_BOUND)
        ):
            raise ValueError("score intensity optimizer did not converge finitely")
        solver_receipt = None
        if not success:
            if status != 2 or iterations >= max_iterations:
                raise ValueError("score intensity optimizer did not converge finitely")
            coefficients, coordinate_iterations = _separable_solution(examples, float(l2))
            _, certified_gradient = objective(coefficients)
            residual = _projected_gradient(coefficients, certified_gradient)
            if residual > 1e-8:
                raise ValueError(
                    "Separable score solution failed the original objective KKT check."
                )
            solver_receipt = ScoreSolverReceipt(
                status, int(iterations), coordinate_iterations, residual
            )
        loss, gradient = objective(coefficients)
        metadata = ScoreStateMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            FEATURE_NAMES,
            tuple(float(value) for value in coefficients),
            canonical_cutoff,
            target_season,
            target_gameweeks,
            allowed_seasons,
            float(l2),
            max_iterations,
            int(result.nit),
            loss,
            float(np.max(np.abs(gradient))),
            self.numerical_tolerance,
            self.max_difference,
            tuple(
                (
                    _basis_digest(row, allow_released_2025_26),
                    row.outcome_sha256,
                    row.settled_at,
                    hashlib.sha256(
                        json.dumps(
                            asdict(row),
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode()
                    ).hexdigest(),
                )
                for row in rows
            ),
        )
        if allow_released_2025_26 or any(isinstance(row, ScoreReplayObservation) for row in rows):
            metadata = ScoreReplayMetadata(
                **asdict(metadata),
                allow_released_2025_26=allow_released_2025_26,
                replay_receipts=tuple(
                    (
                        _basis_digest(row, allow_released_2025_26),
                        canonical_score_replay_basis(
                            row.basis, allow_released_2025_26=allow_released_2025_26
                        ).provenance,
                    )
                    for row in rows
                    if isinstance(row, ScoreReplayObservation)
                ),
            )
        if solver_receipt is not None:
            metadata_type = (
                ScoreSolvedReplayMetadata
                if isinstance(metadata, ScoreReplayMetadata)
                else ScoreSolvedMetadata
            )
            metadata = metadata_type(
                **{item.name: getattr(metadata, item.name) for item in fields(metadata)},
                solver_receipt=solver_receipt,
            )
        encoded = json.dumps(
            asdict(metadata), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        fitted = _Fitted(
            _immutable(coefficients),
            metadata,
            encoded,
            hashlib.sha256(encoded.encode()).hexdigest(),
        )
        _verify(fitted)
        self._fitted = fitted
        return self

    def predict(
        self, fixture: ScoreFixture, *, zero_coefficients: bool = False
    ) -> ScoreStatePrediction:
        fitted = self._require()
        if type(zero_coefficients) is not bool:
            raise ValueError("score zero-coefficient option must be Boolean")
        validate_score_fixture(fixture)
        if (
            fixture.season != fitted.metadata.target_season
            or fixture.gameweek < min(fitted.metadata.target_gameweeks)
            or _utc(fixture.decision_at) < _utc(fitted.metadata.cutoff)
        ):
            raise ValueError("score prediction target or decision precedes the fit contract")
        coefficients = np.zeros(6) if zero_coefficients else fitted.coefficients
        return _predict_score_process(
            fixture,
            coefficients,
            numerical_tolerance=fitted.metadata.numerical_tolerance,
            max_difference=fitted.metadata.max_difference,
            model_sha256=fitted.sha256,
            zero_coefficients=zero_coefficients,
        )


def _predict_score_process(
    fixture: ScoreFixture,
    coefficients: NDArray[np.float64],
    *,
    numerical_tolerance: float,
    max_difference: int,
    model_sha256: str,
    zero_coefficients: bool,
) -> ScoreStatePrediction:
    """Shared numerical kernel after either full or compact contract validation."""
    process = _Process(
        fixture,
        coefficients,
        numerical_tolerance,
        max_difference,
    )
    home, away = process.goals()
    players = []
    for player in sorted(fixture.players, key=lambda item: item.player_code):
        values = tuple(
            0.0 if policy == "not_playing" else process.survival(player.club_code, start, end)
            for start, end, policy in zip(
                player.physical_on, player.physical_off, player.exit_policies, strict=True
            )
        )
        players.append(PlayerCleanSheet(player.player_code, player.club_code, values))
    probabilities = process.entry(fixture.forecast_duration)
    retained = float(probabilities.sum())
    overflow = 1 - retained
    if overflow < -ROUNDING_BOUND or overflow > process.mass_bound:
        raise ValueError("score retained probability mass violates declared numerical bound")
    return ScoreStatePrediction(
        fixture,
        home,
        away,
        tuple(players),
        tuple(int(state) for state in process.states),
        tuple(float(probability) for probability in probabilities),
        max(0.0, overflow),
        process.mass_bound,
        process.moment_bound,
        model_sha256,
        score_input_digest(fixture),
        zero_coefficients,
        process.mean,
        len(process.intervals),
        process.exponentials,
    )
