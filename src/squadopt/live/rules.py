"""The season's rules as the source publishes them, read from a capture.

Scoring values, chip availability, and transfer limits change between seasons — 2025-26
added defensive-contribution points and 2026-27 values a goalkeeper's goal at ten — and
the source publishes the current set inside its bootstrap payload (`game_config`,
`chips`, `game_settings`). Reading them from the capture instead of hard-coding them
does two things: a decision can record which rule set it was made under, and a planner
that models chips or sell-on fees can take the season's numbers rather than last
season's.

This module reads and validates; it does not interpret. What a defensive contribution
requires (the CBIT threshold) is not in the payload, so it is not here either.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.planning import CHIP_NAMES as PLANNER_CHIP_NAMES
from squadopt.planning import ChipAvailability

SEASON_RULES_CONTRACT_VERSION: Final = "season_rules_v1"
POSITIONS: Final = ("GKP", "DEF", "MID", "FWD")
CHIP_NAMES: Final = ("wildcard", "freehit", "bboost", "3xc")


class SeasonRulesError(DataError):
    """Raised when the capture's rules block is missing, malformed, or inconsistent."""


@dataclass(frozen=True, slots=True)
class ChipWindow:
    """One availability window of one chip: usable ``number`` times in [start, stop]."""

    name: str
    number: int
    start_event: int
    stop_event: int
    chip_type: str

    def __post_init__(self) -> None:
        if self.name not in CHIP_NAMES:
            raise SeasonRulesError(f"Unknown chip {self.name!r}.")
        if self.number < 1:
            raise SeasonRulesError(f"Chip {self.name!r} must be usable at least once.")
        if not 1 <= self.start_event <= self.stop_event <= 38:
            raise SeasonRulesError(
                f"Chip {self.name!r} window {self.start_event}-{self.stop_event} is invalid."
            )
        if self.chip_type not in ("transfer", "team"):
            raise SeasonRulesError(f"Chip {self.name!r} has unknown type {self.chip_type!r}.")

    def covers(self, gameweek: int) -> bool:
        return self.start_event <= gameweek <= self.stop_event


@dataclass(frozen=True, slots=True)
class TransferRules:
    squad_size: int
    starting_size: int
    team_limit: int
    budget_tenths: int
    max_extra_free_transfers: int
    transfers_cap: int | None
    sell_on_fee: float
    sell_at_purchase_price: bool

    def __post_init__(self) -> None:
        for name in ("squad_size", "starting_size", "team_limit", "budget_tenths"):
            if getattr(self, name) < 1:
                raise SeasonRulesError(f"{name} must be positive.")
        if self.max_extra_free_transfers < 0:
            raise SeasonRulesError("max_extra_free_transfers may not be negative.")
        if not 0.0 <= self.sell_on_fee <= 1.0:
            raise SeasonRulesError("sell_on_fee must lie in [0, 1].")

    @property
    def max_free_transfers(self) -> int:
        """The most free transfers a manager can hold: one plus the extra bank."""

        return 1 + self.max_extra_free_transfers


@dataclass(frozen=True, slots=True)
class ScoringRules:
    """Per-action point values, position-keyed where the source keys them."""

    long_play: int
    short_play: int
    assists: int
    saves: int
    penalties_saved: int
    penalties_missed: int
    yellow_cards: int
    red_cards: int
    own_goals: int
    bonus: int
    goals_scored: Mapping[str, int]
    clean_sheets: Mapping[str, int]
    goals_conceded: Mapping[str, int]
    defensive_contribution: Mapping[str, int]

    def __post_init__(self) -> None:
        for name in ("goals_scored", "clean_sheets", "goals_conceded", "defensive_contribution"):
            table = getattr(self, name)
            missing = [position for position in POSITIONS if position not in table]
            if missing:
                raise SeasonRulesError(f"scoring.{name} lacks positions {missing!r}.")
            object.__setattr__(self, name, MappingProxyType(dict(table)))

    @property
    def awards_defensive_contribution(self) -> bool:
        return any(value != 0 for value in self.defensive_contribution.values())


@dataclass(frozen=True, slots=True)
class SeasonRules:
    contract_version: str
    season: str
    source_snapshot_id: str
    scoring: ScoringRules
    transfers: TransferRules
    chips: tuple[ChipWindow, ...]
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.contract_version != SEASON_RULES_CONTRACT_VERSION:
            raise SeasonRulesError("Unsupported season rules contract_version.")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    def chips_available(self, gameweek: int) -> tuple[ChipWindow, ...]:
        """Chip windows that cover ``gameweek``, in the order the source lists them."""

        return tuple(window for window in self.chips if window.covers(gameweek))

    @property
    def fingerprint(self) -> str:
        """SHA-256 of the canonical rules payload; equal fingerprints mean equal rules."""

        return hashlib.sha256(
            json.dumps(rules_to_dict(self, include_provenance=False), sort_keys=True).encode()
        ).hexdigest()


def _int(mapping: Mapping[str, object], key: str, label: str) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SeasonRulesError(f"{label}.{key} is missing or not numeric.")
    if float(value) != int(value):
        raise SeasonRulesError(f"{label}.{key} must be an integer.")
    return int(value)


def _position_table(mapping: Mapping[str, object], key: str) -> dict[str, int]:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        raise SeasonRulesError(f"scoring.{key} must be a position-keyed table.")
    return {str(position): _int(value, str(position), f"scoring.{key}") for position in value}


def read_season_rules(snapshot: CapturedSnapshot, *, season: str) -> SeasonRules:
    """Read the season's rules from a capture's bootstrap payload."""

    payload = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if payload is None:
        raise SeasonRulesError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no bootstrap payload."
        )
    document = json.loads(payload.decode("utf-8"))
    config = document.get("game_config")
    if not isinstance(config, Mapping):
        raise SeasonRulesError("Bootstrap payload has no game_config block.")
    scoring_block = config.get("scoring")
    rules_block = config.get("rules")
    if not isinstance(scoring_block, Mapping) or not isinstance(rules_block, Mapping):
        raise SeasonRulesError("game_config must carry scoring and rules blocks.")

    scoring = ScoringRules(
        long_play=_int(scoring_block, "long_play", "scoring"),
        short_play=_int(scoring_block, "short_play", "scoring"),
        assists=_int(scoring_block, "assists", "scoring"),
        saves=_int(scoring_block, "saves", "scoring"),
        penalties_saved=_int(scoring_block, "penalties_saved", "scoring"),
        penalties_missed=_int(scoring_block, "penalties_missed", "scoring"),
        yellow_cards=_int(scoring_block, "yellow_cards", "scoring"),
        red_cards=_int(scoring_block, "red_cards", "scoring"),
        own_goals=_int(scoring_block, "own_goals", "scoring"),
        bonus=_int(scoring_block, "bonus", "scoring"),
        goals_scored=_position_table(scoring_block, "goals_scored"),
        clean_sheets=_position_table(scoring_block, "clean_sheets"),
        goals_conceded=_position_table(scoring_block, "goals_conceded"),
        defensive_contribution=_position_table(scoring_block, "defensive_contribution"),
    )
    cap = rules_block.get("transfers_cap")
    fee = rules_block.get("transfers_sell_on_fee")
    if isinstance(fee, bool) or not isinstance(fee, int | float):
        raise SeasonRulesError("rules.transfers_sell_on_fee is missing or not numeric.")
    transfers = TransferRules(
        squad_size=_int(rules_block, "squad_squadsize", "rules"),
        starting_size=_int(rules_block, "squad_squadplay", "rules"),
        team_limit=_int(rules_block, "squad_team_limit", "rules"),
        budget_tenths=_int(rules_block, "squad_total_spend", "rules"),
        max_extra_free_transfers=_int(rules_block, "max_extra_free_transfers", "rules"),
        transfers_cap=None if cap is None else _int(rules_block, "transfers_cap", "rules"),
        sell_on_fee=float(fee),
        sell_at_purchase_price=bool(rules_block.get("element_sell_at_purchase_price", False)),
    )
    chips_block = document.get("chips")
    if not isinstance(chips_block, list) or not chips_block:
        raise SeasonRulesError("Bootstrap payload has no chips list.")
    chips: list[ChipWindow] = []
    for entry in chips_block:
        if not isinstance(entry, Mapping):
            raise SeasonRulesError("Every chip entry must be an object.")
        chips.append(
            ChipWindow(
                name=str(entry.get("name")),
                number=_int(entry, "number", "chip"),
                start_event=_int(entry, "start_event", "chip"),
                stop_event=_int(entry, "stop_event", "chip"),
                chip_type=str(entry.get("chip_type")),
            )
        )
    return SeasonRules(
        contract_version=SEASON_RULES_CONTRACT_VERSION,
        season=season,
        source_snapshot_id=snapshot.metadata.snapshot_id,
        scoring=scoring,
        transfers=transfers,
        chips=tuple(chips),
        diagnostics={
            "captured_at_utc": snapshot.metadata.captured_at_utc,
            "chip_windows": len(chips),
            "awards_defensive_contribution": scoring.awards_defensive_contribution,
        },
    )


def chip_availability_for(
    rules: SeasonRules,
    gameweeks: Sequence[int],
    *,
    used: Mapping[str, Sequence[int]] | None = None,
    forced: Mapping[int, str] | None = None,
) -> ChipAvailability:
    """Translate the season's chip windows into what the planner may play in a horizon.

    A chip is available in a horizon gameweek when one of its published windows covers
    that gameweek and the chip has not already been used inside that same window
    (``used`` maps chip name to the gameweeks it was played in). Chips the planner does
    not model are left out rather than mapped to something else (since contract v2 it
    models all four, free hit included). If the
    horizon crosses a window boundary the chip is available on both sides, but the
    planner plays each chip at most once per horizon; a horizon-spanning second play
    is a later concern, and it is stated here rather than silently allowed.
    """

    horizon = tuple(int(week) for week in gameweeks)
    played = {name: {int(week) for week in weeks} for name, weeks in dict(used or {}).items()}
    available: dict[str, set[int]] = {}
    for window in rules.chips:
        if window.name not in PLANNER_CHIP_NAMES:
            continue
        spent = any(window.covers(week) for week in played.get(window.name, set()))
        if spent:
            continue
        covered = {week for week in horizon if window.covers(week)}
        if covered:
            available.setdefault(window.name, set()).update(covered)
    return ChipAvailability(
        available={name: frozenset(weeks) for name, weeks in available.items()},
        forced=dict(forced or {}),
    )


def rules_to_dict(rules: SeasonRules, *, include_provenance: bool = True) -> dict[str, object]:
    """Serialise the rules; without provenance the result is the fingerprint payload."""

    document: dict[str, object] = {
        "contract_version": rules.contract_version,
        "scoring": {
            "long_play": rules.scoring.long_play,
            "short_play": rules.scoring.short_play,
            "assists": rules.scoring.assists,
            "saves": rules.scoring.saves,
            "penalties_saved": rules.scoring.penalties_saved,
            "penalties_missed": rules.scoring.penalties_missed,
            "yellow_cards": rules.scoring.yellow_cards,
            "red_cards": rules.scoring.red_cards,
            "own_goals": rules.scoring.own_goals,
            "bonus": rules.scoring.bonus,
            "goals_scored": dict(rules.scoring.goals_scored),
            "clean_sheets": dict(rules.scoring.clean_sheets),
            "goals_conceded": dict(rules.scoring.goals_conceded),
            "defensive_contribution": dict(rules.scoring.defensive_contribution),
        },
        "transfers": {
            "squad_size": rules.transfers.squad_size,
            "starting_size": rules.transfers.starting_size,
            "team_limit": rules.transfers.team_limit,
            "budget_tenths": rules.transfers.budget_tenths,
            "max_extra_free_transfers": rules.transfers.max_extra_free_transfers,
            "max_free_transfers": rules.transfers.max_free_transfers,
            "transfers_cap": rules.transfers.transfers_cap,
            "sell_on_fee": rules.transfers.sell_on_fee,
            "sell_at_purchase_price": rules.transfers.sell_at_purchase_price,
        },
        "chips": [
            {
                "name": window.name,
                "number": window.number,
                "start_event": window.start_event,
                "stop_event": window.stop_event,
                "chip_type": window.chip_type,
            }
            for window in rules.chips
        ],
    }
    if include_provenance:
        document["season"] = rules.season
        document["source_snapshot_id"] = rules.source_snapshot_id
        document["fingerprint"] = rules.fingerprint
        document["diagnostics"] = dict(rules.diagnostics)
    return document


def render_rules(rules: SeasonRules) -> str:
    """A short human-readable summary for reports."""

    lines = [
        f"Season rules {rules.season} ({rules.contract_version})",
        f"  source snapshot     {rules.source_snapshot_id}",
        f"  fingerprint         {rules.fingerprint[:16]}…",
        "  goals               "
        + ", ".join(f"{position} {rules.scoring.goals_scored[position]}" for position in POSITIONS),
        "  clean sheets        "
        + ", ".join(f"{position} {rules.scoring.clean_sheets[position]}" for position in POSITIONS),
        "  defensive contrib.  "
        + ", ".join(
            f"{position} {rules.scoring.defensive_contribution[position]}" for position in POSITIONS
        ),
        f"  free transfers      up to {rules.transfers.max_free_transfers} banked; "
        f"sell-on fee {rules.transfers.sell_on_fee:.0%}",
        "  chips               "
        + "; ".join(
            f"{window.name} GW{window.start_event}-{window.stop_event}" for window in rules.chips
        ),
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "CHIP_NAMES",
    "SEASON_RULES_CONTRACT_VERSION",
    "ChipWindow",
    "ScoringRules",
    "SeasonRules",
    "SeasonRulesError",
    "TransferRules",
    "chip_availability_for",
    "read_season_rules",
    "render_rules",
    "rules_to_dict",
]
