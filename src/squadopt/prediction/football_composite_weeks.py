"""Pure full-population weekly composition, with caller-verified source identities."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from squadopt.features.football_observed_load import (
    ObservedLoadCapturedNativeBasis,
    ObservedLoadWeek,
    observed_load_digest,
    parse_observed_load_clock,
    validate_observed_load_week,
    validate_targets,
)
from squadopt.prediction.football_joint_week_law import (
    JointWeekLaw,
    Sources,
    VerifiedWeekEvidence,
    apply_shared_eligibility,
    apply_verified_week_evidence,
    joint_week_law_digest,
    make_joint_week_law,
    model_week_law,
    transport_load,
    validate_joint_week_law,
)
from squadopt.prediction.football_observed_load import ObservedLoadServingModel

VERSION = "football_composite_weeks_v1"


@dataclass(frozen=True, slots=True)
class CompositePlayer:
    player_code: int
    position: str
    club_code: int
    captured_eligibility: float


@dataclass(frozen=True, slots=True)
class CompositeCalendarFixture:
    gameweek: int
    fixture_id: int
    kickoff: str
    home_club_code: int
    away_club_code: int


@dataclass(frozen=True, slots=True)
class CompositeDeadline:
    gameweek: int
    deadline_at: str


@dataclass(frozen=True, slots=True)
class CompositeWeekInventory:
    season: str
    gameweeks: tuple[int, ...]
    roster: tuple[CompositePlayer, ...]
    calendar: tuple[CompositeCalendarFixture, ...]
    deadlines: tuple[CompositeDeadline, ...]
    source_snapshot_id: str
    source_fingerprint: str
    captured_at: str
    decision_at: str
    calendar_sha256: str
    native_basis_sha256: str
    native_components_sha256: str
    role_metadata_sha256: str
    captured_eligibility_sha256: str
    first_week_flag_result_sha256: str
    version: str = VERSION


@dataclass(frozen=True, slots=True)
class CompositeWeekInput:
    native: JointWeekLaw
    first_week_flag: JointWeekLaw | None
    load_week: ObservedLoadWeek
    captured_eligibility: float
    captured_eligibility_source_sha256: str


@dataclass(frozen=True, slots=True)
class CompositeWeekReceipt:
    gameweek: int
    player_code: int
    input_sha256: str
    load_input_sha256: str
    native_sha256: str
    offset_sha256: str
    load_result_sha256: str
    before_evidence_sha256: str
    final_sha256: str


@dataclass(frozen=True, slots=True)
class CompositeWeeksResult:
    laws: tuple[JointWeekLaw, ...]
    receipts: tuple[CompositeWeekReceipt, ...]
    inventory_sha256: str
    input_population_sha256: str
    evidence_sha256: str
    model_sha256: str
    serving_result_sha256: str
    version: str = VERSION


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _sha(value: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Composite weeks require lowercase SHA256 source identities.")


def _integer(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("Composite weeks require positive integer identities.")


def _eligibility(value: float) -> None:
    if type(value) not in (float, int) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Composite captured eligibility must be a real probability.")


def composite_native_sources(inventory: CompositeWeekInventory) -> Sources:
    """Exact source labels used when binding each original captured native law."""
    return (
        ("native_components", inventory.native_components_sha256),
        ("native_basis", inventory.native_basis_sha256),
        ("snapshot_fingerprint", inventory.source_fingerprint),
        ("calendar", inventory.calendar_sha256),
    )


def _inventory(inventory: CompositeWeekInventory, first_gameweek: int) -> None:
    if type(inventory) is not CompositeWeekInventory or inventory.version != VERSION:
        raise ValueError("Composite inventory requires its frozen version.")
    validate_targets(inventory.season, inventory.gameweeks)
    _integer(first_gameweek)
    if inventory.gameweeks != tuple(
        range(first_gameweek, first_gameweek + len(inventory.gameweeks))
    ):
        raise ValueError(
            "Composite inventory must start at the declared first week and be contiguous."
        )
    for source_hash in (
        inventory.source_fingerprint,
        inventory.calendar_sha256,
        inventory.native_basis_sha256,
        inventory.native_components_sha256,
        inventory.role_metadata_sha256,
        inventory.captured_eligibility_sha256,
        inventory.first_week_flag_result_sha256,
    ):
        _sha(source_hash)
    captured = parse_observed_load_clock(inventory.captured_at, "composite capture")
    decision = parse_observed_load_clock(inventory.decision_at, "composite decision")
    year = int(inventory.season[:4])
    season_start = datetime(year, 7, 1, tzinfo=decision.tzinfo)
    season_end = datetime(year + 1, 7, 1, tzinfo=decision.tzinfo)
    if not captured <= decision or inventory.source_snapshot_id != (
        "fpl-live-" + captured.strftime("%Y%m%dT%H%M%SZ") + "-" + inventory.source_fingerprint[:12]
    ):
        raise ValueError("Composite snapshot identity or chronology is inconsistent.")
    if type(inventory.roster) is not tuple or not 1 <= len(inventory.roster) <= 5000:
        raise ValueError("Composite inventory requires a bounded complete immutable roster.")
    codes = []
    for player in inventory.roster:
        if type(player) is not CompositePlayer or player.position not in (
            "GK",
            "DEF",
            "MID",
            "FWD",
        ):
            raise ValueError(
                "Composite roster requires its frozen player type and native position."
            )
        _integer(player.player_code)
        _integer(player.club_code)
        _eligibility(player.captured_eligibility)
        codes.append(player.player_code)
    if codes != sorted(set(codes)):
        raise ValueError("Composite roster must be ordered by unique persistent player code.")
    if (
        type(inventory.deadlines) is not tuple
        or any(type(d) is not CompositeDeadline for d in inventory.deadlines)
        or tuple(d.gameweek for d in inventory.deadlines) != inventory.gameweeks
    ):
        raise ValueError("Composite inventory requires exactly one ordered deadline per week.")
    deadlines = {}
    previous = decision
    for deadline in inventory.deadlines:
        _integer(deadline.gameweek)
        deadline_clock = parse_observed_load_clock(deadline.deadline_at, "composite deadline")
        if not season_start <= decision < deadline_clock < season_end or deadline_clock <= previous:
            raise ValueError("Composite deadlines must be increasing and after the decision.")
        previous = deadline_clock
        deadlines[deadline.gameweek] = deadline_clock
    if type(inventory.calendar) is not tuple or len(inventory.calendar) > 1140:
        raise ValueError("Composite inventory requires a bounded immutable PL calendar.")
    fixture_ids = set()
    ordering = []
    for fixture in inventory.calendar:
        if type(fixture) is not CompositeCalendarFixture:
            raise ValueError("Composite calendar requires its frozen fixture type.")
        for identity in (
            fixture.gameweek,
            fixture.fixture_id,
            fixture.home_club_code,
            fixture.away_club_code,
        ):
            _integer(identity)
        if (
            fixture.gameweek not in inventory.gameweeks
            or fixture.fixture_id in fixture_ids
            or fixture.home_club_code == fixture.away_club_code
        ):
            raise ValueError(
                "Composite calendar has an unknown week, duplicate fixture or self fixture."
            )
        kickoff = parse_observed_load_clock(fixture.kickoff, "composite kickoff")
        if not deadlines[fixture.gameweek] <= kickoff < season_end:
            raise ValueError("Composite calendar kickoff precedes the week deadline.")
        fixture_ids.add(fixture.fixture_id)
        ordering.append((fixture.gameweek, kickoff, fixture.fixture_id))
    if ordering != sorted(ordering):
        raise ValueError("Composite calendar must use week, kickoff and fixture order.")


def _input(
    row: CompositeWeekInput,
    player: CompositePlayer,
    inventory: CompositeWeekInventory,
    first_gameweek: int,
    model: ObservedLoadServingModel,
) -> None:
    week = row.load_week
    validate_observed_load_week(
        week, allow_released_2025_26=model.parameters.allow_released_2025_26
    )
    native = week.native
    if type(native) is not ObservedLoadCapturedNativeBasis or week.provenance.kind != "prospective":
        raise ValueError(
            "Composite serving requires the explicit prospective captured-native variant."
        )
    if (
        (week.season, week.player_code, week.position, week.decision_at)
        != (inventory.season, player.player_code, player.position, inventory.decision_at)
        or week.deadline_at
        != next(d.deadline_at for d in inventory.deadlines if d.gameweek == week.gameweek)
        or native.source_snapshot_id != inventory.source_snapshot_id
        or native.source_fingerprint != inventory.source_fingerprint
        or native.recorded_at != inventory.captured_at
        or native.calendar_sha256 != inventory.calendar_sha256
        or native.basis_sha256 != inventory.native_basis_sha256
        or not set(inventory.gameweeks).issubset(native.covered_gameweeks)
    ):
        raise ValueError("Composite source identity, native basis, deadline or calendar mismatch.")
    source_hashes = {digest for _, digest in week.provenance.source_hashes}
    if inventory.native_components_sha256 not in source_hashes:
        raise ValueError("Composite LOAD source lacks its original native components binding.")
    _eligibility(row.captured_eligibility)
    if (
        row.captured_eligibility != player.captured_eligibility
        or row.captured_eligibility_source_sha256 != inventory.captured_eligibility_sha256
    ):
        raise ValueError("Composite captured eligibility differs from its roster/source binding.")
    fixtures = tuple(
        f
        for f in inventory.calendar
        if f.gameweek == week.gameweek and player.club_code in (f.home_club_code, f.away_club_code)
    )
    expected = tuple(
        (
            f.fixture_id,
            parse_observed_load_clock(f.kickoff, "calendar kickoff"),
            player.club_code,
            f.away_club_code if player.club_code == f.home_club_code else f.home_club_code,
            int(player.club_code == f.home_club_code),
        )
        for f in fixtures
    )
    actual = tuple(
        (
            f.fixture_id,
            parse_observed_load_clock(f.kickoff, "native kickoff"),
            f.club_code,
            f.opponent_code,
            f.is_home,
        )
        for f in native.fixtures
    )
    if actual != expected:
        raise ValueError(
            "Composite native fixtures do not cover the exact declared player calendar."
        )
    reconstructed = make_joint_week_law(
        season=week.season,
        gameweek=week.gameweek,
        player_code=week.player_code,
        position=week.position,
        fixtures=native.fixtures,
        states=native.states,
        probabilities=native.probabilities,
        role_metadata_sha256=inventory.role_metadata_sha256,
        sources=composite_native_sources(inventory),
    )
    validate_joint_week_law(row.native)
    if row.native != reconstructed:
        raise ValueError(
            "Composite original native law, role metadata or exact source lineage differs."
        )
    flag = row.first_week_flag
    if week.gameweek == first_gameweek:
        if flag is None:
            raise ValueError("Composite first week requires the retained fitted flag law.")
        validate_joint_week_law(flag)
        if (
            len(flag.lineage) != 2
            or dict(flag.lineage[-1].sources).get("retained_flag_result")
            != inventory.first_week_flag_result_sha256
        ):
            raise ValueError("Composite first-week flag lacks its retained result source binding.")
        if (
            model_week_law(
                row.native,
                flag.states,
                flag.probabilities,
                kind="flag",
                sources=flag.lineage[-1].sources,
            )
            != flag
        ):
            raise ValueError("Composite first-week flag differs from the original native source.")
    elif flag is not None:
        raise ValueError("Composite later weeks cannot carry a first-week flag law.")
    if (
        week.season != model.parameters.target_season
        or week.gameweek not in model.parameters.target_gameweeks
        or parse_observed_load_clock(model.parameters.cutoff, "LOAD fit cutoff")
        > parse_observed_load_clock(week.provenance.feature_cutoff, "feature cutoff")
        or tuple(sorted(week.competitions)) not in model.parameters.observed_competition_scopes
    ):
        raise ValueError(
            "Composite LOAD target, fit chronology or trained observed scope mismatch."
        )


def compose_composite_weeks(
    inputs: tuple[CompositeWeekInput, ...],
    model: ObservedLoadServingModel,
    *,
    inventory: CompositeWeekInventory,
    first_gameweek: int,
    evidence: tuple[VerifiedWeekEvidence, ...] = (),
) -> CompositeWeeksResult:
    """Validate the whole declared population before applying any fitted LOAD law.

    Source bytes, completeness of the declared capture and evidence authorization
    belong to the caller. The inventory prevents silently dropping declared rows.
    """
    _inventory(inventory, first_gameweek)
    if type(model) is not ObservedLoadServingModel:
        raise ValueError("Composite weeks require the read-only compact LOAD serving model.")
    if type(inputs) is not tuple or any(type(row) is not CompositeWeekInput for row in inputs):
        raise ValueError("Composite inputs must be an immutable tuple of the frozen input type.")
    expected = tuple(
        (gw, player.player_code) for gw in inventory.gameweeks for player in inventory.roster
    )
    if (
        any(type(row.load_week) is not ObservedLoadWeek for row in inputs)
        or tuple((row.load_week.gameweek, row.load_week.player_code) for row in inputs) != expected
    ):
        raise ValueError(
            "Composite input inventory must cover every declared roster/week in order, "
            "including blanks."
        )
    players = {p.player_code: p for p in inventory.roster}
    for row in inputs:
        _input(row, players[row.load_week.player_code], inventory, first_gameweek, model)
    if type(evidence) is not tuple or any(type(e) is not VerifiedWeekEvidence for e in evidence):
        raise ValueError("Composite evidence must be an immutable tuple of verified claims.")
    if (
        any(type(e.evidence_id) is not str or type(e.player_code) is not int for e in evidence)
        or len({e.evidence_id for e in evidence}) != len(evidence)
        or any(e.player_code not in players or e.gameweek != first_gameweek for e in evidence)
    ):
        raise ValueError(
            "Composite evidence has duplicate identities or an unknown player/first week."
        )
    by_person = {code: tuple(e for e in evidence if e.player_code == code) for code in players}
    for row in inputs:
        if row.native.gameweek == first_gameweek:
            apply_verified_week_evidence(
                row.native, by_person[row.native.player_code], first_gameweek=first_gameweek
            )
    inventory_hash = _digest(asdict(inventory))
    model_sources = (
        ("load_model_metadata", model.model_sha256),
        ("load_serving_result", model.result_sha256),
    )
    laws, receipts = [], []
    for row in inputs:
        result = model.predict(row.load_week)
        input_hash = _digest(asdict(row))
        loaded = model_week_law(
            row.native,
            result.states,
            result.probabilities,
            kind="load",
            sources=(*model_sources, ("load_input", observed_load_digest(row.load_week))),
        )
        offset = row.first_week_flag
        if offset is None:
            offset = apply_shared_eligibility(
                row.native,
                row.captured_eligibility,
                sources=(("captured_eligibility", inventory.captured_eligibility_sha256),),
            )
        before = transport_load(
            row.native,
            loaded,
            offset,
            sources=(*model_sources, ("composition_inventory", inventory_hash)),
        )
        final = apply_verified_week_evidence(
            before,
            by_person[row.native.player_code] if row.native.gameweek == first_gameweek else (),
            first_gameweek=first_gameweek,
        )
        laws.append(final)
        receipts.append(
            CompositeWeekReceipt(
                final.gameweek,
                final.player_code,
                input_hash,
                result.input_sha256,
                joint_week_law_digest(row.native),
                joint_week_law_digest(offset),
                joint_week_law_digest(loaded),
                joint_week_law_digest(before),
                joint_week_law_digest(final),
            )
        )
    return CompositeWeeksResult(
        tuple(laws),
        tuple(receipts),
        inventory_hash,
        _digest(tuple(receipt.input_sha256 for receipt in receipts)),
        _digest(tuple(asdict(item) for item in evidence)),
        model.model_sha256,
        model.result_sha256,
    )
