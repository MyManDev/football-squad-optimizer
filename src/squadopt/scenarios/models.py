"""Public contracts for empirical joint player-point scenarios."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.prediction import PredictionSnapshot

SCENARIO_CONTRACT_VERSION: Final = "hierarchical_residual_scenarios_v1"
SCENARIO_EVALUATION_CONTRACT_VERSION: Final = "fixed_decision_scenario_evaluation_v1"
SCENARIO_OPTIMIZATION_CONTRACT_VERSION: Final = "scenario_cvar_objective_v1"
RESIDUAL_HISTORY_COLUMNS: Final = (
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "team_id",
    "position",
    "predicted_points",
    "realized_points",
    "residual",
)


class ScenarioError(Exception):
    """Base exception for scenario generation and fixed-decision evaluation."""


class ScenarioConfigurationError(ScenarioError):
    """Raised when scenario controls are invalid."""


class ScenarioValidationError(ScenarioError):
    """Raised when projections, residual history, or scenarios violate a contract."""


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ScenarioConfigurationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise ScenarioConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


def _probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ScenarioConfigurationError(f"{name} must be a finite probability.")
    normalized = float(value)
    if not math.isfinite(normalized) or not 0.0 < normalized < 1.0:
        raise ScenarioConfigurationError(f"{name} must be strictly between 0 and 1.")
    return normalized


def _finite_non_negative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ScenarioConfigurationError(f"{name} must be a finite non-negative number.")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        raise ScenarioConfigurationError(f"{name} must be a finite non-negative number.")
    return normalized


def _freeze_value(value: object, path: str) -> object:
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise ScenarioValidationError(f"{path} must be finite.")
        return number
    if isinstance(value, Mapping):
        return _freeze_mapping(value, path)
    if isinstance(value, tuple | list):
        return tuple(_freeze_value(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise ScenarioValidationError(f"{path} must be JSON-compatible metadata.")


def _freeze_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ScenarioValidationError(f"{name} must be a mapping.")
    frozen: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ScenarioValidationError(f"{name} keys must be non-empty strings.")
        frozen[key] = _freeze_value(item, f"{name}[{key!r}]")
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class ScenarioTarget:
    """The deadline for which joint player outcomes are simulated."""

    season: str
    gameweek: int

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ScenarioConfigurationError("season must be a non-empty string.")
        object.__setattr__(self, "season", self.season.strip())
        object.__setattr__(self, "gameweek", _integer(self.gameweek, "gameweek", 1))

    @property
    def fold_id(self) -> str:
        """Return the canonical sortable target identifier."""

        return f"{self.season}-gw{self.gameweek:02d}"


@dataclass(frozen=True, slots=True)
class ScenarioConfig:
    """Controls for deterministic hierarchical empirical residual sampling.

    ``player_location_shrinkage`` is opt-in: ``None`` keeps every component centered
    (the original behavior, bit for bit). A non-negative value adds a per-player
    location component — that player's historical mean residual shrunk by
    ``n / (n + shrinkage)`` — so systematic per-player optimism or pessimism in the
    projections is carried into the scenarios instead of being centered away.
    """

    scenario_count: int = 1_000
    deterministic_seed: int = 0
    min_history_folds: int = 8
    min_player_observations: int = 8
    player_scale_shrinkage: float = 10.0
    player_location_shrinkage: float | None = None
    double_gameweek_scale: float = 1.0
    """Multiplier on the idiosyncratic spread of a player whose team plays twice in the
    target gameweek. One (the default) keeps the calendar-blind scenarios bit for bit;
    a value above one carries the measured fact that a double's residual is wider (the
    fixture-group conformal radii ratio is about 1.3 to 1.5). Any value other than one
    requires the calendar (``fixture_counts``) at generation time."""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "scenario_count", _integer(self.scenario_count, "scenario_count", 1)
        )
        object.__setattr__(
            self,
            "deterministic_seed",
            _integer(self.deterministic_seed, "deterministic_seed", 0),
        )
        object.__setattr__(
            self,
            "min_history_folds",
            _integer(self.min_history_folds, "min_history_folds", 2),
        )
        object.__setattr__(
            self,
            "min_player_observations",
            _integer(self.min_player_observations, "min_player_observations", 2),
        )
        object.__setattr__(
            self,
            "player_scale_shrinkage",
            _finite_non_negative(self.player_scale_shrinkage, "player_scale_shrinkage"),
        )
        if self.player_location_shrinkage is not None:
            object.__setattr__(
                self,
                "player_location_shrinkage",
                _finite_non_negative(self.player_location_shrinkage, "player_location_shrinkage"),
            )
        object.__setattr__(
            self,
            "double_gameweek_scale",
            _finite_non_negative(self.double_gameweek_scale, "double_gameweek_scale"),
        )


@dataclass(frozen=True, slots=True)
class ScenarioEvaluationConfig:
    """Declared summaries for one fixed decision's scenario score distribution."""

    lower_quantile: float = 0.10
    worst_fraction: float = 0.10
    points_threshold: float = 40.0
    location_shift_points: float = 0.0
    """Points added to every scenario score of the fixed decision before the summaries
    are read — the decision-level selection-optimism correction. Scenarios are centred
    on the projections, and the projections of the players an optimizer *selects* are
    optimistic by construction (the winner's curse measured in `selection_optimism`:
    about -3 points a starter, -3.9 for the captain, +34.5 at squad level in the audit),
    so an honest lower tail for the chosen squad is the scenario distribution shifted
    down by that amount. Zero keeps the uncorrected summaries."""
    dispersion_scale: float = 1.0
    """Factor applied to every scenario score's deviation from the raw scenario mean
    before the summaries are read — the decision-level dispersion correction. The
    scenario audit found the squad-level distribution slightly narrow after the location
    shift (PIT tails 0.14 against 0.10); a scale above one widens it around its centre.
    One keeps the raw spread. Applied before the location shift, so the shifted mean is
    unchanged."""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "lower_quantile", _probability(self.lower_quantile, "lower_quantile")
        )
        shift = self.location_shift_points
        if isinstance(shift, bool) or not isinstance(shift, Real) or not math.isfinite(shift):
            raise ScenarioConfigurationError("location_shift_points must be a finite number.")
        object.__setattr__(self, "location_shift_points", float(shift))
        scale = self.dispersion_scale
        if (
            isinstance(scale, bool)
            or not isinstance(scale, Real)
            or not math.isfinite(scale)
            or scale <= 0.0
        ):
            raise ScenarioConfigurationError("dispersion_scale must be a finite positive number.")
        object.__setattr__(self, "dispersion_scale", float(scale))
        object.__setattr__(
            self, "worst_fraction", _probability(self.worst_fraction, "worst_fraction")
        )
        value = self.points_threshold
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ScenarioConfigurationError("points_threshold must be a finite number.")
        threshold = float(value)
        if not math.isfinite(threshold):
            raise ScenarioConfigurationError("points_threshold must be a finite number.")
        object.__setattr__(self, "points_threshold", threshold)


@dataclass(frozen=True, slots=True)
class ScenarioOptimizationConfig:
    """Controls a convex expected-score and lower-tail CVaR objective."""

    risk_aversion: float = 0.25
    tail_fraction: float = 0.10
    objective_weight_scale: int = 1_000
    contract_version: str = SCENARIO_OPTIMIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_OPTIMIZATION_CONTRACT_VERSION:
            raise ScenarioConfigurationError(
                "contract_version does not match the implemented scenario objective."
            )
        weight_scale = _integer(
            self.objective_weight_scale,
            "objective_weight_scale",
            1,
        )
        value = self.risk_aversion
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ScenarioConfigurationError("risk_aversion must be a finite number in [0, 1].")
        normalized = float(value)
        if not math.isfinite(normalized) or not 0.0 <= normalized <= 1.0:
            raise ScenarioConfigurationError("risk_aversion must be a finite number in [0, 1].")
        scaled = int(
            (Decimal(str(normalized)) * weight_scale).quantize(
                Decimal("1"),
                rounding=ROUND_HALF_UP,
            )
        )
        object.__setattr__(self, "objective_weight_scale", weight_scale)
        object.__setattr__(self, "risk_aversion", scaled / weight_scale)
        object.__setattr__(self, "tail_fraction", _probability(self.tail_fraction, "tail_fraction"))

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every comparison-affecting control."""

        payload = {
            "contract_version": self.contract_version,
            "risk_aversion": float(self.risk_aversion).hex(),
            "tail_fraction": float(self.tail_fraction).hex(),
            "objective_weight_scale": self.objective_weight_scale,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def _scenario_fingerprint(
    projections: PredictionSnapshot,
    target: ScenarioTarget,
    config: ScenarioConfig,
    scenario_ids: tuple[str, ...],
    source_fold_ids: tuple[str, ...],
    scenario_points: pd.DataFrame,
) -> str:
    metadata = {
        "contract_version": SCENARIO_CONTRACT_VERSION,
        "prediction_fingerprint": projections.prediction_fingerprint,
        "target": target.fold_id,
        "config": {
            "scenario_count": config.scenario_count,
            "deterministic_seed": config.deterministic_seed,
            "min_history_folds": config.min_history_folds,
            "min_player_observations": config.min_player_observations,
            "player_scale_shrinkage": float(config.player_scale_shrinkage).hex(),
            "player_location_shrinkage": (
                None
                if config.player_location_shrinkage is None
                else float(config.player_location_shrinkage).hex()
            ),
            **(
                {"double_gameweek_scale": float(config.double_gameweek_scale).hex()}
                if config.double_gameweek_scale != 1.0
                else {}
            ),
        },
        "scenario_ids": scenario_ids,
        "source_fold_ids": source_fold_ids,
        "player_ids": [_typed_identifier(value) for value in scenario_points.columns],
    }
    digest = hashlib.sha256(
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    values = scenario_points.to_numpy(dtype="<f8", copy=True)
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ScenarioValidationError(f"{name} must be a lowercase SHA-256 digest.")
    return value


@dataclass(frozen=True, slots=True)
class ScenarioSet:
    """Exact-aligned joint player-point matrix and its reproducibility identity."""

    projections: PredictionSnapshot
    target: ScenarioTarget
    config: ScenarioConfig
    scenario_ids: tuple[str, ...]
    source_fold_ids: tuple[str, ...]
    scenario_points: pd.DataFrame
    scenario_fingerprint: str
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = SCENARIO_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_CONTRACT_VERSION:
            raise ScenarioValidationError("contract_version does not match this implementation.")
        if not isinstance(self.projections, PredictionSnapshot):
            raise ScenarioValidationError("projections must be a PredictionSnapshot.")
        projections = self.projections.validated_copy()
        if not isinstance(self.target, ScenarioTarget):
            raise ScenarioValidationError("target must be a ScenarioTarget.")
        if not isinstance(self.config, ScenarioConfig):
            raise ScenarioValidationError("config must be a ScenarioConfig.")
        expected_ids = tuple(f"scenario-{index:06d}" for index in range(self.config.scenario_count))
        if self.scenario_ids != expected_ids:
            raise ScenarioValidationError(
                "scenario_ids do not match the configured deterministic IDs."
            )
        if len(self.source_fold_ids) != self.config.scenario_count:
            raise ScenarioValidationError("source_fold_ids must align with scenarios.")
        if any(not isinstance(value, str) or not value for value in self.source_fold_ids):
            raise ScenarioValidationError("source_fold_ids must be non-empty strings.")
        if not isinstance(self.scenario_points, pd.DataFrame):
            raise ScenarioValidationError("scenario_points must be a pandas DataFrame.")
        points = self.scenario_points.copy(deep=True)
        if points.shape != (self.config.scenario_count, len(projections.table)):
            raise ScenarioValidationError(
                "scenario_points shape does not match scenarios and players."
            )
        if tuple(points.index.tolist()) != self.scenario_ids:
            raise ScenarioValidationError("scenario_points index must equal scenario_ids.")
        player_ids = tuple(projections.table["player_id"].tolist())
        if tuple(points.columns.tolist()) != player_ids:
            raise ScenarioValidationError(
                "scenario_points columns must exactly align with projection player_id order."
            )
        try:
            points = points.astype("float64")
        except (TypeError, ValueError) as error:
            raise ScenarioValidationError("scenario_points must be numeric.") from error
        if not bool(np.isfinite(points.to_numpy()).all()):
            raise ScenarioValidationError(
                "scenario_points must be finite; negative values are allowed."
            )
        fingerprint = _digest(self.scenario_fingerprint, "scenario_fingerprint")
        expected_fingerprint = _scenario_fingerprint(
            projections,
            self.target,
            self.config,
            self.scenario_ids,
            self.source_fold_ids,
            points,
        )
        if fingerprint != expected_fingerprint:
            raise ScenarioValidationError(
                "scenario_fingerprint does not match the scenario matrix and provenance."
            )
        object.__setattr__(self, "projections", projections)
        object.__setattr__(self, "scenario_points", points)
        object.__setattr__(self, "scenario_fingerprint", fingerprint)
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, "diagnostics"))

    def validated_copy(self) -> "ScenarioSet":
        """Revalidate mutable table state and return an independent scenario set."""

        return ScenarioSet(
            projections=self.projections,
            target=self.target,
            config=self.config,
            scenario_ids=self.scenario_ids,
            source_fold_ids=self.source_fold_ids,
            scenario_points=self.scenario_points,
            scenario_fingerprint=self.scenario_fingerprint,
            diagnostics=self.diagnostics,
            contract_version=self.contract_version,
        )


@dataclass(frozen=True, slots=True)
class ScenarioRiskMetrics:
    """Distribution summaries for one fixed squad decision."""

    scenario_count: int
    point_projection_score: float
    mean_score: float
    score_standard_deviation: float
    lower_quantile_probability: float
    lower_quantile_score: float
    worst_fraction: float
    worst_fraction_count: int
    mean_worst_fraction_score: float
    minimum_score: float
    points_threshold: float
    probability_below_threshold: float

    def __post_init__(self) -> None:
        if self.scenario_count < 1:
            raise ScenarioValidationError("metrics scenario_count must be positive.")
        finite_values = (
            self.point_projection_score,
            self.mean_score,
            self.score_standard_deviation,
            self.lower_quantile_probability,
            self.lower_quantile_score,
            self.worst_fraction,
            self.mean_worst_fraction_score,
            self.minimum_score,
            self.points_threshold,
            self.probability_below_threshold,
        )
        if any(not math.isfinite(value) for value in finite_values):
            raise ScenarioValidationError("Scenario risk metrics must be finite.")
        if self.score_standard_deviation < 0.0:
            raise ScenarioValidationError("score_standard_deviation must be non-negative.")
        if not 0.0 < self.lower_quantile_probability < 1.0:
            raise ScenarioValidationError("lower_quantile_probability must be between 0 and 1.")
        if not 0.0 < self.worst_fraction < 1.0:
            raise ScenarioValidationError("worst_fraction must be between 0 and 1.")
        if not 1 <= self.worst_fraction_count <= self.scenario_count:
            raise ScenarioValidationError("worst_fraction_count must align with scenario_count.")
        if not 0.0 <= self.probability_below_threshold <= 1.0:
            raise ScenarioValidationError("probability_below_threshold must be between 0 and 1.")


@dataclass(frozen=True, slots=True)
class ScenarioEvaluationResult:
    """Scenario scores and summaries for a decision that was not reoptimized."""

    scenario_fingerprint: str
    scenario_scores: tuple[float, ...]
    metrics: ScenarioRiskMetrics
    diagnostics: Mapping[str, object]
    contract_version: str = SCENARIO_EVALUATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_EVALUATION_CONTRACT_VERSION:
            raise ScenarioValidationError("evaluation contract_version is unsupported.")
        _digest(self.scenario_fingerprint, "scenario_fingerprint")
        if not isinstance(self.metrics, ScenarioRiskMetrics):
            raise ScenarioValidationError("metrics must be a ScenarioRiskMetrics instance.")
        if len(self.scenario_scores) != self.metrics.scenario_count:
            raise ScenarioValidationError("scenario_scores must align with metrics.scenario_count.")
        if any(not math.isfinite(value) for value in self.scenario_scores):
            raise ScenarioValidationError("scenario_scores must be finite.")
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, "diagnostics"))


@dataclass(frozen=True, slots=True)
class ScenarioOptimizationResult:
    """Structured scenario-aware decision and its lower-tail diagnostics."""

    optimization_result: OptimizationResult
    scenario_config: ScenarioOptimizationConfig
    scenario_fingerprint: str
    scenario_evaluation: ScenarioEvaluationResult | None
    mean_scenario_score: float | None
    cvar_score: float | None
    mean_bench_score: float | None
    scenario_objective_value: float | None
    risk_penalty_value: float | None
    diagnostics: Mapping[str, object]
    contract_version: str = SCENARIO_OPTIMIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_OPTIMIZATION_CONTRACT_VERSION:
            raise ScenarioValidationError("optimization contract_version is unsupported.")
        if not isinstance(self.optimization_result, OptimizationResult):
            raise ScenarioValidationError("optimization_result must be an OptimizationResult.")
        if not isinstance(self.scenario_config, ScenarioOptimizationConfig):
            raise ScenarioValidationError("scenario_config must be a ScenarioOptimizationConfig.")
        _digest(self.scenario_fingerprint, "scenario_fingerprint")

        values = (
            self.mean_scenario_score,
            self.cvar_score,
            self.mean_bench_score,
            self.scenario_objective_value,
            self.risk_penalty_value,
        )
        if self.optimization_result.has_solution:
            if not isinstance(self.scenario_evaluation, ScenarioEvaluationResult):
                raise ScenarioValidationError(
                    "A feasible scenario optimization must carry scenario_evaluation."
                )
            if self.scenario_evaluation.scenario_fingerprint != self.scenario_fingerprint:
                raise ScenarioValidationError(
                    "scenario_evaluation must describe the optimized scenario_fingerprint."
                )
            if any(value is None or not math.isfinite(value) for value in values):
                raise ScenarioValidationError(
                    "A feasible scenario optimization must carry finite objective metrics."
                )
            assert self.risk_penalty_value is not None
            if self.risk_penalty_value < -1e-9:
                raise ScenarioValidationError("risk_penalty_value must be non-negative.")
        elif self.scenario_evaluation is not None or any(value is not None for value in values):
            raise ScenarioValidationError(
                "An optimization without a solution may not carry scenario metrics."
            )
        object.__setattr__(self, "diagnostics", _freeze_mapping(self.diagnostics, "diagnostics"))

    @property
    def solver_status(self) -> SolverStatus:
        """Expose the shared solver-independent status directly."""

        return self.optimization_result.solver_status
