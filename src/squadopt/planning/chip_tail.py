"""Explicit dated chip opportunities and exact finite-calendar right allocation.

Values are declared marginal selection utilities, not inferred from the current
window or from how many weeks remain. This is a calendar assignment model, not a
season policy: it cannot predict future squads, news or Wildcard carry-over.
"""

import hashlib
import json
import math
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from functools import cache
from itertools import pairwise

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
)

MAX_TAIL_RIGHTS = 8


def chip_tail_context_fingerprint(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    preferences: DecisionPreferences | None,
    *,
    expected_lineups: bool,
) -> str:
    """Bind values to the decision state, objective and human constraints.

    Solver budgets/seeds are deliberately excluded; they do not define utility.
    Player purchase/sale prices and forecasts are bound by the horizon digest.
    """
    config = {
        f.name: dict(value) if hasattr(value, "items") else value
        for f in fields(optimization)
        if not f.name.startswith("solver_") and f.name != "deterministic_seed"
        for value in (getattr(optimization, f.name),)
    }
    payload = {
        "horizon": horizon.horizon_fingerprint,
        "squad": sorted((type(p).__name__, str(p)) for p in initial.squad_player_ids),
        "bank": initial.bank_tenths,
        "ft": initial.free_transfers,
        "optimization": config,
        "transfer": transfer.configuration_fingerprint,
        "preferences": None
        if preferences is None
        else {
            f.name: sorted(value) if isinstance(value, (set, frozenset, tuple)) else value
            for f in fields(preferences)
            for value in (getattr(preferences, f.name),)
        },
        "basis": "expected_lineup_selection_utility"
        if expected_lineups
        else "linear_selection_utility",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class DatedChipOpportunity:
    chip: str
    gameweek: int
    deadline: datetime
    marginal_utility: float


@dataclass(frozen=True)
class ChipTailForecast:
    """Operator-validated complete opportunity calendar for all remaining rights.

    ``source_fingerprint`` identifies the external evidence/forecast; the caller
    must verify it before construction. A hash alone is not a calibration claim.
    Every legal future chip/date needs an explicit value, including explicit zero.
    """

    context_fingerprint: str
    source_fingerprint: str
    as_of: datetime
    opportunities: tuple[DatedChipOpportunity, ...]


@dataclass(frozen=True)
class ChipTailTable:
    rights: tuple[tuple[str, frozenset[int]], ...]
    # used-right bitmask, whether the horizon ends on FH, undiscounted value.
    values: tuple[tuple[int, int, float], ...]
    horizon_end: int
    availability_fingerprint: str
    source_fingerprint: str

    @property
    def fingerprint(self) -> str:
        payload = {
            "rights": [(name, sorted(weeks)) for name, weeks in self.rights],
            "values": self.values,
            "horizon_end": self.horizon_end,
            "availability": self.availability_fingerprint,
            "source": self.source_fingerprint,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def value(self, chips_played: dict[int, str]) -> float:
        mask = sum(
            1 << i
            for i, (name, weeks) in enumerate(self.rights)
            if any(chip == name and gw in weeks for gw, chip in chips_played.items())
        )
        last_fh = int(chips_played.get(self.horizon_end) == "freehit")
        for used, fh, value in self.values:
            if used == mask and fh == last_fh:
                return value
        raise ValueError("Current chip schedule conflicts with a forced future right.")


def _utc(value: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() == UTC.utcoffset(value)
    )


def build_chip_tail_table(
    chips: ChipAvailability,
    horizon_end: int,
    forecast: ChipTailForecast | None,
    *,
    context_fingerprint: str,
) -> ChipTailTable:
    """Allocate dated rights jointly, respecting expiry, renewal and FH adjacency.

    At most 8 rights (256 subsets x two boundary states) and 38 dated weeks;
    memoized assignment does no CP solve and introduces no arrival probability.
    """
    rights = tuple(
        (name, period.gameweeks)
        for name in sorted(chips.available)
        for period in chips.windows_for(name)
    )
    if (
        isinstance(horizon_end, bool)
        or not isinstance(horizon_end, int)
        or not 1 <= horizon_end <= 38
    ):
        raise ValueError("Chip tail horizon end must be a gameweek from 1 to 38.")
    if len(rights) > MAX_TAIL_RIGHTS:
        raise ValueError("Explicit chip tail supports at most eight dated rights.")
    required = {(name, gw) for name, weeks in rights for gw in weeks if gw > horizon_end}
    if not required:
        if forecast is not None and forecast.opportunities:
            raise ValueError("Chip tail supplied opportunities outside remaining rights.")
        return ChipTailTable(
            rights,
            tuple((mask, fh, 0.0) for mask in range(1 << len(rights)) for fh in (0, 1)),
            horizon_end,
            chips.availability_fingerprint,
            "",
        )
    if forecast is None:
        raise ValueError("Automatic chips require a validated dated future opportunity tail.")
    if forecast.context_fingerprint != context_fingerprint:
        raise ValueError("Chip tail context differs from the decision state or score basis.")
    if len(forecast.source_fingerprint) != 64 or any(
        c not in "0123456789abcdef" for c in forecast.source_fingerprint
    ):
        raise ValueError("Chip tail requires an evidence SHA256 fingerprint.")
    if not _utc(forecast.as_of):
        raise ValueError("Chip tail as_of must be a UTC instant.")
    gains: dict[tuple[str, int], float] = {}
    dates: dict[int, datetime] = {}
    for item in forecast.opportunities:
        key = (item.chip, item.gameweek)
        if (
            isinstance(item.gameweek, bool)
            or not isinstance(item.gameweek, int)
            or not 1 <= item.gameweek <= 38
            or key not in required
            or key in gains
        ):
            raise ValueError("Chip tail dates must uniquely match remaining rights.")
        if not _utc(item.deadline) or item.deadline <= forecast.as_of:
            raise ValueError("Chip tail opportunities require future UTC deadlines.")
        if item.gameweek in dates and dates[item.gameweek] != item.deadline:
            raise ValueError("One gameweek cannot have conflicting deadlines.")
        if (
            isinstance(item.marginal_utility, bool)
            or not math.isfinite(item.marginal_utility)
            or item.marginal_utility < 0
        ):
            raise ValueError("Chip opportunity utility must be finite and non-negative.")
        dates[item.gameweek] = item.deadline
        gains[key] = float(item.marginal_utility)
    if set(gains) != required:
        raise ValueError("Chip tail must cover every remaining legal date explicitly.")
    weeks = sorted(dates)
    if any(dates[a] >= dates[b] for a, b in pairwise(weeks)):
        raise ValueError("Chip tail deadlines must follow gameweek order.")

    @cache
    def allocate(index: int, used: int, last_fh_week: int) -> float | None:
        if index == len(weeks):
            return 0.0
        gw = weeks[index]
        forced = chips.forced.get(gw)
        choices: list[float] = []
        if forced is None:
            held = allocate(index + 1, used, last_fh_week)
            if held is not None:
                choices.append(held)
        for i, (name, available) in enumerate(rights):
            if used & (1 << i) or gw not in available or (forced is not None and forced != name):
                continue
            if name == "freehit" and last_fh_week == gw - 1:
                continue
            rest = allocate(index + 1, used | (1 << i), gw if name == "freehit" else last_fh_week)
            if rest is not None:
                choices.append(gains[name, gw] + rest)
        return max(choices) if choices else None

    values = []
    for mask in range(1 << len(rights)):
        for fh in (0, 1):
            value = allocate(0, mask, horizon_end if fh else -1)
            if value is not None:
                if not math.isfinite(value):
                    raise ValueError("Joint chip opportunity utility exceeds the finite range.")
                values.append((mask, fh, value))
    return ChipTailTable(
        rights,
        tuple(values),
        horizon_end,
        chips.availability_fingerprint,
        forecast.source_fingerprint,
    )
