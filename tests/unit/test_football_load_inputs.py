"""Synthetic original-byte workload, identity, calendar and FPL label contracts."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from squadopt.data.errors import DataError
from squadopt.features import football_load_inputs
from squadopt.features.football_load_inputs import (
    LOAD_FEATURE_NAMES,
    MAX_SOURCE_BYTES,
    NATIVE_BASIS_VERSION,
    RAW_LOAD_OUTCOME_VERSION,
    RAW_LOAD_SNAPSHOT_VERSION,
    LoadFixture,
    LoadWeek,
    TrainingLoadWeek,
    load_input_digest,
    native_joint_law_digest,
    read_load_outcomes,
    read_load_snapshot,
    validate_load_week,
    validate_training_load_week,
)

DECISION = "2024-10-04T12:00:00Z"
DEADLINE = "2024-10-05T10:00:00Z"
FIT_CUTOFF = "2024-10-11T12:00:00Z"
BASIS = "b" * 64
COMPETITIONS = ("PL", "FA", "UCL", "INT")


def native_fixtures(count: int = 1) -> tuple[LoadFixture, ...]:
    return tuple(
        LoadFixture(
            101 + index,
            f"2024-10-{5 + 2 * index:02d}T15:00:00Z",
            20,
            30 + index,
            index % 2,
            (0.2, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05),
            (0, 40, 75, 90, 12, 65, 90),
        )
        for index in range(count)
    )


def native_joint(
    fixtures: tuple[LoadFixture, ...],
) -> tuple[tuple[tuple[int, ...], ...], tuple[float, ...]]:
    states = tuple(itertools.product(range(7), repeat=len(fixtures)))
    probabilities = tuple(
        float(
            math.prod(fixture.probabilities[state[index]] for index, fixture in enumerate(fixtures))
        )
        for state in states
    )
    return states, probabilities


def membership(team: int | None, opened: str, closed: str | None = None) -> dict[str, Any]:
    return {
        "team_code": team,
        "valid_from": opened,
        "valid_until": closed,
        "evidence_ref": "synthetic-membership",
    }


def player_match(
    identity: str,
    competition: str,
    kickoff: str,
    settled: str,
    captured: str,
    registered: int,
    team: int,
    physical: float,
    added: float = 0,
    extra: float = 0,
    *,
    national: bool = False,
) -> dict[str, Any]:
    return {
        "fixture_id": identity,
        "competition_id": competition,
        "is_premier_league": competition == "PL",
        "kickoff": kickoff,
        "settled_at": settled,
        "captured_at": captured,
        "published_at": captured,
        "provider_player_id": "provider-national" if national else "provider-club",
        "registered_club_code": registered,
        "team_kind": "national" if national else "club",
        "team_code": team,
        "opponent_code": 200 + team,
        "is_home": 1,
        "physical_minutes": physical,
        "added_minutes": added,
        "extra_time_minutes": extra,
        "physical_minutes_convention": "includes_added_and_extra_time",
        "starts": 1,
        "recorded_exit_at": settled,
    }


def club_match(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "fixture_id",
        "competition_id",
        "is_premier_league",
        "kickoff",
        "captured_at",
        "published_at",
        "team_code",
        "opponent_code",
        "is_home",
    )
    return {
        **{field: row[field] for field in fields},
        "recorded_end_at": row["settled_at"],
        "settled_at": row["settled_at"],
        "target_fpl_fixture_id": None,
    }


def snapshot_document(count: int = 1) -> dict[str, Any]:
    matches = [
        player_match(
            "international",
            "INT",
            "2024-09-20T15:00:00Z",
            "2024-09-20T17:10:00Z",
            "2024-09-20T18:00:00Z",
            10,
            99,
            100,
            10,
            national=True,
        ),
        player_match(
            "league",
            "PL",
            "2024-09-30T18:00:00Z",
            "2024-09-30T20:00:00Z",
            "2024-09-30T21:00:00Z",
            20,
            20,
            90,
        ),
        player_match(
            "cup",
            "FA",
            "2024-10-02T18:00:00Z",
            "2024-10-02T20:20:00Z",
            "2024-10-02T21:00:00Z",
            20,
            20,
            123,
            3,
            30,
        ),
    ]
    upcoming = {
        "fixture_id": "europe",
        "competition_id": "UCL",
        "is_premier_league": False,
        "kickoff": "2024-10-04T18:00:00Z",
        "captured_at": "2024-10-04T10:00:00Z",
        "published_at": "2024-10-04T10:10:00Z",
        "team_code": 20,
        "opponent_code": 40,
        "is_home": 0,
        "recorded_end_at": None,
        "settled_at": None,
        "target_fpl_fixture_id": None,
    }
    targets = [
        {
            **upcoming,
            "fixture_id": f"native-{fixture.fixture_id}",
            "competition_id": "PL",
            "is_premier_league": True,
            "kickoff": fixture.kickoff,
            "team_code": fixture.club_code,
            "opponent_code": fixture.opponent_code,
            "is_home": fixture.is_home,
            "target_fpl_fixture_id": fixture.fixture_id,
        }
        for fixture in native_fixtures(count)
    ]
    native = native_fixtures(count)
    states, probabilities = native_joint(native)
    return {
        "version": RAW_LOAD_SNAPSHOT_VERSION,
        "season": "2024-25",
        "gameweek": 10,
        "player_code": 1001,
        "decision_at": DECISION,
        "deadline_at": DEADLINE,
        "position": "DEF",
        "captured_at": "2024-10-04T10:30:00Z",
        "published_at": "2024-10-04T11:00:00Z",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-no-real-data-rights",
        "native_basis_sha256": BASIS,
        "native_basis_kind": "out_of_fold",
        "native_basis_fit_cutoff": "2024-09-01T00:00:00Z",
        "native_basis_evidence_ref": "synthetic-native-fold",
        "native_basis_version": NATIVE_BASIS_VERSION,
        "native_model_version": "football_joint_role_minutes_v1",
        "native_joint_law_sha256": native_joint_law_digest(native, states, probabilities),
        "coverage": {
            "start_at": "2024-09-06T12:00:00Z",
            "end_at": DECISION,
            "complete": True,
            "competition_ids": list(COMPETITIONS),
            "expected_match_ids": [row["fixture_id"] for row in matches],
            "expected_club_match_ids": ["league", "cup"],
            "expected_upcoming_fixture_ids": ["europe", *[row["fixture_id"] for row in targets]],
            "evidence_ref": "synthetic-full-competition-inventory",
        },
        "mapping": {
            "verified": True,
            "evidence_ref": "synthetic-persistent-crosswalk",
            "player_aliases": [
                {
                    "provider_player_id": provider,
                    "player_code": 1001,
                    "valid_from": "2024-09-01T00:00:00Z",
                    "valid_until": None,
                    "evidence_ref": "synthetic-id",
                }
                for provider in ("provider-club", "provider-national")
            ],
            "club_memberships": [
                membership(10, "2024-09-01T00:00:00Z", "2024-09-23T00:00:00Z"),
                membership(20, "2024-09-23T00:00:00Z"),
            ],
            "national_memberships": [membership(99, "2024-09-01T00:00:00Z")],
        },
        "calendar": {
            "complete": True,
            "covered_gameweeks": [10],
            "fixture_ids": [fixture.fixture_id for fixture in native_fixtures(count)],
            "evidence_ref": "synthetic-native-calendar",
        },
        "fixture_aliases": [],
        "matches": matches,
        "club_matches": [club_match(row) for row in matches[1:]],
        "upcoming_fixtures": [upcoming, *targets],
        "travel": {kind: None for kind in ("actual", "planned", "venue_distance_proxy")},
    }


def encoded(document: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(document, allow_nan=False, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def read_week(
    document: dict[str, Any] | None = None,
    count: int = 1,
    *,
    fixtures: tuple[LoadFixture, ...] | None = None,
    states: tuple[tuple[int, ...], ...] | None = None,
    probabilities: tuple[float, ...] | None = None,
) -> LoadWeek:
    native = native_fixtures(count) if fixtures is None else fixtures
    baseline_states, baseline_probabilities = native_joint(native)
    chosen_states = baseline_states if states is None else states
    chosen_probabilities = baseline_probabilities if probabilities is None else probabilities
    if document is None:
        document = snapshot_document(count)
        document["native_joint_law_sha256"] = native_joint_law_digest(
            native, chosen_states, chosen_probabilities
        )
    raw, digest = encoded(document)
    return read_load_snapshot(
        raw,
        sha256=digest,
        season="2024-25",
        gameweek=10,
        player_code=1001,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        native_fixtures=native,
        native_joint_states=chosen_states,
        native_joint_probabilities=chosen_probabilities,
        native_basis_sha256=BASIS,
        required_competition_ids=COMPETITIONS,
    )


def feature_values(week: LoadWeek) -> dict[str, float | None]:
    return dict(zip(week.feature_names, week.features, strict=True))


def outcome_document(week: LoadWeek) -> dict[str, Any]:
    return {
        "version": RAW_LOAD_OUTCOME_VERSION,
        "season": week.season,
        "gameweek": week.gameweek,
        "player_code": week.player_code,
        "input_sha256": load_input_digest(week),
        "settled_at": "2024-10-10T00:00:00Z",
        "captured_at": "2024-10-10T01:00:00Z",
        "published_at": "2024-10-10T01:10:00Z",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-outcome-admission",
        "mapping_verified": True,
        "mapping_evidence_ref": "synthetic-outcome-mapping",
        "calendar_complete": True,
        "covered_gameweeks": list(week.covered_gameweeks),
        "fixture_ids": [fixture.fixture_id for fixture in week.fixtures],
        "observations": [
            {
                "fixture_id": fixture.fixture_id,
                "kickoff": fixture.kickoff,
                "club_code": fixture.club_code,
                "opponent_code": fixture.opponent_code,
                "is_home": fixture.is_home,
                "minutes": 90,
                "starts": 1,
                "state": 3,
            }
            for fixture in week.fixtures
        ],
    }


def read_labels(document: dict[str, Any], week: LoadWeek) -> TrainingLoadWeek:
    raw, digest = encoded(document)
    return read_load_outcomes(
        raw,
        sha256=digest,
        week=week,
        fit_cutoff=FIT_CUTOFF,
        target_season="2024-25",
        target_gameweeks=(11,),
    )


def test_transfer_national_and_extra_time_exposure_are_distinct_from_fpl_labels() -> None:
    week = read_week(count=2)
    values = feature_values(week)
    assert len(week.features) == len(LOAD_FEATURE_NAMES) == 53
    assert values["player_physical_minutes_7d"] == 213
    assert values["player_physical_minutes_14d"] == 313
    assert values["player_added_minutes_14d"] == 13
    assert values["player_extra_time_minutes_7d"] == 30
    assert values["player_starts_7d"] == 2
    assert values["non_pl_physical_minutes_7d"] == 123
    assert values["non_pl_physical_minutes_14d"] == 223
    assert values["club_matches_14d"] == 2
    assert values["player_hours_since_last_recorded_exit"] == pytest.approx(39 + 2 / 3)
    assert values["player_kickoff_gap_hours"] == 42
    assert values["fixture_1_club_scheduled_kickoff_gap_hours"] == 21
    assert values["fixture_2_club_scheduled_kickoff_gap_hours"] == 48
    assert read_labels(outcome_document(week), week).observed_states == (3, 3)


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_complete_native_sgw_dgw_three_fixture_and_bgw_laws(count: int) -> None:
    week = read_week(count=count)
    assert len(week.native_joint_states) == 7**count
    assert len(read_labels(outcome_document(week), week).observed_states) == count
    if count == 0:
        assert week.native_joint_states == ((),)
        assert week.native_joint_probabilities == (1.0,)


@pytest.mark.parametrize(
    "kickoff", ["2024-06-30T23:59:59Z", "2025-07-01T00:00:00Z", "2028-10-05T15:00:00Z"]
)
def test_relabeled_target_fixture_refuses_outside_declared_season(kickoff: str) -> None:
    week = read_week()
    fixtures = (replace(week.fixtures[0], kickoff=kickoff),)
    digest = native_joint_law_digest(
        fixtures, week.native_joint_states, week.native_joint_probabilities
    )
    with pytest.raises(DataError, match=r"declared July-to-June FPL season|postdeadline"):
        validate_load_week(replace(week, fixtures=fixtures, native_joint_law_sha256=digest))


@pytest.mark.parametrize("kickoff", ["2025-01-01T00:00:00Z", "2025-06-30T23:59:59Z"])
def test_target_season_accepts_next_calendar_year_and_final_instant(kickoff: str) -> None:
    week = read_week()
    fixtures = (replace(week.fixtures[0], kickoff=kickoff),)
    digest = native_joint_law_digest(
        fixtures, week.native_joint_states, week.native_joint_probabilities
    )
    validate_load_week(replace(week, fixtures=fixtures, native_joint_law_sha256=digest))


def test_explicit_correlated_dgw_law_is_not_replaced_by_independent_product() -> None:
    probability = (0.2, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05)
    fixtures = native_fixtures(2)
    states = tuple(itertools.product(range(7), repeat=2))
    joint = tuple(probability[state[0]] if state[0] == state[1] else 0.0 for state in states)
    week = read_week(count=2, fixtures=fixtures, states=states, probabilities=joint)
    assert week.native_joint_probabilities == joint
    assert week.native_joint_probabilities[1] == 0
    assert sum(p for s, p in zip(states, joint, strict=True) if s != (0, 0)) == pytest.approx(0.8)


def test_verified_empty_interval_is_zero_and_unrecorded_recovery_is_unknown() -> None:
    document = snapshot_document()
    document["matches"] = []
    document["club_matches"] = []
    document["upcoming_fixtures"] = [
        row for row in document["upcoming_fixtures"] if row["target_fpl_fixture_id"] is not None
    ]
    for field in ("expected_match_ids", "expected_club_match_ids"):
        document["coverage"][field] = []
    document["coverage"]["expected_upcoming_fixture_ids"] = [
        row["fixture_id"] for row in document["upcoming_fixtures"]
    ]
    values = feature_values(read_week(document))
    assert values["player_physical_minutes_28d"] == 0
    assert values["player_starts_28d"] == 0
    assert values["club_matches_28d"] == 0
    assert values["player_hours_since_last_recorded_exit"] is None
    assert values["player_kickoff_gap_hours"] is None


def test_missing_physical_minutes_and_recorded_starts_propagate_unknown_counts() -> None:
    document = snapshot_document()
    cup = document["matches"][-1]
    cup.update(physical_minutes=None, recorded_exit_at=None, starts=None)
    values = feature_values(read_week(document))
    assert values["player_physical_minutes_7d"] is None
    assert values["player_starts_7d"] is None
    assert values["non_pl_physical_minutes_7d"] is None
    assert values["player_known_minutes_count_7d"] == 1
    assert values["player_missing_minutes_count_7d"] == 1
    assert values["player_known_starts_count_7d"] == 1
    assert values["player_missing_starts_count_7d"] == 1
    assert values["player_hours_since_last_recorded_exit"] is None
    assert values["player_kickoff_gap_hours"] is None


def test_long_playing_time_never_infers_a_recorded_start() -> None:
    document = snapshot_document()
    document["matches"][-1]["starts"] = None
    values = feature_values(read_week(document))
    assert values["player_physical_minutes_7d"] == 213
    assert values["player_starts_7d"] is None


def test_recorded_exit_and_kickoff_proxy_do_not_substitute_for_each_other() -> None:
    document = snapshot_document()
    document["matches"][-1]["recorded_exit_at"] = None
    document["club_matches"][-1]["recorded_end_at"] = None
    values = feature_values(read_week(document))
    assert values["player_hours_since_last_recorded_exit"] is None
    assert values["club_hours_since_last_recorded_end"] is None
    assert values["player_kickoff_gap_hours"] == values["club_kickoff_gap_hours"] == 42


def test_source_clocks_with_declared_dst_offsets_are_compared_as_instants() -> None:
    document = snapshot_document()
    baseline = read_week(document)
    document["decision_at"] = "2024-10-04T13:00:00+01:00"
    document["deadline_at"] = "2024-10-05T12:00:00+02:00"
    document["matches"][-1]["kickoff"] = "2024-10-02T19:00:00+01:00"
    document["club_matches"][-1]["kickoff"] = "2024-10-02T20:00:00+02:00"
    assert read_week(document).features == baseline.features


def test_aliased_exact_duplicate_fixture_deduplicates_and_conflict_refuses() -> None:
    document = snapshot_document()
    document["fixture_aliases"] = [
        {"alias": "cup-alias", "canonical_fixture_id": "cup", "evidence_ref": "synthetic-alias"}
    ]
    duplicate = copy.deepcopy(document["matches"][-1])
    duplicate["fixture_id"] = "cup-alias"
    document["matches"].append(duplicate)
    assert feature_values(read_week(document))["player_physical_minutes_7d"] == 213
    duplicate["physical_minutes"] = 122
    with pytest.raises(DataError, match="Conflicting"):
        read_week(document)


@pytest.mark.parametrize("kind", ["actual", "planned", "venue_distance_proxy"])
def test_optional_travel_kinds_remain_distinct_and_unknown_does_not_become_zero(kind: str) -> None:
    document = snapshot_document()
    opened, closed, duration = (
        ("2024-10-01T08:00:00Z", "2024-10-01T10:00:00Z", 2)
        if kind == "actual"
        else (
            ("2024-10-05T11:00:00Z", "2024-10-05T13:00:00Z", 2)
            if kind == "planned"
            else ("2024-10-05T15:00:00Z", None, None)
        )
    )
    document["travel"][kind] = {
        "complete": True,
        "evidence_ref": "synthetic-travel-coverage",
        "expected_ids": ["trip1"],
        "records": [
            {
                "id": "trip1",
                "start_at": opened,
                "end_at": closed,
                "distance_km": 300,
                "duration_hours": duration,
                "captured_at": "2024-10-04T10:00:00Z",
                "published_at": "2024-10-04T10:10:00Z",
                "evidence_ref": "synthetic-trip",
            }
        ],
    }
    values = feature_values(read_week(document))
    assert values[f"{kind}_travel_distance_km"] == 300
    assert values[f"{kind}_travel_duration_hours"] == duration
    for other in set(("actual", "planned", "venue_distance_proxy")) - {kind}:
        assert values[f"{other}_travel_distance_km"] is None
    document["travel"][kind]["complete"] = False
    assert feature_values(read_week(document))[f"{kind}_travel_distance_km"] is None


def test_covered_empty_travel_is_zero_but_proxy_duration_stays_unknown() -> None:
    document = snapshot_document()
    for kind in document["travel"]:
        document["travel"][kind] = {
            "complete": True,
            "evidence_ref": "synthetic-verified-empty",
            "expected_ids": [],
            "records": [],
        }
    values = feature_values(read_week(document))
    assert values["actual_travel_duration_hours"] == 0
    assert values["venue_distance_proxy_travel_distance_km"] == 0
    assert values["venue_distance_proxy_travel_duration_hours"] is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "wrong"),
        ("player_code", True),
        ("gameweek", 11),
        ("position", "CF"),
        ("decision_at", DEADLINE),
        ("published_at", DECISION),
        ("captured_at", DECISION),
        ("native_basis_sha256", "a" * 64),
        ("native_basis_version", "wrong"),
        ("native_basis_kind", "unknown"),
        ("native_basis_fit_cutoff", DECISION),
        ("native_model_version", "not a version"),
        ("model_use_approved", False),
        ("model_use_evidence_ref", ""),
        ("published_at", "2024-10-04T11:00:00"),
    ],
)
def test_invalid_snapshot_headers_refuse(field: str, value: Any) -> None:
    document = snapshot_document()
    document[field] = value
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("complete", False),
        ("complete", 1),
        ("start_at", "2024-09-07T12:00:00Z"),
        ("end_at", "2024-10-04T11:00:00Z"),
        ("competition_ids", ["PL", "FA"]),
        ("competition_ids", ["PL", "PL", "FA", "UCL", "INT"]),
        ("expected_match_ids", ["cup"]),
        ("expected_club_match_ids", ["league"]),
        ("expected_upcoming_fixture_ids", []),
        ("evidence_ref", ""),
    ],
)
def test_missing_competition_or_calendar_coverage_refuses(field: str, value: Any) -> None:
    document = snapshot_document()
    document["coverage"][field] = value
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("physical_minutes", True),
        ("physical_minutes", "123"),
        ("physical_minutes", -1),
        ("added_minutes", 130),
        ("extra_time_minutes", 124),
        ("starts", True),
        ("starts", 2),
        ("starts", "1"),
        ("registered_club_code", 10),
        ("team_code", 10),
        ("provider_player_id", "unmapped"),
        ("team_kind", "unknown"),
        ("physical_minutes_convention", "fpl_credited"),
        ("settled_at", "2024-10-02T18:00:00Z"),
        ("published_at", DECISION),
        ("captured_at", "2024-10-04T11:00:00Z"),
        ("recorded_exit_at", "2024-10-02T18:00:00Z"),
        ("is_home", True),
    ],
)
def test_invalid_physical_exposure_identity_or_clocks_refuse(field: str, value: Any) -> None:
    document = snapshot_document()
    document["matches"][-1][field] = value
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    "kind", ["gap", "overlap", "unknown-national", "alias-overlap", "paired-conflict", "future-end"]
)
def test_temporal_crosswalk_and_paired_calendar_refusals(kind: str) -> None:
    document = snapshot_document()
    if kind == "gap":
        document["mapping"]["club_memberships"][1]["valid_from"] = "2024-09-24T00:00:00Z"
    elif kind == "overlap":
        document["mapping"]["club_memberships"][1]["valid_from"] = "2024-09-22T00:00:00Z"
    elif kind == "unknown-national":
        document["mapping"]["national_memberships"][0]["team_code"] = None
    elif kind == "alias-overlap":
        document["mapping"]["player_aliases"].append(
            copy.deepcopy(document["mapping"]["player_aliases"][0])
        )
    elif kind == "paired-conflict":
        document["club_matches"][-1]["opponent_code"] = 999
    else:
        document["upcoming_fixtures"][0]["recorded_end_at"] = "2024-10-04T20:00:00Z"
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":-Infinity}',
        b"[]",
        b"\xff",
        b"{}",
    ],
)
def test_strict_json_refuses_duplicate_nonfinite_encoding_and_shape(raw: bytes) -> None:
    states, probabilities = native_joint(native_fixtures())
    with pytest.raises(DataError):
        read_load_snapshot(
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            season="2024-25",
            gameweek=10,
            player_code=1001,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_fixtures=native_fixtures(),
            native_joint_states=states,
            native_joint_probabilities=probabilities,
            native_basis_sha256=BASIS,
            required_competition_ids=COMPETITIONS,
        )


def test_original_bytes_hash_and_size_are_bound() -> None:
    raw, _ = encoded(snapshot_document())
    states, probabilities = native_joint(native_fixtures())
    kwargs = dict(
        season="2024-25",
        gameweek=10,
        player_code=1001,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        native_fixtures=native_fixtures(),
        native_joint_states=states,
        native_joint_probabilities=probabilities,
        native_basis_sha256=BASIS,
        required_competition_ids=COMPETITIONS,
    )
    for invalid, digest in (
        (raw, "a" * 64),
        (bytearray(raw), hashlib.sha256(raw).hexdigest()),
        (b"x" * (MAX_SOURCE_BYTES + 1), "a" * 64),
    ):
        with pytest.raises(DataError):
            read_load_snapshot(invalid, sha256=digest, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("feature_names", ("unknown",)),
        ("features", (None,)),
        ("competition_ids", ("PL", "PL")),
        ("calendar_complete", False),
        ("covered_gameweeks", (11,)),
        ("native_joint_states", ((True,), (1,), (2,), (3,), (4,), (5,), (6,))),
        ("native_joint_probabilities", (1, 0, 0, 0, 0, 0, 0)),
        ("native_basis_version", "unknown"),
        ("native_basis_fit_cutoff", DECISION),
        ("source_sha256", "A" * 64),
    ],
)
def test_direct_load_values_cannot_bypass_typed_receipts(field: str, value: Any) -> None:
    with pytest.raises(DataError):
        validate_load_week(replace(read_week(), **{field: value}))


def test_immutable_digests_bind_native_joint_law_features_and_source_receipts() -> None:
    week = read_week()
    assert load_input_digest(week) != load_input_digest(
        replace(week, native_basis_evidence_ref="other-receipt")
    )
    with pytest.raises(FrozenInstanceError):
        week.gameweek = 11  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        week.fixtures[0].is_home = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("season", "gameweek"), [("2025-26", 1), ("2024-25", 11), ("2024-25", 12), ("2026-27", 1)]
)
def test_protected_target_and_future_week_refuse_before_outcome_decoding(
    monkeypatch: pytest.MonkeyPatch, season: str, gameweek: int
) -> None:
    week = replace(read_week(), season=season, gameweek=gameweek)

    def forbidden_decode(*args: object, **kwargs: object) -> Any:
        raise AssertionError("Outcome bytes must not be decoded.")

    def forbidden_body(*args: object, **kwargs: object) -> Any:
        raise AssertionError("Forbidden training headers must refuse before full input inspection.")

    monkeypatch.setattr(football_load_inputs, "_json", forbidden_decode)
    monkeypatch.setattr(football_load_inputs, "validate_load_week", forbidden_body)
    with pytest.raises(DataError):
        read_load_outcomes(
            b"not outcomes",
            sha256="a" * 64,
            week=week,
            fit_cutoff=FIT_CUTOFF,
            target_season="2024-25",
            target_gameweeks=(11, 13),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minutes", None),
        ("minutes", True),
        ("minutes", 121),
        ("starts", None),
        ("starts", True),
        ("starts", 2),
        ("state", 6),
        ("fixture_id", 999),
        ("is_home", True),
        ("club_code", 10),
    ],
)
def test_final_fpl_labels_require_known_recorded_starts_and_exact_native_identity(
    field: str, value: Any
) -> None:
    week = read_week()
    document = outcome_document(week)
    document["observations"][0][field] = value
    with pytest.raises(DataError):
        read_labels(document, week)


@pytest.mark.parametrize(
    ("minutes", "starts", "state"),
    [(0, 0, 0), (40, 1, 1), (75, 1, 2), (120, 1, 3), (10, 0, 4), (65, 0, 5), (100, 0, 6)],
)
def test_each_fpl_state_is_bound_to_separate_credited_minutes_and_recorded_start(
    minutes: int, starts: int, state: int
) -> None:
    week = read_week()
    document = outcome_document(week)
    document["observations"][0].update(minutes=minutes, starts=starts, state=state)
    assert read_labels(document, week).observed_states == (state,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "unknown"),
        ("input_sha256", "a" * 64),
        ("calendar_complete", False),
        ("fixture_ids", []),
        ("observations", []),
        ("published_at", FIT_CUTOFF),
        ("settled_at", DEADLINE),
        ("model_use_approved", False),
        ("mapping_verified", False),
    ],
)
def test_outcome_full_inventory_finalization_and_receipt_refusals(field: str, value: Any) -> None:
    week = read_week()
    document = outcome_document(week)
    document[field] = value
    with pytest.raises(DataError):
        read_labels(document, week)


def test_manual_training_values_require_complete_final_settlement_and_integer_states() -> None:
    row = read_labels(outcome_document(read_week()), read_week())
    for change in ({"observed_states": ()}, {"observed_states": (True,)}, {"settled_at": DEADLINE}):
        with pytest.raises(DataError):
            validate_training_load_week(
                replace(row, **change),
                fit_cutoff=FIT_CUTOFF,
                target_season="2024-25",
                target_gameweeks=(11,),
            )


def test_joint_receipt_binds_correlation_even_when_each_fixture_marginal_is_identical() -> None:
    document = snapshot_document(2)
    fixtures = native_fixtures(2)
    states = tuple(itertools.product(range(7), repeat=2))
    diagonal = tuple(
        fixtures[0].probabilities[state[0]] if state[0] == state[1] else 0.0 for state in states
    )
    independent = document["native_joint_law_sha256"]
    assert native_joint_law_digest(fixtures, states, diagonal) != independent
    with pytest.raises(DataError, match="joint-law digest"):
        read_week(document, count=2, fixtures=fixtures, states=states, probabilities=diagonal)


def test_joint_receipt_binds_native_minute_supports_and_original_near_unit_mass() -> None:
    document = snapshot_document()
    fixture = replace(native_fixtures()[0], minutes=(0, 41, 75, 90, 12, 65, 90))
    with pytest.raises(DataError, match="joint-law digest"):
        read_week(document, fixtures=(fixture,))
    near_probabilities = (0.2 + 5e-13, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05)
    near_fixture = replace(native_fixtures()[0], probabilities=near_probabilities)
    week = read_week(fixtures=(near_fixture,))
    assert week.native_joint_probabilities == near_probabilities
    normalized = tuple(value / math.fsum(near_probabilities) for value in near_probabilities)
    normalized_fixture = replace(near_fixture, probabilities=normalized)
    assert (
        native_joint_law_digest((normalized_fixture,), week.native_joint_states, normalized)
        != week.native_joint_law_sha256
    )


@pytest.mark.parametrize(
    "kind",
    ["missing", "duplicate", "wrong-club", "wrong-kickoff", "untagged", "non-pl", "past-target"],
)
def test_native_target_crosswalk_requires_exact_complete_once_only_fixture_binding(
    kind: str,
) -> None:
    document = snapshot_document()
    target = document["upcoming_fixtures"][-1]
    if kind == "missing":
        document["upcoming_fixtures"].pop()
        document["coverage"]["expected_upcoming_fixture_ids"].pop()
    elif kind == "duplicate":
        duplicate = copy.deepcopy(target)
        duplicate["fixture_id"] = "other-target-alias"
        document["upcoming_fixtures"].append(duplicate)
        document["coverage"]["expected_upcoming_fixture_ids"].append(duplicate["fixture_id"])
    elif kind == "wrong-club":
        target["team_code"] = 10
    elif kind == "wrong-kickoff":
        target["kickoff"] = "2024-10-05T14:00:00Z"
    elif kind == "untagged":
        target["target_fpl_fixture_id"] = None
    elif kind == "non-pl":
        target["is_premier_league"] = False
    else:
        document["club_matches"][-1]["target_fpl_fixture_id"] = 101
    with pytest.raises(DataError):
        read_week(document)


def test_native_targets_do_not_become_extra_upcoming_opportunities() -> None:
    values = feature_values(read_week(count=3))
    assert values["known_upcoming_club_matches_before_last_target"] == 1
    for index in (1, 2, 3):
        assert values[f"fixture_{index}_known_prior_non_pl_matches"] == 1


@pytest.mark.parametrize(
    "kind",
    [
        "missing-settlement",
        "not-settled",
        "future-settlement",
        "end-after-settlement",
        "short-exit",
    ],
)
def test_past_club_completion_and_physical_player_exit_require_real_recorded_clocks(
    kind: str,
) -> None:
    document = snapshot_document()
    club = document["club_matches"][-1]
    if kind == "missing-settlement":
        club["settled_at"] = None
        club["recorded_end_at"] = None
    elif kind == "not-settled":
        club["settled_at"] = club["kickoff"]
        club["recorded_end_at"] = None
    elif kind == "future-settlement":
        club["settled_at"] = DECISION
        club["recorded_end_at"] = None
    elif kind == "end-after-settlement":
        club["settled_at"] = "2024-10-02T20:00:00Z"
    else:
        document["matches"][-1]["recorded_exit_at"] = "2024-10-02T18:01:00Z"
    with pytest.raises(DataError):
        read_week(document)


def test_postdeadline_native_support_is_strict_and_boolean_probabilities_refuse() -> None:
    week = read_week()
    fixture = replace(week.fixtures[0], kickoff=DEADLINE)
    states, probabilities = native_joint((fixture,))
    changed = replace(
        week,
        fixtures=(fixture,),
        native_joint_law_sha256=native_joint_law_digest((fixture,), states, probabilities),
    )
    with pytest.raises(DataError, match="postdeadline"):
        validate_load_week(changed)
    with pytest.raises(DataError):
        native_joint_law_digest(
            (replace(week.fixtures[0], probabilities=(True, 0, 0, 0, 0, 0, 0)),),
            states,
            (1, 0, 0, 0, 0, 0, 0),
        )


@pytest.mark.parametrize("kind", ["unknown-field", "nested-unknown", "missing-field", "overflow"])
def test_exact_fields_and_numeric_overflow_are_refused(kind: str) -> None:
    document = snapshot_document()
    if kind == "unknown-field":
        document["extra"] = "unrecognized"
    elif kind == "nested-unknown":
        document["matches"][-1]["fpl_minutes"] = 90
    elif kind == "missing-field":
        del document["matches"][-1]["starts"]
    else:
        document["matches"][-1]["physical_minutes"] = 10**400
    with pytest.raises(DataError):
        read_week(document)
