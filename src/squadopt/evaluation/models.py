"""Public contracts for evaluating already-prepared gameweek decisions."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from numbers import Integral, Real
from types import MappingProxyType

import pandas as pd

from squadopt.optimization import OptimizationConfig, OptimizationResult


class EvaluationError(Exception):
    """Base exception for the evaluation package."""


class EvaluationValidationError(EvaluationError):
    """Raised when prepared folds or realized outcomes violate their contract."""


class ScoringPolicy(StrEnum):
    """Versioned realized-points policies supported by the evaluator."""

    STARTING_XI_CAPTAIN_V1 = "realized_squad_points_v1"
    OFFICIAL_AUTOSUB_CAPTAIN_V2 = "official_autosub_captain_v2"


@dataclass(frozen=True, slots=True)
class FrozenSquadDecision:
    """A complete, ordered squad decision that can be scored after settlement."""

    squad: pd.DataFrame
    starting_xi: tuple[object, ...]
    bench: tuple[object, ...]
    captain_id: object
    vice_captain_id: object
    completion_policy: str = "captured_entry_v1"

    def __post_init__(self) -> None:
        if not isinstance(self.squad, pd.DataFrame):
            raise EvaluationValidationError("squad must be a pandas DataFrame.")
        if not isinstance(self.completion_policy, str) or not self.completion_policy.strip():
            raise EvaluationValidationError("completion_policy must be a non-empty string.")
        object.__setattr__(self, "squad", self.squad.copy(deep=True))
        object.__setattr__(self, "starting_xi", tuple(self.starting_xi))
        object.__setattr__(self, "bench", tuple(self.bench))
        object.__setattr__(self, "completion_policy", self.completion_policy.strip())


@dataclass(frozen=True, slots=True)
class RealizedSquadScore:
    """Auditable result of applying one realized scoring policy."""

    policy: ScoringPolicy
    total_points: float
    final_xi: tuple[object, ...]
    autosubs: tuple[tuple[object, object], ...]
    captain_bonus_player_id: object | None
    captain_bonus_points: float
    autosub_points: float


def _freeze_metadata_value(value: object, path: str) -> object:
    """Return an immutable JSON-like copy of one metadata value."""

    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        number = float(value)
        if not math.isfinite(number):
            raise EvaluationValidationError(f"{path} must be finite, got {number!r}.")
        return number
    if isinstance(value, Mapping):
        return _freeze_metadata(value, path)
    if isinstance(value, list | tuple):
        return tuple(
            _freeze_metadata_value(item, f"{path}[{index}]") for index, item in enumerate(value)
        )
    raise EvaluationValidationError(
        f"{path} must be JSON-compatible metadata; got {type(value).__name__}."
    )


def _freeze_metadata(value: object, name: str) -> Mapping[str, object]:
    """Validate and recursively freeze a metadata mapping."""

    if not isinstance(value, Mapping):
        raise EvaluationValidationError(f"{name} must be a mapping.")

    frozen: dict[str, object] = {}
    invalid_keys = [key for key in value if not isinstance(key, str) or not key.strip()]
    if invalid_keys:
        raise EvaluationValidationError(
            f"{name} keys must be non-empty strings; got {invalid_keys!r}."
        )
    for key, item in value.items():
        frozen[key] = _freeze_metadata_value(item, f"{name}[{key!r}]")
    return MappingProxyType(frozen)


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    """Configuration shared by every prepared fold in one evaluation run."""

    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)
    scoring_policy: ScoringPolicy = ScoringPolicy.STARTING_XI_CAPTAIN_V1
    run_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise EvaluationValidationError(
                "optimization_config must be an OptimizationConfig instance."
            )
        if not isinstance(self.scoring_policy, ScoringPolicy):
            raise EvaluationValidationError("scoring_policy must be a ScoringPolicy value.")
        object.__setattr__(
            self,
            "run_metadata",
            _freeze_metadata(self.run_metadata, "run_metadata"),
        )


@dataclass(frozen=True, slots=True)
class EvaluationFold:
    """One pre-split gameweek projection table and its later realized outcomes.

    The class deliberately contains no training rows or split instructions. A
    time-aware data component will prepare these folds; this package only evaluates
    the frozen decisions they describe.
    """

    fold_id: str
    projections: pd.DataFrame
    realized_points: pd.DataFrame
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.fold_id, str) or not self.fold_id.strip():
            raise EvaluationValidationError("fold_id must be a non-empty string.")
        if not isinstance(self.projections, pd.DataFrame):
            raise EvaluationValidationError("projections must be a pandas DataFrame.")
        if not isinstance(self.realized_points, pd.DataFrame):
            raise EvaluationValidationError("realized_points must be a pandas DataFrame.")
        object.__setattr__(self, "fold_id", self.fold_id.strip())
        object.__setattr__(self, "projections", self.projections.copy(deep=True))
        object.__setattr__(self, "realized_points", self.realized_points.copy(deep=True))
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata, "metadata"))


@dataclass(frozen=True, slots=True)
class FoldEvaluationResult:
    """Decision and realized response for one evaluation fold."""

    fold_id: str
    optimization_result: OptimizationResult
    realized_squad_points: float | None
    squad_turnover: int | None
    metadata: Mapping[str, object]
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata, "metadata"))
        object.__setattr__(
            self,
            "diagnostics",
            _freeze_metadata(self.diagnostics, "diagnostics"),
        )

    @property
    def is_scored(self) -> bool:
        """Return whether the fold produced a feasible decision and realized score."""

        return self.realized_squad_points is not None


@dataclass(frozen=True, slots=True)
class EvaluationSummary:
    """Aggregate responses over an ordered collection of prepared folds."""

    attempted_folds: int
    feasible_folds: int
    scored_folds: int
    feasibility_rate: float
    mean_realized_squad_points: float | None
    realized_squad_points_stddev: float | None
    mean_projected_objective_value: float | None
    runtime_observations: int
    median_solver_runtime_seconds: float | None
    p95_solver_runtime_seconds: float | None
    turnover_observations: int
    mean_squad_turnover: float | None


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    """Complete ordered fold results and their aggregate summary."""

    config: EvaluationConfig
    folds: tuple[FoldEvaluationResult, ...]
    summary: EvaluationSummary
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "diagnostics",
            _freeze_metadata(self.diagnostics, "diagnostics"),
        )
