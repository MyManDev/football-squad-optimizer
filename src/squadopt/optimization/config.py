"""Typed and validated optimization configuration."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Literal, TypeAlias

from squadopt.optimization.models import InvalidConfigurationError

Position: TypeAlias = Literal["GK", "DEF", "MID", "FWD"]
POSITIONS: tuple[Position, ...] = ("GK", "DEF", "MID", "FWD")
MAX_DETERMINISTIC_SEED = 2_147_483_647


def _default_squad_position_limits() -> dict[Position, int]:
    return {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _default_starting_position_min() -> dict[Position, int]:
    return {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}


def _default_starting_position_max() -> dict[Position, int]:
    return {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}


def _require_integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise InvalidConfigurationError(f"{name} must be an integer, got {value!r}.")
    normalized = int(value)
    if normalized < minimum:
        raise InvalidConfigurationError(f"{name} must be at least {minimum}, got {normalized}.")
    return normalized


def _freeze_position_limits(
    limits: Mapping[Position, int],
    name: str,
) -> Mapping[Position, int]:
    if not isinstance(limits, Mapping):
        raise InvalidConfigurationError(f"{name} must be a position-to-integer mapping.")

    actual_keys = set(limits)
    expected_keys = set(POSITIONS)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        raise InvalidConfigurationError(
            f"{name} must contain exactly {list(POSITIONS)}; " + ", ".join(details)
        )

    copied: dict[Position, int] = {}
    for position in POSITIONS:
        copied[position] = _require_integer(
            limits[position],
            f"{name}[{position!r}]",
            minimum=0,
        )
    return MappingProxyType(copied)


@dataclass(frozen=True, slots=True)
class OptimizationConfig:
    """Configuration for a single-gameweek squad optimization."""

    budget_tenths: int = 1000
    squad_size: int = 15
    squad_position_limits: Mapping[Position, int] = field(
        default_factory=_default_squad_position_limits
    )
    starting_size: int = 11
    starting_position_min: Mapping[Position, int] = field(
        default_factory=_default_starting_position_min
    )
    starting_position_max: Mapping[Position, int] = field(
        default_factory=_default_starting_position_max
    )
    max_players_per_team: int = 3
    bench_weight: float = 0.1
    expected_points_scale: int = 1000
    solver_time_limit_seconds: float = 10.0
    solver_deterministic_time_limit: float | None = None
    deterministic_seed: int = 0

    def __post_init__(self) -> None:
        budget = _require_integer(self.budget_tenths, "budget_tenths", minimum=0)
        squad_size = _require_integer(self.squad_size, "squad_size", minimum=1)
        starting_size = _require_integer(self.starting_size, "starting_size", minimum=1)
        team_limit = _require_integer(
            self.max_players_per_team,
            "max_players_per_team",
            minimum=1,
        )
        points_scale = _require_integer(
            self.expected_points_scale,
            "expected_points_scale",
            minimum=1,
        )
        seed = _require_integer(self.deterministic_seed, "deterministic_seed", minimum=0)
        if seed > MAX_DETERMINISTIC_SEED:
            raise InvalidConfigurationError(
                f"deterministic_seed must be at most {MAX_DETERMINISTIC_SEED}, got {seed}."
            )

        if isinstance(self.bench_weight, bool) or not isinstance(self.bench_weight, Real):
            raise InvalidConfigurationError("bench_weight must be a finite real number.")
        bench_weight = float(self.bench_weight)
        if not math.isfinite(bench_weight) or not 0.0 <= bench_weight <= 1.0:
            raise InvalidConfigurationError(
                f"bench_weight must be between 0 and 1 inclusive, got {bench_weight!r}."
            )

        if isinstance(self.solver_time_limit_seconds, bool) or not isinstance(
            self.solver_time_limit_seconds, Real
        ):
            raise InvalidConfigurationError(
                "solver_time_limit_seconds must be a finite positive real number."
            )
        time_limit = float(self.solver_time_limit_seconds)
        if not math.isfinite(time_limit) or time_limit <= 0.0:
            raise InvalidConfigurationError(
                "solver_time_limit_seconds must be a finite positive real number."
            )

        deterministic_time_limit = self.solver_deterministic_time_limit
        if deterministic_time_limit is not None:
            if isinstance(deterministic_time_limit, bool) or not isinstance(
                deterministic_time_limit, Real
            ):
                raise InvalidConfigurationError(
                    "solver_deterministic_time_limit must be None or a finite positive real number."
                )
            deterministic_time_limit = float(deterministic_time_limit)
            if not math.isfinite(deterministic_time_limit) or deterministic_time_limit <= 0.0:
                raise InvalidConfigurationError(
                    "solver_deterministic_time_limit must be None or a finite positive real number."
                )

        squad_limits = _freeze_position_limits(
            self.squad_position_limits,
            "squad_position_limits",
        )
        starting_min = _freeze_position_limits(
            self.starting_position_min,
            "starting_position_min",
        )
        starting_max = _freeze_position_limits(
            self.starting_position_max,
            "starting_position_max",
        )

        if sum(squad_limits.values()) != squad_size:
            raise InvalidConfigurationError(
                "squad_size must equal the sum of squad_position_limits."
            )
        if starting_size >= squad_size:
            raise InvalidConfigurationError("starting_size must be smaller than squad_size.")

        for position in POSITIONS:
            minimum = starting_min[position]
            maximum = starting_max[position]
            squad_limit = squad_limits[position]
            if minimum > maximum:
                raise InvalidConfigurationError(
                    f"starting_position_min[{position!r}] cannot exceed "
                    f"starting_position_max[{position!r}]."
                )
            if maximum > squad_limit:
                raise InvalidConfigurationError(
                    f"starting_position_max[{position!r}] cannot exceed "
                    f"squad_position_limits[{position!r}]."
                )

        if starting_min["GK"] != 1 or starting_max["GK"] != 1:
            raise InvalidConfigurationError("Sprint 0 requires exactly one starting goalkeeper.")
        if not sum(starting_min.values()) <= starting_size <= sum(starting_max.values()):
            raise InvalidConfigurationError(
                "starting_size must be between the sums of the starting position minima and maxima."
            )

        object.__setattr__(self, "budget_tenths", budget)
        object.__setattr__(self, "squad_size", squad_size)
        object.__setattr__(self, "squad_position_limits", squad_limits)
        object.__setattr__(self, "starting_size", starting_size)
        object.__setattr__(self, "starting_position_min", starting_min)
        object.__setattr__(self, "starting_position_max", starting_max)
        object.__setattr__(self, "max_players_per_team", team_limit)
        object.__setattr__(self, "bench_weight", bench_weight)
        object.__setattr__(self, "expected_points_scale", points_scale)
        object.__setattr__(self, "solver_time_limit_seconds", time_limit)
        object.__setattr__(
            self,
            "solver_deterministic_time_limit",
            deterministic_time_limit,
        )
        object.__setattr__(self, "deterministic_seed", seed)
