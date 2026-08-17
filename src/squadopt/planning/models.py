"""Public contracts for deterministic multi-gameweek transfer planning."""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.optimization import SolverStatus
from squadopt.optimization.config import POSITIONS

PLANNING_HORIZON_CONTRACT_VERSION: Final = "planning_horizon_v1"
TRANSFER_PLANNING_CONTRACT_VERSION: Final = "deterministic_transfer_planning_v2"
# The chips this planner models. Free hit arrived with contract v2: it makes one week's
# squad temporary and restores the previous squad and bank the week after, which the
# model carries as a per-week "base" state that reverts under the chip.
CHIP_NAMES_V1: Final = ("bboost", "3xc", "wildcard")
CHIP_NAMES_V2: Final = ("bboost", "3xc", "wildcard", "freehit")
CHIP_NAMES: Final = CHIP_NAMES_V2
PLANNING_HORIZON_COLUMNS: Final = (
    "gameweek",
    "player_id",
    "name",
    "team_id",
    "position",
    "buy_price_tenths",
    "sell_price_tenths",
    "expected_points",
)


class TransferPlanningError(Exception):
    """Base exception for multi-gameweek transfer planning."""


class TransferPlanningConfigurationError(TransferPlanningError):
    """Raised when transfer-planning controls are inconsistent."""


class TransferPlanningValidationError(TransferPlanningError):
    """Raised when horizon or initial-state data violate the public contract."""


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TransferPlanningConfigurationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise TransferPlanningConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


def _state_integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise TransferPlanningValidationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise TransferPlanningValidationError(f"{name} must be at least {minimum}.")
    return normalized


def _finite(value: object, name: str, *, minimum: float, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TransferPlanningConfigurationError(f"{name} must be a finite number.")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < minimum:
        raise TransferPlanningConfigurationError(f"{name} must be at least {minimum}.")
    if maximum is not None and normalized > maximum:
        raise TransferPlanningConfigurationError(f"{name} must be at most {maximum}.")
    return normalized


def _identifier_kind(value: object, name: str) -> str:
    if isinstance(value, bool):
        raise TransferPlanningValidationError(f"{name} may not contain boolean identifiers.")
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, str) and value:
        return "string"
    raise TransferPlanningValidationError(f"{name} must contain non-empty string or integer IDs.")


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def _stable_id_key(value: object) -> int | str:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    return str(value)


def _horizon_fingerprint(table: pd.DataFrame, contract_version: str) -> str:
    rows: list[dict[str, object]] = []
    for gameweek in sorted(int(value) for value in table["gameweek"].unique().tolist()):
        week = table.loc[table["gameweek"] == gameweek]
        player_ids = week["player_id"].tolist()
        order = sorted(range(len(week)), key=lambda index: _stable_id_key(player_ids[index]))
        for index in order:
            row = week.iloc[index]
            rows.append(
                {
                    "gameweek": gameweek,
                    "player_id": _typed_identifier(row["player_id"]),
                    "name": str(row["name"]),
                    "team_id": _typed_identifier(row["team_id"]),
                    "position": str(row["position"]),
                    "buy_price_tenths": int(row["buy_price_tenths"]),
                    "sell_price_tenths": int(row["sell_price_tenths"]),
                    "expected_points": float(row["expected_points"]).hex(),
                }
            )
    payload = {"contract_version": contract_version, "rows": rows}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanningHorizon:
    """Exact per-gameweek projection and transaction-price table."""

    table: pd.DataFrame
    contract_version: str = PLANNING_HORIZON_CONTRACT_VERSION
    horizon_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.contract_version != PLANNING_HORIZON_CONTRACT_VERSION:
            raise TransferPlanningValidationError("Unsupported planning horizon contract_version.")
        if not isinstance(self.table, pd.DataFrame):
            raise TransferPlanningValidationError("table must be a pandas DataFrame.")
        if self.table.columns.duplicated().any():
            raise TransferPlanningValidationError("Planning horizon columns must be unique.")
        missing = [column for column in PLANNING_HORIZON_COLUMNS if column not in self.table]
        if missing:
            raise TransferPlanningValidationError(
                f"Planning horizon is missing required columns: {missing!r}."
            )
        table = self.table.copy(deep=True)
        if table.empty:
            raise TransferPlanningValidationError("Planning horizon must contain at least one row.")
        if bool(table.loc[:, PLANNING_HORIZON_COLUMNS].isna().any().any()):
            raise TransferPlanningValidationError(
                "Planning horizon required columns may not be missing."
            )

        gameweeks: list[int] = []
        for value in table["gameweek"].tolist():
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
                raise TransferPlanningValidationError("gameweek must contain positive integers.")
            gameweeks.append(int(value))
        table.loc[:, "gameweek"] = gameweeks
        ordered_gameweeks = tuple(sorted(set(gameweeks)))
        expected_gameweeks = tuple(range(ordered_gameweeks[0], ordered_gameweeks[-1] + 1))
        if ordered_gameweeks != expected_gameweeks:
            raise TransferPlanningValidationError("Planning gameweeks must be consecutive.")
        if bool(table.duplicated(subset=["gameweek", "player_id"]).any()):
            raise TransferPlanningValidationError("Each (gameweek, player_id) row must be unique.")

        player_kinds = {_identifier_kind(value, "player_id") for value in table["player_id"]}
        team_kinds = {_identifier_kind(value, "team_id") for value in table["team_id"]}
        if len(player_kinds) != 1:
            raise TransferPlanningValidationError("player_id must use one consistent ID type.")
        if len(team_kinds) != 1:
            raise TransferPlanningValidationError("team_id must use one consistent ID type.")
        if any(not isinstance(value, str) or not value.strip() for value in table["name"]):
            raise TransferPlanningValidationError("name must contain non-empty strings.")
        invalid_positions = sorted(set(table["position"]) - set(POSITIONS), key=str)
        if invalid_positions:
            raise TransferPlanningValidationError(
                f"position contains unsupported values: {invalid_positions!r}."
            )

        for column in ("buy_price_tenths", "sell_price_tenths"):
            normalized_prices: list[int] = []
            for value in table[column].tolist():
                if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
                    raise TransferPlanningValidationError(
                        f"{column} must contain non-negative integers."
                    )
                normalized_prices.append(int(value))
            table.loc[:, column] = normalized_prices
        if bool((table["sell_price_tenths"] > table["buy_price_tenths"]).any()):
            raise TransferPlanningValidationError(
                "sell_price_tenths may not exceed buy_price_tenths."
            )

        normalized_points: list[float] = []
        for value in table["expected_points"].tolist():
            if isinstance(value, bool) or not isinstance(value, Real):
                raise TransferPlanningValidationError(
                    "expected_points must contain finite non-negative numbers."
                )
            points = float(value)
            if not math.isfinite(points) or points < 0.0:
                raise TransferPlanningValidationError(
                    "expected_points must contain finite non-negative numbers."
                )
            normalized_points.append(points)
        table.loc[:, "expected_points"] = normalized_points

        first_ids = set(table.loc[table["gameweek"] == ordered_gameweeks[0], "player_id"])
        for gameweek in ordered_gameweeks[1:]:
            observed = set(table.loc[table["gameweek"] == gameweek, "player_id"])
            if observed != first_ids:
                missing_ids = sorted(first_ids - observed, key=str)
                extra_ids = sorted(observed - first_ids, key=str)
                raise TransferPlanningValidationError(
                    "Every planning gameweek must contain the same player universe; "
                    f"gameweek={gameweek}, missing={missing_ids[:10]!r}, "
                    f"extra={extra_ids[:10]!r}."
                )

        fingerprint = _horizon_fingerprint(table, self.contract_version)
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "horizon_fingerprint", fingerprint)

    @property
    def gameweeks(self) -> tuple[int, ...]:
        """Return the consecutive gameweek labels in decision order."""

        return tuple(sorted(int(value) for value in self.table["gameweek"].unique().tolist()))

    def validated_copy(self) -> "PlanningHorizon":
        """Revalidate mutable table state and return an independent horizon."""

        verified = PlanningHorizon(self.table, self.contract_version)
        if verified.horizon_fingerprint != self.horizon_fingerprint:
            raise TransferPlanningValidationError(
                "horizon_fingerprint no longer matches the mutable planning table."
            )
        return verified


@dataclass(frozen=True, slots=True)
class InitialSquadState:
    """Squad, bank, and free transfers available before the first planned deadline."""

    squad_player_ids: Sequence[object]
    bank_tenths: int = 0
    free_transfers: int = 1

    def __post_init__(self) -> None:
        if isinstance(self.squad_player_ids, str | bytes) or not isinstance(
            self.squad_player_ids, Sequence
        ):
            raise TransferPlanningValidationError("squad_player_ids must be a sequence of IDs.")
        player_ids = tuple(self.squad_player_ids)
        if not player_ids:
            raise TransferPlanningValidationError("squad_player_ids may not be empty.")
        kinds = {_identifier_kind(value, "squad_player_ids") for value in player_ids}
        if len(kinds) != 1:
            raise TransferPlanningValidationError(
                "squad_player_ids must use one consistent ID type."
            )
        if len(set(player_ids)) != len(player_ids):
            raise TransferPlanningValidationError("squad_player_ids may not contain duplicates.")
        object.__setattr__(self, "squad_player_ids", player_ids)
        object.__setattr__(
            self,
            "bank_tenths",
            _state_integer(self.bank_tenths, "bank_tenths", 0),
        )
        object.__setattr__(
            self,
            "free_transfers",
            _state_integer(self.free_transfers, "free_transfers", 0),
        )


@dataclass(frozen=True, slots=True)
class ChipAvailability:
    """Which chips the planner may play in which gameweeks of one horizon.

    ``available`` maps a chip name to the gameweeks it may be played in; a chip absent
    from the mapping is not available. ``forced`` pins a chip to a gameweek — the
    hand-timed case — and a forced chip must also be available there. The caller
    derives both from the season's published rules and the chips already used; the
    planner does not know about seasons or halves, only about this horizon, and it
    plays each available chip at most once inside it. An empty availability is the
    chip-less planner exactly.
    """

    available: Mapping[str, frozenset[int]] = field(default_factory=dict)
    forced: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        available: dict[str, frozenset[int]] = {}
        for name, gameweeks in dict(self.available).items():
            if name not in CHIP_NAMES:
                raise TransferPlanningValidationError(
                    f"Unknown chip {name!r}; this planner models {CHIP_NAMES!r}."
                )
            weeks = frozenset(_state_integer(week, f"{name} gameweek", 1) for week in gameweeks)
            if weeks:
                available[name] = weeks
        forced: dict[int, str] = {}
        for week, name in dict(self.forced).items():
            gameweek = _state_integer(week, "forced chip gameweek", 1)
            if name not in CHIP_NAMES:
                raise TransferPlanningValidationError(f"Unknown forced chip {name!r}.")
            if gameweek not in available.get(name, frozenset()):
                raise TransferPlanningValidationError(
                    f"Forced chip {name!r} in gameweek {gameweek} is not available there."
                )
            forced[gameweek] = name
        object.__setattr__(self, "available", MappingProxyType(available))
        object.__setattr__(self, "forced", MappingProxyType(forced))

    @property
    def is_empty(self) -> bool:
        return not self.available

    def gameweeks_for(self, name: str) -> frozenset[int]:
        return self.available.get(name, frozenset())

    @property
    def availability_fingerprint(self) -> str:
        """Stable digest of the availability and any forced plays."""

        payload = {
            "available": {name: sorted(weeks) for name, weeks in self.available.items()},
            "forced": {str(week): name for week, name in sorted(self.forced.items())},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TransferPlanningConfig:
    """Controls transfer accounting and deterministic horizon weighting.

    ``wildcard_preserves_free_transfers`` states the rule this planner assumes for a
    wildcard week: transfers made under the chip do not consume banked free transfers,
    and accrual continues as usual. It is a flag rather than a constant because the
    source's payload does not publish it; if the rule turns out otherwise, one flag
    changes and nothing else.
    """

    max_free_transfers: int = 5
    free_transfer_accrual: int = 1
    transfer_hit_cost_points: float = 4.0
    horizon_discount_factor: float = 1.0
    objective_weight_scale: int = 1_000
    wildcard_preserves_free_transfers: bool = True
    max_transfers_per_gameweek: int | None = None
    """Transfer discipline: at most this many transfers in any gameweek (a wildcard
    week is exempt); None leaves the count to the objective and the hit cost."""
    banked_transfer_value_points: float = 0.0
    """Terminal value of each free transfer banked past the horizon's last gameweek,
    in points. Zero means an unused free transfer at the end is worth nothing to the
    plan — the myopic default, which spends a free transfer on any positive gain."""
    chip_holding_value_points: Mapping[str, float] = field(default_factory=dict)
    """Terminal value, in points, of each named chip left unplayed past the horizon:
    the option value a finite horizon cannot otherwise see, so a chip is played only
    when what it buys inside the horizon exceeds it. Absent chips hold no value — the
    default, under which a horizon plays a chip worth anything now."""
    contract_version: str = TRANSFER_PLANNING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != TRANSFER_PLANNING_CONTRACT_VERSION:
            raise TransferPlanningConfigurationError(
                "contract_version does not match the implemented transfer planner."
            )
        if not isinstance(self.wildcard_preserves_free_transfers, bool):
            raise TransferPlanningConfigurationError(
                "wildcard_preserves_free_transfers must be a boolean."
            )
        if self.max_transfers_per_gameweek is not None:
            object.__setattr__(
                self,
                "max_transfers_per_gameweek",
                _integer(self.max_transfers_per_gameweek, "max_transfers_per_gameweek", 1),
            )
        object.__setattr__(
            self,
            "banked_transfer_value_points",
            _finite(self.banked_transfer_value_points, "banked_transfer_value_points", minimum=0.0),
        )
        holding: dict[str, float] = {}
        for name, value in dict(self.chip_holding_value_points).items():
            if name not in CHIP_NAMES:
                raise TransferPlanningConfigurationError(
                    f"chip_holding_value_points names unknown chip {name!r}."
                )
            holding[name] = _finite(value, f"chip_holding_value_points[{name}]", minimum=0.0)
        object.__setattr__(self, "chip_holding_value_points", MappingProxyType(holding))
        maximum = _integer(self.max_free_transfers, "max_free_transfers", 1)
        accrual = _integer(self.free_transfer_accrual, "free_transfer_accrual", 0)
        if accrual > maximum:
            raise TransferPlanningConfigurationError(
                "free_transfer_accrual may not exceed max_free_transfers."
            )
        object.__setattr__(self, "max_free_transfers", maximum)
        object.__setattr__(self, "free_transfer_accrual", accrual)
        object.__setattr__(
            self,
            "transfer_hit_cost_points",
            _finite(self.transfer_hit_cost_points, "transfer_hit_cost_points", minimum=0.0),
        )
        object.__setattr__(
            self,
            "horizon_discount_factor",
            _finite(
                self.horizon_discount_factor,
                "horizon_discount_factor",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if self.horizon_discount_factor <= 0.0:
            raise TransferPlanningConfigurationError(
                "horizon_discount_factor must be strictly positive."
            )
        object.__setattr__(
            self,
            "objective_weight_scale",
            _integer(self.objective_weight_scale, "objective_weight_scale", 1),
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every transfer-planning control."""

        payload = {
            "contract_version": self.contract_version,
            "max_free_transfers": self.max_free_transfers,
            "free_transfer_accrual": self.free_transfer_accrual,
            "transfer_hit_cost_points": float(self.transfer_hit_cost_points).hex(),
            "horizon_discount_factor": float(self.horizon_discount_factor).hex(),
            "objective_weight_scale": self.objective_weight_scale,
            "wildcard_preserves_free_transfers": self.wildcard_preserves_free_transfers,
            "max_transfers_per_gameweek": self.max_transfers_per_gameweek,
            "banked_transfer_value_points": float(self.banked_transfer_value_points).hex(),
            "chip_holding_value_points": {
                name: float(value).hex()
                for name, value in sorted(self.chip_holding_value_points.items())
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PlanningWeekResult:
    """One deadline's decision and state transition."""

    gameweek: int
    selected_squad: pd.DataFrame
    starting_xi: pd.DataFrame
    bench: pd.DataFrame
    captain: pd.Series
    transfers_in: pd.DataFrame
    transfers_out: pd.DataFrame
    bank_before_tenths: int
    bank_after_tenths: int
    free_transfers_before: int
    free_transfers_unused: int
    free_transfers_for_next_gameweek: int
    transfer_count: int
    paid_transfer_count: int
    transfer_hit_points: float
    projected_score: float
    projected_bench_points: float
    discounted_objective_contribution: float
    chip: str | None = None

    def __post_init__(self) -> None:
        if self.chip is not None and self.chip not in CHIP_NAMES:
            raise TransferPlanningValidationError(f"Unknown chip {self.chip!r} on a week result.")
        for name in ("selected_squad", "starting_xi", "bench", "transfers_in", "transfers_out"):
            value = getattr(self, name)
            if not isinstance(value, pd.DataFrame):
                raise TransferPlanningValidationError(f"{name} must be a pandas DataFrame.")
            object.__setattr__(self, name, value.reset_index(drop=True).copy(deep=True))
        if not isinstance(self.captain, pd.Series):
            raise TransferPlanningValidationError("captain must be a pandas Series.")
        object.__setattr__(self, "captain", self.captain.copy(deep=True))


@dataclass(frozen=True, slots=True)
class TransferPlanResult:
    """Structured multi-gameweek plan with solver-independent status."""

    solver_status: SolverStatus
    weeks: tuple[PlanningWeekResult, ...]
    horizon_fingerprint: str
    total_projected_score: float | None
    total_projected_bench_points: float | None
    total_transfer_hit_points: float | None
    objective_value: float | None
    diagnostics: Mapping[str, object]
    contract_version: str = TRANSFER_PLANNING_CONTRACT_VERSION
    chips_played: Mapping[int, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract_version != TRANSFER_PLANNING_CONTRACT_VERSION:
            raise TransferPlanningValidationError("Unsupported transfer plan contract_version.")
        played = {int(week): str(name) for week, name in dict(self.chips_played).items()}
        if any(name not in CHIP_NAMES for name in played.values()):
            raise TransferPlanningValidationError("chips_played names an unknown chip.")
        object.__setattr__(self, "chips_played", MappingProxyType(played))
        if not isinstance(self.solver_status, SolverStatus):
            raise TransferPlanningValidationError("solver_status must be a SolverStatus.")
        if (
            not isinstance(self.horizon_fingerprint, str)
            or len(self.horizon_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.horizon_fingerprint)
        ):
            raise TransferPlanningValidationError(
                "horizon_fingerprint must be a lowercase SHA-256 digest."
            )
        metrics = (
            self.total_projected_score,
            self.total_projected_bench_points,
            self.total_transfer_hit_points,
            self.objective_value,
        )
        if self.has_solution:
            if not self.weeks or any(
                value is None or not math.isfinite(value) for value in metrics
            ):
                raise TransferPlanningValidationError(
                    "A feasible transfer plan must carry weeks and finite metrics."
                )
        elif self.weeks or any(value is not None for value in metrics):
            raise TransferPlanningValidationError(
                "A transfer plan without a solution may not carry decisions or metrics."
            )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def has_solution(self) -> bool:
        """Return whether the solver produced a feasible horizon plan."""

        return self.solver_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
