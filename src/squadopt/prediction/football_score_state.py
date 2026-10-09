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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.sparse import bmat, csc_matrix, diags, eye

from squadopt.features.football_score_state_inputs import (
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
        raise ValueError("score model target gameweeks must be distinct ordered integers in1..38")


def _features(difference: int, phase: int) -> tuple[float, ...]:
    vector = [0.0] * 6
    if difference:
        vector[2 * phase + (0 if difference > 0 else 1)] = 1.0
    return tuple(vector)


def _phase(elapsed: float, horizon: float) -> int:
    return min(2, int(3 * elapsed / horizon))


def _breaks(start: float, end: float, horizon: float) -> tuple[float, ...]:
    return (start, *(point for point in (horizon / 3, 2 * horizon / 3) if start < point < end), end)


def training_design(row: TrainingScoreFixture) -> ScoreTrainingExample:
    """Build the event likelihood after its source has been fully validated."""
    horizon = row.input.forecast_duration
    home_rate = row.input.native_home_goals / horizon
    away_rate = row.input.native_away_goals / horizon
    masses: list[float] = []
    exposure: list[tuple[float, ...]] = []
    offsets: list[float] = []
    events: list[tuple[float, ...]] = []
    difference = 0
    previous = 0.0
    for goal in (*row.goals, None):
        elapsed = row.actual_duration if goal is None else goal.elapsed
        points = _breaks(previous, elapsed, horizon)
        for left, right in pairwise(points):
            phase = _phase((left + right) / 2, horizon)
            for rate, sign in ((home_rate, difference), (away_rate, -difference)):
                masses.append(rate * (right - left))
                exposure.append(_features(sign, phase))
        if goal is None:
            break
        is_home = goal.beneficiary_club_code == row.input.home_club_code
        rate = home_rate if is_home else away_rate
        if rate <= 0:
            raise ValueError("historical physical goal has no native intensity support")
        offsets.append(math.log(rate))
        events.append(_features(difference if is_home else -difference, _phase(elapsed, horizon)))
        difference += 1 if is_home else -1
        previous = elapsed
    return ScoreTrainingExample(tuple(masses), tuple(exposure), tuple(offsets), tuple(events))


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
            raise ValueError("score numerical tolerance must be finite in1e-12..1e-6")
        if type(max_difference) is not int or not 1 <= max_difference <= 512:
            raise ValueError("score max difference must be an integer in1..512")
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
        observations: Sequence[TrainingScoreFixture],
        *,
        cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
        allowed_seasons: tuple[str, ...],
        l2: float = 1.0,
        max_iterations: int = MAX_ITERATIONS,
    ) -> ScoreStateModel:
        _targets(target_season, target_gameweeks)
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
            if season == "2025-26" or _season(season) > _season(target_season):
                raise ValueError("score allowed season is protected or future")
        if (
            not isinstance(l2, (int, float))
            or isinstance(l2, bool)
            or not math.isfinite(l2)
            or l2 < 0
        ):
            raise ValueError("score l2 must be finite and nonnegative")
        if type(max_iterations) is not int or not 1 <= max_iterations <= MAX_ITERATIONS:
            raise ValueError("score max iterations must be an integer in1..1000")
        rows = tuple(observations)
        if not rows:
            raise ValueError("score training observations must not be empty")
        clocks: dict[tuple[str, int], datetime] = {}
        identities: set[tuple[str, int]] = set()
        for row in rows:
            if not isinstance(row, TrainingScoreFixture) or not isinstance(row.input, ScoreFixture):
                raise ValueError("score training requires declared source types")
            season = row.input.season
            if (
                season == "2025-26"
                or season not in allowed_seasons
                or _season(season) > _season(target_season)
                or (season == target_season and row.input.gameweek >= min(target_gameweeks))
            ):
                raise ValueError("score causal training season or gameweek is excluded")
            validate_training_score_header(
                row,
                fit_cutoff=canonical_cutoff,
                target_season=target_season,
                target_gameweeks=target_gameweeks,
            )
            key = (season, row.input.gameweek)
            decision = _utc(row.input.decision_at)
            if key in clocks and clocks[key] != decision:
                raise ValueError("score historical gameweek requires one original decision clock")
            clocks[key] = decision
            identity = (season, row.input.fixture_id)
            if identity in identities:
                raise ValueError("score training fixture identity is duplicated")
            identities.add(identity)
        for row in rows:
            validate_training_score_fixture(
                row,
                fit_cutoff=canonical_cutoff,
                target_season=target_season,
                target_gameweeks=target_gameweeks,
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
        if not result.success or not np.isfinite(result.x).all():
            raise ValueError("score intensity optimizer did not converge finitely")
        coefficients = np.asarray(result.x, dtype=float)
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
                    score_input_digest(row.input),
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
        process = _Process(
            fixture,
            coefficients,
            fitted.metadata.numerical_tolerance,
            fitted.metadata.max_difference,
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
            fitted.sha256,
            score_input_digest(fixture),
            zero_coefficients,
            process.mean,
            len(process.intervals),
            process.exponentials,
        )
