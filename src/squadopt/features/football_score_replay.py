"""Training-only score replay receipts, distinct from captured live forecasts.

These typed records validate declared provenance and bindings. They do not fetch
sources, authenticate Git publication, or compare supplied hashes to file bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass

from squadopt.features.football_score_state_inputs import (
    CLOCK_VERSION,
    MAX_PLAYERS,
    NATIVE_MODEL_VERSIONS,
    POSITIONS,
    FPLCredit,
    ObservedPlayerExposure,
    PhysicalGoal,
    PhysicalPeriod,
    _clock,
    _integer,
    _number,
    _sha,
    _text,
    _tuple,
    _validate_score_outcome,
)

REPLAY_VERSION = "football_score_public_revision_replay_v1"
REPLAY_FIT_VERSION = "football_score_public_replay_fit_v1"
REQUIRED_SOURCE_HASHES = frozenset(
    {
        "players_raw.csv",
        "teams.csv",
        "fixtures.csv",
        "gws/merged_gw.csv",
        "native_fit.json",
        "native_baseline.json",
        "duration_history.json",
        "duration_forecast.json",
    }
)


@dataclass(frozen=True, slots=True)
class ScoreReplayPlayer:
    player_code: int
    club_code: int
    position: str


@dataclass(frozen=True, slots=True)
class ScoreReplayProvenance:
    revision: str
    recorded_at: str
    retrieved_at: str
    generated_at: str
    feature_cutoff: str
    native_fit_information_cutoff: str
    latest_native_history_settled_at: str
    duration_history_latest_settled_at: str
    duration_history_fixtures: tuple[tuple[str, int, int], ...]
    source_hashes: tuple[tuple[str, str], ...]
    native_implementation_sha256: str
    duration_implementation_sha256: str
    model_use_approved: bool
    model_use_evidence_ref: str
    version: str = REPLAY_VERSION


@dataclass(frozen=True, slots=True)
class ScoreReplayBasis:
    season: str
    gameweek: int
    fixture_id: int
    decision_at: str
    gameweek_first_kickoff: str
    kickoff: str
    home_club_code: int
    away_club_code: int
    native_home_goals: float
    native_away_goals: float
    forecast_duration: float
    clock_version: str
    players: tuple[ScoreReplayPlayer, ...]
    native_model_version: str
    native_basis_sha256: str
    duration_forecast_sha256: str
    provenance: ScoreReplayProvenance


@dataclass(frozen=True, slots=True)
class ScoreReplayObservation:
    basis: ScoreReplayBasis
    goals: tuple[PhysicalGoal, ...]
    periods: tuple[PhysicalPeriod, ...]
    actual_duration: float
    final_home_goals: int
    final_away_goals: int
    fpl_credits: tuple[FPLCredit, ...]
    exposures: tuple[ObservedPlayerExposure, ...]
    settled_at: str
    outcome_sha256: str
    outcome_retrieved_at: str
    outcome_generated_at: str
    outcome_evidence_ref: str
    dismissal_events: tuple[str, ...] = ()


def _replay_season(value: object) -> str:
    season = _text(value, "replay season")
    if not re.fullmatch(r"20\d{2}-\d{2}", season) or int(season[5:]) != (int(season[:4]) + 1) % 100:
        raise ValueError("Replay season must be consecutive YYYY-YY.")
    return season


def validate_score_replay_basis(
    basis: ScoreReplayBasis, *, allow_released_2025_26: bool = False
) -> None:
    """Validate feature-side declarations without inspecting outcome labels."""
    if type(allow_released_2025_26) is not bool:
        raise ValueError("Released-season selection must be Boolean.")
    if type(basis) is not ScoreReplayBasis:
        raise ValueError("Score replay requires its frozen basis type.")
    season = _replay_season(basis.season)
    if season == "2025-26" and not allow_released_2025_26:
        raise ValueError("Released 2025-26 replay requires explicit training opt-in.")
    _integer(basis.gameweek, "replay gameweek", maximum=38)
    _integer(basis.fixture_id, "replay fixture")
    decision = _clock(basis.decision_at, "replay reference decision")
    first = _clock(basis.gameweek_first_kickoff, "original gameweek first kickoff")
    kickoff = _clock(basis.kickoff, "original fixture kickoff")
    if not decision < first <= kickoff or not (
        f"{season[:4]}-07-01" <= kickoff.date().isoformat() < f"{int(season[:4]) + 1}-07-01"
    ):
        raise ValueError("Replay reference decision and original calendar disagree.")
    clubs = {
        _integer(basis.home_club_code, "home club"),
        _integer(basis.away_club_code, "away club"),
    }
    if len(clubs) != 2:
        raise ValueError("Replay requires two distinct clubs.")
    _number(basis.native_home_goals, "native home goals", maximum=100)
    _number(basis.native_away_goals, "native away goals", maximum=100)
    _number(basis.forecast_duration, "forecast physical duration", minimum=1, maximum=180)
    if (
        basis.clock_version != CLOCK_VERSION
        or _text(basis.native_model_version, "native model version") not in NATIVE_MODEL_VERSIONS
    ):
        raise ValueError("Replay cannot change the physical clock or native model contract.")
    roster = _tuple(basis.players, "original paired roster", MAX_PLAYERS)
    seen: set[int] = set()
    roster_clubs: set[int] = set()
    for player in roster:
        if type(player) is not ScoreReplayPlayer:
            raise ValueError("Replay roster requires frozen person/club/position records.")
        code = _integer(player.player_code, "replay player")
        club = _integer(player.club_code, "replay player club")
        position = _text(player.position, "replay player position")
        if code in seen or club not in clubs or position not in POSITIONS:
            raise ValueError("Replay roster has duplicate or contradictory identities.")
        seen.add(code)
        roster_clubs.add(club)
    if roster_clubs != clubs:
        raise ValueError("Replay roster must cover both original clubs.")
    provenance = basis.provenance
    if type(provenance) is not ScoreReplayProvenance or provenance.version != REPLAY_VERSION:
        raise ValueError("Replay requires supported frozen provenance.")
    if not isinstance(provenance.revision, str) or not re.fullmatch(
        r"[a-f0-9]{40}", provenance.revision
    ):
        raise ValueError("Replay requires a full original Git revision.")
    hashes: dict[str, str] = {}
    for pair in _tuple(provenance.source_hashes, "replay source hashes", 1024):
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("Replay source hashes must be immutable named pairs.")
        name = _text(pair[0], "source hash name")
        if name in hashes:
            raise ValueError("Replay source hash names must be unique.")
        hashes[name] = _sha(pair[1], "source hash")
    if not REQUIRED_SOURCE_HASHES.issubset(hashes):
        raise ValueError(
            "Replay requires original roster/calendar/history and both forecast receipts."
        )
    if hashes["native_baseline.json"] != _sha(
        basis.native_basis_sha256, "native basis hash"
    ) or hashes["duration_forecast.json"] != _sha(
        basis.duration_forecast_sha256, "duration forecast hash"
    ):
        raise ValueError("Replay forecast hashes contradict their source bindings.")
    _sha(provenance.native_implementation_sha256, "native implementation")
    _sha(provenance.duration_implementation_sha256, "duration implementation")
    if provenance.model_use_approved is not True:
        raise ValueError("Replay requires the operator model-use receipt.")
    _text(provenance.model_use_evidence_ref, "operator model-use evidence")
    recorded = _clock(provenance.recorded_at, "original revision recording")
    retrieved = _clock(provenance.retrieved_at, "actual feature source retrieval")
    generated = _clock(provenance.generated_at, "actual feature generation")
    feature = _clock(provenance.feature_cutoff, "historical feature cutoff")
    native_fit = _clock(provenance.native_fit_information_cutoff, "native information cutoff")
    native_settled = _clock(
        provenance.latest_native_history_settled_at, "native history settlement"
    )
    duration_settled = _clock(
        provenance.duration_history_latest_settled_at, "duration history settlement"
    )
    if not recorded <= feature <= decision < retrieved <= generated:
        raise ValueError("Replay recording, reference, retrieval and generation clocks disagree.")
    if not native_settled < native_fit <= feature or not duration_settled < feature:
        raise ValueError(
            "Replay native and duration histories must settle before their feature use."
        )
    inventory = _tuple(provenance.duration_history_fixtures, "duration history inventory", 10000)
    duration_keys: set[tuple[str, int]] = set()
    if not inventory:
        raise ValueError("Forecast duration requires a nonempty prior fixture inventory.")
    for item in inventory:
        if type(item) is not tuple or len(item) != 3:
            raise ValueError("Duration history requires season, gameweek and fixture identities.")
        historical_season = _replay_season(item[0])
        historical_week = _integer(item[1], "duration history gameweek", maximum=38)
        historical_fixture = _integer(item[2], "duration history fixture")
        key = (historical_season, historical_fixture)
        if (
            key in duration_keys
            or historical_season > season
            or (
                historical_season == season
                and (historical_week >= basis.gameweek or historical_fixture == basis.fixture_id)
            )
        ):
            raise ValueError("Duration forecast cannot use duplicate, target or future outcomes.")
        duration_keys.add(key)


def validate_score_replay_header(
    row: ScoreReplayObservation,
    *,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
    allow_released_2025_26: bool = False,
) -> None:
    """Check all source and population headers before any observation labels."""
    if type(row) is not ScoreReplayObservation:
        raise ValueError("Score replay requires a frozen observation.")
    validate_score_replay_basis(row.basis, allow_released_2025_26=allow_released_2025_26)
    basis = row.basis
    target = _replay_season(target_season)
    targets = _tuple(target_gameweeks, "target gameweeks", 38)
    for gw in targets:
        _integer(gw, "target gameweek", maximum=38)
    if not targets or tuple(sorted(set(targets))) != targets:
        raise ValueError("Replay targets must be distinct ordered gameweeks.")
    if basis.season > target or (basis.season == target and basis.gameweek >= min(targets)):
        raise ValueError("Target and future replay headers refuse before labels.")
    cutoff = _clock(fit_cutoff, "score fitting cutoff")
    generated = _clock(basis.provenance.generated_at, "feature generation")
    settled = _clock(row.settled_at, "outcome settlement")
    retrieved = _clock(row.outcome_retrieved_at, "outcome retrieval")
    outcome_generated = _clock(row.outcome_generated_at, "outcome generation")
    if not (
        generated < cutoff
        and _clock(basis.kickoff, "kickoff") < settled <= retrieved <= outcome_generated < cutoff
    ):
        raise ValueError("Replay acquisition, generation and settlement must precede fitting.")
    _sha(row.outcome_sha256, "outcome hash")
    _text(row.outcome_evidence_ref, "outcome evidence")


def validate_score_replay_observation(
    row: ScoreReplayObservation,
    *,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
    allow_released_2025_26: bool = False,
) -> None:
    validate_score_replay_header(
        row,
        fit_cutoff=fit_cutoff,
        target_season=target_season,
        target_gameweeks=target_gameweeks,
        allow_released_2025_26=allow_released_2025_26,
    )
    if _tuple(row.dismissal_events, "dismissal events", MAX_PLAYERS):
        raise ValueError("Dismissal exposure policy remains unsupported.")
    basis = row.basis
    _validate_score_outcome(
        row,
        players={p.player_code: p.club_code for p in basis.players},
        home=basis.home_club_code,
        away=basis.away_club_code,
        kickoff=basis.kickoff,
    )


def score_replay_basis_digest(
    basis: ScoreReplayBasis, *, allow_released_2025_26: bool = False
) -> str:
    validate_score_replay_basis(basis, allow_released_2025_26=allow_released_2025_26)
    return hashlib.sha256(
        json.dumps(asdict(basis), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
