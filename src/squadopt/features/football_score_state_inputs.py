"""Strict private score-process inputs; receipt assertions do not admit real data."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from typing import Any, NoReturn

SCORE_INPUT_VERSION = "football_score_fixture_input_v1"
RAW_SCORE_SNAPSHOT_VERSION = "football_score_snapshot_v1"
RAW_SCORE_OUTCOME_VERSION = "football_score_outcomes_v1"
CLOCK_VERSION = "physical_playing_minutes_including_stoppage_excluding_breaks_v1"
PROTECTED_SEASON = "2025-26"
NATIVE_MODEL_VERSIONS = (
    "football_team_share_v1",
    "football_joint_role_minutes_v1",
    "football_joint_role_retained_history_v1",
)
REPRESENTATIONS = {"four_bins": 4, "seven_roles": 7}
EXIT_POLICIES = ("not_playing", "normal_substitution", "full_time")
POSITIONS = ("GK", "DEF", "MID", "FWD")
MASS_TOLERANCE = 1e-12
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_PLAYERS = 256
MAX_GOALS = 100


@dataclass(frozen=True, slots=True)
class ScorePlayer:
    player_code: int
    club_code: int
    position: str
    probabilities: tuple[float, ...]
    credited_minutes: tuple[float, ...]
    physical_on: tuple[float, ...]
    physical_off: tuple[float, ...]
    exit_policies: tuple[str, ...]
    minute_representation: str = "seven_roles"


@dataclass(frozen=True, slots=True)
class ScoreFixture:
    season: str
    gameweek: int
    fixture_id: int
    decision_at: str
    deadline_at: str
    kickoff: str
    home_club_code: int
    away_club_code: int
    native_home_goals: float
    native_away_goals: float
    forecast_duration: float
    clock_version: str
    players: tuple[ScorePlayer, ...]
    native_basis_sha256: str
    native_model_version: str
    native_basis_kind: str
    native_basis_fit_cutoff: str
    native_basis_evidence_ref: str
    source_sha256: str
    coverage_evidence_ref: str
    calendar_evidence_ref: str


@dataclass(frozen=True, slots=True)
class PhysicalPeriod:
    period: int
    duration: float


@dataclass(frozen=True, slots=True)
class PhysicalGoal:
    event_id: str
    elapsed: float
    period: int
    period_elapsed: float
    beneficiary_club_code: int
    scorer_club_code: int
    scorer_player_code: int | None
    own_goal: bool
    ordinal: int


@dataclass(frozen=True, slots=True)
class FPLCredit:
    goal_event_id: str
    scorer_player_code: int | None
    assist_player_code: int | None


@dataclass(frozen=True, slots=True)
class ObservedPlayerExposure:
    player_code: int
    club_code: int
    physical_on: float
    physical_off: float
    credited_minutes: int
    starts: int
    exit_policy: str


@dataclass(frozen=True, slots=True)
class TrainingScoreFixture:
    input: ScoreFixture
    goals: tuple[PhysicalGoal, ...]
    periods: tuple[PhysicalPeriod, ...]
    actual_duration: float
    final_home_goals: int
    final_away_goals: int
    fpl_credits: tuple[FPLCredit, ...]
    exposures: tuple[ObservedPlayerExposure, ...]
    settled_at: str
    outcome_sha256: str


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{name} must be a nonempty unpadded string.")
    return value


def _integer(value: object, name: str, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(f"{name} must be an integer within declared bounds.")
    return value


def _number(value: object, name: str, minimum: float = 0, maximum: float = 1e6) -> float:
    if type(value) not in (int, float):
        _fail(f"{name} must be a finite JSON number.")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{name} must be finite.") from error
    if not math.isfinite(result) or not minimum <= result <= maximum:
        _fail(f"{name} is outside finite declared bounds.")
    return result


def _sha(value: object, name: str) -> str:
    result = _text(value, name)
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        _fail(f"{name} must be a lowercase SHA256.")
    return result


def _season(value: object) -> str:
    result = _text(value, "season")
    if not re.fullmatch(r"\d{4}-\d{2}", result) or int(result[5:]) != (int(result[:4]) + 1) % 100:
        _fail("Season must have a consecutive YYYY-YY identity.")
    if result == PROTECTED_SEASON:
        _fail("Protected season is excluded before source decoding.")
    return result


def _clock(value: object, name: str) -> datetime:
    text = _text(value, name)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{name} must be a valid clock.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail(f"{name} requires an explicit timezone.")
    return parsed.astimezone(UTC)


def _tuple(value: object, name: str, maximum: int) -> tuple[Any, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{name} must be a bounded immutable tuple.")
    return value


def _object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        _fail(f"{name} requires every exact field, including explicit nullable values.")
    return value


def _array(value: object, name: str, maximum: int) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        _fail(f"{name} must be a bounded JSON array.")
    return value


def _json(raw: bytes, sha256: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_SOURCE_BYTES:
        _fail("Source must be nonempty bounded immutable bytes.")
    if hashlib.sha256(raw).hexdigest() != _sha(sha256, "source_sha256"):
        _fail("Original source byte SHA256 mismatch.")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail("Duplicate JSON field.")
            result[key] = value
        return result

    def constant(value: str) -> None:
        _fail(f"Nonfinite JSON constant {value} is refused.")

    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Source must be strict UTF-8 JSON.") from error
    if type(parsed) is not dict:
        _fail("Source must be a JSON object.")
    return parsed


def _capture(captured: object, published: object, cutoff: datetime, name: str) -> datetime:
    capture, publication = (
        _clock(captured, name + " captured"),
        _clock(published, name + " published"),
    )
    if not capture <= publication < cutoff:
        _fail(f"{name} capture must precede archive publication and the decision cutoff.")
    return capture


def _rights(value: object) -> None:
    rights = _object(value, {"model_use_claim", "evidence_ref"}, "rights")
    if rights["model_use_claim"] is not True:
        _fail("An explicit operator source permission receipt is required.")
    _text(rights["evidence_ref"], "rights evidence_ref")


def _credited_bin(minutes: object, index: int, count: int) -> float:
    m = _number(minutes, "credited minute support", maximum=120)
    b = index if count == 4 else (0 if index == 0 else 1 + (index - 1) % 3)
    if (
        (b == 0 and m != 0)
        or (b == 1 and not 0 < m < 60)
        or (b == 2 and not 60 <= m < 90)
        or (b == 3 and not 90 <= m <= 120)
    ):
        _fail("Credited minute support contradicts its declared native bin.")
    return m


def _exposure(
    on: object, off: object, credited: object, policy: object, horizon: float, *, zero: bool
) -> None:
    entry = _number(on, "physical entry", maximum=horizon)
    exit_at = _number(off, "physical exit", maximum=horizon)
    credited_value = _number(credited, "credited exposure minutes", maximum=120)
    if zero:
        if entry != 0 or exit_at != 0 or credited != 0 or policy != "not_playing":
            _fail("Absence requires zero exposure and the not_playing policy.")
        return
    if not entry < exit_at or policy not in ("normal_substitution", "full_time"):
        _fail("Positive exposure requires an explicit supported exit policy.")
    if (policy == "full_time" and exit_at != horizon) or (
        policy == "normal_substitution" and exit_at >= horizon
    ):
        _fail("Normal substitution and full-time horizons cannot be conflated.")
    if credited_value > exit_at - entry + MASS_TOLERANCE:
        _fail("FPL credited minutes cannot exceed physical playing exposure.")


def validate_score_fixture(fixture: ScoreFixture) -> None:
    """Validate a genuinely predecision claimed native basis and explicit intervals."""
    if type(fixture) is not ScoreFixture:
        _fail("Score input must be a frozen ScoreFixture.")
    _season(fixture.season)
    _integer(fixture.gameweek, "gameweek", maximum=38)
    _integer(fixture.fixture_id, "fixture_id")
    decision, deadline, kickoff = (
        _clock(getattr(fixture, field), field)
        for field in ("decision_at", "deadline_at", "kickoff")
    )
    if not decision < deadline < kickoff:
        _fail("Decision, deadline and target kickoff must be strictly ordered.")
    season_start = datetime(int(fixture.season[:4]), 7, 1, tzinfo=UTC)
    season_end = datetime(int(fixture.season[:4]) + 1, 7, 1, tzinfo=UTC)
    if not season_start <= kickoff < season_end:
        _fail("Native target fixture must belong to its declared season.")
    home = _integer(fixture.home_club_code, "home_club_code")
    away = _integer(fixture.away_club_code, "away_club_code")
    if home == away:
        _fail("Paired clubs must be distinct.")
    _number(fixture.native_home_goals, "native_home_goals", maximum=100)
    _number(fixture.native_away_goals, "native_away_goals", maximum=100)
    horizon = _number(fixture.forecast_duration, "forecast_duration", minimum=1, maximum=180)
    if fixture.clock_version != CLOCK_VERSION:
        _fail("Unknown physical forecast clock normalization.")
    if fixture.native_model_version not in NATIVE_MODEL_VERSIONS:
        _fail("Unknown native model version.")
    if fixture.native_basis_kind not in ("out_of_fold", "prospective"):
        _fail("Native basis must be explicitly out_of_fold or prospective.")
    if _clock(fixture.native_basis_fit_cutoff, "native fit cutoff") >= decision:
        _fail("Native fitting must precede the original decision.")
    for field in ("native_basis_sha256", "source_sha256"):
        _sha(getattr(fixture, field), field)
    for field in ("native_basis_evidence_ref", "coverage_evidence_ref", "calendar_evidence_ref"):
        _text(getattr(fixture, field), field)
    players = _tuple(fixture.players, "players", MAX_PLAYERS)
    if not players or {player.club_code for player in players if type(player) is ScorePlayer} != {
        home,
        away,
    }:
        _fail("Complete paired club player coverage is required.")
    seen: set[int] = set()
    for player in players:
        if type(player) is not ScorePlayer:
            _fail("Players must be frozen ScorePlayer records.")
        code = _integer(player.player_code, "player_code")
        if code in seen:
            _fail("Duplicated persistent player identity.")
        seen.add(code)
        if (
            _integer(player.club_code, "player club") not in (home, away)
            or player.position not in POSITIONS
        ):
            _fail("Invalid persistent player club or position.")
        if player.minute_representation not in REPRESENTATIONS:
            _fail("Unknown native minute representation.")
        count = REPRESENTATIONS[player.minute_representation]
        if fixture.native_model_version == "football_team_share_v1" and count != 4:
            _fail("The native v1 model requires explicitly declared four-bin support.")
        for field in (
            "probabilities",
            "credited_minutes",
            "physical_on",
            "physical_off",
            "exit_policies",
        ):
            values = _tuple(getattr(player, field), field, 7)
            if len(values) != count:
                _fail("Every player support must match its declared native representation.")
        probabilities = tuple(
            _number(p, "native probability", maximum=1) for p in player.probabilities
        )
        if abs(math.fsum(probabilities) - 1) > MASS_TOLERANCE:
            _fail("Native player support must retain unit mass without rescaling.")
        for index in range(count):
            m = _credited_bin(player.credited_minutes[index], index, count)
            _exposure(
                player.physical_on[index],
                player.physical_off[index],
                m,
                player.exit_policies[index],
                horizon,
                zero=index == 0,
            )
            if count == 7 and index in (1, 2, 3) and player.physical_on[index] != 0:
                _fail("Recorded native start support must begin at the physical kickoff.")


def validate_training_score_header(
    row: TrainingScoreFixture,
    *,
    fit_cutoff: str | None = None,
    target_season: str | None = None,
    target_gameweeks: tuple[int, ...] = (),
) -> None:
    """Preflight source and settlement headers before any events or exposure labels."""
    if type(row) is not TrainingScoreFixture:
        _fail("Training must use frozen TrainingScoreFixture records.")
    fixture = row.input
    validate_score_fixture(fixture)
    if (fit_cutoff is None) != (target_season is None):
        _fail("Target season and fit cutoff must be supplied together.")
    targets = _tuple(target_gameweeks, "target_gameweeks", 38)
    if len(set(targets)) != len(targets):
        _fail("Target gameweeks must be unique.")
    for gw in targets:
        _integer(gw, "target gameweek", maximum=38)
    if target_season is None and targets:
        _fail("Target gameweeks require their season.")
    if target_season is not None:
        _season(target_season)
        if not targets:
            _fail("A complete nonempty target inventory is required.")
        if int(fixture.season[:4]) > int(target_season[:4]) or (
            fixture.season == target_season and fixture.gameweek >= min(targets)
        ):
            _fail("Protected, target and future fixture headers refuse before outcome decoding.")
        if _clock(fixture.decision_at, "decision_at") >= _clock(fit_cutoff, "fit_cutoff"):
            _fail("Historical decision must precede fitting.")
    settled = _clock(row.settled_at, "settled_at")
    if settled <= _clock(fixture.kickoff, "kickoff"):
        _fail("Final fixture settlement must follow kickoff.")
    if fit_cutoff is not None and settled >= _clock(fit_cutoff, "fit_cutoff"):
        _fail("Historical settlement must precede the fitting cutoff.")
    _sha(row.outcome_sha256, "outcome_sha256")


def validate_training_score_fixture(
    row: TrainingScoreFixture,
    *,
    fit_cutoff: str | None = None,
    target_season: str | None = None,
    target_gameweeks: tuple[int, ...] = (),
) -> None:
    validate_training_score_header(
        row, fit_cutoff=fit_cutoff, target_season=target_season, target_gameweeks=target_gameweeks
    )
    actual = _number(row.actual_duration, "actual_duration", minimum=1, maximum=180)
    periods = _tuple(row.periods, "periods", 2)
    if (
        len(periods) != 2
        or any(type(p) is not PhysicalPeriod for p in periods)
        or tuple(p.period for p in periods) != (1, 2)
    ):
        _fail("Two complete ordered physical periods are required.")
    for p in periods:
        _integer(p.period, "period", maximum=2)
        _number(p.duration, "period duration", minimum=1, maximum=90)
    if not math.isclose(
        math.fsum(p.duration for p in periods), actual, rel_tol=0, abs_tol=MASS_TOLERANCE
    ):
        _fail("Actual physical duration must reconcile both periods.")
    if (
        _clock(row.settled_at, "settled_at") - _clock(row.input.kickoff, "kickoff")
    ).total_seconds() / 60 < actual:
        _fail("Finalization cannot precede the recorded physical playing duration.")
    players = {p.player_code: p for p in row.input.players}
    exposures = _tuple(row.exposures, "observed exposures", MAX_PLAYERS)
    seen: set[int] = set()
    for exposure in exposures:
        if type(exposure) is not ObservedPlayerExposure:
            _fail("Observed exposure must retain its frozen record.")
        code = _integer(exposure.player_code, "exposure player")
        if (
            code in seen
            or code not in players
            or _integer(exposure.club_code, "exposure club") != players[code].club_code
        ):
            _fail("Observed exposure has duplicate or contradictory persistent identity.")
        seen.add(code)
        credited = _integer(exposure.credited_minutes, "final FPL credited minutes", 0, 120)
        start = _integer(exposure.starts, "recorded start", 0, 1)
        _exposure(
            exposure.physical_on,
            exposure.physical_off,
            credited,
            exposure.exit_policy,
            actual,
            zero=exposure.physical_on == exposure.physical_off,
        )
        if start == 1 and (credited == 0 or exposure.physical_on != 0):
            _fail("Recorded starter must have positive credited exposure from kickoff.")
    if seen != set(players):
        _fail("Final observed exposure must cover the complete original paired roster.")
    exposure_by_player = {exposure.player_code: exposure for exposure in exposures}
    goals = _tuple(row.goals, "physical goals", MAX_GOALS)
    goal_ids: set[str] = set()
    previous_elapsed, previous_ordinal, previous_period = -1.0, 0, 1
    score = {row.input.home_club_code: 0, row.input.away_club_code: 0}
    for goal in goals:
        if type(goal) is not PhysicalGoal:
            _fail("Physical goals must use frozen original event records.")
        event_id = _text(goal.event_id, "goal event_id")
        elapsed = _number(goal.elapsed, "physical goal elapsed", maximum=actual)
        ordinal = _integer(goal.ordinal, "goal ordinal")
        if event_id in goal_ids or elapsed < previous_elapsed or ordinal <= previous_ordinal:
            _fail("Goal IDs and original chronology must be unique and ordered.")
        goal_ids.add(event_id)
        previous_elapsed, previous_ordinal = elapsed, ordinal
        period = _integer(goal.period, "goal period", maximum=2)
        if period < previous_period:
            _fail("Original physical goal periods must not move backwards.")
        previous_period = period
        period_elapsed = _number(
            goal.period_elapsed, "goal period elapsed", maximum=periods[period - 1].duration
        )
        expected = period_elapsed + (periods[0].duration if period == 2 else 0)
        if not math.isclose(elapsed, expected, rel_tol=0, abs_tol=MASS_TOLERANCE):
            _fail("Physical goal period clock contradicts its cumulative elapsed clock.")
        beneficiary = _integer(goal.beneficiary_club_code, "goal beneficiary")
        scorer_club = _integer(goal.scorer_club_code, "physical scorer club")
        if beneficiary not in score or scorer_club not in score or type(goal.own_goal) is not bool:
            _fail("Physical scoring club and own-goal facts must be explicit.")
        if (scorer_club != beneficiary) != goal.own_goal:
            _fail("Own goals must benefit the opposing physical club.")
        if goal.scorer_player_code is not None:
            code = _integer(goal.scorer_player_code, "physical scorer")
            if code not in players or players[code].club_code != scorer_club:
                _fail("Physical scorer contradicts persistent club/person identity.")
            exposure = exposure_by_player[code]
            if not (
                exposure.physical_on < exposure.physical_off
                and exposure.physical_on <= elapsed <= exposure.physical_off
            ):
                _fail("A known physical scorer must be on the pitch at the recorded goal.")
        score[beneficiary] += 1
    if score[row.input.home_club_code] != _integer(
        row.final_home_goals, "final home goals", 0, MAX_GOALS
    ) or score[row.input.away_club_code] != _integer(
        row.final_away_goals, "final away goals", 0, MAX_GOALS
    ):
        _fail("Complete ordered physical goals must reconcile the final score.")
    credits = _tuple(row.fpl_credits, "final FPL credits", MAX_GOALS)
    if len(credits) != len(goals) or any(type(c) is not FPLCredit for c in credits):
        _fail("Separately scoped final FPL credits must cover every physical goal.")
    by_goal = {goal.event_id: goal for goal in goals}
    credited_ids: set[str] = set()
    for credit in credits:
        event_id = _text(credit.goal_event_id, "credited goal_event_id")
        if event_id in credited_ids or event_id not in by_goal:
            _fail("Final FPL credits have duplicated or unknown physical goal IDs.")
        credited_ids.add(event_id)
        goal = by_goal[event_id]
        if goal.own_goal:
            if credit.scorer_player_code is not None:
                _fail("A physical own goal cannot be a positive FPL credited goal.")
        elif (
            credit.scorer_player_code is None
            or credit.scorer_player_code != goal.scorer_player_code
        ):
            _fail("A final FPL goal requires its exact recorded physical scorer.")
        for credit_code in (credit.scorer_player_code, credit.assist_player_code):
            if credit_code is not None:
                _integer(credit_code, "FPL credited player")
                if (
                    credit_code not in players
                    or players[credit_code].club_code != goal.beneficiary_club_code
                ):
                    _fail("FPL credited identity must belong to the beneficiary club.")
                credited_exposure = exposure_by_player[credit_code]
                if credited_exposure.physical_on >= credited_exposure.physical_off:
                    _fail("A final FPL credit requires positive observed physical exposure.")
        if (
            credit.scorer_player_code is not None
            and credit.scorer_player_code == credit.assist_player_code
        ):
            _fail("A player cannot receive both credited goal and assist for the same event.")


def score_input_digest(fixture: ScoreFixture) -> str:
    validate_score_fixture(fixture)
    document = asdict(fixture)
    for field in ("decision_at", "deadline_at", "kickoff", "native_basis_fit_cutoff"):
        document[field] = _clock(document[field], field).isoformat()
    return hashlib.sha256(
        json.dumps(
            {"version": SCORE_INPUT_VERSION, "input": document},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def read_score_snapshot(
    raw: bytes,
    *,
    sha256: str,
    season: str,
    gameweek: int,
    fixture_id: int,
    decision_at: str,
    deadline_at: str,
    native_basis_sha256: str,
) -> ScoreFixture:
    """Read an operator-admitted original-byte predecision fixture source."""
    _season(season)
    _integer(gameweek, "gameweek", maximum=38)
    _integer(fixture_id, "fixture_id")
    decision, deadline = _clock(decision_at, "decision_at"), _clock(deadline_at, "deadline_at")
    if decision >= deadline:
        _fail("Decision must precede deadline.")
    _sha(native_basis_sha256, "native_basis_sha256")
    doc = _object(
        _json(raw, sha256),
        {
            "version",
            "captured_at",
            "published_at",
            "rights",
            "native_basis_clock",
            "coverage",
            "calendar",
            "club_mapping",
            "person_mapping",
            "projection",
        },
        "snapshot",
    )
    if doc["version"] != RAW_SCORE_SNAPSHOT_VERSION:
        _fail("Unknown score snapshot version.")
    capture = _capture(doc["captured_at"], doc["published_at"], decision, "snapshot")
    _rights(doc["rights"])
    native_clock = _object(
        doc["native_basis_clock"], {"captured_at", "published_at"}, "native basis clock"
    )
    if (
        _capture(
            native_clock["captured_at"], native_clock["published_at"], decision, "native basis"
        )
        > capture
    ):
        _fail("Native basis cannot be captured after its containing source snapshot.")
    keys = {f.name for f in fields(ScoreFixture)} - {"source_sha256"}
    projection = dict(_object(doc["projection"], keys, "projection"))
    for field, expected in (
        ("season", season),
        ("gameweek", gameweek),
        ("fixture_id", fixture_id),
        ("native_basis_sha256", native_basis_sha256),
    ):
        if projection[field] != expected or type(projection[field]) is not type(expected):
            _fail("Original projection identity or native basis differs from supplied header.")
    if (
        _clock(projection["decision_at"], "projection decision") != decision
        or _clock(projection["deadline_at"], "projection deadline") != deadline
    ):
        _fail("Projection clocks differ from the supplied original decision.")
    player_keys = {f.name for f in fields(ScorePlayer)}
    players = []
    for item in _array(projection["players"], "players", MAX_PLAYERS):
        player = dict(_object(item, player_keys, "player"))
        for field in (
            "probabilities",
            "credited_minutes",
            "physical_on",
            "physical_off",
            "exit_policies",
        ):
            player[field] = tuple(_array(player[field], field, 7))
        players.append(ScorePlayer(**player))
    projection["players"] = tuple(players)
    fixture = ScoreFixture(**projection, source_sha256=sha256)
    validate_score_fixture(fixture)
    if _clock(fixture.native_basis_fit_cutoff, "native fit cutoff") >= _clock(
        native_clock["captured_at"], "native capture"
    ):
        _fail("Native fit cutoff must precede native forecast capture.")
    coverage = _object(
        doc["coverage"],
        {"complete", "physical_clock_known", "exit_policies_known", "player_codes", "evidence_ref"},
        "coverage",
    )
    if (
        any(
            coverage[field] is not True
            for field in ("complete", "physical_clock_known", "exit_policies_known")
        )
        or coverage["evidence_ref"] != fixture.coverage_evidence_ref
    ):
        _fail("Complete physical-clock and exit-policy coverage is required.")
    expected_codes = [
        _integer(code, "coverage player")
        for code in _array(coverage["player_codes"], "coverage player_codes", MAX_PLAYERS)
    ]
    if len(set(expected_codes)) != len(expected_codes) or set(expected_codes) != {
        p.player_code for p in fixture.players
    }:
        _fail("Coverage must bind the complete paired persistent player inventory.")
    mapping_keys = {"player_code", "club_code", "provider_id", "available_at", "evidence_ref"}
    mapped: dict[int, int] = {}
    provider_people: set[str] = set()
    for item in _array(doc["person_mapping"], "person_mapping", MAX_PLAYERS):
        person = _object(item, mapping_keys, "person mapping")
        code, club = (
            _integer(person["player_code"], "mapped player"),
            _integer(person["club_code"], "mapped club"),
        )
        provider = _text(person["provider_id"], "provider person identity")
        if (
            code in mapped
            or provider in provider_people
            or _clock(person["available_at"], "person mapping available_at") > capture
        ):
            _fail("Persistent person crosswalk must be unique and captured before the source.")
        mapped[code] = club
        provider_people.add(provider)
        _text(person["evidence_ref"], "person mapping evidence_ref")
    if mapped != {p.player_code: p.club_code for p in fixture.players}:
        _fail("Persistent person crosswalk contradicts complete paired club membership.")
    club_keys = {"club_code", "provider_id", "available_at", "evidence_ref"}
    clubs: set[int] = set()
    provider_clubs: set[str] = set()
    for item in _array(doc["club_mapping"], "club_mapping", 2):
        club_row = _object(item, club_keys, "club mapping")
        code, provider = (
            _integer(club_row["club_code"], "mapped club"),
            _text(club_row["provider_id"], "provider club identity"),
        )
        if (
            code in clubs
            or provider in provider_clubs
            or _clock(club_row["available_at"], "club mapping available_at") > capture
        ):
            _fail("Persistent club crosswalk must be unique and already available.")
        clubs.add(code)
        provider_clubs.add(provider)
        _text(club_row["evidence_ref"], "club mapping evidence_ref")
    if clubs != {fixture.home_club_code, fixture.away_club_code}:
        _fail("Persistent club crosswalk lacks the exact opposing sides.")
    calendar_keys = {
        "fixture_id",
        "club_code",
        "opponent_code",
        "home",
        "kickoff",
        "available_at",
        "evidence_ref",
    }
    sides: dict[int, tuple[int, int]] = {}
    for item in _array(doc["calendar"], "calendar", 2):
        side = _object(item, calendar_keys, "calendar side")
        code, opponent = (
            _integer(side["club_code"], "calendar club"),
            _integer(side["opponent_code"], "calendar opponent"),
        )
        home = _integer(side["home"], "calendar home", 0, 1)
        if (
            code in sides
            or _integer(side["fixture_id"], "calendar fixture") != fixture.fixture_id
            or _clock(side["kickoff"], "calendar kickoff") != _clock(fixture.kickoff, "kickoff")
            or _clock(side["available_at"], "calendar available_at") > capture
            or side["evidence_ref"] != fixture.calendar_evidence_ref
        ):
            _fail("Paired calendar identity and publication receipts disagree.")
        sides[code] = (opponent, home)
    if sides != {
        fixture.home_club_code: (fixture.away_club_code, 1),
        fixture.away_club_code: (fixture.home_club_code, 0),
    }:
        _fail("Calendar must contain exactly coherent home and away sides.")
    return fixture


def read_score_outcomes(
    raw: bytes,
    *,
    sha256: str,
    fixture: ScoreFixture,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
) -> TrainingScoreFixture:
    """Reject protected/target/future headers before decoding any outcome bytes."""
    # Header settlement is not yet available. Guard causal input identity first.
    validate_score_fixture(fixture)
    _season(target_season)
    targets = _tuple(target_gameweeks, "target_gameweeks", 38)
    if not targets or len(set(targets)) != len(targets):
        _fail("A unique nonempty target inventory is required.")
    for gw in targets:
        _integer(gw, "target gameweek", maximum=38)
    cutoff = _clock(fit_cutoff, "fit_cutoff")
    if (
        int(fixture.season[:4]) > int(target_season[:4])
        or (fixture.season == target_season and fixture.gameweek >= min(targets))
        or _clock(fixture.decision_at, "decision_at") >= cutoff
    ):
        _fail("Protected, target and future headers refuse before outcome decoding.")
    doc = _object(
        _json(raw, sha256),
        {
            "version",
            "season",
            "gameweek",
            "fixture_id",
            "input_sha256",
            "captured_at",
            "published_at",
            "rights",
            "coverage",
            "outcome",
        },
        "outcome source",
    )
    if doc["version"] != RAW_SCORE_OUTCOME_VERSION:
        _fail("Unknown score outcome version.")
    for field in ("season", "gameweek", "fixture_id"):
        if doc[field] != getattr(fixture, field) or type(doc[field]) is not type(
            getattr(fixture, field)
        ):
            _fail("Final outcome source belongs to a different original fixture.")
    if _sha(doc["input_sha256"], "input_sha256") != score_input_digest(fixture):
        _fail("Final outcome source does not bind its original predecision input.")
    capture = _capture(doc["captured_at"], doc["published_at"], cutoff, "outcomes")
    _rights(doc["rights"])
    coverage = _object(
        doc["coverage"],
        {
            "physical_events_complete",
            "physical_periods_complete",
            "physical_exposures_complete",
            "fpl_credits_complete",
            "fpl_credit_scope",
            "dismissals_complete",
            "evidence_ref",
        },
        "final coverage",
    )
    if (
        any(
            coverage[field] is not True
            for field in (
                "physical_events_complete",
                "physical_periods_complete",
                "physical_exposures_complete",
                "fpl_credits_complete",
                "dismissals_complete",
            )
        )
        or coverage["fpl_credit_scope"] != "final_fpl_goal_assist_credits_v1"
    ):
        _fail("Complete separately scoped final physical and FPL observations are required.")
    _text(coverage["evidence_ref"], "final coverage evidence_ref")
    result_keys = {f.name for f in fields(TrainingScoreFixture)} - {"input", "outcome_sha256"}
    outcome = dict(_object(doc["outcome"], result_keys | {"dismissal_events"}, "outcome"))
    if _array(outcome.pop("dismissal_events"), "dismissal_events", MAX_PLAYERS):
        _fail("Dismissal exposure policy is unsupported in this first experiment.")
    for name, cls, maximum in (
        ("goals", PhysicalGoal, MAX_GOALS),
        ("periods", PhysicalPeriod, 2),
        ("fpl_credits", FPLCredit, MAX_GOALS),
        ("exposures", ObservedPlayerExposure, MAX_PLAYERS),
    ):
        keys = {field.name for field in fields(cls)}
        outcome[name] = tuple(
            cls(**_object(item, keys, name)) for item in _array(outcome[name], name, maximum)
        )
    row = TrainingScoreFixture(**outcome, input=fixture, outcome_sha256=sha256)
    validate_training_score_fixture(
        row, fit_cutoff=fit_cutoff, target_season=target_season, target_gameweeks=target_gameweeks
    )
    if _clock(row.settled_at, "settled_at") > capture:
        _fail("Final physical settlement must precede outcome capture.")
    return row
