"""Observed non-PL records, separate from complete all-competition workload.

Readers check supplied bytes and declared clocks, not remote source authenticity.
Reported minutes are never interpreted as physical duration or complete workload.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from typing import Any, TypeVar

from squadopt.features.football_load_inputs import (
    POSITIONS,
    LoadFixture,
    _clock,
    _integer,
    _json,
    _list,
    _number,
    _object,
    _sha,
    _text,
    _validate_native_law,
    native_joint_law_digest,
)

INPUT_VERSION = "football_observed_non_pl_load_input_v1"
OUTCOME_VERSION = "football_observed_non_pl_load_outcome_v1"
FEATURE_VERSION = "observed_non_pl_reported_records_v1"
COVERAGE_KIND = "observed_provider_player_records_not_complete_history"
MINUTE_DEFINITION = "provider_reported_minutes_not_physical_elapsed"
CAPTURED_NATIVE_VERSION = "captured_snapshot_v1"
FEATURE_NAMES = tuple(
    f"observed_non_pl_{name}_{days}d"
    for days in (7, 14, 28)
    for name in (
        "record_count",
        "known_minute_count",
        "unknown_minute_count",
        "known_reported_minute_sum",
        "known_start_count",
        "unknown_start_count",
        "confirmed_start_sum",
        "hours_since_latest_observed_positive_kickoff",
    )
)


@dataclass(frozen=True, slots=True)
class ObservedLoadRecord:
    fixture: str
    competition: str
    player_code: int
    kickoff: str
    reported_minutes: float | None
    confirmed_start: bool | None
    completed_by: str
    completion_revision: str
    completion_sha256: str
    completion_evidence_ref: str
    source_sha256: str
    source_line: int
    is_premier_league: bool = False


@dataclass(frozen=True, slots=True)
class ObservedLoadProvenance:
    kind: str
    source_revision: str
    source_recorded_at: str
    retrieved_at: str
    generated_at: str
    feature_cutoff: str
    source_hashes: tuple[tuple[str, str], ...]
    implementation_sha256: str
    model_use_approved: bool
    model_use_evidence_ref: str


@dataclass(frozen=True, slots=True)
class ObservedLoadNativeBasis:
    fixtures: tuple[LoadFixture, ...]
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    law_sha256: str
    basis_sha256: str
    model_version: str
    fit_information_cutoff: str
    history_completed_by: str
    original_revision: str
    recorded_at: str
    retrieved_at: str
    calendar_complete: bool
    covered_gameweeks: tuple[int, ...]
    calendar_sha256: str
    evidence_ref: str


@dataclass(frozen=True, slots=True)
class ObservedLoadCapturedNativeBasis:
    fixtures: tuple[LoadFixture, ...]
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    law_sha256: str
    basis_sha256: str
    model_version: str
    fit_information_cutoff: str
    history_completed_by: str
    source_snapshot_id: str
    source_fingerprint: str
    recorded_at: str
    retrieved_at: str
    native_generated_at: str
    calendar_complete: bool
    covered_gameweeks: tuple[int, ...]
    calendar_sha256: str
    evidence_ref: str
    version: str = CAPTURED_NATIVE_VERSION


@dataclass(frozen=True, slots=True)
class ObservedLoadWeek:
    season: str
    gameweek: int
    player_code: int
    position: str
    decision_at: str
    deadline_at: str
    competitions: tuple[str, ...]
    records: tuple[ObservedLoadRecord, ...]
    native: ObservedLoadNativeBasis | ObservedLoadCapturedNativeBasis
    provenance: ObservedLoadProvenance
    version: str = INPUT_VERSION
    coverage_kind: str = COVERAGE_KIND
    minute_definition: str = MINUTE_DEFINITION


@dataclass(frozen=True, slots=True)
class ObservedLoadOutcome:
    week: ObservedLoadWeek
    input_sha256: str
    observed_states: tuple[int, ...]
    credited_minutes: tuple[int, ...]
    starts: tuple[int, ...]
    settled_at: str
    retrieved_at: str
    generated_at: str
    source_sha256: str
    evidence_ref: str
    version: str = OUTCOME_VERSION


def season_year(value: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
        raise ValueError("Observed load season requires YYYY-YY.")
    year = int(value[:4])
    if year < 2000 or int(value[-2:]) != (year + 1) % 100:
        raise ValueError("Observed load season must be consecutive.")
    return year


def validate_targets(season: str, gameweeks: tuple[int, ...]) -> None:
    season_year(season)
    if (
        type(gameweeks) is not tuple
        or not gameweeks
        or any(type(gw) is not int or not 1 <= gw <= 38 for gw in gameweeks)
        or tuple(sorted(set(gameweeks))) != gameweeks
    ):
        raise ValueError("Observed load targets need ordered unique gameweeks in 1..38.")


def _release(season: str, allow_released_2025_26: bool) -> None:
    season_year(season)
    if type(allow_released_2025_26) is not bool:
        raise ValueError("Observed load released-season option must be Boolean.")
    if season == "2025-26" and not allow_released_2025_26:
        raise ValueError("Observed load 2025-26 requires explicit released-season opt-in.")


def _revision(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError("Observed load public revision must be an exact Git identifier.")


def _hashes(provenance: ObservedLoadProvenance) -> set[str]:
    if type(provenance.source_hashes) is not tuple or not provenance.source_hashes:
        raise ValueError("Observed load requires immutable named source hashes.")
    names: set[str] = set()
    hashes: set[str] = set()
    for pair in provenance.source_hashes:
        if type(pair) is not tuple or len(pair) != 2:
            raise ValueError("Observed load source hashes need name/digest pairs.")
        name, digest = pair
        _text(name, "source name")
        _sha(digest, "source digest")
        if name in names:
            raise ValueError("Observed load source names must be unique.")
        names.add(name)
        hashes.add(digest)
    return hashes


def validate_observed_load_week(
    week: ObservedLoadWeek, *, allow_released_2025_26: bool = False
) -> None:
    """Validate scope, historical completion evidence and complete native PL support."""
    if type(week) is not ObservedLoadWeek:
        raise ValueError("Observed load requires its separate frozen week type.")
    _release(week.season, allow_released_2025_26)
    if (week.version, week.coverage_kind, week.minute_definition) != (
        INPUT_VERSION,
        COVERAGE_KIND,
        MINUTE_DEFINITION,
    ):
        raise ValueError("Observed load scope/version/minute definition mismatch.")
    _integer(week.gameweek, "gameweek", 1, 38)
    _integer(week.player_code, "player code")
    if week.position not in POSITIONS:
        raise ValueError("Observed load needs its native FPL position.")
    decision = _clock(week.decision_at, "decision")
    deadline = _clock(week.deadline_at, "deadline")
    if not decision < deadline:
        raise ValueError("Observed load decision must precede deadline.")
    year = season_year(week.season)
    season_start = datetime(year, 7, 1, tzinfo=decision.tzinfo)
    season_end = datetime(year + 1, 7, 1, tzinfo=decision.tzinfo)
    if not season_start <= decision < deadline < season_end:
        raise ValueError("Observed load decision/deadline lie outside the declared season.")
    if type(week.competitions) is not tuple or not week.competitions:
        raise ValueError("Observed load needs an explicit observed competition scope.")
    for competition in week.competitions:
        _text(competition, "competition")
        if competition.lower().replace("_", "-").replace(" ", "-") in (
            "prem",
            "pl",
            "epl",
            "premier-league",
        ):
            raise ValueError("Observed non-PL scope cannot include Premier League.")
    if len(set(week.competitions)) != len(week.competitions):
        raise ValueError("Observed load competition scope contains duplicates.")
    p = week.provenance
    if type(p) is not ObservedLoadProvenance:
        raise ValueError("Observed load provenance requires its frozen type.")
    _revision(p.source_revision)
    recorded = _clock(p.source_recorded_at, "source recorded")
    retrieved = _clock(p.retrieved_at, "source retrieved")
    generated = _clock(p.generated_at, "source generated")
    feature = _clock(p.feature_cutoff, "feature cutoff")
    if not recorded <= retrieved <= generated or feature > decision:
        raise ValueError("Observed load source/feature chronology is inconsistent.")
    if p.kind == "prospective":
        if not generated <= feature:
            raise ValueError("Prospective observed load must be prepared before feature use.")
    elif p.kind == "public_revision_replay":
        if not decision < retrieved:
            raise ValueError("Replayed observed load must retain actual later acquisition.")
    else:
        raise ValueError("Unknown observed load acquisition policy.")
    hashes = _hashes(p)
    _sha(p.implementation_sha256, "implementation digest")
    if p.model_use_approved is not True:
        raise ValueError("Observed load requires declared operator source-use approval.")
    _text(p.model_use_evidence_ref, "operator source-use evidence")
    native = week.native
    if type(native) not in (ObservedLoadNativeBasis, ObservedLoadCapturedNativeBasis):
        raise ValueError("Observed load requires a separate native basis.")
    _validate_native_law(native.fixtures, native.states, native.probabilities, deadline=deadline)
    if native.calendar_complete is not True:
        raise ValueError("Observed load still requires a complete native PL calendar.")
    validate_targets(week.season, native.covered_gameweeks)
    if week.gameweek not in native.covered_gameweeks:
        raise ValueError("Native calendar does not cover this observed-load week.")
    if any(not season_start <= _clock(f.kickoff, "kickoff") < season_end for f in native.fixtures):
        raise ValueError("Native fixture lies outside its declared season.")
    for digest in (native.basis_sha256, native.calendar_sha256):
        _sha(digest, "native source digest")
        if digest not in hashes:
            raise ValueError("Native source digest lacks its source manifest binding.")
    if native.law_sha256 != native_joint_law_digest(
        native.fixtures, native.states, native.probabilities
    ):
        raise ValueError("Observed load native joint-law digest mismatch.")
    _text(native.model_version, "native model version")
    if re.fullmatch(r"[a-z][a-z0-9_]*_v[0-9]+", native.model_version) is None:
        raise ValueError("Native model needs an exact versioned identifier.")
    native_recorded = _clock(native.recorded_at, "native revision recorded")
    native_retrieved = _clock(native.retrieved_at, "native retrieved")
    native_fit = _clock(native.fit_information_cutoff, "native fit information cutoff")
    if isinstance(native, ObservedLoadCapturedNativeBasis):
        if native.version != CAPTURED_NATIVE_VERSION or p.kind != "prospective":
            raise ValueError("Captured native basis requires its prospective source variant.")
        _sha(native.source_fingerprint, "native snapshot fingerprint")
        expected_id = (
            "fpl-live-"
            + native_recorded.strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + native.source_fingerprint[:12]
        )
        if native.source_snapshot_id != expected_id or native.source_fingerprint not in hashes:
            raise ValueError("Captured native snapshot identity lacks its source binding.")
        native_generated = _clock(native.native_generated_at, "native generation")
        if not (
            native_recorded <= native_retrieved <= native_generated <= generated <= feature
            and native_fit <= native_generated
        ):
            raise ValueError("Captured native generation is outside its source chronology.")
    else:
        _revision(native.original_revision)
    if not (
        _clock(native.history_completed_by, "native history completion") < native_fit <= feature
        and native_recorded <= feature
        and native_recorded <= native_retrieved <= generated
    ):
        raise ValueError("Observed load native history/revision chronology is inconsistent.")
    if p.kind == "public_revision_replay" and not decision < native_retrieved:
        raise ValueError("Replayed native basis must retain its later retrieval clock.")
    if p.kind == "prospective" and native_retrieved > feature:
        raise ValueError("Prospective native basis was retrieved after feature use.")
    _text(native.evidence_ref, "native basis evidence")
    if type(week.records) is not tuple or len(week.records) > 4096:
        raise ValueError("Observed records need bounded immutable support.")
    identities: set[tuple[str, str]] = set()
    for row in week.records:
        if type(row) is not ObservedLoadRecord:
            raise ValueError("Observed records require their frozen type.")
        _text(row.fixture, "observed fixture")
        _text(row.competition, "observed competition")
        if row.competition not in week.competitions or row.is_premier_league is not False:
            raise ValueError("Observed record lies outside the declared non-PL scope.")
        if type(row.player_code) is not int or row.player_code != week.player_code:
            raise ValueError("Observed record does not bind the persistent person.")
        key = row.competition, row.fixture
        if key in identities:
            raise ValueError("Duplicate observed player-match record.")
        identities.add(key)
        kickoff = _clock(row.kickoff, "observed kickoff")
        completed = _clock(row.completed_by, "original finished observation bound")
        if (
            not decision - timedelta(days=28) <= kickoff < completed < feature
            or completed > recorded
        ):
            raise ValueError("Observed record lacks prior completed 28-day exposure.")
        _revision(row.completion_revision)
        _text(row.completion_evidence_ref, "original finished revision evidence")
        for digest in (row.source_sha256, row.completion_sha256):
            _sha(digest, "observed record source digest")
            if digest not in hashes:
                raise ValueError("Observed record source lacks manifest binding.")
        _integer(row.source_line, "source line")
        if (
            row.reported_minutes is not None
            and _number(row.reported_minutes, "reported minutes") > 240
        ):
            raise ValueError("Reported minutes exceed bounded source support.")
        if row.confirmed_start is not None and type(row.confirmed_start) is not bool:
            raise ValueError("Observed start is Boolean or unknown.")


def observed_load_features(week: ObservedLoadWeek) -> tuple[float | None, ...]:
    """Summarize a validated week; an absent record is never a nonappearance."""
    decision = _clock(week.decision_at, "decision")
    result: list[float | None] = []
    for days in (7, 14, 28):
        rows = [
            r
            for r in week.records
            if _clock(r.kickoff, "kickoff") >= decision - timedelta(days=days)
        ]
        minutes = [float(r.reported_minutes) for r in rows if r.reported_minutes is not None]
        starts = [r.confirmed_start for r in rows if r.confirmed_start is not None]
        positive = [r for r in rows if r.reported_minutes is not None and r.reported_minutes > 0]
        latest = max((_clock(r.kickoff, "kickoff") for r in positive), default=None)
        result.extend(
            (
                float(len(rows)),
                float(len(minutes)),
                float(len(rows) - len(minutes)),
                math.fsum(minutes) if minutes else None,
                float(len(starts)),
                float(len(rows) - len(starts)),
                float(sum(starts)) if starts else None,
                (decision - latest).total_seconds() / 3600 if latest is not None else None,
            )
        )
    return tuple(result)


def observed_load_digest(week: ObservedLoadWeek) -> str:
    return hashlib.sha256(
        json.dumps(asdict(week), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def validate_observed_load_header(
    row: ObservedLoadOutcome,
    *,
    cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
    allow_released_2025_26: bool = False,
) -> None:
    """No observed state, minutes or start labels are accessed by this preflight."""
    validate_targets(target_season, target_gameweeks)
    if type(row) is not ObservedLoadOutcome or type(row.week) is not ObservedLoadWeek:
        raise ValueError("Observed load training requires its separate frozen outcome type.")
    week = row.week
    _release(week.season, allow_released_2025_26)
    if season_year(week.season) > season_year(target_season) or (
        week.season == target_season and week.gameweek >= min(target_gameweeks)
    ):
        raise ValueError("Observed load target and later training weeks are excluded.")
    validate_observed_load_week(week, allow_released_2025_26=allow_released_2025_26)
    fit = _clock(cutoff, "fit cutoff")
    if (
        not _clock(week.decision_at, "decision") < fit
        or _clock(week.provenance.generated_at, "generation") >= fit
    ):
        raise ValueError("Observed load input must be prepared before fitting.")
    if row.version != OUTCOME_VERSION:
        raise ValueError("Unknown observed load outcome version.")
    if row.input_sha256 != observed_load_digest(week):
        raise ValueError("Observed load outcome input digest mismatch.")
    settled = _clock(row.settled_at, "outcome settlement")
    if not (
        _clock(week.deadline_at, "deadline")
        < settled
        <= _clock(row.retrieved_at, "outcome retrieval")
        <= _clock(row.generated_at, "outcome generation")
        < fit
    ) or any(_clock(f.kickoff, "kickoff") >= settled for f in week.native.fixtures):
        raise ValueError("Observed load outcome chronology is inconsistent.")
    _sha(row.source_sha256, "outcome source digest")
    _text(row.evidence_ref, "outcome evidence")


def validate_observed_load_outcome(row: ObservedLoadOutcome) -> None:
    """Check independent FPL labels after the complete population header preflight."""
    count = len(row.week.native.fixtures)
    for values in (row.observed_states, row.credited_minutes, row.starts):
        if type(values) is not tuple or len(values) != count:
            raise ValueError("Observed load labels must cover the complete native calendar.")
    for state, minutes, starts in zip(
        row.observed_states, row.credited_minutes, row.starts, strict=True
    ):
        _integer(state, "observed state", 0, 6)
        _integer(minutes, "credited FPL minutes", 0, 120)
        _integer(starts, "credited start", 0, 1)
        expected = (
            0
            if minutes == 0
            else (1 if starts else 4) + (0 if minutes < 60 else 1 if minutes < 90 else 2)
        )
        if state != expected or (minutes == 0 and starts):
            raise ValueError("Observed state disagrees with independent FPL minute/start labels.")
    index = row.week.native.states.index(row.observed_states)
    if row.week.native.probabilities[index] <= 0:
        raise ValueError("Observed load label has no native support.")


T = TypeVar("T")


def _record(cls: type[T], value: Any) -> T:
    # All source classes here are dataclasses; strict fields prevent silent extras.
    names = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    return cls(**_object(value, names, cls.__name__))


def read_observed_load_snapshot(
    raw: bytes,
    *,
    sha256: str,
    allow_released_2025_26: bool = False,
) -> ObservedLoadWeek:
    """Read caller-supplied strict JSON bytes; no filesystem or network access."""
    document = _object(
        _json(raw, sha256), {f.name for f in fields(ObservedLoadWeek)}, "observed week"
    )
    source_native = document["native"]
    captured = isinstance(source_native, dict) and "version" in source_native
    native_fields = fields(ObservedLoadCapturedNativeBasis if captured else ObservedLoadNativeBasis)
    native = dict(_object(source_native, {f.name for f in native_fields}, "native basis"))
    native["fixtures"] = tuple(
        _record(
            LoadFixture,
            dict(
                _object(r, {f.name for f in fields(LoadFixture)}, "native fixture"),
                probabilities=tuple(_list(r["probabilities"], "fixture probabilities")),
                minutes=tuple(_list(r["minutes"], "fixture minutes")),
            ),
        )
        for r in _list(native["fixtures"], "native fixtures")
    )
    native["states"] = tuple(
        tuple(_list(r, "native state")) for r in _list(native["states"], "native states")
    )
    native["probabilities"] = tuple(_list(native["probabilities"], "native probabilities"))
    native["covered_gameweeks"] = tuple(_list(native["covered_gameweeks"], "covered gameweeks"))
    provenance = dict(
        _object(
            document["provenance"], {f.name for f in fields(ObservedLoadProvenance)}, "provenance"
        )
    )
    provenance["source_hashes"] = tuple(
        tuple(_list(r, "source hash pair"))
        for r in _list(provenance["source_hashes"], "source hashes")
    )
    week = _record(
        ObservedLoadWeek,
        dict(
            document,
            native=(
                _record(ObservedLoadCapturedNativeBasis, native)
                if captured
                else _record(ObservedLoadNativeBasis, native)
            ),
            provenance=_record(ObservedLoadProvenance, provenance),
            competitions=tuple(_list(document["competitions"], "competitions")),
            records=tuple(
                _record(ObservedLoadRecord, r)
                for r in _list(document["records"], "observed records")
            ),
        ),
    )
    validate_observed_load_week(week, allow_released_2025_26=allow_released_2025_26)
    return week


def read_observed_load_outcome(
    raw: bytes,
    *,
    sha256: str,
    week: ObservedLoadWeek,
    cutoff: str,
    target_season: str,
    target_gameweeks: tuple[int, ...],
    allow_released_2025_26: bool = False,
) -> ObservedLoadOutcome:
    """Guard input identity and population before decoding outcome bytes."""
    validate_targets(target_season, target_gameweeks)
    validate_observed_load_week(week, allow_released_2025_26=allow_released_2025_26)
    if season_year(week.season) > season_year(target_season) or (
        week.season == target_season and week.gameweek >= min(target_gameweeks)
    ):
        raise ValueError("Observed load target and later outcome bytes are excluded.")
    if _clock(week.provenance.generated_at, "generation") >= _clock(cutoff, "fit cutoff"):
        raise ValueError("Observed load input generation must precede fitting.")
    document = _object(
        _json(raw, sha256),
        {f.name for f in fields(ObservedLoadOutcome)} - {"week"},
        "observed outcomes",
    )
    # The header validator does not access these still-unparsed label values.
    header = _record(ObservedLoadOutcome, dict(document, week=week))
    validate_observed_load_header(
        header,
        cutoff=cutoff,
        target_season=target_season,
        target_gameweeks=target_gameweeks,
        allow_released_2025_26=allow_released_2025_26,
    )
    row = _record(
        ObservedLoadOutcome,
        dict(
            document,
            week=week,
            observed_states=tuple(_list(document["observed_states"], "observed states")),
            credited_minutes=tuple(_list(document["credited_minutes"], "credited minutes")),
            starts=tuple(_list(document["starts"], "credited starts")),
        ),
    )
    validate_observed_load_outcome(row)
    return row


def parse_observed_load_clock(value: str, name: str) -> datetime:
    """Parse the shared source/model UTC clock through this public boundary."""
    return _clock(value, name)
