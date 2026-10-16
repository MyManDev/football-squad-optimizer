"""Explicit predecision point intervals, not a learned substitution distribution.

The uniform clock approximation preserves native credited-minute atoms. Source
hashes bind caller-supplied declarations; this module does not authenticate files.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass

from squadopt.features.football_score_state_inputs import (
    MASS_TOLERANCE,
    MAX_PLAYERS,
    POSITIONS,
    ScorePlayer,
    _clock,
    _credited_bin,
    _exposure,
    _integer,
    _number,
    _sha,
)

PROJECTION_POLICY = "uniform_forecast_clock_native_atom_point_intervals_v1"
DURATION_POLICY = "past_verified_nonzero_period_end_seconds_arithmetic_mean_v1"


@dataclass(frozen=True)
class ScorePastDuration:
    season: str
    gameweek: int
    fixture_id: int
    kickoff: str
    completed_by: str
    period_seconds: tuple[int, int]
    source_sha256: str
    completion_sha256: str


@dataclass(frozen=True)
class ScoreDurationForecast:
    target_season: str
    target_gameweek: int
    target_fixture_id: int
    feature_cutoff: str
    source_captured_at: str
    generated_at: str
    history: tuple[ScorePastDuration, ...]
    duration_policy: str = DURATION_POLICY


@dataclass(frozen=True)
class ScoreNativePlayer:
    player_code: int
    club_code: int
    position: str
    probabilities: tuple[float, ...]
    credited_minutes: tuple[float, ...]


@dataclass(frozen=True)
class ScoreIntervalReceipt:
    projection_policy: str
    native_basis_sha256: str
    native_players_sha256: str
    duration_forecast_sha256: str
    forecast_duration: float
    target_season: str
    target_gameweek: int
    target_fixture_id: int
    decision_at: str
    generated_at: str
    positive_cameo90_count: int
    interpretation: str = "conditional_point_intervals_not_a_learned_interval_mixture"
    added_time_assumption: str = "uniformly_spread_over_90_regulation_minutes"
    substitution_assumption: str = "starters_exit_once_and_substitutes_finish"
    zero_mass_cameo90_boundary: str = "entry_zero_exit_forecast_horizon_not_positive_support"
    eligibility_applied: bool = False


@dataclass(frozen=True)
class ScoreIntervalProjection:
    players: tuple[ScorePlayer, ...]
    receipt: ScoreIntervalReceipt
    receipt_sha256: str


def _encode(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _season(value: str) -> int:
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
        raise ValueError("Score duration season must be YYYY-YY.")
    try:
        year, end = int(value[:4]), int(value[5:])
    except ValueError as error:
        raise ValueError("Score duration season must be YYYY-YY.") from error
    if year < 2000 or end != (year + 1) % 100:
        raise ValueError("Score duration season must be consecutive.")
    return year


def forecast_physical_duration(forecast: ScoreDurationForecast, *, decision_at: str) -> float:
    """Validate declared prior evidence and compute its exact arithmetic-mean policy."""
    if type(forecast) is not ScoreDurationForecast or forecast.duration_policy != DURATION_POLICY:
        raise ValueError("Score duration requires its distinct typed forecast policy.")
    year = _season(forecast.target_season)
    _integer(forecast.target_gameweek, "target gameweek", 1, 38)
    _integer(forecast.target_fixture_id, "target fixture")
    decision = _clock(decision_at, "decision")
    if not (decision.year == year and decision.month >= 7) and not (
        decision.year == year + 1 and decision.month < 7
    ):
        raise ValueError("Score projection decision disagrees with its target season.")
    feature = _clock(forecast.feature_cutoff, "feature cutoff")
    captured = _clock(forecast.source_captured_at, "duration source acquisition")
    generated = _clock(forecast.generated_at, "duration forecast generation")
    if not feature <= generated <= decision or not captured <= generated:
        raise ValueError("Score duration source and forecast must precede the decision.")
    if type(forecast.history) is not tuple or not 1 <= len(forecast.history) <= 10_000:
        raise ValueError("Score duration requires a bounded nonempty prior fixture population.")
    seen: set[tuple[str, int]] = set()
    seconds: list[int] = []
    for row in forecast.history:
        if type(row) is not ScorePastDuration:
            raise ValueError("Score duration history requires frozen source records.")
        history_year = _season(row.season)
        _integer(row.gameweek, "history gameweek", 1, 38)
        _integer(row.fixture_id, "history fixture")
        if history_year > year or (
            row.season == forecast.target_season
            and (
                row.gameweek >= forecast.target_gameweek
                or row.fixture_id == forecast.target_fixture_id
            )
        ):
            raise ValueError(
                "Score duration history excludes the target whole gameweek and future."
            )
        key = row.season, row.fixture_id
        if key in seen:
            raise ValueError("Score duration history repeats a fixture.")
        seen.add(key)
        kickoff = _clock(row.kickoff, "history kickoff")
        completed = _clock(row.completed_by, "history observed completion bound")
        if not kickoff < completed <= min(feature, captured):
            raise ValueError("Score duration history lacks a prior completion bound.")
        if not (kickoff.year == history_year and kickoff.month >= 7) and not (
            kickoff.year == history_year + 1 and kickoff.month < 7
        ):
            raise ValueError("Score duration kickoff disagrees with its season.")
        if (
            type(row.period_seconds) is not tuple
            or len(row.period_seconds) != 2
            or any(
                type(value) is not int or not 2700 <= value <= 5400 for value in row.period_seconds
            )
            or sum(row.period_seconds) > 10_800
        ):
            raise ValueError(
                "Score duration needs two verified physical periods of at least 45 minutes."
            )
        _sha(row.source_sha256, "duration event source")
        _sha(row.completion_sha256, "duration completion source")
        seconds.append(sum(row.period_seconds))
    return math.fsum(seconds) / len(seconds) / 60


def project_score_intervals(
    players: tuple[ScoreNativePlayer, ...],
    forecast: ScoreDurationForecast,
    *,
    native_basis_sha256: str,
    decision_at: str,
    generated_at: str,
) -> ScoreIntervalProjection:
    """Map unchanged native atoms through an explicitly assumed uniform clock."""
    _sha(native_basis_sha256, "native basis")
    horizon = forecast_physical_duration(forecast, decision_at=decision_at)
    if (
        not _clock(forecast.generated_at, "forecast generation")
        <= _clock(generated_at, "interval generation")
        <= _clock(decision_at, "decision")
    ):
        raise ValueError("Score interval generation must follow its forecast and precede decision.")
    if type(players) is not tuple or not 1 <= len(players) <= MAX_PLAYERS:
        raise ValueError(
            "Score interval projection needs its complete immutable native player set."
        )
    seen: set[int] = set()
    result = []
    for player in players:
        if type(player) is not ScoreNativePlayer:
            raise ValueError("Score interval projection requires distinct native player records.")
        _integer(player.player_code, "native player")
        _integer(player.club_code, "native club")
        if player.player_code in seen or player.position not in POSITIONS:
            raise ValueError("Score interval player identity or position is invalid.")
        seen.add(player.player_code)
        if any(
            type(values) is not tuple or len(values) != 7
            for values in (player.probabilities, player.credited_minutes)
        ):
            raise ValueError("Score interval projection retains exactly seven native atoms.")
        for probability in player.probabilities:
            _number(probability, "native probability", maximum=1)
        if abs(math.fsum(player.probabilities) - 1) > MASS_TOLERANCE:
            raise ValueError("Score interval native probabilities must already sum to one.")
        if player.probabilities[6] != 0:
            raise ValueError("This point interval policy refuses positive native cameo90 support.")
        on, off, exits = [], [], []
        for index, minutes in enumerate(player.credited_minutes):
            _credited_bin(minutes, index, 7)
            if minutes > 90:
                raise ValueError("Uniform score clock only supports credited minutes through 90.")
            duration = horizon * minutes / 90
            if index == 0:
                entry, end, exit_policy = 0.0, 0.0, "not_playing"
            elif index <= 3:
                entry, end = 0.0, horizon if minutes == 90 else duration
                exit_policy = "full_time" if minutes == 90 else "normal_substitution"
            else:
                entry, end, exit_policy = horizon - duration, horizon, "full_time"
            _exposure(entry, end, minutes, exit_policy, horizon, zero=index == 0)
            on.append(entry)
            off.append(end)
            exits.append(exit_policy)
        result.append(
            ScorePlayer(
                player.player_code,
                player.club_code,
                player.position,
                player.probabilities,
                player.credited_minutes,
                tuple(on),
                tuple(off),
                tuple(exits),
            )
        )
    receipt = ScoreIntervalReceipt(
        PROJECTION_POLICY,
        native_basis_sha256,
        hashlib.sha256(_encode([asdict(player) for player in players])).hexdigest(),
        hashlib.sha256(_encode(asdict(forecast))).hexdigest(),
        horizon,
        forecast.target_season,
        forecast.target_gameweek,
        forecast.target_fixture_id,
        decision_at,
        generated_at,
        0,
    )
    return ScoreIntervalProjection(
        tuple(result), receipt, hashlib.sha256(_encode(asdict(receipt))).hexdigest()
    )
