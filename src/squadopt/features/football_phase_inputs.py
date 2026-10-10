"""Private causal inputs for phase-specific FPL credited goal/assist allocation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, TypedDict, cast

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.snapshots import (
    SNAPSHOT_SCHEMA_VERSION,
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_set_pieces import TAKER_FIELDS, captured_taker_priorities
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

PHASE_INPUT_VERSION = "football_phase_inputs_v1"
PHASE_DEFINITION_VERSION = "football_scoring_phase_v1"
PHASES = ("penalty", "direct_free_kick", "corner", "delivered_free_kick", "other")
POSITIONS = ("GK", "DEF", "MID", "FWD")
PROTECTED_SEASON = "2025-26"
MAX_PHASE_STATES = 1024
_CONTEXT = ("season", "gameweek", "fixture", "club", "opponent", "home", "kickoff", "decision_at")


class _PhaseContext(TypedDict):
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    home: bool
    kickoff: str
    decision_at: str


@dataclass(frozen=True, slots=True)
class PhaseSource:
    source_id: str
    provider: str
    version: str
    raw_sha256: str
    published_at: str
    captured_at: str
    source_kind: Literal["baseline", "phase-events", "fpl-totals", "projection"]
    model_use_approved: bool
    model_use_evidence_ref: str


@dataclass(frozen=True, slots=True)
class PhaseDutyPlayer:
    player_code: int
    club: int
    penalties_order: int | None
    direct_freekicks_order: int | None
    corners_and_indirect_freekicks_order: int | None


@dataclass(frozen=True, slots=True)
class PhaseDutyCapture:
    season: str
    snapshot_id: str
    source_fingerprint: str
    captured_at: str
    valid_until: str
    model_use_approved: bool
    model_use_evidence_ref: str
    players: tuple[PhaseDutyPlayer, ...]


@dataclass(frozen=True, slots=True)
class PhasePlayer:
    player_code: int
    position: str
    minutes: float
    goal_weight90: float
    assist_weight90: float


@dataclass(frozen=True, slots=True)
class PhaseGoal:
    event_id: str
    phase: str
    scorer: int | None
    assist: int | None
    own_goal: bool
    credit_evidence_ref: str
    credit_status: str = "final"


@dataclass(frozen=True, slots=True)
class PhaseTotal:
    player_code: int
    goals: int
    assists: int


@dataclass(frozen=True, slots=True)
class PhaseObservation:
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    home: bool
    kickoff: str
    decision_at: str
    outcome_available_at: str
    duties: PhaseDutyCapture
    baseline_source: PhaseSource
    outcome_source: PhaseSource
    totals_source: PhaseSource
    players: tuple[PhasePlayer, ...]
    events: tuple[PhaseGoal, ...]
    totals: tuple[PhaseTotal, ...]
    phase_definition_version: str
    rules_version: str
    complete_coverage: bool


@dataclass(frozen=True, slots=True)
class PhaseState:
    state_id: str
    weight: float
    players: tuple[PhasePlayer, ...]
    goal_mass: float
    assist_mass: float
    physical_goal_mass: float


@dataclass(frozen=True, slots=True)
class PhaseProjection:
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    home: bool
    kickoff: str
    decision_at: str
    duties: PhaseDutyCapture
    states: tuple[PhaseState, ...]
    source: PhaseSource


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f"{label} must be nonempty bounded text.")
    return value


def _id(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError(f"{label} must be a positive integer identity.")
    return value


def _number(value: object, label: str, *, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric, not coerced.")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} exceeds finite numeric support.") from error
    if not math.isfinite(number) or number < 0 or (maximum is not None and number > maximum):
        raise ValueError(f"{label} must be finite and within its declared bounds.")
    return number


def _time(value: object, label: str) -> str:
    try:
        return normalize_utc_timestamp(value, label=label)
    except DataError as error:
        raise ValueError(f"{label} must be a valid UTC timestamp.") from error


def validate_phase_season(value: object) -> str:
    """Return a complete consecutive season identity shared by phase consumers."""
    if not isinstance(value, str) or not re.fullmatch(r"20\d{2}-\d{2}", value):
        raise ValueError("A phase season must be a full season identity.")
    if int(value[-2:]) != (int(value[:4]) + 1) % 100:
        raise ValueError("The phase season year pair is inconsistent.")
    return value


def source_receipt(source: PhaseSource, *, cutoff: str, kind: str) -> dict[str, object]:
    """Validate admitted caller evidence; the receipt is not a rights authenticator."""
    if not isinstance(source, PhaseSource):
        raise ValueError("A phase source receipt is required.")
    for name in ("source_id", "provider", "version", "model_use_evidence_ref"):
        _text(getattr(source, name), name)
    if not isinstance(source.raw_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source.raw_sha256
    ):
        raise ValueError("A phase source needs its full raw SHA256.")
    if source.source_kind != kind:
        raise ValueError("A phase source has the wrong semantic kind.")
    if type(source.model_use_approved) is not bool or not source.model_use_approved:
        raise ValueError("A phase source lacks admitted model-use evidence.")
    limit = as_instant(_time(cutoff, "source cutoff"))
    for name in ("published_at", "captured_at"):
        if as_instant(_time(getattr(source, name), name)) > limit:
            raise ValueError("A phase source was unavailable at its causal cutoff.")
    return asdict(source)


def _context(value: PhaseObservation | PhaseProjection) -> None:
    validate_phase_season(value.season)
    for name in ("gameweek", "fixture", "club", "opponent"):
        _id(getattr(value, name), name)
    if value.gameweek > 38 or value.club == value.opponent or type(value.home) is not bool:
        raise ValueError("The phase fixture context is inconsistent.")
    kickoff = as_instant(_time(value.kickoff, "kickoff"))
    if as_instant(_time(value.decision_at, "decision_at")) > kickoff:
        raise ValueError("A phase decision cannot follow kickoff.")
    start = int(value.season[:4])
    if not datetime(start, 7, 1, tzinfo=UTC) <= kickoff < datetime(start + 1, 8, 1, tzinfo=UTC):
        raise ValueError("A phase kickoff falls outside its declared season.")


def _duties(capture: PhaseDutyCapture, *, season: str, decision_at: str) -> None:
    if not isinstance(capture, PhaseDutyCapture) or capture.season != season:
        raise ValueError("A duty capture has the wrong season identity.")
    _text(capture.snapshot_id, "snapshot_id")
    if not isinstance(capture.source_fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", capture.source_fingerprint
    ):
        raise ValueError("A duty capture needs its complete source fingerprint.")
    _text(capture.model_use_evidence_ref, "duty model_use_evidence_ref")
    if type(capture.model_use_approved) is not bool or not capture.model_use_approved:
        raise ValueError("Duty captures need admitted model-use evidence.")
    captured = as_instant(_time(capture.captured_at, "duty captured_at"))
    expiry = as_instant(_time(capture.valid_until, "duty valid_until"))
    decision = as_instant(_time(decision_at, "duty decision_at"))
    if not captured <= decision <= expiry:
        raise ValueError("A duty capture is stale or future at its decision cutoff.")
    if type(capture.players) is not tuple or not capture.players:
        raise ValueError("A duty capture needs its complete immutable roster.")
    seen = set()
    for player in capture.players:
        if not isinstance(player, PhaseDutyPlayer):
            raise ValueError("A duty capture has an invalid player record.")
        _id(player.player_code, "duty player_code")
        _id(player.club, "duty club")
        if player.player_code in seen:
            raise ValueError("A duty capture repeats a persistent player identity.")
        seen.add(player.player_code)
        for name in TAKER_FIELDS:
            rank = getattr(player, name)
            if rank is not None:
                _id(rank, "duty rank")


def _players(players: tuple[PhasePlayer, ...], duties: PhaseDutyCapture, club: int) -> None:
    if type(players) is not tuple or not players:
        raise ValueError("A phase roster must be an immutable complete club roster.")
    seen = set()
    for player in players:
        if not isinstance(player, PhasePlayer):
            raise ValueError("A phase roster has an invalid player record.")
        _id(player.player_code, "player_code")
        if player.player_code in seen or player.position not in POSITIONS:
            raise ValueError("A phase roster repeats an identity or has an invalid position.")
        seen.add(player.player_code)
        _number(player.minutes, "minutes", maximum=120)
        _number(player.goal_weight90, "goal_weight90")
        _number(player.assist_weight90, "assist_weight90")
    if seen != {p.player_code for p in duties.players if p.club == club}:
        raise ValueError("A phase roster does not cover the complete captured club.")


def validate_observation_header(
    observation: PhaseObservation,
    *,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> None:
    """Check all causal headers before inspecting credited outcome records."""
    if not isinstance(observation, PhaseObservation):
        raise ValueError("A phase observation is required.")
    if type(allowed_seasons) is not tuple or not allowed_seasons:
        raise ValueError("Phase training requires an explicit immutable season allowlist.")
    if len(set(allowed_seasons)) != len(allowed_seasons):
        raise ValueError("The phase season allowlist repeats a season.")
    for season in allowed_seasons:
        validate_phase_season(season)
        if season == PROTECTED_SEASON:
            raise ValueError("The protected season is excluded from phase training.")
    if observation.season == PROTECTED_SEASON or observation.season not in allowed_seasons:
        raise ValueError("A phase observation belongs to a protected or unselected season.")
    if excluded_target == (observation.season, observation.gameweek):
        raise ValueError("The whole target gameweek is excluded from phase training.")
    _context(observation)
    cutoff = as_instant(_time(training_cutoff, "training_cutoff"))
    decision = as_instant(_time(observation.decision_at, "decision_at"))
    available = as_instant(_time(observation.outcome_available_at, "outcome_available_at"))
    if (
        decision >= cutoff
        or not as_instant(_time(observation.kickoff, "kickoff")) < available < cutoff
    ):
        raise ValueError("Phase outcomes were not settled strictly before training cutoff.")
    _duties(observation.duties, season=observation.season, decision_at=observation.decision_at)
    source_receipt(observation.baseline_source, cutoff=observation.decision_at, kind="baseline")
    source_receipt(observation.outcome_source, cutoff=training_cutoff, kind="phase-events")
    source_receipt(observation.totals_source, cutoff=training_cutoff, kind="fpl-totals")
    for source in (observation.outcome_source, observation.totals_source):
        if as_instant(_time(source.captured_at, "settled source captured_at")) < available:
            raise ValueError("A claimed settled phase label precedes its source capture.")
        if (
            max(
                as_instant(_time(source.captured_at, "captured_at")),
                as_instant(_time(source.published_at, "published_at")),
            )
            >= cutoff
        ):
            raise ValueError("Settled phase source bytes must predate the training cutoff.")
    if observation.phase_definition_version != PHASE_DEFINITION_VERSION:
        raise ValueError("An unknown phase definition cannot be pooled.")
    _text(observation.rules_version, "rules_version")
    if type(observation.complete_coverage) is not bool or not observation.complete_coverage:
        raise ValueError("Unknown phase coverage cannot become a zero-event fixture.")


def validate_observation(
    observation: PhaseObservation,
    *,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> None:
    validate_observation_header(
        observation,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    _players(observation.players, observation.duties, observation.club)
    if type(observation.events) is not tuple or type(observation.totals) is not tuple:
        raise ValueError("Phase credits and independent FPL totals must be immutable.")
    roster = {p.player_code: p for p in observation.players}
    counts = {code: [0, 0] for code in roster}
    event_ids = set()
    for event in observation.events:
        if not isinstance(event, PhaseGoal):
            raise ValueError("A phase goal has an invalid record.")
        _text(event.event_id, "event_id")
        _text(event.credit_evidence_ref, "credit_evidence_ref")
        if (
            event.event_id in event_ids
            or event.phase not in PHASES
            or event.credit_status != "final"
        ):
            raise ValueError(
                "A phase event repeats, lacks a disjoint phase or has unsettled credit."
            )
        event_ids.add(event.event_id)
        if type(event.own_goal) is not bool or (event.scorer is None) != event.own_goal:
            raise ValueError("Own goals must have no credited attacking scorer.")
        if event.scorer is not None and event.scorer == event.assist:
            raise ValueError("A credited goal cannot have a same-player FPL assist.")
        for code, head in ((event.scorer, 0), (event.assist, 1)):
            if code is not None:
                _id(code, "credited player_code")
                if code not in roster or roster[code].minutes <= 0:
                    raise ValueError("A credited player is outside the complete on-field roster.")
                counts[code][head] += 1
    total_codes = set()
    for total in observation.totals:
        if not isinstance(total, PhaseTotal):
            raise ValueError("An independent FPL total has an invalid record.")
        _id(total.player_code, "FPL total player_code")
        if total.player_code in total_codes or total.player_code not in counts:
            raise ValueError("Independent FPL totals repeat or name another roster.")
        total_codes.add(total.player_code)
        for value in (total.goals, total.assists):
            if type(value) is not int or value < 0:
                raise ValueError("FPL goal/assist totals must be nonnegative integer counts.")
        if counts[total.player_code] != [total.goals, total.assists]:
            raise ValueError("Disjoint phase credits do not reconcile to independent FPL totals.")
    if total_codes != set(roster):
        raise ValueError("Independent FPL totals omit captured club players.")


def validate_projection(projection: PhaseProjection, *, model_cutoff: str) -> None:
    if not isinstance(projection, PhaseProjection):
        raise ValueError("An explicit phase projection is required.")
    _context(projection)
    if projection.season == PROTECTED_SEASON:
        raise ValueError("The protected season is excluded from phase projections.")
    if as_instant(_time(projection.decision_at, "decision_at")) < as_instant(
        _time(model_cutoff, "model_cutoff")
    ):
        raise ValueError("A phase prediction cannot precede its training cutoff.")
    _duties(projection.duties, season=projection.season, decision_at=projection.decision_at)
    source_receipt(projection.source, cutoff=projection.decision_at, kind="projection")
    if type(projection.states) is not tuple or not 0 < len(projection.states) <= MAX_PHASE_STATES:
        raise ValueError("Complete phase states must be immutable and within the declared cap.")
    seen = set()
    reference = None
    for state in projection.states:
        if not isinstance(state, PhaseState):
            raise ValueError("A phase state has an invalid record.")
        _text(state.state_id, "state_id")
        if state.state_id in seen:
            raise ValueError("A phase projection repeats a state identity.")
        seen.add(state.state_id)
        _number(state.weight, "state weight", maximum=1)
        _players(state.players, projection.duties, projection.club)
        signature = {
            p.player_code: (p.position, p.goal_weight90, p.assist_weight90) for p in state.players
        }
        if reference is not None and signature != reference:
            raise ValueError("State rosters or causal baseline weights disagree.")
        reference = signature
        physical = _number(state.physical_goal_mass, "physical_goal_mass")
        for name in ("goal_mass", "assist_mass"):
            mass = _number(getattr(state, name), name)
            if mass > physical + 1e-12:
                raise ValueError("A state credited mass exceeds physical club goals.")
            weights = [
                p.minutes
                * getattr(p, "goal_weight90" if name == "goal_mass" else "assist_weight90")
                for p in state.players
            ]
            if mass > 0 and math.fsum(weights) <= 0:
                raise ValueError("Positive phase mass lacks positive on-field exposure weights.")
        if physical > 0 and not any(p.minutes > 0 for p in state.players):
            raise ValueError("A positive physical goal rate lacks any on-field player.")
    if not math.isclose(
        math.fsum(s.weight for s in projection.states), 1, rel_tol=0, abs_tol=1e-12
    ):
        raise ValueError("The complete phase state weights must sum to one.")


def _digest(value: PhaseObservation | PhaseProjection) -> str:
    content = json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def observation_digest(observation: PhaseObservation) -> str:
    return _digest(observation)


def projection_digest(projection: PhaseProjection) -> str:
    return _digest(projection)


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("A private phase JSON object repeats a key.")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("A private phase JSON document contains a nonfinite constant.")


def _json(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes or not payload or len(payload) > 20_000_000:
        raise ValueError("A private phase payload must be bounded UTF-8 bytes.")
    try:
        document = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("A private phase payload is not valid UTF-8 JSON.") from error
    if not isinstance(document, dict):
        raise ValueError("A private phase JSON document must be an object.")
    return document


def read_phase_duties(
    snapshot: CapturedSnapshot,
    *,
    season: str,
    decision_at: str,
    valid_until: str,
    model_use_approved: bool,
    model_use_evidence_ref: str,
) -> PhaseDutyCapture:
    """Read existing immutable bootstrap bytes; never fetch or infer a duty."""
    validate_phase_season(season)
    if not isinstance(snapshot, CapturedSnapshot):
        raise ValueError("A verified captured bootstrap is required.")
    metadata = snapshot.metadata
    if not isinstance(metadata, SnapshotMetadata):
        raise ValueError("A phase duty snapshot lacks typed provenance metadata.")
    if metadata.source != FPL_LIVE_SOURCE or metadata.schema_version != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError("A phase duty snapshot has an unsupported source or schema.")
    captured = _time(metadata.captured_at_utc, "duty captured_at")
    if (
        set(metadata.checksums) != set(snapshot.payloads)
        or BOOTSTRAP_PAYLOAD not in snapshot.payloads
    ):
        raise ValueError("A phase duty snapshot lacks its exact recorded payload inventory.")
    if any(
        type(payload) is not bytes or payload_checksum(payload) != metadata.checksums[name]
        for name, payload in snapshot.payloads.items()
    ):
        raise ValueError("A phase duty snapshot raw payload checksum differs.")
    fingerprint = snapshot_fingerprint(
        source=metadata.source,
        captured_at_utc=captured,
        schema_version=metadata.schema_version,
        checksums=metadata.checksums,
    )
    identifier = build_snapshot_id(
        source=metadata.source, captured_at_utc=captured, fingerprint=fingerprint
    )
    if fingerprint != metadata.fingerprint or identifier != metadata.snapshot_id:
        raise ValueError("A phase duty snapshot identity or fingerprint differs.")
    bootstrap = _json(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    if not isinstance(bootstrap.get("elements"), list) or not isinstance(
        bootstrap.get("teams"), list
    ):
        raise ValueError("A captured bootstrap lacks players or persistent club mapping.")
    clubs = {}
    club_codes = set()
    for team in _records(bootstrap["teams"]):
        if not isinstance(team, dict) or not {"id", "code"} <= team.keys():
            raise ValueError("A captured bootstrap lacks explicit club identities.")
        team_id, code = _id(team["id"], "team id"), _id(team["code"], "club code")
        if team_id in clubs or code in club_codes:
            raise ValueError("A captured bootstrap has ambiguous club identities.")
        clubs[team_id] = code
        club_codes.add(code)
    try:
        priorities = captured_taker_priorities(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    except (DataError, KeyError, TypeError) as error:
        raise ValueError(
            "Captured phase priorities violate the existing taker contract."
        ) from error
    ranks = priorities.set_index("player_id")
    players = []
    for element in _records(bootstrap["elements"]):
        if not isinstance(element, dict) or "team" not in element:
            raise ValueError("A captured duty player lacks its club identity.")
        team_id = _id(element["team"], "player team id")
        if team_id not in clubs:
            raise ValueError("A captured duty player names an unmapped club.")
        code = _id(element["code"], "player code")
        row = ranks.loc[code]
        values = tuple(None if pd.isna(row[field]) else int(row[field]) for field in TAKER_FIELDS)
        players.append(PhaseDutyPlayer(code, clubs[team_id], *values))
    capture = PhaseDutyCapture(
        season,
        identifier,
        fingerprint,
        captured,
        valid_until,
        model_use_approved,
        model_use_evidence_ref,
        tuple(players),
    )
    _duties(capture, season=season, decision_at=decision_at)
    return capture


def _keys(document: dict[str, object], expected: set[str]) -> None:
    if set(document) != expected:
        raise ValueError("A private phase document has missing or unexpected fields.")


def _records(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("A private phase table must be an array of records.")
    return cast(list[dict[str, object]], value)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be an explicit boolean.")
    return value


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("A credited total must be a nonnegative integer.")
    return value


def _header(document: dict[str, object]) -> _PhaseContext:
    for name in _CONTEXT:
        if name not in document:
            raise ValueError("A private phase document lacks its fixture context.")
    return {
        "season": validate_phase_season(document["season"]),
        "gameweek": _id(document["gameweek"], "gameweek"),
        "fixture": _id(document["fixture"], "fixture"),
        "club": _id(document["club"], "club"),
        "opponent": _id(document["opponent"], "opponent"),
        "home": _boolean(document["home"], "home"),
        "kickoff": _time(document["kickoff"], "kickoff"),
        "decision_at": _time(document["decision_at"], "decision_at"),
    }


def _source_json(
    payload: bytes, source: PhaseSource, *, cutoff: str, kind: str
) -> dict[str, object]:
    source_receipt(source, cutoff=cutoff, kind=kind)
    if type(payload) is not bytes or payload_checksum(payload) != source.raw_sha256:
        raise ValueError("Private phase bytes differ from their exact source receipt.")
    return _json(payload)


def read_phase_observation(
    event_payload: bytes,
    totals_payload: bytes,
    baseline_payload: bytes,
    *,
    duties: PhaseDutyCapture,
    outcome_source: PhaseSource,
    totals_source: PhaseSource,
    baseline_source: PhaseSource,
    season: str,
    gameweek: int,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> PhaseObservation:
    """Read three separately bound documents after source-header preflight.

    The caller passes independently admitted source season/GW headers before
    any payload decoding, so a protected or target outcome is not opened first.
    """
    validate_phase_season(season)
    _id(gameweek, "gameweek")
    if (
        type(allowed_seasons) is not tuple
        or season == PROTECTED_SEASON
        or season not in allowed_seasons
    ):
        raise ValueError("The declared phase source season is protected or unselected.")
    if excluded_target == (season, gameweek):
        raise ValueError("The whole target gameweek is excluded before decoding outcomes.")
    for selected in allowed_seasons:
        validate_phase_season(selected)
        if selected == PROTECTED_SEASON:
            raise ValueError("The protected season cannot enter the phase source allowlist.")
    # Reject unavailable source headers before decoding any credited outcomes.
    source_receipt(outcome_source, cutoff=training_cutoff, kind="phase-events")
    source_receipt(totals_source, cutoff=training_cutoff, kind="fpl-totals")
    cutoff_instant = as_instant(_time(training_cutoff, "training_cutoff"))
    for settled_source in (outcome_source, totals_source):
        if any(
            as_instant(_time(value, "settled source timestamp")) >= cutoff_instant
            for value in (settled_source.published_at, settled_source.captured_at)
        ):
            raise ValueError(
                "Settled phase labels must be strictly before the training cutoff before decoding."
            )
    baseline = _source_json(
        baseline_payload, baseline_source, cutoff=training_cutoff, kind="baseline"
    )
    _keys(baseline, {*_CONTEXT, "schema_version", "players"})
    if baseline["schema_version"] != "football_phase_baseline_v1":
        raise ValueError("Unknown phase baseline schema.")
    context = _header(baseline)
    if context["season"] != season or context["gameweek"] != gameweek:
        raise ValueError("The phase source header and payload scope disagree.")
    decision_at = context["decision_at"]
    source_receipt(baseline_source, cutoff=decision_at, kind="baseline")
    _duties(duties, season=season, decision_at=decision_at)
    events = _source_json(
        event_payload, outcome_source, cutoff=training_cutoff, kind="phase-events"
    )
    totals = _source_json(totals_payload, totals_source, cutoff=training_cutoff, kind="fpl-totals")
    _keys(
        events,
        {
            *_CONTEXT,
            "schema_version",
            "rules_version",
            "phase_definition_version",
            "outcome_available_at",
            "complete_coverage",
            "events",
        },
    )
    _keys(
        totals,
        {*_CONTEXT, "schema_version", "rules_version", "outcome_available_at", "final", "players"},
    )
    if (
        events["schema_version"] != "football_phase_credits_v1"
        or totals["schema_version"] != "football_phase_fpl_totals_v1"
    ):
        raise ValueError("Unknown phase credit or independent FPL total schema.")
    if _header(events) != context or _header(totals) != context:
        raise ValueError(
            "Phase events, causal baseline and FPL totals have different fixture contexts."
        )
    rules = _text(events["rules_version"], "rules_version")
    available = _time(events["outcome_available_at"], "outcome_available_at")
    if (
        totals["rules_version"] != rules
        or _time(totals["outcome_available_at"], "outcome_available_at") != available
    ):
        raise ValueError("Phase events and FPL total finality/rules receipts disagree.")
    if not _boolean(totals["final"], "final"):
        raise ValueError("Independent FPL totals are not final.")
    baseline_rows = _records(baseline["players"])
    total_rows = _records(totals["players"])
    base_by_code = {}
    for row in baseline_rows:
        _keys(row, {"player_code", "position", "goal_weight90", "assist_weight90"})
        code = _id(row["player_code"], "baseline player_code")
        if code in base_by_code:
            raise ValueError("The causal phase baseline repeats a player.")
        base_by_code[code] = row
    players = []
    credits = []
    for row in total_rows:
        _keys(row, {"player_code", "minutes", "goals", "assists"})
        code = _id(row["player_code"], "FPL total player_code")
        if code not in base_by_code:
            raise ValueError("An FPL total has no causal player baseline.")
        base = base_by_code[code]
        players.append(
            PhasePlayer(
                code,
                _text(base["position"], "position"),
                _number(row["minutes"], "minutes", maximum=120),
                _number(base["goal_weight90"], "goal_weight90"),
                _number(base["assist_weight90"], "assist_weight90"),
            )
        )
        credits.append(PhaseTotal(code, _count(row["goals"]), _count(row["assists"])))
    if {p.player_code for p in players} != set(base_by_code):
        raise ValueError("The phase baseline and FPL total rosters differ.")
    goals = []
    for row in _records(events["events"]):
        _keys(
            row,
            {
                "event_id",
                "phase",
                "scorer",
                "assist",
                "own_goal",
                "credit_evidence_ref",
                "credit_status",
            },
        )
        scorer = None if row["scorer"] is None else _id(row["scorer"], "scorer")
        assister = None if row["assist"] is None else _id(row["assist"], "assist")
        goals.append(
            PhaseGoal(
                _text(row["event_id"], "event_id"),
                _text(row["phase"], "phase"),
                scorer,
                assister,
                _boolean(row["own_goal"], "own_goal"),
                _text(row["credit_evidence_ref"], "credit_evidence_ref"),
                _text(row["credit_status"], "credit_status"),
            )
        )
    observation = PhaseObservation(
        **context,
        outcome_available_at=available,
        duties=duties,
        baseline_source=baseline_source,
        outcome_source=outcome_source,
        totals_source=totals_source,
        players=tuple(players),
        events=tuple(goals),
        totals=tuple(credits),
        phase_definition_version=_text(
            events["phase_definition_version"], "phase_definition_version"
        ),
        rules_version=rules,
        complete_coverage=_boolean(events["complete_coverage"], "complete_coverage"),
    )
    validate_observation(
        observation,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    return observation


def read_phase_projection(
    payload: bytes,
    *,
    duties: PhaseDutyCapture,
    source: PhaseSource,
    model_cutoff: str,
) -> PhaseProjection:
    if not isinstance(source, PhaseSource):
        raise ValueError("A phase source receipt is required.")
    # A later-window projection may be captured after model fitting, provided
    # it is still known before its own recorded decision. It is not an outcome.
    known_at = max(
        as_instant(_time(source.published_at, "published_at")),
        as_instant(_time(source.captured_at, "captured_at")),
    ).isoformat()
    document = _source_json(payload, source, cutoff=known_at, kind="projection")
    _keys(document, {*_CONTEXT, "schema_version", "states"})
    if document["schema_version"] != "football_phase_projection_v1":
        raise ValueError("Unknown private phase projection schema.")
    context = _header(document)
    rows = _records(document["states"])
    if not 0 < len(rows) <= MAX_PHASE_STATES:
        raise ValueError("The private projected state array exceeds its declared cap.")
    states = []
    for row in rows:
        _keys(
            row, {"state_id", "weight", "goal_mass", "assist_mass", "physical_goal_mass", "players"}
        )
        players = []
        for player in _records(row["players"]):
            _keys(
                player, {"player_code", "position", "minutes", "goal_weight90", "assist_weight90"}
            )
            players.append(
                PhasePlayer(
                    _id(player["player_code"], "projected player_code"),
                    _text(player["position"], "position"),
                    _number(player["minutes"], "minutes", maximum=120),
                    _number(player["goal_weight90"], "goal_weight90"),
                    _number(player["assist_weight90"], "assist_weight90"),
                )
            )
        states.append(
            PhaseState(
                _text(row["state_id"], "state_id"),
                _number(row["weight"], "weight", maximum=1),
                tuple(players),
                _number(row["goal_mass"], "goal_mass"),
                _number(row["assist_mass"], "assist_mass"),
                _number(row["physical_goal_mass"], "physical_goal_mass"),
            )
        )
    projection = PhaseProjection(**context, duties=duties, states=tuple(states), source=source)
    validate_projection(projection, model_cutoff=model_cutoff)
    return projection
