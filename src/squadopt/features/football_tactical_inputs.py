"""Private named tactical facts and explicitly supplied paired predecision states."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal, cast

import numpy as np
import numpy.typing as npt

from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

TACTICAL_INPUT_VERSION = "football_tactical_inputs_v1"
STYLE_DEFINITION_VERSION = "football_tactical_style_counts_v1"
TRAIT_DEFINITION_VERSION = "football_tactical_named_traits_v1"
PROTECTED_SEASON = "2025-26"
MAX_TACTICAL_STATES = 1024
MAX_TACTICAL_PLAYERS = 64
MAX_TACTICAL_SOURCE_BYTES = 64 * 1024 * 1024
RAW_PROJECTION_VERSION = "football_tactical_projection_v1"
RAW_PHYSICAL_GOALS_VERSION = "football_tactical_physical_goals_v1"
RAW_FPL_CREDITS_VERSION = "football_tactical_fpl_credits_v1"
TRAITS = (
    "heading",
    "jumping_reach",
    "gk_aerial_reach",
    "pace",
    "acceleration",
    "anticipation",
    "positioning",
    "marking",
    "tackling",
    "strength",
    "off_the_ball",
    "crossing",
    "passing",
    "vision",
    "decisions",
    "technique",
)
STYLE_COUNTS = (
    "cross_attempts",
    "headed_shots",
    "throughball_attempts",
    "fast_break_shots",
    "pressure_events",
    "high_pass_attempts",
)
ATTACK_TRAITS = (
    "heading",
    "jumping_reach",
    "pace",
    "acceleration",
    "strength",
    "off_the_ball",
    "decisions",
    "technique",
)
DELIVERY_TRAITS = ("crossing", "passing", "vision", "decisions", "technique")
DEFENSE_TRAITS = (
    "heading",
    "jumping_reach",
    "pace",
    "anticipation",
    "positioning",
    "marking",
    "tackling",
    "strength",
)
TACTICAL_ROLES = ("goalkeeper", "defender", "midfielder", "attacker")
_TEAM_MAIN = (
    *("own_style_" + name for name in STYLE_COUNTS),
    *("opponent_style_" + name for name in STYLE_COUNTS),
    *("own_goal_weighted_" + name for name in ATTACK_TRAITS),
    *("own_assist_weighted_" + name for name in DELIVERY_TRAITS),
    *("opponent_defending_" + name for name in DEFENSE_TRAITS),
    "opponent_gk_aerial_reach",
)
_TEAM_PAIRS = (
    ("own_goal_weighted_heading", "opponent_defending_heading"),
    ("own_goal_weighted_jumping_reach", "opponent_defending_jumping_reach"),
    ("own_goal_weighted_pace", "opponent_defending_pace"),
    ("own_goal_weighted_off_the_ball", "opponent_defending_positioning"),
    ("own_assist_weighted_vision", "opponent_defending_anticipation"),
    ("own_assist_weighted_passing", "opponent_style_pressure_events"),
)
_TEAM_TRIPLES = (
    ("own_style_cross_attempts", "own_goal_weighted_heading", "opponent_defending_heading"),
    ("own_style_cross_attempts", "own_goal_weighted_jumping_reach", "opponent_gk_aerial_reach"),
    ("own_style_fast_break_shots", "own_goal_weighted_pace", "opponent_defending_pace"),
    (
        "own_style_throughball_attempts",
        "own_goal_weighted_off_the_ball",
        "opponent_defending_positioning",
    ),
    (
        "own_style_throughball_attempts",
        "own_assist_weighted_vision",
        "opponent_defending_anticipation",
    ),
    (
        "opponent_style_pressure_events",
        "own_assist_weighted_passing",
        "own_assist_weighted_decisions",
    ),
)
TEAM_FEATURES = (
    *_TEAM_MAIN,
    *("*".join(pair) for pair in _TEAM_PAIRS),
    *("*".join(triple) for triple in _TEAM_TRIPLES),
)
Array = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class TacticalSource:
    source_id: str
    provider: str
    version: str
    raw_sha256: str
    published_at: str
    captured_at: str
    source_kind: Literal["projection", "traits", "style", "physical-goals", "fpl-totals"]
    model_use_approved: bool
    model_use_evidence_ref: str


@dataclass(frozen=True, slots=True)
class TacticalProfile:
    player_code: int
    club: int
    position: str
    attributes: tuple[int | None, ...]
    attribute_definition_version: str
    original_identity: str
    identity_kind: Literal["uid", "versioned_row"]
    reviewed_mapping_ref: str
    observed_at: str
    valid_until: str
    source: TacticalSource


@dataclass(frozen=True, slots=True)
class TacticalStyleFixture:
    fixture: int
    gameweek: int
    kickoff: str
    final_at: str
    minutes: float


@dataclass(frozen=True, slots=True)
class TacticalStyle:
    club: int
    season: str
    window_start: str
    window_end: str
    fixtures: tuple[TacticalStyleFixture, ...]
    counts: tuple[int | None, ...]
    definition_version: str
    provider_mapping_ref: str
    complete_coverage: bool
    source: TacticalSource


@dataclass(frozen=True, slots=True)
class TacticalPlayerState:
    profile: TacticalProfile
    tactical_role: str
    minutes: float
    native_goal_share: float
    native_assist_share: float


@dataclass(frozen=True, slots=True)
class TacticalSideState:
    club: int
    base_goal_rate: float
    scored_fraction: float
    assist_fraction: float
    players: tuple[TacticalPlayerState, ...]


@dataclass(frozen=True, slots=True)
class TacticalJointState:
    state_id: str
    weight: float
    home: TacticalSideState
    away: TacticalSideState


@dataclass(frozen=True, slots=True)
class TacticalProjection:
    season: str
    gameweek: int
    fixture: int
    home_club: int
    away_club: int
    kickoff: str
    decision_at: str
    home_style: TacticalStyle
    away_style: TacticalStyle
    states: tuple[TacticalJointState, ...]
    source: TacticalSource


@dataclass(frozen=True, slots=True)
class TacticalCredit:
    player_code: int
    club: int
    goals: int
    assists: int


@dataclass(frozen=True, slots=True)
class TacticalObservation:
    projection: TacticalProjection
    outcome_available_at: str
    physical_goals: tuple[int, int]
    credits: tuple[TacticalCredit, ...]
    rules_version: str
    final: bool
    goal_source: TacticalSource
    credit_source: TacticalSource


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f"{label} must be bounded nonempty text.")
    return value


def _id(value: object, label: str) -> int:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError(f"{label} needs a positive persistent integer.")
    return value


def _number(value: object, label: str, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} needs an explicit number.")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} exceeds finite support.") from error
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        raise ValueError(f"{label} is outside its finite support.")
    return result


def _count(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"{label} needs a nonnegative integer count.")
    return value


def _time(value: object, label: str) -> str:
    try:
        return normalize_utc_timestamp(value, label=label)
    except DataError as error:
        raise ValueError(f"{label} needs an explicit UTC instant.") from error


def _season(value: object) -> str:
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"20\d{2}-\d{2}", value)
        or int(value[-2:]) != (int(value[:4]) + 1) % 100
    ):
        raise ValueError("A tactical season needs its consistent complete year pair.")
    return value


def source_receipt(
    source: TacticalSource, *, kind: str, cutoff: str, strict: bool = False
) -> dict[str, object]:
    if not isinstance(source, TacticalSource) or source.source_kind != kind:
        raise ValueError("A tactical source has the wrong semantic kind.")
    for field in ("source_id", "provider", "version", "model_use_evidence_ref"):
        _text(getattr(source, field), field)
    if not isinstance(source.raw_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", source.raw_sha256
    ):
        raise ValueError("A tactical source needs its exact original SHA256.")
    if type(source.model_use_approved) is not bool or not source.model_use_approved:
        raise ValueError("A tactical source needs admitted model-use evidence.")
    limit = as_instant(_time(cutoff, "source cutoff"))
    for field in ("published_at", "captured_at"):
        value = as_instant(_time(getattr(source, field), field))
        if value > limit or (strict and value == limit):
            raise ValueError("A tactical source was unavailable before its causal cutoff.")
    return asdict(source)


def projection_digest(projection: TacticalProjection) -> str:
    return hashlib.sha256(
        json.dumps(
            asdict(projection), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def observation_digest(observation: TacticalObservation) -> str:
    return hashlib.sha256(
        json.dumps(
            asdict(observation), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _fields(value: object, names: tuple[str, ...], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != set(names):
        raise ValueError(f"{label} must have exactly its versioned named fields.")
    return cast(dict[str, object], value)


def _rows(value: object, maximum: int, label: str) -> list[object]:
    if type(value) is not list or not 1 <= len(value) <= maximum:
        raise ValueError(f"{label} must be a bounded nonempty JSON array.")
    return cast(list[object], value)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} must be an explicit boolean.")
    return value


def _nullable_count(value: object, label: str) -> int | None:
    return None if value is None else _count(value, label)


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("A tactical JSON object repeats a named field.")
        result[name] = value
    return result


def _json_constant(value: str) -> object:
    raise ValueError("A tactical JSON source contains a nonfinite literal.")


def _verify_raw(payload: bytes, source: TacticalSource) -> None:
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_TACTICAL_SOURCE_BYTES:
        raise ValueError("A tactical source needs bounded nonempty original bytes.")
    if hashlib.sha256(payload).hexdigest() != source.raw_sha256:
        raise ValueError("Tactical original bytes differ from their source SHA256.")


def _raw_json(payload: bytes) -> object:
    try:
        return json.loads(
            payload.decode("utf-8"), object_pairs_hook=_json_pairs, parse_constant=_json_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("A tactical source requires bounded valid UTF8 JSON.") from error


def _source_json(value: object) -> TacticalSource:
    row = _fields(
        value,
        (
            "source_id",
            "provider",
            "version",
            "raw_sha256",
            "published_at",
            "captured_at",
            "source_kind",
            "model_use_approved",
            "model_use_evidence_ref",
        ),
        "nested tactical source",
    )
    kind = _text(row["source_kind"], "source_kind")
    if kind not in ("projection", "traits", "style", "physical-goals", "fpl-totals"):
        raise ValueError("A nested tactical source has an unknown semantic kind.")
    return TacticalSource(
        _text(row["source_id"], "source_id"),
        _text(row["provider"], "provider"),
        _text(row["version"], "version"),
        _text(row["raw_sha256"], "raw_sha256"),
        _time(row["published_at"], "published_at"),
        _time(row["captured_at"], "captured_at"),
        cast(Literal["projection", "traits", "style", "physical-goals", "fpl-totals"], kind),
        _boolean(row["model_use_approved"], "model_use_approved"),
        _text(row["model_use_evidence_ref"], "model_use_evidence_ref"),
    )


def _profile_json(value: object) -> TacticalProfile:
    row = _fields(
        value,
        (
            "player_code",
            "club",
            "position",
            "attributes",
            "attribute_definition_version",
            "original_identity",
            "identity_kind",
            "reviewed_mapping_ref",
            "observed_at",
            "valid_until",
            "source",
        ),
        "tactical profile",
    )
    attributes = _fields(row["attributes"], TRAITS, "named tactical attributes")
    kind = _text(row["identity_kind"], "identity_kind")
    if kind not in ("uid", "versioned_row"):
        raise ValueError("A tactical identity must explicitly be uid or versioned_row.")
    return TacticalProfile(
        _id(row["player_code"], "player_code"),
        _id(row["club"], "club"),
        _text(row["position"], "position"),
        tuple(_nullable_count(attributes[name], name) for name in TRAITS),
        _text(row["attribute_definition_version"], "attribute_definition_version"),
        _text(row["original_identity"], "original_identity"),
        cast(Literal["uid", "versioned_row"], kind),
        _text(row["reviewed_mapping_ref"], "reviewed_mapping_ref"),
        _time(row["observed_at"], "observed_at"),
        _time(row["valid_until"], "valid_until"),
        _source_json(row["source"]),
    )


def _style_json(value: object) -> TacticalStyle:
    row = _fields(
        value,
        (
            "club",
            "season",
            "window_start",
            "window_end",
            "fixtures",
            "counts",
            "definition_version",
            "provider_mapping_ref",
            "complete_coverage",
            "source",
        ),
        "tactical style",
    )
    fixtures = []
    for value in _rows(row["fixtures"], 512, "tactical style fixtures"):
        fixture = _fields(
            value, ("fixture", "gameweek", "kickoff", "final_at", "minutes"), "style fixture"
        )
        fixtures.append(
            TacticalStyleFixture(
                _id(fixture["fixture"], "style fixture"),
                _id(fixture["gameweek"], "style gameweek"),
                _time(fixture["kickoff"], "style kickoff"),
                _time(fixture["final_at"], "style final_at"),
                _number(fixture["minutes"], "style minutes", 120),
            )
        )
    counts = _fields(row["counts"], STYLE_COUNTS, "named tactical style counts")
    return TacticalStyle(
        _id(row["club"], "style club"),
        _season(row["season"]),
        _time(row["window_start"], "style window_start"),
        _time(row["window_end"], "style window_end"),
        tuple(fixtures),
        tuple(_nullable_count(counts[name], name) for name in STYLE_COUNTS),
        _text(row["definition_version"], "style definition_version"),
        _text(row["provider_mapping_ref"], "provider_mapping_ref"),
        _boolean(row["complete_coverage"], "complete_coverage"),
        _source_json(row["source"]),
    )


def _side_json(value: object) -> TacticalSideState:
    row = _fields(
        value,
        ("club", "base_goal_rate", "scored_fraction", "assist_fraction", "players"),
        "tactical side",
    )
    players = []
    for value in _rows(row["players"], MAX_TACTICAL_PLAYERS, "tactical roster"):
        player = _fields(
            value,
            ("profile", "tactical_role", "minutes", "native_goal_share", "native_assist_share"),
            "tactical player state",
        )
        players.append(
            TacticalPlayerState(
                _profile_json(player["profile"]),
                _text(player["tactical_role"], "tactical_role"),
                _number(player["minutes"], "projected minutes", 120),
                _number(player["native_goal_share"], "native_goal_share", 1),
                _number(player["native_assist_share"], "native_assist_share", 1),
            )
        )
    return TacticalSideState(
        _id(row["club"], "state club"),
        _number(row["base_goal_rate"], "base_goal_rate"),
        _number(row["scored_fraction"], "scored_fraction", 1),
        _number(row["assist_fraction"], "assist_fraction", 1),
        tuple(players),
    )


def read_tactical_projection(
    payload: bytes, *, source: TacticalSource, season: str, gameweek: int
) -> TacticalProjection:
    """Read one exact private projection envelope after declared context and SHA guards.

    Envelope fields are contract_version, season, gameweek, fixture, home_club,
    away_club, kickoff, decision_at, home_style, away_style and states. Every nested
    record has exactly its dataclass fields, except attributes/counts are complete
    named objects in TRAITS/STYLE_COUNTS order. The outer source is supplied by the
    caller and binds the original bytes. Nested sources are captured receipts.
    """
    _season(season)
    if season == PROTECTED_SEASON:
        raise ValueError("The protected season cannot enter tactical projections.")
    if _id(gameweek, "declared gameweek") > 38:
        raise ValueError("A declared tactical gameweek exceeds the season.")
    if not isinstance(source, TacticalSource):
        raise ValueError("A tactical source has the wrong semantic kind.")
    source_receipt(source, kind="projection", cutoff=source.captured_at)
    _verify_raw(payload, source)
    row = _fields(
        _raw_json(payload),
        (
            "contract_version",
            "season",
            "gameweek",
            "fixture",
            "home_club",
            "away_club",
            "kickoff",
            "decision_at",
            "home_style",
            "away_style",
            "states",
        ),
        "tactical projection envelope",
    )
    if (
        row["contract_version"] != RAW_PROJECTION_VERSION
        or _season(row["season"]) != season
        or _id(row["gameweek"], "gameweek") != gameweek
    ):
        raise ValueError(
            "A tactical projection envelope differs from its declared version/context."
        )
    states = []
    for value in _rows(row["states"], MAX_TACTICAL_STATES, "paired tactical states"):
        state = _fields(value, ("state_id", "weight", "home", "away"), "paired tactical state")
        states.append(
            TacticalJointState(
                _text(state["state_id"], "state_id"),
                _number(state["weight"], "state weight", 1),
                _side_json(state["home"]),
                _side_json(state["away"]),
            )
        )
    result = TacticalProjection(
        season,
        gameweek,
        _id(row["fixture"], "fixture"),
        _id(row["home_club"], "home_club"),
        _id(row["away_club"], "away_club"),
        _time(row["kickoff"], "kickoff"),
        _time(row["decision_at"], "decision_at"),
        _style_json(row["home_style"]),
        _style_json(row["away_style"]),
        tuple(states),
        source,
    )
    validate_tactical_projection(result)
    return result


_FINAL_IDENTITY_FIELDS = (
    "season",
    "gameweek",
    "fixture",
    "home_club",
    "away_club",
    "kickoff",
    "decision_at",
    "projection_sha256",
    "outcome_available_at",
    "final",
    "rules_version",
)


def _final_header(
    row: dict[str, object], *, projection: TacticalProjection, version: str
) -> tuple[str, str]:
    if row["contract_version"] != version:
        raise ValueError("A final tactical source has an unsupported envelope version.")
    for name in ("gameweek", "fixture", "home_club", "away_club"):
        if _id(row[name], name) != getattr(projection, name):
            raise ValueError(
                "Final tactical paired fixture identities differ from their projection."
            )
    if _season(row["season"]) != projection.season or row["projection_sha256"] != projection_digest(
        projection
    ):
        raise ValueError("Final tactical sources differ from the captured projection identity.")
    for name in ("kickoff", "decision_at"):
        if _time(row[name], name) != _time(getattr(projection, name), name):
            raise ValueError("Final tactical source clocks differ from their captured projection.")
    if not _boolean(row["final"], "final"):
        raise ValueError("Tactical FPL totals must be final, not TBC zero.")
    return _time(row["outcome_available_at"], "outcome_available_at"), _text(
        row["rules_version"], "rules_version"
    )


def read_tactical_observation(
    goal_payload: bytes,
    credit_payload: bytes,
    *,
    projection: TacticalProjection,
    goal_source: TacticalSource,
    credit_source: TacticalSource,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> TacticalObservation:
    """Read independently captured paired goals and full-roster final FPL credits.

    Each envelope repeats contract_version and all _FINAL_IDENTITY_FIELDS. Physical
    goals have physical_goals=[home,away]; credits have credits records with exactly
    player_code, club, goals, assists. Source/context/SHA checks for both documents
    precede JSON decoding. Their settlement clock, rules and projection must agree.
    """
    _training_context(
        projection,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    source_receipt(goal_source, kind="physical-goals", cutoff=training_cutoff, strict=True)
    source_receipt(credit_source, kind="fpl-totals", cutoff=training_cutoff, strict=True)
    _verify_raw(goal_payload, goal_source)
    _verify_raw(credit_payload, credit_source)
    goal = _fields(
        _raw_json(goal_payload),
        ("contract_version", *_FINAL_IDENTITY_FIELDS, "physical_goals"),
        "physical tactical goals envelope",
    )
    credit = _fields(
        _raw_json(credit_payload),
        ("contract_version", *_FINAL_IDENTITY_FIELDS, "credits"),
        "final tactical FPL credits envelope",
    )
    goal_header = _final_header(goal, projection=projection, version=RAW_PHYSICAL_GOALS_VERSION)
    credit_header = _final_header(credit, projection=projection, version=RAW_FPL_CREDITS_VERSION)
    if goal_header != credit_header:
        raise ValueError("Independent tactical final sources disagree on settlement/rules.")
    header = TacticalObservation(
        projection, goal_header[0], (0, 0), (), goal_header[1], True, goal_source, credit_source
    )
    validate_observation_header(
        header,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    physical = _rows(goal["physical_goals"], 2, "paired physical goals")
    if len(physical) != 2:
        raise ValueError("Tactical physical goals must cover exactly both fixture sides.")
    records = []
    for value in _rows(credit["credits"], 2 * MAX_TACTICAL_PLAYERS, "final FPL credits"):
        row = _fields(
            value, ("player_code", "club", "goals", "assists"), "final player FPL credits"
        )
        records.append(
            TacticalCredit(
                _id(row["player_code"], "credited player_code"),
                _id(row["club"], "credited club"),
                _count(row["goals"], "final goals"),
                _count(row["assists"], "final assists"),
            )
        )
    result = TacticalObservation(
        projection,
        goal_header[0],
        (_count(physical[0], "home physical goals"), _count(physical[1], "away physical goals")),
        tuple(records),
        goal_header[1],
        True,
        goal_source,
        credit_source,
    )
    validate_observation(
        result,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    return result


def _profile(profile: TacticalProfile, *, club: int, decision_at: str) -> None:
    if not isinstance(profile, TacticalProfile) or profile.club != club:
        raise ValueError("A tactical profile names another captured club.")
    _id(profile.player_code, "player_code")
    _id(profile.club, "profile club")
    if profile.position not in ("GK", "DEF", "MID", "FWD"):
        raise ValueError("A tactical profile lacks its native FPL scoring position.")
    if profile.attribute_definition_version != TRAIT_DEFINITION_VERSION:
        raise ValueError("A tactical profile has an unsupported trait definition.")
    if type(profile.attributes) is not tuple or len(profile.attributes) != len(TRAITS):
        raise ValueError("A tactical profile needs every named nullable trait.")
    for value in profile.attributes:
        if value is not None and (type(value) is not int or not 1 <= value <= 20):
            raise ValueError("A native tactical trait must be integer1..20 or published unknown.")
    _text(profile.original_identity, "original_identity")
    _text(profile.reviewed_mapping_ref, "reviewed_mapping_ref")
    if profile.identity_kind not in ("uid", "versioned_row"):
        raise ValueError("A tactical profile lacks its explicit original identity kind.")
    decision = as_instant(_time(decision_at, "profile decision"))
    observed = as_instant(_time(profile.observed_at, "profile observed_at"))
    if not observed <= decision <= as_instant(_time(profile.valid_until, "profile valid_until")):
        raise ValueError("A tactical trait profile is future or expired at its decision.")
    source_receipt(profile.source, kind="traits", cutoff=decision_at)
    if observed > as_instant(_time(profile.source.captured_at, "trait source captured_at")):
        raise ValueError("A tactical profile vintage follows its own source capture.")


def _style(style: TacticalStyle, *, club: int, projection: TacticalProjection) -> None:
    if (
        not isinstance(style, TacticalStyle)
        or style.club != club
        or style.season != projection.season
    ):
        raise ValueError("A tactical style source has the wrong club/season identity.")
    if style.definition_version != STYLE_DEFINITION_VERSION:
        raise ValueError("A tactical style uses an unsupported metric definition.")
    _id(style.club, "style club")
    _text(style.provider_mapping_ref, "provider_mapping_ref")
    if type(style.complete_coverage) is not bool or not style.complete_coverage:
        raise ValueError("Tactical style needs complete admitted event coverage.")
    source_receipt(style.source, kind="style", cutoff=projection.decision_at)
    start = as_instant(_time(style.window_start, "style window_start"))
    end = as_instant(_time(style.window_end, "style window_end"))
    decision = as_instant(_time(projection.decision_at, "style decision"))
    if not start < end < decision or end > as_instant(
        _time(style.source.captured_at, "style capture")
    ):
        raise ValueError("A tactical style window is future, empty or predates source finality.")
    if type(style.counts) is not tuple or len(style.counts) != len(STYLE_COUNTS):
        raise ValueError("Tactical style must preserve each nullable named count.")
    for count in style.counts:
        if count is not None:
            _count(count, "tactical style count")
    if type(style.fixtures) is not tuple or not style.fixtures:
        raise ValueError("Tactical style requires known fixture exposure.")
    seen = set()
    year = int(projection.season[:4])
    season_start = datetime(year, 7, 1, tzinfo=UTC)
    season_end = datetime(year + 1, 8, 1, tzinfo=UTC)
    for fixture in style.fixtures:
        if not isinstance(fixture, TacticalStyleFixture):
            raise ValueError("A tactical style exposure has an invalid fixture record.")
        _id(fixture.fixture, "style fixture")
        _id(fixture.gameweek, "style gameweek")
        if (
            fixture.fixture in seen
            or fixture.fixture == projection.fixture
            or fixture.gameweek >= projection.gameweek
        ):
            raise ValueError("Tactical style repeats or includes a target/later gameweek fixture.")
        seen.add(fixture.fixture)
        kickoff = as_instant(_time(fixture.kickoff, "style kickoff"))
        final = as_instant(_time(fixture.final_at, "style final_at"))
        if (
            not start <= kickoff < final <= end
            or not season_start <= kickoff < season_end
            or _number(fixture.minutes, "style minutes", 120) <= 0
        ):
            raise ValueError("Tactical style fixture exposure or finality is inconsistent.")


def _side(side: TacticalSideState, *, club: int, projection: TacticalProjection) -> None:
    if not isinstance(side, TacticalSideState) or side.club != club:
        raise ValueError("A paired tactical state has another club identity.")
    _id(side.club, "state club")
    _number(side.base_goal_rate, "base_goal_rate")
    for field in ("scored_fraction", "assist_fraction"):
        _number(getattr(side, field), field, 1)
    if type(side.players) is not tuple or not 1 <= len(side.players) <= MAX_TACTICAL_PLAYERS:
        raise ValueError("A tactical state requires a bounded complete source roster.")
    seen = set()
    for player in side.players:
        if not isinstance(player, TacticalPlayerState):
            raise ValueError("A tactical player state has an invalid record type.")
        _profile(player.profile, club=club, decision_at=projection.decision_at)
        code = player.profile.player_code
        if code in seen:
            raise ValueError("A tactical club state repeats a persistent player.")
        seen.add(code)
        if player.tactical_role not in TACTICAL_ROLES:
            raise ValueError("An explicit projected tactical role is required.")
        minutes = _number(player.minutes, "projected minutes", 120)
        for field in ("native_goal_share", "native_assist_share"):
            value = _number(getattr(player, field), field, 1)
            if minutes == 0 and value != 0:
                raise ValueError("An absent tactical player cannot have native attacking exposure.")
        if (
            player.native_goal_share * side.scored_fraction
            + player.native_assist_share * side.scored_fraction * side.assist_fraction
        ) > 1 + 1e-12:
            raise ValueError("Native player G/A exposure exceeds a physical scoring event.")
    active = any(player.minutes > 0 for player in side.players)
    for field in ("native_goal_share", "native_assist_share"):
        if not math.isclose(
            math.fsum(getattr(player, field) for player in side.players),
            float(active),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Native tactical shares do not conserve full projected club exposure.")
    if not active and side.base_goal_rate > 0:
        raise ValueError("Positive tactical physical intensity has no projected club exposure.")
    if math.fsum(player.minutes for player in side.players) > 11 * 120 + 1e-12:
        raise ValueError("The tactical state exceeds eleven-player minute exposure.")


def validate_tactical_projection(
    projection: TacticalProjection, *, model_cutoff: str | None = None
) -> None:
    if not isinstance(projection, TacticalProjection):
        raise ValueError("A complete paired tactical projection is required.")
    _season(projection.season)
    if projection.season == PROTECTED_SEASON:
        raise ValueError("The protected season cannot enter tactical projections.")
    for field in ("gameweek", "fixture", "home_club", "away_club"):
        _id(getattr(projection, field), field)
    if projection.gameweek > 38 or projection.home_club == projection.away_club:
        raise ValueError("A tactical fixture has invalid paired identity.")
    decision = as_instant(_time(projection.decision_at, "decision_at"))
    kickoff = as_instant(_time(projection.kickoff, "kickoff"))
    year = int(projection.season[:4])
    if decision > kickoff or not datetime(year, 7, 1, tzinfo=UTC) <= kickoff < datetime(
        year + 1, 8, 1, tzinfo=UTC
    ):
        raise ValueError("A tactical decision/kickoff disagrees with its season.")
    if model_cutoff is not None and decision < as_instant(_time(model_cutoff, "model cutoff")):
        raise ValueError("A tactical projection precedes the fitted model cutoff.")
    source_receipt(projection.source, kind="projection", cutoff=projection.decision_at)
    _style(projection.home_style, club=projection.home_club, projection=projection)
    _style(projection.away_style, club=projection.away_club, projection=projection)
    if (
        type(projection.states) is not tuple
        or not 1 <= len(projection.states) <= MAX_TACTICAL_STATES
    ):
        raise ValueError("A tactical projection needs bounded complete paired states.")
    names = set()
    identities: dict[tuple[int, int], TacticalProfile] | None = None
    fractions: tuple[float, ...] | None = None
    for state in projection.states:
        if not isinstance(state, TacticalJointState) or _text(state.state_id, "state_id") in names:
            raise ValueError("Tactical paired state identities are invalid or repeated.")
        names.add(state.state_id)
        _number(state.weight, "state weight", 1)
        _side(state.home, club=projection.home_club, projection=projection)
        _side(state.away, club=projection.away_club, projection=projection)
        current = {
            (side.club, player.profile.player_code): player.profile
            for side in (state.home, state.away)
            for player in side.players
        }
        codes = [code for _, code in current]
        if len(codes) != len(set(codes)):
            raise ValueError("One persistent player belongs to both fixture sides.")
        originals = [
            (
                profile.source.provider,
                profile.source.version,
                profile.identity_kind,
                profile.original_identity,
            )
            for profile in current.values()
        ]
        if len(originals) != len(set(originals)):
            raise ValueError("An original tactical source identity maps to multiple players.")
        if identities is not None and current != identities:
            raise ValueError("Tactical states changed captured roster/profile identity.")
        identities = current
        current_fractions = (
            state.home.scored_fraction,
            state.home.assist_fraction,
            state.away.scored_fraction,
            state.away.assist_fraction,
        )
        if fractions is not None and current_fractions != fractions:
            raise ValueError("Tactical states changed the native credited-fraction basis.")
        fractions = current_fractions
    if not math.isclose(
        math.fsum(state.weight for state in projection.states), 1, rel_tol=1e-12, abs_tol=1e-12
    ):
        raise ValueError("Paired tactical state probabilities must sum to one.")


def _training_context(
    projection: TacticalProjection,
    *,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> datetime:
    if not isinstance(projection, TacticalProjection):
        raise ValueError("A tactical observation lacks predecision states.")
    if (
        type(allowed_seasons) is not tuple
        or not allowed_seasons
        or not all(isinstance(selected, str) for selected in allowed_seasons)
        or len(set(allowed_seasons)) != len(allowed_seasons)
    ):
        raise ValueError("A unique explicit tactical season allowlist is required.")
    for selected in allowed_seasons:
        _season(selected)
        if selected == PROTECTED_SEASON:
            raise ValueError("The protected season cannot enter tactical training.")
    if projection.season not in allowed_seasons or projection.season == PROTECTED_SEASON:
        raise ValueError("A tactical observation has a protected/unselected season.")
    if excluded_target == (projection.season, projection.gameweek):
        raise ValueError("The whole target gameweek is excluded before tactical labels.")
    validate_tactical_projection(projection)
    cutoff = as_instant(_time(training_cutoff, "training_cutoff"))
    if as_instant(_time(projection.kickoff, "kickoff")) >= cutoff:
        raise ValueError("Tactical final outcomes were unavailable before training.")
    return cutoff


def validate_observation_header(
    observation: TacticalObservation,
    *,
    training_cutoff: str,
    allowed_seasons: tuple[str, ...],
    excluded_target: tuple[str, int] | None = None,
) -> None:
    if not isinstance(observation, TacticalObservation):
        raise ValueError("A tactical training observation is required.")
    projection = observation.projection
    cutoff = _training_context(
        projection,
        training_cutoff=training_cutoff,
        allowed_seasons=allowed_seasons,
        excluded_target=excluded_target,
    )
    kickoff = as_instant(_time(projection.kickoff, "kickoff"))
    final = as_instant(_time(observation.outcome_available_at, "outcome_available_at"))
    if not kickoff < final < cutoff:
        raise ValueError("Tactical final outcomes were unavailable before training.")
    for source, kind in (
        (observation.goal_source, "physical-goals"),
        (observation.credit_source, "fpl-totals"),
    ):
        source_receipt(source, kind=kind, cutoff=training_cutoff, strict=True)
        if as_instant(_time(source.captured_at, "final source capture")) < final:
            raise ValueError("A tactical final source capture predates declared settlement.")
    _text(observation.rules_version, "rules_version")
    if type(observation.final) is not bool or not observation.final:
        raise ValueError("Tactical FPL totals must be final, not TBC zero.")


def validate_observation(
    observation: TacticalObservation,
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
    if type(observation.physical_goals) is not tuple or len(observation.physical_goals) != 2:
        raise ValueError("Tactical physical goals must cover exactly both fixture sides.")
    for goals in observation.physical_goals:
        _count(goals, "physical goals")
    if type(observation.credits) is not tuple:
        raise ValueError("Final tactical FPL credits must be immutable complete records.")
    projection = observation.projection
    roster = {
        (side.club, player.profile.player_code)
        for side in (projection.states[0].home, projection.states[0].away)
        for player in side.players
    }
    seen = set()
    for credit in observation.credits:
        if not isinstance(credit, TacticalCredit):
            raise ValueError("A tactical credited record has an invalid type.")
        _id(credit.player_code, "credited player_code")
        _id(credit.club, "credited club")
        key = (credit.club, credit.player_code)
        if key not in roster or key in seen:
            raise ValueError("Tactical final credits invent or repeat captured identity.")
        seen.add(key)
        for field in ("goals", "assists"):
            _count(getattr(credit, field), "final " + field)
    if seen != roster:
        raise ValueError("Missing tactical FPL totals cannot become zero credit.")
    for club, physical in zip(
        (projection.home_club, projection.away_club), observation.physical_goals, strict=True
    ):
        records = [credit for credit in observation.credits if credit.club == club]
        if any(
            sum(getattr(credit, head) for credit in records) > physical
            for head in ("goals", "assists")
        ) or any(credit.goals + credit.assists > physical for credit in records):
            raise ValueError("Final tactical G/A credit is incompatible with physical goals.")


def _trait(player: TacticalPlayerState, name: str) -> float:
    value = player.profile.attributes[TRAITS.index(name)]
    if value is None:
        raise ValueError(f"The enabled tactical channel lacks named trait {name}.")
    return float(value) / 20


def _weighted_trait(side: TacticalSideState, name: str, basis: str) -> float:
    terms = []
    weights = []
    for player in side.players:
        weight = (
            player.native_goal_share
            if basis == "goal"
            else player.native_assist_share
            if basis == "assist"
            else player.minutes
            if basis == "defense" and player.tactical_role in ("defender", "midfielder")
            else player.minutes
            if basis == "keeper" and player.tactical_role == "goalkeeper"
            else 0.0
        )
        if weight > 0:
            weights.append(weight)
            terms.append(weight * _trait(player, name))
    denominator = math.fsum(weights)
    if denominator <= 0:
        raise ValueError(f"A tactical {basis} channel has no projected trait exposure.")
    return math.fsum(terms) / denominator


def _style_rates(style: TacticalStyle) -> dict[str, float]:
    minutes = math.fsum(fixture.minutes for fixture in style.fixtures)
    if minutes <= 0 or any(count is None for count in style.counts):
        raise ValueError("An enabled tactical style channel has unavailable exposure or counts.")
    return {
        name: float(cast(int, count)) * 90 / minutes
        for name, count in zip(STYLE_COUNTS, style.counts, strict=True)
    }


def team_features(
    projection: TacticalProjection, state: TacticalJointState, *, home: bool
) -> Array:
    own, opponent = (state.home, state.away) if home else (state.away, state.home)
    own_style, opponent_style = (
        (projection.home_style, projection.away_style)
        if home
        else (projection.away_style, projection.home_style)
    )
    values = {"own_style_" + name: value for name, value in _style_rates(own_style).items()}
    values.update(
        {"opponent_style_" + name: value for name, value in _style_rates(opponent_style).items()}
    )
    values.update(
        {"own_goal_weighted_" + name: _weighted_trait(own, name, "goal") for name in ATTACK_TRAITS}
    )
    values.update(
        {
            "own_assist_weighted_" + name: _weighted_trait(own, name, "assist")
            for name in DELIVERY_TRAITS
        }
    )
    values.update(
        {
            "opponent_defending_" + name: _weighted_trait(opponent, name, "defense")
            for name in DEFENSE_TRAITS
        }
    )
    values["opponent_gk_aerial_reach"] = _weighted_trait(opponent, "gk_aerial_reach", "keeper")
    for fields in (*_TEAM_PAIRS, *_TEAM_TRIPLES):
        values["*".join(fields)] = math.prod(values[name] for name in fields)
    result = np.array([values[name] for name in TEAM_FEATURES], dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Tactical team features exceed finite support.")
    return result


def recipient_feature_names(head: str) -> tuple[str, ...]:
    if head not in ("goals", "assists"):
        raise ValueError("A tactical recipient head must name goals or assists.")
    traits = ATTACK_TRAITS if head == "goals" else DELIVERY_TRAITS
    names = (
        *("player_" + name for name in traits),
        *("role_" + role for role in TACTICAL_ROLES),
        *("opponent_defending_" + name for name in DEFENSE_TRAITS),
        "opponent_gk_aerial_reach",
        *("own_style_" + name for name in STYLE_COUNTS),
        *("opponent_style_" + name for name in STYLE_COUNTS),
    )
    interactions = (
        (
            "player_heading*opponent_defending_heading",
            "player_jumping_reach*opponent_defending_jumping_reach",
            "player_pace*opponent_defending_pace",
            "player_off_the_ball*opponent_defending_positioning",
            "own_style_cross_attempts*player_heading*opponent_defending_heading",
            "own_style_throughball_attempts*player_off_the_ball*opponent_defending_positioning",
        )
        if head == "goals"
        else (
            "player_passing*opponent_defending_anticipation",
            "player_vision*opponent_defending_positioning",
            "player_crossing*opponent_defending_heading",
            "opponent_style_pressure_events*player_passing*player_decisions",
            "own_style_cross_attempts*player_crossing*opponent_defending_heading",
            "own_style_throughball_attempts*player_vision*opponent_defending_anticipation",
        )
    )
    return (*names, *interactions)


def recipient_features(
    projection: TacticalProjection,
    state: TacticalJointState,
    player: TacticalPlayerState,
    *,
    home: bool,
    head: str,
) -> Array:
    names = recipient_feature_names(head)
    if player.minutes == 0:
        return np.zeros(len(names), dtype=float)
    own, opponent = (state.home, state.away) if home else (state.away, state.home)
    if player not in own.players:
        raise ValueError("Tactical recipient is outside its supplied complete club state.")
    own_style, opponent_style = (
        (projection.home_style, projection.away_style)
        if home
        else (projection.away_style, projection.home_style)
    )
    traits = ATTACK_TRAITS if head == "goals" else DELIVERY_TRAITS
    values = {"player_" + name: _trait(player, name) for name in traits}
    values.update({"role_" + role: float(player.tactical_role == role) for role in TACTICAL_ROLES})
    values.update(
        {
            "opponent_defending_" + name: _weighted_trait(opponent, name, "defense")
            for name in DEFENSE_TRAITS
        }
    )
    values["opponent_gk_aerial_reach"] = _weighted_trait(opponent, "gk_aerial_reach", "keeper")
    values.update({"own_style_" + name: value for name, value in _style_rates(own_style).items()})
    values.update(
        {"opponent_style_" + name: value for name, value in _style_rates(opponent_style).items()}
    )
    for name in names:
        if "*" in name:
            values[name] = math.prod(values[field] for field in name.split("*"))
    result = np.array([values[name] for name in names], dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Tactical recipient features exceed finite support.")
    return result
