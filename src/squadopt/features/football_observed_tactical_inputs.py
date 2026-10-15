"""Partial tactical evidence and full-roster native marginal-context inputs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from squadopt.features.football_tactical_inputs import (
    ATTACK_TRAITS,
    DEFENSE_TRAITS,
    DELIVERY_TRAITS,
    TRAITS,
    TacticalCredit,
    _count,
    _id,
    _number,
    _season,
    _text,
    _time,
)

INPUT_VERSION = "football_observed_tactical_inputs_v2"
STYLE_VERSION = "observed_four_event_counts_per_fixture_28_days_v1"
ROLE_POLICY = "latest_confirmed_role_same_current_club_within28d_v1"
CONTEXT_POLICY = "native_full_roster_marginal_context_v1"
REPLAY_VERSION = "retrospective_observed_tactical_facts_v1"
CHANNELS = ("cross_attempts", "throughball_attempts", "headed_shots", "fast_break_shots")
ROLES = ("G", "D", "M", "F")
REQUIRED_HISTORY = ("players_raw.csv", "teams.csv", "fixtures.csv", "gws/merged_gw.csv")


@dataclass(frozen=True, slots=True)
class ObservedTacticalSource:
    source_id: str
    provider: str
    version: str
    sha256: str
    published_at: str
    retrieved_at: str
    model_use_approved: bool
    model_use_evidence_ref: str


@dataclass(frozen=True, slots=True)
class ObservedTacticalReplay:
    revision: str
    recorded_at: str
    retrieved_at: str
    generated_at: str
    feature_cutoff: str
    latest_native_history_kickoff: str
    source_hashes: tuple[tuple[str, str], ...]
    version: str = REPLAY_VERSION


@dataclass(frozen=True, slots=True)
class ObservedEventFixture:
    season: str
    gameweek: int
    fixture: int
    club: int
    opponent: int
    kickoff: str
    finished_at: str
    provider_match_id: str
    provider_club_id: str
    bridge_sha256: str
    inventory_sha256: str
    counts: tuple[int, ...]
    event_rows: int
    selected_event_ids: tuple[int, ...]
    source: ObservedTacticalSource
    complete_selected_fixture: bool
    definition_version: str = STYLE_VERSION
    pressure_events: None = None
    high_pass_attempts: None = None


@dataclass(frozen=True, slots=True)
class ObservedRole:
    season: str
    gameweek: int
    fixture: int
    kickoff: str
    finished_at: str
    player_code: int
    club: int
    provider_role: str
    provider_player_id: str
    original_row: int
    mapping_ref: str
    source: ObservedTacticalSource


@dataclass(frozen=True, slots=True)
class ObservedTacticalProfile:
    player_code: int
    club: int
    fpl_position: str
    attributes: tuple[int | None, ...]
    original_identity: str | None
    mapping_ref: str | None
    trait_source: ObservedTacticalSource | None
    role_inventory_sha256: str | None
    role_inventory_complete: bool
    role_history: tuple[ObservedRole, ...]
    trait_columns: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ObservedTacticalPlayer:
    profile: ObservedTacticalProfile
    minutes: float
    native_goal_share: float
    native_assist_share: float


@dataclass(frozen=True, slots=True)
class ObservedTacticalSide:
    club: int
    players: tuple[ObservedTacticalPlayer, ...]
    base_goal_rate: float
    scored_fraction: float
    assist_fraction: float
    observed_fixtures: tuple[ObservedEventFixture, ...]


@dataclass(frozen=True, slots=True)
class ObservedTacticalProjection:
    season: str
    gameweek: int
    fixture: int
    kickoff: str
    decision_at: str
    feature_cutoff: str
    generated_at: str
    home: ObservedTacticalSide
    away: ObservedTacticalSide
    roster: tuple[tuple[int, int, str], ...]
    native_source: ObservedTacticalSource
    roster_source: ObservedTacticalSource
    replay: ObservedTacticalReplay | None = None
    version: str = INPUT_VERSION
    context_policy: str = CONTEXT_POLICY
    coverage_scope: str = "enumerated_observed_provider_fixtures_not_complete_world"


@dataclass(frozen=True, slots=True)
class ObservedTacticalObservation:
    projection: ObservedTacticalProjection
    outcome_available_at: str
    goal_source: ObservedTacticalSource
    credit_source: ObservedTacticalSource
    physical_goals: tuple[int, int]
    credits: tuple[TacticalCredit, ...]
    rules_version: str
    final: bool


def instant(value: str) -> datetime:
    return datetime.fromisoformat(_time(value, "observed tactical clock").replace("Z", "+00:00"))


def sha(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("Observed tactical evidence requires an exact SHA256.")
    return value


def digest(value: ObservedTacticalProjection | ObservedTacticalObservation) -> str:
    return hashlib.sha256(
        json.dumps(asdict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_source(source: ObservedTacticalSource, available_by: str) -> None:
    if type(source) is not ObservedTacticalSource:
        raise ValueError("Observed tactical source type is required.")
    for name in ("source_id", "provider", "version", "model_use_evidence_ref"):
        _text(getattr(source, name), name)
    sha(source.sha256)
    if source.model_use_approved is not True:
        raise ValueError("Observed tactical model use requires explicit evidence.")
    if not instant(source.published_at) <= instant(source.retrieved_at) <= instant(available_by):
        raise ValueError("Observed tactical source clocks are inconsistent.")


def validate_training_release(season: str, flag: bool) -> None:
    if type(flag) is not bool:
        raise ValueError("Observed tactical released-season opt-in must be Boolean.")
    _season(season)
    if season == "2025-26" and not flag:
        raise ValueError("Observed tactical 2025-26 requires explicit training opt-in.")


def _earlier(season: str, gameweek: int, fixture: int, p: ObservedTacticalProjection) -> None:
    _season(season)
    _id(fixture, "historical fixture")
    if type(gameweek) is not int or not 1 <= gameweek <= 38:
        raise ValueError("Observed tactical historical gameweek is invalid.")
    if season != p.season or gameweek >= p.gameweek or fixture == p.fixture:
        raise ValueError("Observed tactical history must exclude the whole target and later GW.")


def _availability(p: ObservedTacticalProjection) -> str:
    return p.generated_at


def forecast_role(profile: ObservedTacticalProfile, p: ObservedTacticalProjection) -> str | None:
    """Lagged same-club categorical feature, without a future-position or continuity claim."""
    if not profile.role_inventory_complete:
        return None
    start = instant(p.feature_cutoff) - timedelta(days=28)
    eligible = [
        r
        for r in profile.role_history
        if r.club == profile.club and start <= instant(r.kickoff) < instant(p.feature_cutoff)
    ]
    if not eligible:
        return None
    latest = max(instant(r.kickoff) for r in eligible)
    roles = {r.provider_role for r in eligible if instant(r.kickoff) == latest}
    if len(roles) != 1:
        raise ValueError("Latest provider-role observations contradict one another.")
    return roles.pop()


def _profile(profile: ObservedTacticalProfile, p: ObservedTacticalProjection, club: int) -> None:
    if type(profile) is not ObservedTacticalProfile or profile.club != club:
        raise ValueError("Observed tactical player/club identity differs.")
    _id(profile.player_code, "player_code")
    if profile.fpl_position not in ("GK", "DEF", "MID", "FWD"):
        raise ValueError("Observed tactical FPL scoring position is invalid.")
    if type(profile.attributes) is not tuple or len(profile.attributes) != len(TRAITS):
        raise ValueError("Observed tactical traits require the sixteen named nullable values.")
    if any(v is not None and (type(v) is not int or not 1 <= v <= 20) for v in profile.attributes):
        raise ValueError("Observed tactical traits must be explicit integers1..20 or None.")
    if profile.trait_source is None:
        if (
            any(v is not None for v in profile.attributes)
            or profile.original_identity is not None
            or profile.mapping_ref is not None
            or profile.trait_columns
        ):
            raise ValueError("Unknown FM source cannot supply traits or a fabricated identity.")
    else:
        validate_source(profile.trait_source, _availability(p))
        _text(profile.original_identity, "FM original identity")
        _text(profile.mapping_ref, "FM exact mapping")
        if instant(profile.trait_source.published_at) > instant(p.feature_cutoff):
            raise ValueError("FM attributes were published after the historical feature cutoff.")
        if type(profile.trait_columns) is not tuple:
            raise ValueError("FM source columns require an immutable named mapping.")
        columns = dict(profile.trait_columns)
        if (
            len(columns) != len(profile.trait_columns)
            or not set(columns) <= set(TRAITS)
            or len(set(columns.values())) != len(columns)
        ):
            raise ValueError("FM source columns must map distinct supported trait names.")
        for _name, column in profile.trait_columns:
            _text(column, "original FM attribute column")
        if any(
            value is not None and name not in columns
            for name, value in zip(TRAITS, profile.attributes, strict=True)
        ):
            raise ValueError("Observed FM attribute lacks its original source-column mapping.")
    if type(profile.role_inventory_complete) is not bool:
        raise ValueError("Provider-role inventory completeness must be Boolean.")
    if profile.role_inventory_complete and profile.role_inventory_sha256 is None:
        raise ValueError("Complete selected provider-role inventory needs its source hash.")
    if profile.role_inventory_sha256 is not None:
        sha(profile.role_inventory_sha256)
    if type(profile.role_history) is not tuple or len(profile.role_history) > 128:
        raise ValueError("Provider-role history must be a bounded immutable inventory.")
    seen = set()
    for r in profile.role_history:
        if type(r) is not ObservedRole or r.player_code != profile.player_code:
            raise ValueError("Provider role has another persistent person identity.")
        _id(r.player_code, "role persistent person")
        _earlier(r.season, r.gameweek, r.fixture, p)
        _id(r.club, "role club")
        _id(r.original_row, "role source row")
        _text(r.provider_player_id, "provider player")
        _text(r.mapping_ref, "role exact mapping")
        validate_source(r.source, _availability(p))
        if r.provider_role not in ROLES or not instant(r.kickoff) < instant(
            r.finished_at
        ) < instant(p.feature_cutoff):
            raise ValueError("Provider role is unconfirmed, future or unavailable.")
        if instant(r.finished_at) > instant(r.source.retrieved_at):
            raise ValueError("Provider role source was acquired before the declared finished fact.")
        key = r.season, r.fixture
        if key in seen:
            raise ValueError("Provider-role fixture is duplicated.")
        seen.add(key)
    forecast_role(profile, p)


def _side(side: ObservedTacticalSide, p: ObservedTacticalProjection) -> None:
    if type(side) is not ObservedTacticalSide:
        raise ValueError("Observed tactical paired side is required.")
    _id(side.club, "club")
    _number(side.base_goal_rate, "native paired goal rate")
    for name in ("scored_fraction", "assist_fraction"):
        _number(getattr(side, name), name, 1)
    if type(side.players) is not tuple or not 11 <= len(side.players) <= 64:
        raise ValueError("Observed tactical context needs its full original club roster.")
    seen = set()
    for player in side.players:
        if type(player) is not ObservedTacticalPlayer:
            raise ValueError("Observed tactical player state type is required.")
        _profile(player.profile, p, side.club)
        code = player.profile.player_code
        if code in seen:
            raise ValueError("Observed tactical roster repeats a persistent player.")
        seen.add(code)
        _number(player.minutes, "projected minutes", 90)
        for name in ("native_goal_share", "native_assist_share"):
            value = _number(getattr(player, name), name, 1)
            if player.minutes == 0 and value != 0:
                raise ValueError("Absent player has positive native recipient support.")
        if (
            side.scored_fraction
            * (player.native_goal_share + side.assist_fraction * player.native_assist_share)
            > 1 + 1e-12
        ):
            raise ValueError("Native player G+A exceeds physical event support.")
    for name in ("native_goal_share", "native_assist_share"):
        if not math.isclose(
            math.fsum(getattr(player, name) for player in side.players),
            1,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("Native observed-tactical recipient shares must conserve club mass.")
    if type(side.observed_fixtures) is not tuple or len(side.observed_fixtures) > 64:
        raise ValueError("Observed style needs a bounded enumerated fixture population.")
    seen_fixtures, seen_provider_matches = set(), set()
    lower, upper = instant(p.feature_cutoff) - timedelta(days=28), instant(p.feature_cutoff)
    for f in side.observed_fixtures:
        if type(f) is not ObservedEventFixture or f.club != side.club or f.opponent == side.club:
            raise ValueError("Observed event fixture club identity differs.")
        _earlier(f.season, f.gameweek, f.fixture, p)
        _id(f.opponent, "observed opponent")
        if f.fixture in seen_fixtures or f.provider_match_id in seen_provider_matches:
            raise ValueError("Observed event fixture is duplicated.")
        seen_fixtures.add(f.fixture)
        seen_provider_matches.add(f.provider_match_id)
        if not lower <= instant(f.kickoff) < instant(f.finished_at) < upper:
            raise ValueError("Observed event fixture is outside the prior28day finished window.")
        if f.complete_selected_fixture is not True or f.definition_version != STYLE_VERSION:
            raise ValueError("Four event counts need complete selected fixture source rows.")
        if f.pressure_events is not None or f.high_pass_attempts is not None:
            raise ValueError("Unsupported pressure/high-pass evidence must remain unknown.")
        if type(f.counts) is not tuple or len(f.counts) != 4:
            raise ValueError("Four exact named event counts are required.")
        for value in f.counts:
            _count(value, "observed event count")
        _id(f.event_rows, "complete source row count")
        if (
            type(f.selected_event_ids) is not tuple
            or not f.selected_event_ids
            or len(set(f.selected_event_ids)) != len(f.selected_event_ids)
            or len(f.selected_event_ids) != f.event_rows
        ):
            raise ValueError("Observed event row identities must be unique and complete.")
        for event_id in f.selected_event_ids:
            _id(event_id, "provider event ID")
        if any(value > f.event_rows for value in f.counts):
            raise ValueError("Observed event counts exceed the actual source population.")
        sha(f.bridge_sha256)
        sha(f.inventory_sha256)
        _text(f.provider_match_id, "provider match")
        _text(f.provider_club_id, "provider club")
        validate_source(f.source, _availability(p))
        if instant(f.finished_at) > instant(f.source.retrieved_at):
            raise ValueError("Observed event source was acquired before its finished fact.")


def validate_projection(
    p: ObservedTacticalProjection, *, allow_released_2025_26: bool = False
) -> None:
    if type(p) is not ObservedTacticalProjection:
        raise ValueError("A distinct observed tactical projection is required.")
    validate_training_release(p.season, allow_released_2025_26)
    if (
        p.version != INPUT_VERSION
        or p.context_policy != CONTEXT_POLICY
        or p.coverage_scope != "enumerated_observed_provider_fixtures_not_complete_world"
    ):
        raise ValueError("Observed tactical projection version or scope differs.")
    if type(p.gameweek) is not int or not 1 <= p.gameweek <= 38:
        raise ValueError("Observed tactical target gameweek is invalid.")
    _id(p.fixture, "fixture")
    feature, decision, kickoff = (
        instant(getattr(p, n)) for n in ("feature_cutoff", "decision_at", "kickoff")
    )
    if not feature <= decision < kickoff or not datetime(
        int(p.season[:4]), 7, 1, tzinfo=UTC
    ) <= kickoff < datetime(int(p.season[:4]) + 1, 7, 1, tzinfo=UTC):
        raise ValueError("Observed tactical feature/decision/kickoff ordering is invalid.")
    generated = instant(p.generated_at)
    if p.replay is None:
        if generated > decision:
            raise ValueError("Current projection generation must precede its decision.")
    else:
        r = p.replay
        if (
            type(r) is not ObservedTacticalReplay
            or r.version != REPLAY_VERSION
            or re.fullmatch(r"[0-9a-f]{40}", r.revision) is None
        ):
            raise ValueError("Observed tactical replay provenance is invalid.")
        if (
            r.feature_cutoff != p.feature_cutoff
            or r.generated_at != p.generated_at
            or not instant(r.latest_native_history_kickoff)
            < instant(r.recorded_at)
            <= feature
            <= decision
            < instant(r.retrieved_at)
            <= generated
        ):
            raise ValueError("Observed tactical replay clocks are inconsistent.")
        if type(r.source_hashes) is not tuple or len(dict(r.source_hashes)) != len(r.source_hashes):
            raise ValueError("Observed tactical replay source hashes must be unique.")
        hashes = dict(r.source_hashes)
        if not set(REQUIRED_HISTORY) | {"native_baseline.json"} <= set(hashes):
            raise ValueError(
                "Observed tactical replay requires original history and native hashes."
            )
        for name, value in r.source_hashes:
            _text(name, "replay source name")
            sha(value)
        if (
            hashes["native_baseline.json"] != p.native_source.sha256
            or hashes["players_raw.csv"] != p.roster_source.sha256
        ):
            raise ValueError("Observed tactical native/roster replay hash binding differs.")
        if p.roster_source.published_at != r.recorded_at:
            raise ValueError("Observed tactical roster must bind the original revision clock.")
    for source in (p.native_source, p.roster_source):
        validate_source(source, _availability(p))
    _side(p.home, p)
    _side(p.away, p)
    if p.home.club == p.away.club:
        raise ValueError("Observed tactical paired clubs must differ.")
    roster = tuple(
        sorted(
            (x.profile.player_code, side.club, x.profile.fpl_position)
            for side in (p.home, p.away)
            for x in side.players
        )
    )
    if (
        type(p.roster) is not tuple
        or p.roster != roster
        or len({r[0] for r in roster}) != len(roster)
    ):
        raise ValueError("Observed tactical states must equal the complete original paired roster.")
    identities = [
        (
            x.profile.trait_source.provider,
            x.profile.trait_source.version,
            x.profile.original_identity,
        )
        for side in (p.home, p.away)
        for x in side.players
        if x.profile.trait_source is not None
    ]
    if len(set(identities)) != len(identities):
        raise ValueError("An original FM identity cannot map to two persistent people.")


def validate_header(
    o: ObservedTacticalObservation,
    *,
    cutoff: str,
    target_season: str,
    target_gameweek: int,
    allowed_seasons: tuple[str, ...],
    allow_released_2025_26: bool = False,
) -> None:
    if type(o) is not ObservedTacticalObservation:
        raise ValueError("Observed tactical training requires its distinct immutable DTO.")
    validate_training_release(target_season, allow_released_2025_26)
    if type(target_gameweek) is not int or not 1 <= target_gameweek <= 38:
        raise ValueError("Observed tactical fit target gameweek is invalid.")
    if (
        type(allowed_seasons) is not tuple
        or not allowed_seasons
        or len(set(allowed_seasons)) != len(allowed_seasons)
    ):
        raise ValueError("Observed tactical fit requires an explicit season allowlist.")
    for season in allowed_seasons:
        validate_training_release(season, allow_released_2025_26)
        if season > target_season:
            raise ValueError("Observed tactical allowlist contains a future season.")
    p = o.projection
    if (
        p.season not in allowed_seasons
        or p.season > target_season
        or (p.season == target_season and p.gameweek >= target_gameweek)
    ):
        raise ValueError("Whole target and later gameweeks are excluded before outcome access.")
    validate_projection(p, allow_released_2025_26=allow_released_2025_26)
    final, fit = instant(o.outcome_available_at), instant(cutoff)
    if not instant(p.kickoff) < final < fit or instant(p.generated_at) >= fit:
        raise ValueError("Observed tactical outcomes or generated inputs follow the fit cutoff.")
    for source in (o.goal_source, o.credit_source):
        validate_source(source, cutoff)
        if not final <= instant(source.retrieved_at) < fit:
            raise ValueError("Observed tactical final source acquisition precedes availability.")
    _text(o.rules_version, "FPL rules version")
    if o.final is not True:
        raise ValueError("Observed tactical outcomes must be explicitly final.")


def validate_outcome(o: ObservedTacticalObservation) -> None:
    """Only call after all training headers passed; no features inspect these labels."""
    if type(o.physical_goals) is not tuple or len(o.physical_goals) != 2:
        raise ValueError("Observed tactical physical goals must cover both clubs.")
    for value in o.physical_goals:
        _count(value, "physical goal count")
    roster = {(code, club) for code, club, _ in o.projection.roster}
    if type(o.credits) is not tuple:
        raise ValueError("Observed tactical FPL totals must be immutable and complete.")
    seen = set()
    for credit in o.credits:
        if (
            type(credit) is not TacticalCredit
            or (credit.player_code, credit.club) not in roster
            or (credit.player_code, credit.club) in seen
        ):
            raise ValueError("Observed tactical FPL credits invent or duplicate a person.")
        seen.add((credit.player_code, credit.club))
        _count(credit.goals, "FPL goals")
        _count(credit.assists, "FPL assists")
    if seen != roster:
        raise ValueError("Missing FPL credit rows cannot be filled with invented zeros.")
    for side, physical in zip(
        (o.projection.home, o.projection.away), o.physical_goals, strict=True
    ):
        rows = [c for c in o.credits if c.club == side.club]
        if (
            sum(c.goals for c in rows) > physical
            or sum(c.assists for c in rows) > physical
            or any(c.goals + c.assists > physical for c in rows)
        ):
            raise ValueError("Observed tactical FPL credit exceeds physical goal support.")


def style_values(side: ObservedTacticalSide) -> dict[str, float | None]:
    count = len(side.observed_fixtures)
    return {
        **{
            f"observed_{name}_per_fixture": sum(f.counts[index] for f in side.observed_fixtures)
            / count
            if count
            else None
            for index, name in enumerate(CHANNELS)
        },
        "observed_fixture_count": float(count),
    }


def _trait_terms(
    side: ObservedTacticalSide, p: ObservedTacticalProjection, name: str, basis: str
) -> tuple[float | None, float, float]:
    total, known, terms = [], [], []
    for player in side.players:
        role = forecast_role(player.profile, p)
        weight = (
            player.native_goal_share
            if basis == "goal"
            else player.native_assist_share
            if basis == "assist"
            else player.minutes
        )
        # Unknown roles stay in the support denominator, but never become defenders/GKs.
        total.append(weight)
        role_matches = basis in ("goal", "assist") or role in (
            ("D", "M") if basis == "defense" else ("G",)
        )
        value = player.profile.attributes[TRAITS.index(name)]
        if role_matches and value is not None and weight > 0:
            known.append(weight)
            terms.append(weight * value / 20)
    denominator, support = math.fsum(total), math.fsum(known)
    return (
        math.fsum(terms) / support if support else None,
        support / denominator if denominator else 0.0,
        float(len(known)),
    )


def _team_terms(p: ObservedTacticalProjection, home: bool) -> dict[str, float | None]:
    own, opponent = (p.home, p.away) if home else (p.away, p.home)
    values = {
        **{"own_" + k: v for k, v in style_values(own).items()},
        **{"opponent_" + k: v for k, v in style_values(opponent).items()},
    }
    for prefix, side, basis, traits in (
        ("own_goal_weighted_", own, "goal", ATTACK_TRAITS),
        ("own_assist_weighted_", own, "assist", DELIVERY_TRAITS),
        ("opponent_defending_", opponent, "defense", DEFENSE_TRAITS),
        ("opponent_keeper_", opponent, "keeper", ("gk_aerial_reach",)),
    ):
        for name in traits:
            mean, fraction, count = _trait_terms(side, p, name, basis)
            values[prefix + name] = mean
            values[prefix + name + "_observed_weight_fraction"] = fraction
            values[prefix + name + "_known_player_count"] = count
    return values


TEAM_INTERACTIONS = (
    (
        "own_observed_cross_attempts_per_fixture",
        "own_goal_weighted_heading",
        "opponent_defending_heading",
    ),
    (
        "own_observed_cross_attempts_per_fixture",
        "own_goal_weighted_jumping_reach",
        "opponent_keeper_gk_aerial_reach",
    ),
    (
        "own_observed_fast_break_shots_per_fixture",
        "own_goal_weighted_pace",
        "opponent_defending_pace",
    ),
    (
        "own_observed_throughball_attempts_per_fixture",
        "own_goal_weighted_off_the_ball",
        "opponent_defending_positioning",
    ),
    (
        "own_observed_throughball_attempts_per_fixture",
        "own_assist_weighted_vision",
        "opponent_defending_anticipation",
    ),
)


def _interact(values: dict[str, float | None], interactions: tuple[tuple[str, ...], ...]) -> None:
    for names in interactions:
        terms = [values[n] for n in names]
        values["*".join(names)] = (
            None if any(v is None for v in terms) else math.prod(v for v in terms if v is not None)
        )


def team_features(p: ObservedTacticalProjection, *, home: bool) -> dict[str, float | None]:
    values = _team_terms(p, home)
    _interact(values, TEAM_INTERACTIONS)
    return values


def recipient_features(
    p: ObservedTacticalProjection, player: ObservedTacticalPlayer, *, home: bool, head: str
) -> dict[str, float | None]:
    if head not in ("goals", "assists"):
        raise ValueError("Observed tactical recipient head must be goals or assists.")
    own = p.home if home else p.away
    if player not in own.players:
        raise ValueError("Observed tactical recipient is outside the supplied roster.")
    values = {
        k: v
        for k, v in _team_terms(p, home).items()
        if k.startswith("opponent_") or k.startswith("own_observed_")
    }
    traits = ATTACK_TRAITS if head == "goals" else DELIVERY_TRAITS
    for name in traits:
        value = player.profile.attributes[TRAITS.index(name)]
        values["player_" + name] = value / 20 if value is not None else None
    role = forecast_role(player.profile, p)
    values.update(
        {
            "provider_role_" + name: float(role == name) if role is not None else None
            for name in ROLES
        }
    )
    interactions = (
        (
            (
                "own_observed_cross_attempts_per_fixture",
                "player_heading",
                "opponent_defending_heading",
            ),
            (
                "own_observed_throughball_attempts_per_fixture",
                "player_off_the_ball",
                "opponent_defending_positioning",
            ),
        )
        if head == "goals"
        else (
            (
                "own_observed_cross_attempts_per_fixture",
                "player_crossing",
                "opponent_defending_heading",
            ),
            (
                "own_observed_throughball_attempts_per_fixture",
                "player_vision",
                "opponent_defending_anticipation",
            ),
        )
    )
    _interact(values, interactions)
    return values
