"""Private, immutable all-competition workload and native-law source contracts.

Publication is archive publication after capture. Permission and completeness
receipts are operator assertions; strings do not establish actual admission.
Physical exposure, FPL state labels, recovery clocks and travel proxies differ.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn, cast

from squadopt.data.errors import DataError

LOAD_INPUT_VERSION = "football_load_week_input_v1"
RAW_LOAD_SNAPSHOT_VERSION = "football_load_snapshot_v1"
RAW_LOAD_OUTCOME_VERSION = "football_load_outcomes_v1"
NATIVE_BASIS_VERSION = "football_load_native_joint_basis_v1"
NATIVE_BASIS_VERSIONS = (NATIVE_BASIS_VERSION,)
PROTECTED_SEASON = "2025-26"
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_WEEK_FIXTURES = 3
MAX_MATCHES = 4096
MASS_TOLERANCE = 1e-12
POSITIONS = ("GK", "DEF", "MID", "FWD")
TRAVEL_KINDS = ("actual", "planned", "venue_distance_proxy")
LOAD_FEATURE_NAMES = (
    *(
        name
        for days in (7, 14, 28)
        for name in (
            f"player_physical_minutes_{days}d",
            f"player_added_minutes_{days}d",
            f"player_extra_time_minutes_{days}d",
            f"player_starts_{days}d",
            f"player_known_minutes_count_{days}d",
            f"player_missing_minutes_count_{days}d",
            f"player_known_starts_count_{days}d",
            f"player_missing_starts_count_{days}d",
            f"club_matches_{days}d",
            f"non_pl_physical_minutes_{days}d",
            f"non_pl_starts_{days}d",
        )
    ),
    "player_hours_since_last_recorded_exit",
    "club_hours_since_last_recorded_end",
    "player_kickoff_gap_hours",
    "club_kickoff_gap_hours",
    "known_upcoming_club_matches_before_last_target",
    *(
        name
        for index in (1, 2, 3)
        for name in (
            f"fixture_{index}_club_scheduled_kickoff_gap_hours",
            f"fixture_{index}_known_prior_non_pl_matches",
        )
    ),
    *(
        f"{kind}_travel_{metric}"
        for kind in TRAVEL_KINDS
        for metric in ("distance_km", "duration_hours", "leg_count")
    ),
)


@dataclass(frozen=True, slots=True)
class LoadFixture:
    fixture_id: int
    kickoff: str
    club_code: int
    opponent_code: int
    is_home: int
    probabilities: tuple[float, ...]
    minutes: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class LoadWeek:
    season: str
    gameweek: int
    player_code: int
    decision_at: str
    deadline_at: str
    position: str
    fixtures: tuple[LoadFixture, ...]
    native_joint_states: tuple[tuple[int, ...], ...]
    native_joint_probabilities: tuple[float, ...]
    native_basis_sha256: str
    native_basis_kind: str
    native_basis_fit_cutoff: str
    native_basis_evidence_ref: str
    source_sha256: str
    features: tuple[float | None, ...]
    feature_names: tuple[str, ...]
    native_basis_version: str
    interval_start_at: str
    interval_end_at: str
    competition_ids: tuple[str, ...]
    coverage_evidence_ref: str
    mapping_evidence_ref: str
    calendar_complete: bool
    covered_gameweeks: tuple[int, ...]
    calendar_evidence_ref: str
    native_model_version: str
    native_joint_law_sha256: str


@dataclass(frozen=True, slots=True)
class TrainingLoadWeek:
    input: LoadWeek
    observed_states: tuple[int, ...]
    settled_at: str
    outcome_sha256: str


def _fail(message: str) -> NoReturn:
    raise DataError(message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        _fail(f"{name} must be a nonblank exact string.")
    return value


def _integer(value: object, name: str, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        _fail(f"{name} must be an integer in its declared range.")
    return value


def _number(value: object, name: str, minimum: float = 0.0) -> float:
    if type(value) not in (int, float):
        _fail(f"{name} must be a finite numeric value.")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as error:
        raise DataError(f"{name} must be finite.") from error
    if not math.isfinite(result) or result < minimum:
        _fail(f"{name} must be finite and at least {minimum}.")
    return result


def _nullable_number(value: object, name: str) -> float | None:
    return None if value is None else _number(value, name)


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be a boolean.")
    return value


def _clock(value: object, name: str) -> datetime:
    value = _text(value, name)
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as error:
        raise DataError(f"{name} must be an ISO-8601 instant.") from error
    if instant.tzinfo is None or instant.utcoffset() is None:
        _fail(f"{name} must declare its UTC offset.")
    return instant.astimezone(UTC)


def _utc(value: object, name: str) -> str:
    return _clock(value, name).isoformat().replace("+00:00", "Z")


def _season(value: object) -> str:
    value = _text(value, "season")
    if not re.fullmatch(r"\d{4}-\d{2}", value):
        _fail("season must use YYYY-YY.")
    if int(value[-2:]) != (int(value[:4]) + 1) % 100:
        _fail("season years must be consecutive.")
    if value == PROTECTED_SEASON:
        _fail("Protected 2025-26 outcomes and inputs are excluded.")
    return value


def _sha(value: object, name: str) -> str:
    value = _text(value, name)
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail(f"{name} must be an exact lowercase SHA256.")
    return value


def _object(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail(f"{name} must contain exactly its declared fields.")
    return cast(dict[str, Any], value)


def _list(value: object, name: str) -> list[Any]:
    if type(value) is not list or len(value) > MAX_MATCHES:
        _fail(f"{name} must be a bounded JSON array.")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    result = tuple(_text(item, name) for item in _list(value, name))
    if len(set(result)) != len(result):
        _fail(f"{name} contains duplicate identifiers.")
    return result


def _json(raw: bytes, sha256: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > MAX_SOURCE_BYTES:
        _fail("Source must be nonempty bounded immutable bytes.")
    _sha(sha256, "source_sha256")
    if hashlib.sha256(raw).hexdigest() != sha256:
        _fail("Source original-byte SHA256 mismatch.")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail("Duplicate JSON field.")
            result[key] = value
        return result

    def invalid_constant(value: str) -> NoReturn:
        _fail(f"Nonfinite JSON constant {value} is refused.")

    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise DataError("Source must be strict UTF-8 JSON.") from error
    if type(document) is not dict:
        _fail("Source root must be an object.")
    return document


def _unit_mass(values: tuple[float, ...], name: str) -> None:
    if type(values) is not tuple or not values:
        _fail(f"{name} must be a nonempty immutable tuple.")
    numbers = tuple(_number(value, name) for value in values)
    if any(value > 1 for value in numbers) or not math.isclose(
        math.fsum(numbers), 1.0, rel_tol=0, abs_tol=MASS_TOLERANCE
    ):
        _fail(f"{name} must be a finite unit-mass law.")


def _validate_native_law(
    fixtures: tuple[LoadFixture, ...],
    states: tuple[tuple[int, ...], ...],
    probabilities: tuple[float, ...],
    *,
    deadline: datetime | None = None,
) -> None:
    if type(fixtures) is not tuple or len(fixtures) > MAX_WEEK_FIXTURES:
        _fail("Fixtures require immutable bounded support.")
    fixture_ids: set[int] = set()
    clubs: set[int] = set()
    previous: datetime | None = None
    for fixture in fixtures:
        if type(fixture) is not LoadFixture:
            _fail("Native fixtures must be frozen LoadFixture values.")
        fixture_id = _integer(fixture.fixture_id, "fixture_id")
        if fixture_id in fixture_ids:
            _fail("Duplicate native fixture.")
        fixture_ids.add(fixture_id)
        club = _integer(fixture.club_code, "club_code")
        if club == _integer(fixture.opponent_code, "opponent_code"):
            _fail("A fixture cannot play the same club on both sides.")
        clubs.add(club)
        _integer(fixture.is_home, "is_home", 0, 1)
        kickoff = _clock(fixture.kickoff, "kickoff")
        if (deadline is not None and kickoff <= deadline) or (
            previous is not None and kickoff <= previous
        ):
            _fail("Native fixtures must be distinct chronological postdeadline fixtures.")
        previous = kickoff
        if (
            type(fixture.probabilities) is not tuple
            or type(fixture.minutes) is not tuple
            or len(fixture.probabilities) != 7
            or len(fixture.minutes) != 7
        ):
            _fail("Native fixtures require seven states.")
        _unit_mass(fixture.probabilities, "fixture probabilities")
        for index, value in enumerate(fixture.minutes):
            minutes = _number(value, "native minutes")
            valid = (
                minutes == 0
                if index == 0
                else (
                    0 < minutes < 60
                    if index in (1, 4)
                    else (60 <= minutes < 90 if index in (2, 5) else 90 <= minutes <= 120)
                )
            )
            if not valid:
                _fail("Native minutes contradict their declared state bins.")
    if len(clubs) > 1:
        _fail("A native week must use one registered club.")
    expected = tuple(itertools.product(range(7), repeat=len(fixtures)))
    if type(states) is not tuple or states != expected:
        _fail("Native states must be the complete canonical weekly Cartesian inventory.")
    if any(
        type(state) is not tuple or any(type(index) is not int for index in state)
        for state in states
    ):
        _fail("Native state indices must be immutable exact integers.")
    if type(probabilities) is not tuple or len(probabilities) != len(expected):
        _fail("Native joint law length does not match its complete inventory.")
    _unit_mass(probabilities, "native joint probabilities")
    for index, fixture in enumerate(fixtures):
        for state_index, declared in enumerate(fixture.probabilities):
            observed = math.fsum(
                probability
                for state, probability in zip(expected, probabilities, strict=True)
                if state[index] == state_index
            )
            if not math.isclose(observed, declared, rel_tol=0, abs_tol=MASS_TOLERANCE):
                _fail("Native joint law contradicts fixture marginals.")


def native_joint_law_digest(
    fixtures: tuple[LoadFixture, ...],
    states: tuple[tuple[int, ...], ...],
    probabilities: tuple[float, ...],
) -> str:
    """Bind exact fixture supports and original correlated weekly mass."""
    _validate_native_law(fixtures, states, probabilities)
    fixture_values = [asdict(fixture) for fixture in fixtures]
    for value in fixture_values:
        value["kickoff"] = _utc(value["kickoff"], "kickoff")
    payload = json.dumps(
        {
            "version": NATIVE_BASIS_VERSION,
            "fixtures": fixture_values,
            "states": states,
            "probabilities": probabilities,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_load_week(week: LoadWeek) -> None:
    """Refuse invalid enabled facts and bind the complete native weekly law."""
    if type(week) is not LoadWeek:
        _fail("Expected a frozen LoadWeek.")
    _season(week.season)
    _integer(week.gameweek, "gameweek", 1, 38)
    _integer(week.player_code, "player_code")
    decision = _clock(week.decision_at, "decision_at")
    deadline = _clock(week.deadline_at, "deadline_at")
    if decision >= deadline:
        _fail("decision_at must precede deadline_at.")
    if week.position not in POSITIONS:
        _fail("Unknown FPL position.")
    _validate_native_law(
        week.fixtures, week.native_joint_states, week.native_joint_probabilities, deadline=deadline
    )
    season_year = int(week.season[:4])
    season_start = datetime(season_year, 7, 1, tzinfo=UTC)
    season_end = datetime(season_year + 1, 7, 1, tzinfo=UTC)
    if any(
        not season_start <= _clock(fixture.kickoff, "kickoff") < season_end
        for fixture in week.fixtures
    ):
        _fail("Native target kickoff must belong to its declared July-to-June FPL season.")
    if _sha(week.native_joint_law_sha256, "native_joint_law_sha256") != native_joint_law_digest(
        week.fixtures, week.native_joint_states, week.native_joint_probabilities
    ):
        _fail("Declared native joint-law digest does not bind supplied correlation/supports.")
    _sha(week.native_basis_sha256, "native_basis_sha256")
    _sha(week.source_sha256, "source_sha256")
    if week.native_basis_version not in NATIVE_BASIS_VERSIONS:
        _fail("Unknown native basis version.")
    if not re.fullmatch(
        r"[a-z][a-z0-9_]*_v\d+", _text(week.native_model_version, "native_model_version")
    ):
        _fail("Native model version must be an exact versioned identifier.")
    if week.native_basis_kind not in ("out_of_fold", "prospective"):
        _fail("Native basis must declare out_of_fold or prospective provenance.")
    if _clock(week.native_basis_fit_cutoff, "native_basis_fit_cutoff") >= decision:
        _fail("Native basis fit cutoff must precede its decision.")
    _text(week.native_basis_evidence_ref, "native_basis_evidence_ref")
    if type(week.feature_names) is not tuple or week.feature_names != LOAD_FEATURE_NAMES:
        _fail("Features must use the exact versioned feature inventory.")
    if type(week.features) is not tuple or len(week.features) != len(LOAD_FEATURE_NAMES):
        _fail("Features must be an immutable exact-length tuple.")
    for name, value in zip(week.feature_names, week.features, strict=True):
        if value is not None:
            _number(value, name)
    if _clock(week.interval_start_at, "interval_start_at") != decision - timedelta(days=28):
        _fail("Coverage must begin exactly 28 days before the decision.")
    if _clock(week.interval_end_at, "interval_end_at") != decision:
        _fail("Coverage must end exactly at the decision.")
    if type(week.competition_ids) is not tuple or not week.competition_ids:
        _fail("A complete declared competition inventory is required.")
    if len(set(week.competition_ids)) != len(week.competition_ids):
        _fail("Duplicate competition identifier.")
    for competition in week.competition_ids:
        _text(competition, "competition_id")
    _text(week.coverage_evidence_ref, "coverage_evidence_ref")
    _text(week.mapping_evidence_ref, "mapping_evidence_ref")
    if type(week.calendar_complete) is not bool or not week.calendar_complete:
        _fail("The native week calendar must be complete, including explicit BGW.")
    if type(week.covered_gameweeks) is not tuple or not week.covered_gameweeks:
        _fail("Covered gameweeks must be an immutable inventory.")
    covered = tuple(_integer(value, "covered_gameweek", 1, 38) for value in week.covered_gameweeks)
    if covered != tuple(sorted(set(covered))) or week.gameweek not in covered:
        _fail("Covered gameweeks must be unique and bind the target.")
    _text(week.calendar_evidence_ref, "calendar_evidence_ref")


def _training_guard(
    week: LoadWeek,
    fit_cutoff: str | None,
    target_season: str | None,
    target_gameweeks: tuple[int, ...],
) -> None:
    if type(week) is not LoadWeek:
        _fail("Training input must be LoadWeek.")
    _season(week.season)
    _integer(week.gameweek, "gameweek", 1, 38)
    if (fit_cutoff is None) != (target_season is None):
        _fail("Training cutoff and target season must be supplied together.")
    if type(target_gameweeks) is not tuple:
        _fail("Target gameweeks must be immutable.")
    targets = tuple(_integer(value, "target gameweek", 1, 38) for value in target_gameweeks)
    if len(set(targets)) != len(targets):
        _fail("Duplicate target gameweek.")
    if target_season is None:
        if targets:
            _fail("Target gameweeks require their season.")
        return
    _season(target_season)
    if not targets:
        _fail("A nonempty target inventory is required.")
    if int(week.season[:4]) > int(target_season[:4]) or (
        week.season == target_season and week.gameweek >= min(targets)
    ):
        _fail("Target and future training weeks are excluded before label decoding.")
    if _clock(week.decision_at, "decision_at") >= _clock(fit_cutoff, "fit_cutoff"):
        _fail("Training input decision must precede fitting.")


def validate_training_load_week(
    row: TrainingLoadWeek,
    *,
    fit_cutoff: str | None = None,
    target_season: str | None = None,
    target_gameweeks: tuple[int, ...] = (),
) -> None:
    if type(row) is not TrainingLoadWeek:
        _fail("Training rows must be immutable TrainingLoadWeek values.")
    _training_guard(row.input, fit_cutoff, target_season, target_gameweeks)
    validate_load_week(row.input)
    if type(row.observed_states) is not tuple or len(row.observed_states) != len(
        row.input.fixtures
    ):
        _fail("Training requires complete final per-fixture state labels.")
    for state in row.observed_states:
        _integer(state, "observed state", 0, 6)
    settled = _clock(row.settled_at, "settled_at")
    latest = max(
        (_clock(fixture.kickoff, "kickoff") for fixture in row.input.fixtures),
        default=_clock(row.input.deadline_at, "deadline_at"),
    )
    if settled <= latest:
        _fail("Labels must settle beyond every fixture kickoff or BGW deadline.")
    if fit_cutoff is not None and settled >= _clock(fit_cutoff, "fit_cutoff"):
        _fail("Labels must settle strictly before fitting.")
    _sha(row.outcome_sha256, "outcome_sha256")


def load_input_digest(week: LoadWeek) -> str:
    validate_load_week(week)
    payload = json.dumps(
        {"version": LOAD_INPUT_VERSION, "input": asdict(week)},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_SOURCE_FIELDS = {
    "version",
    "season",
    "gameweek",
    "player_code",
    "decision_at",
    "deadline_at",
    "position",
    "published_at",
    "captured_at",
    "model_use_approved",
    "model_use_evidence_ref",
    "native_basis_sha256",
    "native_basis_kind",
    "native_basis_fit_cutoff",
    "native_basis_evidence_ref",
    "native_basis_version",
    "native_model_version",
    "native_joint_law_sha256",
    "coverage",
    "mapping",
    "calendar",
    "fixture_aliases",
    "matches",
    "club_matches",
    "upcoming_fixtures",
    "travel",
}
_COVERAGE_FIELDS = {
    "start_at",
    "end_at",
    "complete",
    "competition_ids",
    "expected_match_ids",
    "expected_club_match_ids",
    "expected_upcoming_fixture_ids",
    "evidence_ref",
}
_MAPPING_FIELDS = {
    "verified",
    "evidence_ref",
    "player_aliases",
    "club_memberships",
    "national_memberships",
}
_MEMBERSHIP_FIELDS = {"team_code", "valid_from", "valid_until", "evidence_ref"}
_PLAYER_ALIAS_FIELDS = {
    "provider_player_id",
    "player_code",
    "valid_from",
    "valid_until",
    "evidence_ref",
}
_CALENDAR_FIELDS = {"complete", "covered_gameweeks", "fixture_ids", "evidence_ref"}
_FIXTURE_ALIAS_FIELDS = {"alias", "canonical_fixture_id", "evidence_ref"}
_MATCH_FIELDS = {
    "fixture_id",
    "competition_id",
    "is_premier_league",
    "kickoff",
    "settled_at",
    "captured_at",
    "published_at",
    "provider_player_id",
    "registered_club_code",
    "team_kind",
    "team_code",
    "opponent_code",
    "is_home",
    "physical_minutes",
    "added_minutes",
    "extra_time_minutes",
    "physical_minutes_convention",
    "starts",
    "recorded_exit_at",
}
_CLUB_FIELDS = {
    "fixture_id",
    "competition_id",
    "is_premier_league",
    "kickoff",
    "captured_at",
    "published_at",
    "team_code",
    "opponent_code",
    "is_home",
    "recorded_end_at",
    "settled_at",
    "target_fpl_fixture_id",
}


def _publication(record: dict[str, Any], decision: datetime, capture_limit: datetime) -> None:
    captured = _clock(record["captured_at"], "record captured_at")
    published = _clock(record["published_at"], "record published_at")
    if not captured <= published < decision or captured > capture_limit:
        _fail("Record capture/archive publication must precede decision and bind snapshot capture.")


def _permission(document: dict[str, Any]) -> None:
    if not _boolean(document["model_use_approved"], "model_use_approved"):
        _fail("Explicit model-use admission receipt is required.")
    _text(document["model_use_evidence_ref"], "model_use_evidence_ref")


def _memberships(raw: object, name: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
    records = [_object(row, _MEMBERSHIP_FIELDS, name) for row in _list(raw, name)]
    if not records:
        _fail(f"{name} must cover the entire workload interval.")
    previous_end: datetime | None = None
    for index, row in enumerate(records):
        if row["team_code"] is not None:
            _integer(row["team_code"], "membership team_code")
        _text(row["evidence_ref"], "membership evidence_ref")
        opened = _clock(row["valid_from"], "membership valid_from")
        closed = (
            None
            if row["valid_until"] is None
            else _clock(row["valid_until"], "membership valid_until")
        )
        if closed is not None and opened >= closed:
            _fail("Membership interval must have positive length.")
        if index == 0 and opened > start:
            _fail("Membership coverage starts too late.")
        if index and (previous_end is None or opened != previous_end):
            _fail("Memberships require chronological gap-free nonoverlapping intervals.")
        previous_end = closed
    if previous_end is not None and previous_end <= end:
        _fail("Membership coverage must include decision_at.")
    return records


def _team_at(records: list[dict[str, Any]], instant: datetime) -> int | None:
    for row in records:
        opened = _clock(row["valid_from"], "valid_from")
        closed = None if row["valid_until"] is None else _clock(row["valid_until"], "valid_until")
        if opened <= instant and (closed is None or instant < closed):
            return cast(int | None, row["team_code"])
    _fail("A match has no temporal team membership.")


def _nullable_sum(rows: list[dict[str, Any]], field: str) -> float | None:
    values = [row[field] for row in rows]
    return None if any(value is None for value in values) else math.fsum(values)


def _travel_features(
    raw: object, decision: datetime, capture_limit: datetime, start: datetime, horizon: datetime
) -> list[float | None]:
    travel = _object(raw, set(TRAVEL_KINDS), "travel")
    values: list[float | None] = []
    group_fields = {"complete", "evidence_ref", "expected_ids", "records"}
    record_fields = {
        "id",
        "start_at",
        "end_at",
        "distance_km",
        "duration_hours",
        "captured_at",
        "published_at",
        "evidence_ref",
    }
    for kind in TRAVEL_KINDS:
        if travel[kind] is None:
            values.extend((None, None, None))
            continue
        group = _object(travel[kind], group_fields, f"{kind} travel")
        complete = _boolean(group["complete"], "travel complete")
        if complete or group["evidence_ref"] is not None:
            _text(group["evidence_ref"], "travel evidence_ref")
        expected = _strings(group["expected_ids"], "travel expected_ids")
        records: list[dict[str, Any]] = []
        ids: list[str] = []
        for raw_record in _list(group["records"], "travel records"):
            row = _object(raw_record, record_fields, "travel record")
            ids.append(_text(row["id"], "travel id"))
            _text(row["evidence_ref"], "travel record evidence_ref")
            _publication(row, decision, capture_limit)
            opened = _clock(row["start_at"], "travel start_at")
            closed = None if row["end_at"] is None else _clock(row["end_at"], "travel end_at")
            if closed is not None and closed < opened:
                _fail("Travel end precedes its start.")
            distance = _nullable_number(row["distance_km"], "travel distance_km")
            duration = _nullable_number(row["duration_hours"], "travel duration_hours")
            if kind == "actual":
                if (
                    not start <= opened < decision
                    or closed is None
                    or closed > _clock(row["captured_at"], "captured_at")
                ):
                    _fail("Actual travel requires recorded completed predecision itinerary clocks.")
            elif kind == "planned":
                if not decision <= opened <= horizon or (closed is not None and closed > horizon):
                    _fail("Planned travel must bind the declared future target horizon.")
            else:
                if not start <= opened <= horizon or closed is not None or duration is not None:
                    _fail("A venue-distance proxy cannot assert actual itinerary or duration.")
            if (
                duration is not None
                and closed is not None
                and not math.isclose(
                    duration, (closed - opened).total_seconds() / 3600, rel_tol=0, abs_tol=1e-9
                )
            ):
                _fail("Travel duration contradicts declared journey clocks.")
            records.append({"distance_km": distance, "duration_hours": duration})
        if len(set(ids)) != len(ids) or (complete and set(ids) != set(expected)):
            _fail("Travel inventory contains duplicates or lacks declared covered journeys.")
        if not complete:
            values.extend((None, None, None))
        else:
            values.extend(
                (
                    _nullable_sum(records, "distance_km"),
                    None
                    if kind == "venue_distance_proxy"
                    else _nullable_sum(records, "duration_hours"),
                    float(len(records)),
                )
            )
    return values


def read_load_snapshot(
    raw: bytes,
    *,
    sha256: str,
    season: str,
    gameweek: int,
    player_code: int,
    decision_at: str,
    deadline_at: str,
    native_fixtures: tuple[LoadFixture, ...],
    native_joint_states: tuple[tuple[int, ...], ...],
    native_joint_probabilities: tuple[float, ...],
    native_basis_sha256: str,
    required_competition_ids: tuple[str, ...],
) -> LoadWeek:
    """Parse only an explicitly admitted, complete and temporally bound snapshot."""
    _season(season)
    _integer(gameweek, "gameweek", 1, 38)
    _integer(player_code, "player_code")
    decision, deadline = _clock(decision_at, "decision_at"), _clock(deadline_at, "deadline_at")
    if decision >= deadline:
        _fail("Decision must precede deadline.")
    if (
        type(required_competition_ids) is not tuple
        or not required_competition_ids
        or len(set(required_competition_ids)) != len(required_competition_ids)
    ):
        _fail("Callers must declare a unique nonempty complete competition inventory.")
    for competition in required_competition_ids:
        _text(competition, "required competition")
    document = _object(_json(raw, sha256), _SOURCE_FIELDS, "snapshot")
    if document["version"] != RAW_LOAD_SNAPSHOT_VERSION:
        _fail("Unknown workload snapshot version.")
    if (
        _season(document["season"]),
        _integer(document["gameweek"], "gameweek", 1, 38),
        _integer(document["player_code"], "player_code"),
    ) != (season, gameweek, player_code):
        _fail("Snapshot identity does not match requested player/week.")
    if (
        _clock(document["decision_at"], "decision_at") != decision
        or _clock(document["deadline_at"], "deadline_at") != deadline
    ):
        _fail("Snapshot decision/deadline binding mismatch.")
    captured = _clock(document["captured_at"], "captured_at")
    if not captured <= _clock(document["published_at"], "published_at") < decision:
        _fail("Snapshot capture/archive publication must precede its decision.")
    _permission(document)
    coverage = _object(document["coverage"], _COVERAGE_FIELDS, "coverage")
    start = decision - timedelta(days=28)
    if (
        _clock(coverage["start_at"], "coverage start_at") != start
        or _clock(coverage["end_at"], "coverage end_at") != decision
        or not _boolean(coverage["complete"], "coverage complete")
    ):
        _fail("Complete exact 28-day coverage is required.")
    competitions = _strings(coverage["competition_ids"], "competition_ids")
    if set(competitions) != set(required_competition_ids):
        _fail("Snapshot competition coverage differs from required scope.")
    _text(coverage["evidence_ref"], "coverage evidence_ref")
    mapping = _object(document["mapping"], _MAPPING_FIELDS, "mapping")
    if not _boolean(mapping["verified"], "mapping verified"):
        _fail("Verified persistent player mapping is required.")
    _text(mapping["evidence_ref"], "mapping evidence_ref")
    club_memberships = _memberships(
        mapping["club_memberships"], "club memberships", start, decision
    )
    if any(row["team_code"] is None for row in club_memberships):
        _fail("Registered club membership must be explicit throughout coverage.")
    national_memberships = _memberships(
        mapping["national_memberships"], "national memberships", start, decision
    )
    current_club = _team_at(club_memberships, decision)
    aliases: list[dict[str, Any]] = []
    for item in _list(mapping["player_aliases"], "player_aliases"):
        alias = _object(item, _PLAYER_ALIAS_FIELDS, "player alias")
        _text(alias["provider_player_id"], "provider_player_id")
        _text(alias["evidence_ref"], "player alias evidence_ref")
        if _integer(alias["player_code"], "player alias player_code") != player_code:
            _fail("Player alias maps to another persistent player.")
        opened = _clock(alias["valid_from"], "alias valid_from")
        closed = (
            None
            if alias["valid_until"] is None
            else _clock(alias["valid_until"], "alias valid_until")
        )
        if closed is not None and opened >= closed:
            _fail("Player alias interval is empty.")
        for previous in aliases:
            if previous["provider_player_id"] != alias["provider_player_id"]:
                continue
            prior_open = _clock(previous["valid_from"], "valid_from")
            prior_close = (
                datetime.max.replace(tzinfo=UTC)
                if previous["valid_until"] is None
                else _clock(previous["valid_until"], "valid_until")
            )
            if opened < prior_close and (closed is None or closed > prior_open):
                _fail("Overlapping duplicate player aliases are refused.")
        aliases.append(alias)
    if not aliases:
        _fail("At least one persistent provider player mapping is required.")
    fixture_aliases: dict[str, str] = {}
    for item in _list(document["fixture_aliases"], "fixture aliases"):
        row = _object(item, _FIXTURE_ALIAS_FIELDS, "fixture alias")
        fixture_alias = _text(row["alias"], "fixture alias")
        canonical_id = _text(row["canonical_fixture_id"], "canonical_fixture_id")
        _text(row["evidence_ref"], "fixture alias evidence_ref")
        if fixture_alias in fixture_aliases or fixture_alias == canonical_id:
            _fail("Duplicate or identity fixture aliases are refused.")
        fixture_aliases[fixture_alias] = canonical_id
    if set(fixture_aliases) & set(fixture_aliases.values()):
        _fail("Fixture aliases cannot form chains or cycles.")

    def canonical(value: object) -> str:
        identity = _text(value, "fixture_id")
        return fixture_aliases.get(identity, identity)

    matches: dict[str, dict[str, Any]] = {}
    for item in _list(document["matches"], "matches"):
        row = dict(_object(item, _MATCH_FIELDS, "match"))
        identity = canonical(row["fixture_id"])
        row["fixture_id"] = identity
        kickoff = _clock(row["kickoff"], "match kickoff")
        if not start <= kickoff < decision:
            _fail("Workload match lies outside declared interval.")
        _publication(row, decision, captured)
        settled = _clock(row["settled_at"], "match settled_at")
        if not kickoff < settled <= _clock(row["captured_at"], "captured_at"):
            _fail("Physical workload must settle after kickoff and before capture.")
        if _text(row["competition_id"], "competition_id") not in competitions:
            _fail("Match competition is outside admitted coverage.")
        _boolean(row["is_premier_league"], "is_premier_league")
        registered = _integer(row["registered_club_code"], "registered_club_code")
        if registered != _team_at(club_memberships, kickoff):
            _fail("Match registered club contradicts temporal transfer mapping.")
        team = _integer(row["team_code"], "team_code")
        if row["team_kind"] == "club":
            if team != registered:
                _fail("Club participation must bind the registered club at kickoff.")
        elif row["team_kind"] == "national":
            if team != _team_at(national_memberships, kickoff) or row["is_premier_league"]:
                _fail("National participation requires explicit temporal national-team mapping.")
        else:
            _fail("Unknown participating team kind.")
        if team == _integer(row["opponent_code"], "opponent_code"):
            _fail("Match opponent cannot equal participating team.")
        _integer(row["is_home"], "is_home", 0, 1)
        provider_id = _text(row["provider_player_id"], "provider_player_id")
        if not any(
            alias["provider_player_id"] == provider_id
            and _clock(alias["valid_from"], "valid_from") <= kickoff
            and (
                alias["valid_until"] is None
                or kickoff < _clock(alias["valid_until"], "valid_until")
            )
            for alias in aliases
        ):
            _fail("Match player lacks an explicit temporal persistent mapping.")
        if row["physical_minutes_convention"] != "includes_added_and_extra_time":
            _fail("Physical minutes require explicit added/extra-time convention.")
        for field in ("physical_minutes", "added_minutes", "extra_time_minutes"):
            row[field] = _nullable_number(row[field], field)
        physical = row["physical_minutes"]
        added, extra = row["added_minutes"], row["extra_time_minutes"]
        if physical is not None and (
            physical > (settled - kickoff).total_seconds() / 60
            or (added is not None and added > physical)
            or (extra is not None and extra > physical)
            or (added is not None and extra is not None and added + extra > physical)
        ):
            _fail("Physical added/extra-time exposure contradicts total exposure.")
        if row["starts"] is not None:
            _integer(row["starts"], "recorded starts", 0, 1)
            if physical == 0 and row["starts"] == 1:
                _fail("A recorded starter cannot have zero physical exposure.")
        if row["recorded_exit_at"] is not None:
            exited = _clock(row["recorded_exit_at"], "recorded_exit_at")
            if physical is None or physical == 0 or not kickoff < exited <= settled:
                _fail("Recorded exit requires known positive exposure and settled chronology.")
            if physical > (exited - kickoff).total_seconds() / 60:
                _fail("Recorded player exit cannot precede their physical exposure duration.")
        previous_match = matches.get(identity)
        if previous_match is not None and previous_match != row:
            _fail("Conflicting aliased duplicate player fixture.")
        matches[identity] = row
    expected_matches = _strings(coverage["expected_match_ids"], "expected_match_ids")
    if set(matches) != set(expected_matches):
        _fail("Player workload lacks its complete declared expected fixture inventory.")
    if set(fixture_aliases.values()) - set(expected_matches):
        _fail("Fixture alias points outside expected player fixture inventory.")

    def club_rows(raw_rows: object, *, future: bool) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in _list(raw_rows, "club fixtures"):
            row = _object(item, _CLUB_FIELDS, "club fixture")
            identity = canonical(row["fixture_id"])
            if identity in result:
                _fail("Duplicate club calendar fixture.")
            kickoff = _clock(row["kickoff"], "club kickoff")
            if (not future and not start <= kickoff < decision) or (future and kickoff < decision):
                _fail("Club calendar fixture lies outside its declared temporal interval.")
            _publication(row, decision, captured)
            if _integer(row["team_code"], "club team_code") != current_club:
                _fail("Club calendar must bind the native currently registered club.")
            if current_club == _integer(row["opponent_code"], "opponent_code"):
                _fail("Club opponent cannot equal club.")
            _integer(row["is_home"], "is_home", 0, 1)
            _boolean(row["is_premier_league"], "is_premier_league")
            if _text(row["competition_id"], "competition_id") not in competitions:
                _fail("Club fixture competition lacks admitted coverage.")
            if future:
                if row["recorded_end_at"] is not None or row["settled_at"] is not None:
                    _fail("Future calendar cannot contain an actual match end or settlement.")
            else:
                settled = _clock(row["settled_at"], "club settled_at")
                if not kickoff < settled <= _clock(row["captured_at"], "captured_at"):
                    _fail("Past club fixtures must settle after kickoff and before capture.")
            if row["recorded_end_at"] is not None and not kickoff < _clock(
                row["recorded_end_at"], "recorded_end_at"
            ) <= _clock(row["settled_at"], "settled_at"):
                _fail("Club end clock must be recorded after kickoff and no later than settlement.")
            if identity in matches:
                player = matches[identity]
                for field in (
                    "competition_id",
                    "is_premier_league",
                    "team_code",
                    "opponent_code",
                    "is_home",
                ):
                    if player["team_kind"] != "club" or player[field] != row[field]:
                        _fail("Paired player/club fixture identities conflict.")
                if _clock(player["kickoff"], "kickoff") != kickoff:
                    _fail("Paired player/club kickoff clocks conflict.")
            result[identity] = row
        return result

    clubs = club_rows(document["club_matches"], future=False)
    upcoming = club_rows(document["upcoming_fixtures"], future=True)
    if set(clubs) != set(
        _strings(coverage["expected_club_match_ids"], "expected_club_match_ids")
    ) or set(upcoming) != set(
        _strings(coverage["expected_upcoming_fixture_ids"], "expected_upcoming_fixture_ids")
    ):
        _fail("Club calendar lacks its complete expected settled or upcoming inventory.")
    if set(clubs) & set(upcoming):
        _fail("A club fixture cannot be both settled and future.")
    calendar = _object(document["calendar"], _CALENDAR_FIELDS, "calendar")
    covered = tuple(
        _integer(value, "covered gameweek", 1, 38)
        for value in _list(calendar["covered_gameweeks"], "covered_gameweeks")
    )
    if [
        _integer(value, "calendar fixture_id")
        for value in _list(calendar["fixture_ids"], "fixture_ids")
    ] != [fixture.fixture_id for fixture in native_fixtures]:
        _fail("Native complete calendar fixture inventory mismatch.")
    if any(fixture.club_code != current_club for fixture in native_fixtures):
        _fail("Native fixtures contradict current registered club.")
    horizon = max(
        (_clock(fixture.kickoff, "kickoff") for fixture in native_fixtures), default=deadline
    )
    if any(_clock(row["kickoff"], "kickoff") > horizon for row in upcoming.values()):
        _fail("Future calendar exceeds the target horizon.")
    target_by_id = {fixture.fixture_id: fixture for fixture in native_fixtures}
    covered_targets: set[int] = set()
    for future, calendar_rows in ((False, clubs), (True, upcoming)):
        for row in calendar_rows.values():
            target_id = row["target_fpl_fixture_id"]
            if target_id is None:
                if future and any(
                    _clock(row["kickoff"], "kickoff") == _clock(fixture.kickoff, "kickoff")
                    for fixture in native_fixtures
                ):
                    _fail("A future target kickoff requires its explicit native fixture crosswalk.")
                continue
            target_id = _integer(target_id, "target_fpl_fixture_id")
            if not future or target_id not in target_by_id or target_id in covered_targets:
                _fail(
                    "Target calendar crosswalk must cover each native future fixture exactly once."
                )
            fixture = target_by_id[target_id]
            if not row["is_premier_league"] or (
                _clock(row["kickoff"], "kickoff"),
                row["team_code"],
                row["opponent_code"],
                row["is_home"],
            ) != (
                _clock(fixture.kickoff, "kickoff"),
                fixture.club_code,
                fixture.opponent_code,
                fixture.is_home,
            ):
                _fail("Future target crosswalk contradicts native fixture identity.")
            covered_targets.add(target_id)
    if covered_targets != set(target_by_id):
        _fail("Future club calendar lacks a native target fixture crosswalk.")
    feature_values: list[float | None] = []
    for days in (7, 14, 28):
        bound = decision - timedelta(days=days)
        rows = [row for row in matches.values() if _clock(row["kickoff"], "kickoff") >= bound]
        non_pl = [row for row in rows if not row["is_premier_league"]]
        feature_values.extend(
            (
                _nullable_sum(rows, "physical_minutes"),
                _nullable_sum(rows, "added_minutes"),
                _nullable_sum(rows, "extra_time_minutes"),
                _nullable_sum(rows, "starts"),
                float(sum(row["physical_minutes"] is not None for row in rows)),
                float(sum(row["physical_minutes"] is None for row in rows)),
                float(sum(row["starts"] is not None for row in rows)),
                float(sum(row["starts"] is None for row in rows)),
                float(sum(_clock(row["kickoff"], "kickoff") >= bound for row in clubs.values())),
                _nullable_sum(non_pl, "physical_minutes"),
                _nullable_sum(non_pl, "starts"),
            )
        )
    positive = [
        row
        for row in matches.values()
        if row["physical_minutes"] is not None and row["physical_minutes"] > 0
    ]
    unknown = any(row["physical_minutes"] is None for row in matches.values())
    latest_player = max(positive, key=lambda row: _clock(row["kickoff"], "kickoff"), default=None)
    latest_club = max(
        clubs.values(), key=lambda row: _clock(row["kickoff"], "kickoff"), default=None
    )

    def elapsed(row: dict[str, Any] | None, field: str) -> float | None:
        if row is None or row[field] is None:
            return None
        return (decision - _clock(row[field], field)).total_seconds() / 3600

    feature_values.extend(
        (
            None if unknown else elapsed(latest_player, "recorded_exit_at"),
            elapsed(latest_club, "recorded_end_at"),
            None if unknown else elapsed(latest_player, "kickoff"),
            elapsed(latest_club, "kickoff"),
            float(
                sum(
                    row["target_fpl_fixture_id"] is None
                    and _clock(row["kickoff"], "kickoff") < horizon
                    for row in upcoming.values()
                )
            ),
        )
    )
    for index in range(3):
        if index >= len(native_fixtures):
            feature_values.extend((None, None))
            continue
        target = _clock(native_fixtures[index].kickoff, "kickoff")
        past = [
            _clock(row["kickoff"], "kickoff")
            for row in (*clubs.values(), *upcoming.values())
            if _clock(row["kickoff"], "kickoff") < target
        ]
        past.extend(_clock(fixture.kickoff, "kickoff") for fixture in native_fixtures[:index])
        feature_values.extend(
            (
                None if not past else (target - max(past)).total_seconds() / 3600,
                float(
                    sum(
                        not row["is_premier_league"] and _clock(row["kickoff"], "kickoff") < target
                        for row in upcoming.values()
                    )
                ),
            )
        )
    feature_values.extend(_travel_features(document["travel"], decision, captured, start, horizon))
    if _sha(document["native_basis_sha256"], "native_basis_sha256") != _sha(
        native_basis_sha256, "native_basis_sha256"
    ):
        _fail("Native basis hash differs from supplied causal native law.")
    week = LoadWeek(
        season,
        gameweek,
        player_code,
        _utc(decision_at, "decision_at"),
        _utc(deadline_at, "deadline_at"),
        _text(document["position"], "position"),
        native_fixtures,
        native_joint_states,
        native_joint_probabilities,
        native_basis_sha256,
        _text(document["native_basis_kind"], "native_basis_kind"),
        _utc(document["native_basis_fit_cutoff"], "native_basis_fit_cutoff"),
        _text(document["native_basis_evidence_ref"], "native_basis_evidence_ref"),
        sha256,
        tuple(feature_values),
        LOAD_FEATURE_NAMES,
        _text(document["native_basis_version"], "native_basis_version"),
        start.isoformat().replace("+00:00", "Z"),
        decision.isoformat().replace("+00:00", "Z"),
        competitions,
        _text(coverage["evidence_ref"], "coverage evidence_ref"),
        _text(mapping["evidence_ref"], "mapping evidence_ref"),
        _boolean(calendar["complete"], "calendar complete"),
        covered,
        _text(calendar["evidence_ref"], "calendar evidence_ref"),
        _text(document["native_model_version"], "native_model_version"),
        _sha(document["native_joint_law_sha256"], "native_joint_law_sha256"),
    )
    validate_load_week(week)
    return week


_OUTCOME_FIELDS = {
    "version",
    "season",
    "gameweek",
    "player_code",
    "input_sha256",
    "settled_at",
    "captured_at",
    "published_at",
    "model_use_approved",
    "model_use_evidence_ref",
    "mapping_verified",
    "mapping_evidence_ref",
    "calendar_complete",
    "covered_gameweeks",
    "fixture_ids",
    "observations",
}
_OBSERVATION_FIELDS = {
    "fixture_id",
    "kickoff",
    "club_code",
    "opponent_code",
    "is_home",
    "minutes",
    "starts",
    "state",
}


def read_load_outcomes(
    raw: bytes,
    *,
    sha256: str,
    week: LoadWeek,
    fit_cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
) -> TrainingLoadWeek:
    """Guard protected/target/future headers before any outcome byte decoding."""
    _training_guard(week, fit_cutoff, target_season, target_gameweeks)
    validate_load_week(week)
    document = _object(_json(raw, sha256), _OUTCOME_FIELDS, "outcomes")
    if document["version"] != RAW_LOAD_OUTCOME_VERSION:
        _fail("Unknown workload outcome version.")
    if (
        _season(document["season"]),
        _integer(document["gameweek"], "gameweek", 1, 38),
        _integer(document["player_code"], "player_code"),
    ) != (week.season, week.gameweek, week.player_code):
        _fail("Outcome player/week binding mismatch.")
    if _sha(document["input_sha256"], "input_sha256") != load_input_digest(week):
        _fail("Outcome input digest does not bind this captured native workload basis.")
    _permission(document)
    if not _boolean(document["mapping_verified"], "mapping_verified"):
        _fail("Outcomes need verified persistent player mapping.")
    _text(document["mapping_evidence_ref"], "mapping_evidence_ref")
    if not _boolean(document["calendar_complete"], "calendar_complete"):
        _fail("Outcome calendar must be complete including BGW.")
    covered = tuple(
        _integer(value, "covered gameweek", 1, 38)
        for value in _list(document["covered_gameweeks"], "covered_gameweeks")
    )
    if covered != week.covered_gameweeks or [
        _integer(value, "fixture_id") for value in _list(document["fixture_ids"], "fixture_ids")
    ] != [fixture.fixture_id for fixture in week.fixtures]:
        _fail("Outcome calendar inventory differs from its input.")
    settled = _clock(document["settled_at"], "settled_at")
    captured = _clock(document["captured_at"], "captured_at")
    published = _clock(document["published_at"], "published_at")
    if not settled <= captured <= published < _clock(fit_cutoff, "fit_cutoff"):
        _fail("Outcome finalization/capture/archive publication must precede fitting.")
    observations = _list(document["observations"], "observations")
    if len(observations) != len(week.fixtures):
        _fail("Outcomes must include every target fixture.")
    states: list[int] = []
    for item, fixture in zip(observations, week.fixtures, strict=True):
        row = _object(item, _OBSERVATION_FIELDS, "observation")
        identity = (
            _integer(row["fixture_id"], "fixture_id"),
            _clock(row["kickoff"], "kickoff"),
            _integer(row["club_code"], "club_code"),
            _integer(row["opponent_code"], "opponent_code"),
            _integer(row["is_home"], "is_home", 0, 1),
        )
        if identity != (
            fixture.fixture_id,
            _clock(fixture.kickoff, "kickoff"),
            fixture.club_code,
            fixture.opponent_code,
            fixture.is_home,
        ):
            _fail("Outcome fixture identity differs from its native input.")
        minutes = _integer(row["minutes"], "FPL credited minutes", 0, 120)
        starts = _integer(row["starts"], "recorded FPL starts", 0, 1)
        state = _integer(row["state"], "state", 0, 6)
        if minutes == 0:
            if starts or state:
                _fail("Zero-minute FPL label contradicts recorded start or state.")
            expected_state = 0
        else:
            expected_state = (1 if minutes < 60 else (2 if minutes < 90 else 3)) + (
                0 if starts else 3
            )
        if state != expected_state:
            _fail("FPL minutes and recorded starts contradict the supplied state index.")
        states.append(state)
    result = TrainingLoadWeek(
        week, tuple(states), _utc(document["settled_at"], "settled_at"), sha256
    )
    validate_training_load_week(
        result,
        fit_cutoff=fit_cutoff,
        target_season=target_season,
        target_gameweeks=target_gameweeks,
    )
    return result
