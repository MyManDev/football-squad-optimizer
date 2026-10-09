"""Private captured flag facts and supplied, predecision native minute supports.

Source permission and mapping receipts are operator assertions. These readers verify
their shape and causal binding; they do not establish actual rights or genuine folds.
No reader accesses a network, a filesystem, or an outcome not explicitly supplied.
Capture published_at is the archive publication clock, distinct from news_added.
Its required order is captured_at <= published_at < decision_at.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import cast

from squadopt.data.errors import DataError
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

FLAG_INPUT_VERSION = "football_flag_week_input_v1"
RAW_FLAG_CAPTURE_VERSION = "football_flag_captures_v1"
RAW_FLAG_OUTCOME_VERSION = "football_flag_outcomes_v1"
PROTECTED_SEASON = "2025-26"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_WEEK_FIXTURES = 3
MAX_CAPTURE_COUNT = 4096
STATE_NAMES = (
    "zero",
    "start_short",
    "start_60",
    "start_full",
    "cameo_short",
    "cameo_60",
    "cameo_full",
)
POSITIONS = ("GK", "DEF", "MID", "FWD")
STATUSES = ("a", "d", "i", "s", "u", "n")
LABELS = (0, 25, 50, 75, 100)
NEWS_STATES = ("never_flagged", "cleared", "flagged", "unknown")


@dataclass(frozen=True, slots=True)
class MinuteFixture:
    fixture: int
    kickoff: str
    club: int
    opponent: int
    home: int
    probabilities: tuple[float, ...]
    minutes: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class PlayerWeekInput:
    season: str
    gameweek: int
    player_code: int
    decision_at: str
    deadline_at: str
    position: str
    status: str | None
    label: int | None
    news_state: str
    news_age_hours: float | None
    capture_age_hours: float
    history_covered: bool
    label_changed: bool | None
    fixtures: tuple[MinuteFixture, ...]
    source_sha256: str
    native_basis_sha256: str
    native_basis_evidence_ref: str
    native_basis_kind: str
    native_basis_fit_cutoff: str
    calendar_complete: bool
    covered_gameweeks: tuple[int, ...]
    calendar_evidence_ref: str
    legacy_next_round_label: int | None = None


@dataclass(frozen=True, slots=True)
class TrainingWeek:
    input: PlayerWeekInput
    observed_states: tuple[int, ...]
    settled_at: str
    outcome_sha256: str


def _fail(message: str) -> None:
    raise DataError(message)


def _integer(value: object, label: str, low: int = 1, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        _fail(f"{label} must be an integer in the declared range.")
    return cast(int, value)


def _number(value: object, label: str, low: float = 0.0) -> float:
    if type(value) not in (int, float):
        _fail(f"{label} must be a finite number.")
    try:
        result = float(cast(float, value))
    except (OverflowError, ValueError) as error:
        raise DataError(f"{label} must be a finite number.") from error
    if not math.isfinite(result) or result < low:
        _fail(f"{label} must be a finite number >= {low}.")
    return result


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        _fail(f"{label} must be a nonblank, unpadded string.")
    return cast(str, value)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean.")
    return cast(bool, value)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail(f"{label} must be a lowercase SHA256.")
    return cast(str, value)


def _season(value: object, label: str = "season") -> str:
    text = _text(value, label)
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}", text) is None:
        _fail(f"{label} must use YYYY-YY.")
    if int(text[5:]) != (int(text[:4]) + 1) % 100:
        _fail(f"{label} must name consecutive years.")
    if text == PROTECTED_SEASON:
        _fail("Protected 2025-26 is excluded before source decoding.")
    return text


def _clock(value: object, label: str) -> str:
    return normalize_utc_timestamp(value, label=label)


def _label(value: object, name: str) -> int | None:
    if value is None:
        return None
    result = _integer(value, name, 0, 100)
    if result not in LABELS:
        _fail(f"{name} is outside the versioned editorial vocabulary.")
    return result


def _status(value: object) -> str | None:
    if value is None:
        return None
    result = _text(value, "status")
    if result not in STATUSES:
        _fail("Unknown source status needs a new declared contract.")
    return result


def _keys(record: object, keys: set[str], label: str) -> dict[str, object]:
    if not isinstance(record, dict) or set(record) != keys:
        _fail(f"{label} requires exactly its complete declared fields.")
    return cast(dict[str, object], record)


def _json(raw: bytes, sha256: str) -> dict[str, object]:
    _digest(sha256, "raw SHA256")
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES:
        _fail("Source must be immutable bounded bytes.")
    if hashlib.sha256(raw).hexdigest() != sha256:
        _fail("Source bytes do not match the declared SHA256.")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("Duplicate JSON keys are refused.")
            result[key] = value
        return result

    def constant(value: str) -> object:
        _fail(f"Nonfinite JSON constant {value} is refused.")
        return None

    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise DataError("Source must be strict UTF-8 JSON.") from error
    if not isinstance(document, dict):
        _fail("Source root must be an object.")
    return cast(dict[str, object], document)


def _tuple(value: object, label: str) -> tuple[object, ...]:
    if type(value) is not tuple:
        _fail(f"{label} must be an immutable tuple.")
    return cast(tuple[object, ...], value)


def _list(value: object, label: str, maximum: int) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(f"{label} must be a bounded JSON list.")
    return cast(list[object], value)


def _covered(value: object) -> tuple[int, ...]:
    items = _tuple(value, "covered_gameweeks")
    weeks = tuple(_integer(item, "covered_gameweeks", 1, 38) for item in items)
    if not weeks or weeks != tuple(sorted(set(weeks))):
        _fail("covered_gameweeks must be sorted, unique and nonempty.")
    return weeks


def validate_week_input(week: PlayerWeekInput) -> None:
    """Validate facts without treating editorial labels as calibrated estimates."""
    if type(week) is not PlayerWeekInput:
        _fail("Expected a frozen PlayerWeekInput.")
    _season(week.season)
    _integer(week.gameweek, "gameweek", 1, 38)
    _integer(week.player_code, "player_code")
    decision = as_instant(_clock(week.decision_at, "decision_at"))
    deadline = as_instant(_clock(week.deadline_at, "deadline_at"))
    if decision >= deadline:
        _fail("decision_at must precede deadline_at.")
    if week.position not in POSITIONS:
        _fail("Unknown FPL position.")
    _status(week.status)
    _label(week.label, "label")
    _label(week.legacy_next_round_label, "legacy_next_round_label")
    if week.news_state not in NEWS_STATES:
        _fail("Unknown news state.")
    if week.news_age_hours is not None:
        _number(week.news_age_hours, "news_age_hours")
    if week.news_state in ("never_flagged", "unknown") and week.news_age_hours is not None:
        _fail("An unknown or never-flagged news stamp cannot have an age.")
    if week.news_state == "cleared" and week.news_age_hours is None:
        _fail("A cleared news state requires its recorded stamp.")
    _number(week.capture_age_hours, "capture_age_hours")
    _boolean(week.history_covered, "history_covered")
    if week.label_changed is not None:
        _boolean(week.label_changed, "label_changed")
        if not week.history_covered:
            _fail("Incomplete history cannot declare label_changed.")
    _digest(week.source_sha256, "source_sha256")
    _digest(week.native_basis_sha256, "native_basis_sha256")
    _text(week.native_basis_evidence_ref, "native_basis_evidence_ref")
    if week.native_basis_kind not in ("out_of_fold", "prospective"):
        _fail("Native basis must be explicitly out_of_fold or prospective.")
    fit = as_instant(_clock(week.native_basis_fit_cutoff, "native_basis_fit_cutoff"))
    if fit >= decision:
        _fail("Native basis fit cutoff must precede decision_at.")
    if _boolean(week.calendar_complete, "calendar_complete") is not True:
        _fail("A complete fixture calendar is required, including BGW.")
    if week.gameweek not in _covered(week.covered_gameweeks):
        _fail("Calendar does not explicitly cover the target gameweek.")
    _text(week.calendar_evidence_ref, "calendar_evidence_ref")
    fixtures = _tuple(week.fixtures, "fixtures")
    if len(fixtures) > MAX_WEEK_FIXTURES:
        _fail("More than three fixtures are outside bounded support.")
    identities: set[int] = set()
    clubs: set[int] = set()
    kickoffs: list[str] = []
    for item in fixtures:
        if type(item) is not MinuteFixture:
            _fail("fixtures must contain frozen MinuteFixture values.")
        fixture = cast(MinuteFixture, item)
        identifier = _integer(fixture.fixture, "fixture")
        if identifier in identities:
            _fail("Duplicate player fixture.")
        identities.add(identifier)
        club = _integer(fixture.club, "club")
        opponent = _integer(fixture.opponent, "opponent")
        if club == opponent:
            _fail("A club cannot play itself.")
        clubs.add(club)
        _integer(fixture.home, "home", 0, 1)
        kickoff = _clock(fixture.kickoff, "kickoff")
        if as_instant(kickoff) < deadline:
            _fail("Every target kickoff must be at or after the deadline.")
        kickoffs.append(kickoff)
        probabilities = _tuple(fixture.probabilities, "probabilities")
        minutes = _tuple(fixture.minutes, "minutes")
        if len(probabilities) != 7 or len(minutes) != 7:
            _fail("Every fixture requires exactly seven minute states.")
        values = tuple(_number(value, "probability") for value in probabilities)
        if any(value > 1.0 for value in values) or not math.isclose(
            math.fsum(values), 1.0, abs_tol=1e-12, rel_tol=0.0
        ):
            _fail("Fixture probabilities must sum to one.")
        minute_values = tuple(_number(value, "state minutes") for value in minutes)
        if minute_values[0] != 0 or any(not 90 <= minute_values[index] <= 120 for index in (3, 6)):
            _fail("Zero states must be zero and full minute states must be within ninety to 120.")
        if any(not 0 < minute_values[index] < 60 for index in (1, 4)):
            _fail("Short minute states must be positive and below sixty.")
        if any(not 60 <= minute_values[index] < 90 for index in (2, 5)):
            _fail("Sixty minute states must be at least sixty and below ninety.")
    if len(clubs) > 1:
        _fail("One player-week cannot declare inconsistent club identities.")
    instants = tuple(as_instant(value) for value in kickoffs)
    if instants != tuple(sorted(set(instants))):
        _fail("Player fixtures must have distinct chronological kickoffs.")


def _training_guard(
    week: PlayerWeekInput,
    fit_cutoff: str | None,
    target_season: str | None,
    target_gameweeks: tuple[int, ...],
) -> None:
    if type(week) is not PlayerWeekInput:
        _fail("Expected a frozen PlayerWeekInput before outcome decoding.")
    _season(week.season)
    _integer(week.gameweek, "training gameweek", 1, 38)
    if target_season is not None:
        _season(target_season, "target_season")
    weeks = _tuple(target_gameweeks, "target_gameweeks")
    parsed = tuple(_integer(value, "target gameweek", 1, 38) for value in weeks)
    if len(set(parsed)) != len(parsed):
        _fail("Duplicate target gameweeks.")
    if (target_season is None) != (fit_cutoff is None):
        _fail("Fit cutoff and target season must be supplied together.")
    if target_season is not None and not parsed:
        _fail("An explicit nonempty target gameweek inventory is required.")
    if target_season is not None and int(week.season[:4]) > int(target_season[:4]):
        _fail("Future seasons are excluded before outcome decoding.")
    if week.season == target_season and week.gameweek >= min(parsed):
        _fail(
            "Entire target gameweek and all later gameweeks are excluded before outcome decoding."
        )
    if fit_cutoff is not None:
        cutoff = as_instant(_clock(fit_cutoff, "fit_cutoff"))
        if as_instant(_clock(week.decision_at, "decision_at")) >= cutoff:
            _fail("Training decisions must precede fit_cutoff.")


def validate_training_week(
    row: TrainingWeek,
    *,
    fit_cutoff: str | None = None,
    target_season: str | None = None,
    target_gameweeks: tuple[int, ...] = (),
) -> None:
    if type(row) is not TrainingWeek:
        _fail("Expected a frozen TrainingWeek.")
    _training_guard(row.input, fit_cutoff, target_season, target_gameweeks)
    validate_week_input(row.input)
    settled = as_instant(_clock(row.settled_at, "settled_at"))
    if settled <= as_instant(_clock(row.input.deadline_at, "deadline_at")) or any(
        settled <= as_instant(_clock(fixture.kickoff, "kickoff")) for fixture in row.input.fixtures
    ):
        _fail("Observed labels must settle strictly after all target kickoffs.")
    if fit_cutoff is not None and settled >= as_instant(_clock(fit_cutoff, "fit_cutoff")):
        _fail("Observed labels must settle strictly before fit_cutoff.")
    if as_instant(_clock(row.input.native_basis_fit_cutoff, "native_basis_fit_cutoff")) >= settled:
        _fail("Native basis must be fitted before observed labels settle.")
    states = _tuple(row.observed_states, "observed_states")
    if len(states) != len(row.input.fixtures):
        _fail("Observed states must cover every native fixture exactly.")
    for state in states:
        _integer(state, "observed state", 0, 6)
    _digest(row.outcome_sha256, "outcome_sha256")


def input_digest(week: PlayerWeekInput) -> str:
    validate_week_input(week)
    return hashlib.sha256(
        json.dumps(
            {"version": FLAG_INPUT_VERSION, "input": asdict(week)},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


_CAPTURE_FIELDS = {
    "captured_at",
    "published_at",
    "element_id",
    "player_code",
    "club_code",
    "current_event_id",
    "next_event_id",
    "status",
    "chance_of_playing_this_round",
    "chance_of_playing_next_round",
    "news",
    "news_added",
}
_SOURCE_FIELDS = {
    "version",
    "season",
    "gameweek",
    "player_code",
    "position",
    "mapping_verified",
    "mapping_evidence_ref",
    "model_use_approved",
    "model_use_evidence_ref",
    "calendar_complete",
    "covered_gameweeks",
    "fixture_ids",
    "calendar_evidence_ref",
    "history_covered",
    "history_start_at",
    "history_end_at",
    "expected_capture_count",
    "history_evidence_ref",
    "captures",
    "native_basis_sha256",
    "native_basis_evidence_ref",
    "native_basis_kind",
    "native_basis_fit_cutoff",
}


def _receipt(document: dict[str, object]) -> None:
    if not _boolean(document["mapping_verified"], "mapping_verified"):
        _fail("An explicitly verified player mapping receipt is required.")
    _text(document["mapping_evidence_ref"], "mapping_evidence_ref")
    if not _boolean(document["model_use_approved"], "model_use_approved"):
        _fail("Operator model-use admission is required.")
    _text(document["model_use_evidence_ref"], "model_use_evidence_ref")


def _event_label(capture: dict[str, object], gameweek: int) -> tuple[bool, int | None]:
    current = capture["current_event_id"]
    following = capture["next_event_id"]
    for name, value in (("current_event_id", current), ("next_event_id", following)):
        if value is not None:
            _integer(value, name, 1, 38)
    if current is not None and current == following:
        _fail("Current and next event identities cannot coincide.")
    this_label = _label(capture["chance_of_playing_this_round"], "this_round label")
    next_label = _label(capture["chance_of_playing_next_round"], "next_round label")
    if current == gameweek:
        return True, this_label
    if following == gameweek:
        return True, next_label
    return False, None


def read_flag_week_source(
    raw: bytes,
    *,
    sha256: str,
    season: str,
    gameweek: int,
    player_code: int,
    decision_at: str,
    deadline_at: str,
    native_fixtures: tuple[MinuteFixture, ...],
    native_basis_sha256: str,
) -> PlayerWeekInput:
    """Read one admitted private player's original this/next-round captures."""
    _season(season)
    _integer(gameweek, "gameweek", 1, 38)
    _integer(player_code, "player_code")
    decision = as_instant(_clock(decision_at, "decision_at"))
    deadline_at = _clock(deadline_at, "deadline_at")
    _tuple(native_fixtures, "native_fixtures")
    if any(type(fixture) is not MinuteFixture for fixture in native_fixtures):
        _fail("native_fixtures must contain frozen MinuteFixture values.")
    _digest(native_basis_sha256, "native_basis_sha256")
    document = _keys(_json(raw, sha256), _SOURCE_FIELDS, "Flag capture source")
    if document["version"] != RAW_FLAG_CAPTURE_VERSION:
        _fail("Unknown flag source version.")
    if (document["season"], document["gameweek"], document["player_code"]) != (
        season,
        gameweek,
        player_code,
    ):
        _fail("Flag source identity does not match the requested player-week.")
    _season(document["season"])
    _integer(document["gameweek"], "source gameweek", 1, 38)
    _integer(document["player_code"], "source player_code")
    _receipt(document)
    if _digest(document["native_basis_sha256"], "source native basis") != native_basis_sha256:
        _fail("Flag source is bound to a different native forecast basis.")
    covered = tuple(
        _integer(value, "covered gameweek", 1, 38)
        for value in _list(document["covered_gameweeks"], "covered_gameweeks", 38)
    )
    fixture_ids = tuple(
        _integer(value, "fixture_ids")
        for value in _list(document["fixture_ids"], "fixture_ids", MAX_WEEK_FIXTURES)
    )
    if fixture_ids != tuple(fixture.fixture for fixture in native_fixtures):
        _fail("Source calendar must exactly cover the supplied native fixture roster.")
    covered_history = _boolean(document["history_covered"], "history_covered")
    count = _integer(
        document["expected_capture_count"], "expected_capture_count", 1, MAX_CAPTURE_COUNT
    )
    captures = [
        _keys(item, _CAPTURE_FIELDS, "capture")
        for item in _list(document["captures"], "captures", MAX_CAPTURE_COUNT)
    ]
    if not captures or count != len(captures):
        _fail("Capture history count is incomplete.")
    observed: list[tuple[str, bool, int | None]] = []
    elements: set[int] = set()
    capture_clubs: set[int] = set()
    for capture in captures:
        stamp = _clock(capture["captured_at"], "capture captured_at")
        published = as_instant(_clock(capture["published_at"], "archive published_at"))
        if not as_instant(stamp) <= published < decision:
            _fail("Capture <= archive publication < decision is required.")
        if _integer(capture["player_code"], "capture player_code") != player_code:
            _fail("Capture persistent player mapping differs.")
        elements.add(_integer(capture["element_id"], "element_id"))
        capture_clubs.add(_integer(capture["club_code"], "club_code"))
        _status(capture["status"])
        news = capture["news"]
        if news is not None and not isinstance(news, str):
            _fail("Original news must be a string or explicit null.")
        if capture["news_added"] is not None and as_instant(
            _clock(capture["news_added"], "news_added")
        ) > as_instant(stamp):
            _fail("News timestamp cannot follow its capture.")
        bound, label = _event_label(capture, gameweek)
        observed.append((stamp, bound, label))
    stamps = tuple(as_instant(item[0]) for item in observed)
    if stamps != tuple(sorted(set(stamps))):
        _fail("Captures must be distinct and strictly chronological.")
    if len(elements) != 1 or len(capture_clubs) != 1:
        _fail("Capture identities require one exact seasonal element and club mapping.")
    if native_fixtures and capture_clubs != {native_fixtures[0].club}:
        _fail("Captured club does not match the native fixture roster.")
    start = document["history_start_at"]
    end = document["history_end_at"]
    history_ref = document["history_evidence_ref"]
    if covered_history:
        _text(history_ref, "history_evidence_ref")
        if (_clock(start, "history_start_at"), _clock(end, "history_end_at")) != (
            observed[0][0],
            observed[-1][0],
        ):
            _fail("Complete history bounds must match the supplied captures exactly.")
    elif start is not None or end is not None or history_ref is not None:
        _fail("Uncovered history must preserve absent bounds and receipt as null.")
    latest = captures[-1]
    if not observed[-1][1]:
        _fail("Latest capture does not bind this or next label to the target event.")
    news = latest["news"]
    news_stamp = latest["news_added"]
    news_state = (
        "unknown"
        if news is None
        else (
            "flagged"
            if cast(str, news).strip()
            else ("cleared" if news_stamp is not None else "never_flagged")
        )
    )
    news_age = None
    if news_state != "unknown" and news_stamp is not None:
        news_age = (decision - as_instant(_clock(news_stamp, "news_added"))).total_seconds() / 3600
    label_changed = None
    if (
        covered_history
        and len(observed) >= 2
        and all(item[1] and item[2] is not None for item in observed[-2:])
    ):
        label_changed = observed[-2][2] != observed[-1][2]
    week = PlayerWeekInput(
        season,
        gameweek,
        player_code,
        _clock(decision_at, "decision_at"),
        deadline_at,
        _text(document["position"], "position"),
        _status(latest["status"]),
        observed[-1][2],
        news_state,
        news_age,
        (decision - stamps[-1]).total_seconds() / 3600,
        covered_history,
        label_changed,
        native_fixtures,
        sha256,
        native_basis_sha256,
        _text(document["native_basis_evidence_ref"], "native_basis_evidence_ref"),
        _text(document["native_basis_kind"], "native_basis_kind"),
        _clock(document["native_basis_fit_cutoff"], "native_basis_fit_cutoff"),
        _boolean(document["calendar_complete"], "calendar_complete"),
        covered,
        _text(document["calendar_evidence_ref"], "calendar_evidence_ref"),
        _label(latest["chance_of_playing_next_round"], "legacy_next_round_label"),
    )
    validate_week_input(week)
    return week


_OUTCOME_FIELDS = {
    "version",
    "season",
    "gameweek",
    "player_code",
    "input_sha256",
    "settled_at",
    "published_at",
    "captured_at",
    "mapping_verified",
    "mapping_evidence_ref",
    "model_use_approved",
    "model_use_evidence_ref",
    "calendar_complete",
    "covered_gameweeks",
    "fixture_ids",
    "observations",
}
_OBSERVATION_FIELDS = {
    "fixture",
    "kickoff",
    "club",
    "opponent",
    "home",
    "minutes",
    "starts",
    "state",
}


def read_flag_outcome_source(
    raw: bytes,
    *,
    sha256: str,
    week: PlayerWeekInput,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
) -> TrainingWeek:
    """Refuse protected or target weeks before decoding any supplied label bytes."""
    _training_guard(week, fit_cutoff, target_season, target_gameweeks)
    validate_week_input(week)
    document = _keys(_json(raw, sha256), _OUTCOME_FIELDS, "Flag outcome source")
    if document["version"] != RAW_FLAG_OUTCOME_VERSION:
        _fail("Unknown outcome source version.")
    if (document["season"], document["gameweek"], document["player_code"]) != (
        week.season,
        week.gameweek,
        week.player_code,
    ):
        _fail("Outcome source identity differs from its input player-week.")
    _integer(document["gameweek"], "outcome gameweek", 1, 38)
    _integer(document["player_code"], "outcome player_code")
    _receipt(document)
    if _digest(document["input_sha256"], "input_sha256") != input_digest(week):
        _fail("Outcome labels do not bind to the exact input digest.")
    settled_at = _clock(document["settled_at"], "settled_at")
    settled = as_instant(settled_at)
    published = as_instant(_clock(document["published_at"], "outcome published_at"))
    captured = as_instant(_clock(document["captured_at"], "outcome captured_at"))
    cutoff = as_instant(_clock(fit_cutoff, "fit_cutoff"))
    if not settled <= captured <= published < cutoff:
        _fail("Settled <= captured <= published < fit cutoff is required.")
    if not _boolean(document["calendar_complete"], "outcome calendar_complete"):
        _fail("Outcome fixture calendar is incomplete.")
    covered = tuple(
        _integer(value, "outcome covered gameweek", 1, 38)
        for value in _list(document["covered_gameweeks"], "covered_gameweeks", 38)
    )
    if _covered(covered) != week.covered_gameweeks:
        _fail("Outcome calendar coverage differs from input.")
    ids = tuple(
        _integer(value, "outcome fixture ID")
        for value in _list(document["fixture_ids"], "fixture_ids", MAX_WEEK_FIXTURES)
    )
    if ids != tuple(fixture.fixture for fixture in week.fixtures):
        _fail("Outcome labels must cover the complete native fixture roster.")
    rows = _list(document["observations"], "observations", MAX_WEEK_FIXTURES)
    if len(rows) != len(week.fixtures):
        _fail("Every native fixture needs a recorded minutes and starts label.")
    states: list[int] = []
    for item, fixture in zip(rows, week.fixtures, strict=True):
        row = _keys(item, _OBSERVATION_FIELDS, "fixture observation")
        identity = tuple(
            _integer(row[name], name, 0 if name == "home" else 1, 1 if name == "home" else None)
            for name in ("fixture", "club", "opponent", "home")
        )
        if identity != (fixture.fixture, fixture.club, fixture.opponent, fixture.home) or (
            _clock(row["kickoff"], "observed kickoff") != _clock(fixture.kickoff, "kickoff")
        ):
            _fail("Outcome fixture identity differs from the native basis.")
        minute = _integer(row["minutes"], "observed minutes", 0, 120)
        start = _integer(row["starts"], "recorded starts", 0, 1)
        state = _integer(row["state"], "observed state", 0, 6)
        if minute == 0:
            expected = 0
            if start != 0:
                _fail("Zero appearance cannot be a recorded start.")
        else:
            expected = (1 if minute < 60 else 2 if minute < 90 else 3) + (0 if start else 3)
        if state != expected:
            _fail("Observed state conflicts with explicit recorded starts and minutes.")
        states.append(state)
    result = TrainingWeek(week, tuple(states), settled_at, sha256)
    validate_training_week(
        result,
        fit_cutoff=fit_cutoff,
        target_season=target_season,
        target_gameweeks=target_gameweeks,
    )
    return result
