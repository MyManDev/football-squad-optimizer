"""View models of the ``ui_view_v1`` contract.

Frozen dataclasses whose ``to_dict()`` yields JSON-native values only (str, int, float,
bool, None, lists and dicts of those). They carry what a page renders and nothing a page
would have to compute: prices stay in tenths (the frontend formats), probabilities stay
probabilities, and every claim keeps the words that limit it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Final

from squadopt.application.contract import UI_VIEW_CONTRACT_VERSION

JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

_MISSING: Final = object()


class ViewError(ValueError):
    """A view model was given something it cannot represent."""


def jsonable(value: object) -> JsonValue:
    """Coerce a value to JSON-native form; refuse anything that would not round-trip."""

    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ViewError("Non-finite numbers cannot be shown; state the limit instead.")
        return value
    if isinstance(value, PurePath):
        return value.as_posix()  # the same bytes on every platform
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(item) for item in value]
    to_dict = getattr(value, "to_dict", _MISSING)
    if to_dict is not _MISSING and callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return jsonable(result)
    # numpy scalars and similar: they expose item(); Decimal, Path and enums: str.
    item = getattr(value, "item", _MISSING)
    if item is not _MISSING and callable(item):
        return jsonable(item())
    return str(value)


class _View:
    """Mixin: ``to_dict`` walks the dataclass fields through ``jsonable``."""

    def to_dict(self) -> dict[str, JsonValue]:
        return {f.name: jsonable(getattr(self, f.name)) for f in fields(self)}  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class PlayerView(_View):
    """One player as a page shows him: identity, price, projection, role in the squad."""

    player_id: int
    name: str
    short_name: str
    """A display name that fits a chip: the surname with its particle (``van Dijk``)."""
    team: str
    position: str
    price_tenths: int
    expected_points: float
    role: str
    """``starter`` | ``bench`` | ``out`` | ``in`` | ``pool``."""
    is_captain: bool = False
    bench_order: int | None = None
    event_points: float | None = None
    """Realized points once the gameweek is settled; null until then."""


@dataclass(frozen=True, slots=True)
class TransferView(_View):
    """The transfer block of a mid-season decision (mirrors ``ledger_transfers_v1``)."""

    previous_gameweek: int
    transfers_in: tuple[PlayerView, ...]
    transfers_out: tuple[PlayerView, ...]
    transfer_count: int
    paid_transfer_count: int
    transfer_hit_points: float
    free_transfers_before: int
    free_transfers_after: int
    bank_before_tenths: int
    bank_after_tenths: int
    squad_sell_value_tenths: int
    chip: str | None
    chips_available: tuple[str, ...]
    planner_solver_status: str
    max_free_transfers: int
    transfer_hit_cost_points: float


@dataclass(frozen=True, slots=True)
class RivalComparisonView(_View):
    rival: str
    probability_ahead: float
    probability_ahead_interval: tuple[float, float]
    mean_difference: float
    shared_starters: int


@dataclass(frozen=True, slots=True)
class RiskView(_View):
    """The distributional risk block, or the honest reason it is absent."""

    status: str
    """``available`` | ``unavailable`` | ``not_requested``."""
    reason: str
    blockers: tuple[str, ...]
    scenario_count: int | None
    lower_quantile_probability: float | None
    lower_quantile_score: float | None
    mean_score: float | None
    mean_worst_fraction_score: float | None
    worst_fraction: float | None
    points_threshold: float | None
    probability_below_threshold: float | None
    probability_below_threshold_interval: tuple[float, float] | None
    location_shift_points: float | None
    stated_limits: tuple[str, ...]
    rivals: tuple[RivalComparisonView, ...]
    residual_source: str | None


@dataclass(frozen=True, slots=True)
class RecommendationView(_View):
    """One gameweek's frozen decision, as a page shows it."""

    season: str
    gameweek: int
    deadline_utc: str
    snapshot_id: str
    captured_at_utc: str
    model_name: str
    model_version: str
    feature_contract_version: str
    prediction_fingerprint: str
    report_contract_version: str
    solver_status: str
    solver_proved_optimal: bool
    decision_kind: str
    """``opening`` | ``transfer``."""
    squad: tuple[PlayerView, ...]
    starting_xi: tuple[PlayerView, ...]
    bench: tuple[PlayerView, ...]
    captain_player_id: int
    total_cost_tenths: int
    projected_score: float
    unavailable_player_count: int
    risk: RiskView
    transfers: TransferView | None
    outcome_realized_score: float | None
    outcome_net_score: float | None
    settled: bool
    captain_multiplier: int = 2
    """What the captain's points count as: 3 under a triple captain, otherwise 2."""
    metadata: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LedgerRowView(_View):
    """One row of the season ledger."""

    gameweek: int
    snapshot_id: str
    deadline_utc: str
    solver_status: str
    decision_kind: str
    captain_player_id: int
    projected_score: float
    realized_score: float | None
    projection_error: float | None
    transfer_count: int
    transfer_hit_points: float
    realized_net_score: float | None
    chip: str | None
    unavailable_player_count: int
    settled: bool
    cumulative_projected_score: float
    """Projected score summed over this and every earlier decided gameweek."""
    cumulative_realized_score: float | None
    """Realized score summed over the settled gameweeks up to this one; None until one settles."""


@dataclass(frozen=True, slots=True)
class PoolPlayerView(_View):
    """One player of the projected pool, ranked within his position by expected points."""

    player_id: int
    name: str
    short_name: str
    team: str
    position: str
    price_tenths: int
    expected_points: float
    rank_in_position: int
    selected: bool
    """In the frozen squad (starter or bench)."""
    role: str
    """``starter`` | ``bench`` | ``pool``."""


@dataclass(frozen=True, slots=True)
class PoolView(_View):
    """Why these players: the top of the projected pool per position, chosen or not."""

    season: str
    gameweek: int
    pool_size: int
    per_position: int
    players: tuple[PoolPlayerView, ...]


@dataclass(frozen=True, slots=True)
class LedgerView(_View):
    season: str
    rows: tuple[LedgerRowView, ...]
    decided_gameweeks: int
    settled_gameweeks: int
    total_projected_score: float
    total_projected_score_settled: float | None
    """Projected score summed over the settled gameweeks only (comparable with realized)."""
    total_realized_score: float | None
    total_projection_error: float | None
    """Realized minus projected over the settled gameweeks; the page shows it, never computes it."""
    total_realized_net_score: float | None
    total_transfer_hit_points: float
    chips_played: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TickActionView(_View):
    kind: str
    reason: str
    gameweek: int | None
    snapshot_id: str | None
    handoff_path: str | None


@dataclass(frozen=True, slots=True)
class RunLogEventView(_View):
    ts: str
    level: str
    message: str
    run_id: str
    fields: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StatusView(_View):
    """What the season tick would do now, and what it last did."""

    now_utc: str
    season: str | None
    latest_capture: str | None
    next_gameweek: int | None
    next_deadline_utc: str | None
    hours_to_deadline: float | None
    actions: tuple[TickActionView, ...]
    is_idle: bool
    decided_gameweeks: tuple[int, ...]
    settled_gameweeks: tuple[int, ...]
    recent_events: tuple[RunLogEventView, ...]
    tick_contract_version: str


@dataclass(frozen=True, slots=True)
class SiteIndex(_View):
    """The site's table of contents: what exists and where the latest decision is."""

    generated_at_utc: str
    seasons: tuple[str, ...]
    gameweeks: Mapping[str, tuple[int, ...]]
    latest: Mapping[str, JsonValue] | None
    """``{"season", "gameweek", "path"}`` of the newest decision, or None."""
    schema_path: str
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ViewEnvelope:
    """What every written JSON file looks like: version, timestamp, payload."""

    payload: dict[str, JsonValue]
    generated_at_utc: str
    contract_version: str = UI_VIEW_CONTRACT_VERSION

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": self.contract_version,
            "generated_at_utc": self.generated_at_utc,
            "payload": self.payload,
        }


def utc_now_iso(now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    return stamp.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


_PARTICLES: Final = frozenset(
    {
        "van",
        "de",
        "da",
        "di",
        "del",
        "della",
        "der",
        "le",
        "la",
        "el",
        "dos",
        "du",
        "von",
        "ter",
        "ten",
        "den",
    }
)


def short_name(name: str) -> str:
    """The surname, keeping a lowercase particle before it (``Virgil van Dijk`` -> ``van Dijk``)."""

    tokens = [t for t in str(name).split() if t]
    if len(tokens) <= 1:
        return str(name).strip()
    tail = tokens[-1]
    particles: list[str] = []
    for token in reversed(tokens[:-1]):
        if token.lower() in _PARTICLES:
            particles.insert(0, token)
        else:
            break
    return " ".join([*particles, tail])


def positions_in_order(players: Sequence[PlayerView]) -> tuple[PlayerView, ...]:
    """Pitch order: GK, DEF, MID, FWD, then by expected points descending."""

    rank = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
    return tuple(
        sorted(players, key=lambda p: (rank.get(p.position, 9), -p.expected_points, p.player_id))
    )
