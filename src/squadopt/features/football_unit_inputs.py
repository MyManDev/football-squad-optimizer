"""Private, immutable inputs for the separately invoked club-unit experiment.

Historical on-field units are observations, not reconstructed predecision forecasts.
Projected states must be supplied jointly. No appearance marginals are accepted here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Literal, cast

UNIT_INPUT_VERSION = "football_unit_inputs_v1"
POSITIONS = ("GK", "DEF", "MID", "FWD")


def utc_time(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must have an explicit timezone.")
    return value


def positive_id(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive persistent integer identity.")


def finite_number(value: float, name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number, not a boolean.")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive.")


def scope(season: str, gameweek: int, fixture_id: int) -> None:
    if not isinstance(season, str) or not re.fullmatch(r"20\d{2}-\d{2}", season):
        raise ValueError("Season must identify both years.")
    if int(season[-2:]) != (int(season[:4]) + 1) % 100:
        raise ValueError("Season years must be consecutive.")
    positive_id(gameweek, "gameweek")
    if gameweek > 38:
        raise ValueError("Gameweek must be within the supported league calendar.")
    positive_id(fixture_id, "fixture_id")


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    provider: str
    version: str
    kind: Literal["synthetic", "provider", "fm"]
    sha256: str
    published_at: datetime
    captured_at: datetime
    effective_at: datetime
    valid_until: datetime
    rights_reference: str
    permitted_model_development: bool

    def __post_init__(self) -> None:
        if not all(
            isinstance(x, str) and x.strip()
            for x in (self.source_id, self.provider, self.version, self.rights_reference)
        ):
            raise ValueError("Sources require explicit provider, version and rights evidence.")
        if self.kind not in ("synthetic", "provider", "fm"):
            raise ValueError("Unsupported source kind.")
        if not isinstance(self.sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", self.sha256):
            raise ValueError("Source requires a lowercase SHA256 receipt.")
        for label in ("published_at", "captured_at", "effective_at", "valid_until"):
            utc_time(getattr(self, label), label)
        if self.published_at > self.captured_at or self.effective_at > self.valid_until:
            raise ValueError("Source clocks are inconsistent.")
        if self.permitted_model_development is not True:
            raise ValueError("Source permission must explicitly cover model development.")
        synthetic_receipt = self.rights_reference.startswith("synthetic:")
        if synthetic_receipt != (self.kind == "synthetic"):
            raise ValueError("Synthetic receipts cannot establish actual source rights.")

    def available_at(self, cutoff: datetime) -> None:
        utc_time(cutoff, "source cutoff")
        if max(self.published_at, self.captured_at, self.effective_at) > cutoff:
            raise ValueError("Source was unavailable at the explicit decision cutoff.")
        if self.valid_until < cutoff:
            raise ValueError("Source is stale at the explicit decision cutoff.")


@dataclass(frozen=True)
class NumericAttributeSpec:
    name: str
    source_id: str
    minimum: float
    maximum: float
    unit: str
    definition: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(x, str) and x.strip()
            for x in (self.name, self.source_id, self.unit, self.definition)
        ):
            raise ValueError("Numeric attributes need names, units and definitions.")
        finite_number(self.minimum, "attribute minimum")
        finite_number(self.maximum, "attribute maximum")
        if self.minimum >= self.maximum:
            raise ValueError("Numeric attribute bounds must be ordered.")


@dataclass(frozen=True)
class PlayerMapping:
    source_id: str
    source_player_id: str
    player_id: int
    club: int
    valid_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(x, str) and x.strip() for x in (self.source_id, self.source_player_id)
        ):
            raise ValueError("Player mapping needs a source identity.")
        positive_id(self.player_id, "player_id")
        positive_id(self.club, "club")
        utc_time(self.valid_from, "mapping valid_from")
        utc_time(self.valid_until, "mapping valid_until")
        if self.valid_from > self.valid_until:
            raise ValueError("Player mapping dates must be ordered.")


@dataclass(frozen=True)
class PlayerAttributes:
    source_id: str
    source_player_id: str
    values: tuple[tuple[str, float | None], ...]

    def __post_init__(self) -> None:
        values = tuple(tuple(x) for x in self.values)
        if len({name for name, _ in values}) != len(values):
            raise ValueError("Duplicate numeric attribute.")
        object.__setattr__(self, "values", tuple(sorted(values, key=lambda pair: pair[0])))
        if not all(
            isinstance(x, str) and x.strip() for x in (self.source_id, self.source_player_id)
        ):
            raise ValueError("Attributes require a source player identity.")
        for _, value in self.values:
            if value is not None:
                finite_number(value, "numeric attribute")


@dataclass(frozen=True)
class UnitPlayer:
    """Persistent player with the contemporaneous published FPL scoring position.

    This position groups unit attributes; it does not claim the on-pitch tactical
    role. A real-club winger classified MID by FPL must remain MID here.
    """

    player_id: int
    position: str

    def __post_init__(self) -> None:
        positive_id(self.player_id, "player_id")
        if self.position not in POSITIONS:
            raise ValueError("Unit players need explicit supported football roles.")


@dataclass(frozen=True)
class ClubUnit:
    club: int
    players: tuple[UnitPlayer, ...]

    def __post_init__(self) -> None:
        positive_id(self.club, "club")
        object.__setattr__(self, "players", tuple(sorted(self.players, key=lambda x: x.player_id)))
        if len(self.players) != 11 or len({x.player_id for x in self.players}) != 11:
            raise ValueError("This version requires eleven distinct on-field players.")
        if sum(x.position == "GK" for x in self.players) != 1:
            raise ValueError("A complete club unit requires exactly one goalkeeper.")


def validate_pair(own: ClubUnit, opponent: ClubUnit) -> None:
    if own.club == opponent.club or {x.player_id for x in own.players} & {
        x.player_id for x in opponent.players
    }:
        raise ValueError(
            "A club cannot face itself or share on-field identities with its opponent."
        )


@dataclass(frozen=True)
class UnitInputCatalog:
    season: str
    gameweek: int
    fixture_id: int
    decision_cutoff: datetime
    sources: tuple[SourceRecord, ...]
    attributes: tuple[NumericAttributeSpec, ...]
    mappings: tuple[PlayerMapping, ...]
    player_attributes: tuple[PlayerAttributes, ...]
    baseline_source_id: str
    reference_source_id: str
    projection_source_id: str

    def __post_init__(self) -> None:
        scope(self.season, self.gameweek, self.fixture_id)
        utc_time(self.decision_cutoff, "decision_cutoff")
        for field in ("sources", "attributes", "mappings", "player_attributes"):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        sources = {x.source_id: x for x in self.sources}
        if not sources or len(sources) != len(self.sources):
            raise ValueError("Catalog requires uniquely identified sources.")
        for source_id in (
            self.baseline_source_id,
            self.reference_source_id,
            self.projection_source_id,
        ):
            if source_id not in sources:
                raise ValueError(
                    "Baseline, reference and projection need explicit source receipts."
                )
        for source in self.sources:
            source.available_at(self.decision_cutoff)
        specs = {(x.source_id, x.name): x for x in self.attributes}
        if len(specs) != len(self.attributes):
            raise ValueError("Attribute definitions must be unique within each source.")
        for spec in self.attributes:
            if spec.source_id not in sources:
                raise ValueError("Attribute source is absent from the catalog.")
            if sources[spec.source_id].kind == "fm" and (spec.minimum, spec.maximum) != (1, 20):
                raise ValueError("FM numeric attributes must declare the supported 1 to 20 scale.")
        mapping_keys: dict[tuple[str, str], list[PlayerMapping]] = {}
        active_clubs: dict[int, int] = {}
        active_source_ids: set[tuple[str, int]] = set()
        for mapping in self.mappings:
            if mapping.source_id not in sources:
                raise ValueError("Mapping source is absent from the catalog.")
            key = mapping.source_id, mapping.source_player_id
            for previous in mapping_keys.setdefault(key, []):
                if max(previous.valid_from, mapping.valid_from) <= min(
                    previous.valid_until, mapping.valid_until
                ):
                    raise ValueError("Ambiguous or duplicated temporal player mapping.")
            mapping_keys[key].append(mapping)
            if mapping.valid_from <= self.decision_cutoff <= mapping.valid_until:
                persistent_key = mapping.source_id, mapping.player_id
                if persistent_key in active_source_ids:
                    raise ValueError(
                        "Source maps multiple active identities to one persistent player."
                    )
                active_source_ids.add(persistent_key)
                previous_club = active_clubs.setdefault(mapping.player_id, mapping.club)
                if previous_club != mapping.club:
                    raise ValueError("Persistent player maps to multiple clubs at the cutoff.")
        attr_keys = [(x.source_id, x.source_player_id) for x in self.player_attributes]
        if len(set(attr_keys)) != len(attr_keys):
            raise ValueError("Duplicate source player attribute snapshot.")
        values: dict[tuple[str, int, str], float | None] = {}
        for snapshot in self.player_attributes:
            key = snapshot.source_id, snapshot.source_player_id
            active = [
                x
                for x in mapping_keys.get(key, ())
                if x.valid_from <= self.decision_cutoff <= x.valid_until
            ]
            if len(active) != 1:
                raise ValueError("Attribute snapshot needs one active persistent player mapping.")
            for name, value in snapshot.values:
                snapshot_spec = specs.get((snapshot.source_id, name))
                if snapshot_spec is None:
                    raise ValueError("Attribute snapshot uses an undeclared numeric field.")
                if value is not None and not (
                    snapshot_spec.minimum <= value <= snapshot_spec.maximum
                ):
                    raise ValueError("Numeric attribute is outside its declared scale.")
                values[snapshot.source_id, active[0].player_id, name] = value
        # Derived immutable indexes are not dataclass fields. Canonical input
        # serialization and source fingerprints retain only the supplied facts.
        object.__setattr__(self, "_club_index", MappingProxyType(active_clubs))
        object.__setattr__(self, "_value_index", MappingProxyType(values))

    def validate_unit(self, unit: ClubUnit) -> None:
        active = cast(Mapping[int, int], self.__dict__["_club_index"])
        if any(active.get(x.player_id) != unit.club for x in unit.players):
            raise ValueError("Complete unit requires active persistent mappings for every player.")

    def value(self, player_id: int, spec: NumericAttributeSpec) -> float | None:
        values = cast(Mapping[tuple[str, int, str], float | None], self.__dict__["_value_index"])
        return values.get((spec.source_id, player_id, spec.name))


def validate_scope(
    catalog: UnitInputCatalog,
    *,
    season: str,
    gameweek: int,
    fixture_id: int,
    decision_cutoff: datetime,
) -> None:
    if (catalog.season, catalog.gameweek, catalog.fixture_id, catalog.decision_cutoff) != (
        season,
        gameweek,
        fixture_id,
        decision_cutoff,
    ):
        raise ValueError(
            "Catalog must be captured for this fixture and explicit GW decision cutoff."
        )


@dataclass(frozen=True)
class UnitObservation:
    season: str
    gameweek: int
    fixture_id: int
    decision_cutoff: datetime
    kickoff: datetime
    outcome_available_at: datetime
    outcome_source: SourceRecord
    catalog: UnitInputCatalog
    home: bool
    own: ClubUnit
    opponent: ClubUnit
    reference_own: ClubUnit
    reference_opponent: ClubUnit
    start_minute: float
    minutes: float
    own_goals: int
    opponent_goals: int
    causal_baseline_own_goal_rate: float
    causal_baseline_opponent_goal_rate: float

    def __post_init__(self) -> None:
        scope(self.season, self.gameweek, self.fixture_id)
        for name in ("decision_cutoff", "kickoff", "outcome_available_at"):
            utc_time(getattr(self, name), name)
        if self.decision_cutoff >= self.kickoff:
            raise ValueError("Historical features require an explicit pre-kickoff decision cutoff.")
        if self.outcome_available_at < self.kickoff + timedelta(hours=3):
            raise ValueError("Historical outcomes require a declared settled receipt.")
        self.outcome_source.available_at(self.outcome_available_at)
        validate_scope(
            self.catalog,
            season=self.season,
            gameweek=self.gameweek,
            fixture_id=self.fixture_id,
            decision_cutoff=self.decision_cutoff,
        )
        _validate_basis(
            self.home,
            self.own,
            self.opponent,
            self.reference_own,
            self.reference_opponent,
            self.catalog,
            self.causal_baseline_own_goal_rate,
            self.causal_baseline_opponent_goal_rate,
        )
        finite_number(self.start_minute, "start_minute")
        finite_number(self.minutes, "minutes", positive=True)
        if self.start_minute < 0 or self.start_minute + self.minutes > 120:
            raise ValueError("Exposure segments must be within the supported match duration.")
        for goals in (self.own_goals, self.opponent_goals):
            if isinstance(goals, bool) or not isinstance(goals, int) or goals < 0:
                raise ValueError("Exposure outcomes must be nonnegative observed goal counts.")


def _validate_basis(
    home: bool,
    own: ClubUnit,
    opponent: ClubUnit,
    reference_own: ClubUnit,
    reference_opponent: ClubUnit,
    catalog: UnitInputCatalog,
    own_rate: float,
    opponent_rate: float,
) -> None:
    if not isinstance(home, bool):
        raise ValueError("Home venue must be an explicit boolean.")
    validate_pair(own, opponent)
    validate_pair(reference_own, reference_opponent)
    if (own.club, opponent.club) != (reference_own.club, reference_opponent.club):
        raise ValueError("Reference units must represent the same paired clubs.")
    for unit in (own, opponent, reference_own, reference_opponent):
        catalog.validate_unit(unit)
    finite_number(own_rate, "causal baseline own goal rate", positive=True)
    finite_number(opponent_rate, "causal baseline opponent goal rate", positive=True)


@dataclass(frozen=True)
class ProjectedUnitState:
    probability: float
    own: ClubUnit
    opponent: ClubUnit

    def __post_init__(self) -> None:
        finite_number(self.probability, "joint state probability")
        if not 0 < self.probability <= 1:
            raise ValueError("Joint projected states require positive mass at most one.")
        validate_pair(self.own, self.opponent)


@dataclass(frozen=True)
class UnitProjection:
    season: str
    gameweek: int
    fixture_id: int
    decision_cutoff: datetime
    kickoff: datetime
    captured_at: datetime
    catalog: UnitInputCatalog
    home: bool
    reference_own: ClubUnit
    reference_opponent: ClubUnit
    states: tuple[ProjectedUnitState, ...]
    causal_baseline_own_goal_rate: float
    causal_baseline_opponent_goal_rate: float

    def __post_init__(self) -> None:
        scope(self.season, self.gameweek, self.fixture_id)
        for name in ("decision_cutoff", "kickoff", "captured_at"):
            utc_time(getattr(self, name), name)
        if self.captured_at > self.decision_cutoff or self.decision_cutoff >= self.kickoff:
            raise ValueError(
                "Future fixture projection must be captured by its actual decision cutoff."
            )
        validate_scope(
            self.catalog,
            season=self.season,
            gameweek=self.gameweek,
            fixture_id=self.fixture_id,
            decision_cutoff=self.decision_cutoff,
        )
        object.__setattr__(self, "states", tuple(self.states))
        if not self.states or len(self.states) > 1024:
            raise ValueError("Supply one complete deterministic unit or at most 1024 joint states.")
        mass = math.fsum(x.probability for x in self.states)
        if abs(mass - 1) > 1e-12:
            raise ValueError("Projected joint state probabilities must sum to one.")
        if mass != 1:
            object.__setattr__(
                self,
                "states",
                tuple(replace(x, probability=x.probability / mass) for x in self.states),
            )
        keys = [(x.own, x.opponent) for x in self.states]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate projected joint unit states.")
        for state in self.states:
            _validate_basis(
                self.home,
                state.own,
                state.opponent,
                self.reference_own,
                self.reference_opponent,
                self.catalog,
                self.causal_baseline_own_goal_rate,
                self.causal_baseline_opponent_goal_rate,
            )
