"""Invented physical clocks and FPL credits, with independent refusal cases."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest

from squadopt.features import football_score_state_inputs as source
from squadopt.features.football_score_state_inputs import (
    CLOCK_VERSION,
    RAW_SCORE_OUTCOME_VERSION,
    RAW_SCORE_SNAPSHOT_VERSION,
    FPLCredit,
    ObservedPlayerExposure,
    PhysicalGoal,
    PhysicalPeriod,
    ScoreFixture,
    ScorePlayer,
    TrainingScoreFixture,
    read_score_outcomes,
    read_score_snapshot,
    score_input_digest,
    validate_score_fixture,
    validate_training_score_fixture,
    validate_training_score_header,
)

DECISION = "2024-10-05T10:00:00Z"
DEADLINE = "2024-10-05T11:00:00Z"
KICKOFF = "2024-10-05T12:00:00Z"
CUTOFF = "2024-10-11T00:00:00Z"
BASE_SHA = "a" * 64


def player(code: int, club: int, position: str, representation: str = "seven_roles") -> ScorePlayer:
    if representation == "four_bins":
        return ScorePlayer(
            code,
            club,
            position,
            (0.2, 0.2, 0.3, 0.3),
            (0, 40, 75, 90),
            (0, 0, 0, 0),
            (0, 40, 75, 100),
            ("not_playing", "normal_substitution", "normal_substitution", "full_time"),
            representation,
        )
    return ScorePlayer(
        code,
        club,
        position,
        (0.2, 0.1, 0.25, 0.2, 0.1, 0.1, 0.05),
        (0, 40, 75, 90, 20, 65, 90),
        (0, 0, 0, 0, 60, 30, 5),
        (0, 40, 75, 100, 80, 95, 100),
        (
            "not_playing",
            "normal_substitution",
            "normal_substitution",
            "full_time",
            "normal_substitution",
            "normal_substitution",
            "full_time",
        ),
        representation,
    )


def projection(representation: str = "seven_roles") -> ScoreFixture:
    return ScoreFixture(
        "2024-25",
        10,
        101,
        DECISION,
        DEADLINE,
        KICKOFF,
        10,
        20,
        1.8,
        1.2,
        100,
        CLOCK_VERSION,
        tuple(
            player(code, 10 if code <= 2 else 20, pos, representation)
            for code, pos in ((1, "GK"), (2, "MID"), (3, "DEF"), (4, "FWD"))
        ),
        BASE_SHA,
        "football_team_share_v1"
        if representation == "four_bins"
        else "football_joint_role_minutes_v1",
        "out_of_fold",
        "2024-10-01T00:00:00Z",
        "invented-native-receipt",
        "b" * 64,
        "invented-complete-physical-support",
        "invented-paired-calendar",
    )


def snapshot_document(representation: str = "seven_roles") -> dict[str, Any]:
    fixture = projection(representation)
    fields = json.loads(json.dumps(asdict(fixture)))
    fields.pop("source_sha256")
    return {
        "version": RAW_SCORE_SNAPSHOT_VERSION,
        "captured_at": "2024-10-05T09:10:00Z",
        "published_at": "2024-10-05T09:20:00Z",
        "rights": {
            "model_use_claim": True,
            "evidence_ref": "invented-operator-receipt-not-real-admission",
        },
        "native_basis_clock": {
            "captured_at": "2024-10-05T09:00:00Z",
            "published_at": "2024-10-05T09:05:00Z",
        },
        "coverage": {
            "complete": True,
            "physical_clock_known": True,
            "exit_policies_known": True,
            "player_codes": [1, 2, 3, 4],
            "evidence_ref": fixture.coverage_evidence_ref,
        },
        "calendar": [
            {
                "fixture_id": 101,
                "club_code": club,
                "opponent_code": opponent,
                "home": home,
                "kickoff": KICKOFF,
                "available_at": "2024-10-04T00:00:00Z",
                "evidence_ref": fixture.calendar_evidence_ref,
            }
            for club, opponent, home in ((10, 20, 1), (20, 10, 0))
        ],
        "club_mapping": [
            {
                "club_code": club,
                "provider_id": f"club:{club}",
                "available_at": "2024-10-04T00:00:00Z",
                "evidence_ref": "invented-club-mapping",
            }
            for club in (10, 20)
        ],
        "person_mapping": [
            {
                "player_code": p.player_code,
                "club_code": p.club_code,
                "provider_id": f"person:{p.player_code}",
                "available_at": "2024-10-04T00:00:00Z",
                "evidence_ref": "invented-person-mapping",
            }
            for p in fixture.players
        ],
        "projection": fields,
    }


def encode(document: object) -> tuple[bytes, str]:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def read_fixture(
    document: dict[str, Any] | None = None, representation: str = "seven_roles"
) -> ScoreFixture:
    raw, digest = encode(snapshot_document(representation) if document is None else document)
    return read_score_snapshot(
        raw,
        sha256=digest,
        season="2024-25",
        gameweek=10,
        fixture_id=101,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        native_basis_sha256=BASE_SHA,
    )


def training(fixture: ScoreFixture | None = None) -> TrainingScoreFixture:
    fixture = read_fixture() if fixture is None else fixture
    return TrainingScoreFixture(
        fixture,
        (
            PhysicalGoal("goal:1", 20, 1, 20, 10, 10, 2, False, 4),
            PhysicalGoal("goal:2", 75, 2, 26, 20, 10, 2, True, 21),
            PhysicalGoal("goal:3", 104, 2, 55, 20, 20, 4, False, 44),
        ),
        (PhysicalPeriod(1, 49), PhysicalPeriod(2, 55)),
        104,
        1,
        2,
        (FPLCredit("goal:1", 2, 1), FPLCredit("goal:2", None, 4), FPLCredit("goal:3", 4, 3)),
        (
            ObservedPlayerExposure(1, 10, 0, 104, 90, 1, "full_time"),
            ObservedPlayerExposure(2, 10, 0, 100, 90, 1, "normal_substitution"),
            ObservedPlayerExposure(3, 20, 0, 104, 90, 1, "full_time"),
            ObservedPlayerExposure(4, 20, 49, 104, 45, 0, "full_time"),
        ),
        "2024-10-05T15:00:00Z",
        "c" * 64,
    )


def outcome_document(fixture: ScoreFixture) -> dict[str, Any]:
    outcome = json.loads(json.dumps(asdict(training(fixture))))
    outcome.pop("input")
    outcome.pop("outcome_sha256")
    outcome["dismissal_events"] = []
    return {
        "version": RAW_SCORE_OUTCOME_VERSION,
        "season": fixture.season,
        "gameweek": fixture.gameweek,
        "fixture_id": fixture.fixture_id,
        "input_sha256": score_input_digest(fixture),
        "captured_at": "2024-10-05T15:05:00Z",
        "published_at": "2024-10-05T15:10:00Z",
        "rights": {"model_use_claim": True, "evidence_ref": "invented-final-source-permission"},
        "coverage": {
            "physical_events_complete": True,
            "physical_periods_complete": True,
            "physical_exposures_complete": True,
            "fpl_credits_complete": True,
            "fpl_credit_scope": "final_fpl_goal_assist_credits_v1",
            "dismissals_complete": True,
            "evidence_ref": "invented-final-observation-coverage",
        },
        "outcome": outcome,
    }


def read_outcomes(
    document: dict[str, Any] | None = None, fixture: ScoreFixture | None = None
) -> TrainingScoreFixture:
    fixture = read_fixture() if fixture is None else fixture
    raw, digest = encode(outcome_document(fixture) if document is None else document)
    return read_score_outcomes(
        raw,
        sha256=digest,
        fixture=fixture,
        fit_cutoff=CUTOFF,
        target_season="2024-25",
        target_gameweeks=(11,),
    )


@pytest.mark.parametrize("representation", ("four_bins", "seven_roles"))
def test_original_bytes_preserve_explicit_native_support_and_independent_physical_intervals(
    representation,
):
    fixture = read_fixture(representation=representation)
    assert fixture.forecast_duration == 100
    assert fixture.players[0].physical_off[-1] == 100
    assert fixture.players[0].credited_minutes[-1] == 90
    assert fixture.players[0].minute_representation == representation
    assert len(fixture.players[0].probabilities) == (4 if representation == "four_bins" else 7)
    assert fixture.native_home_goals == 1.8 and fixture.native_away_goals == 1.2
    assert fixture.source_sha256 == encode(snapshot_document(representation))[1]
    with pytest.raises(FrozenInstanceError):
        fixture.players[0].physical_off = ()


def test_actual_final_duration_and_stoppage_goal_do_not_replace_predecision_forecast():
    fixture = read_fixture()
    before = score_input_digest(fixture)
    row = read_outcomes(fixture=fixture)
    assert row.actual_duration == 104 != fixture.forecast_duration
    assert row.goals[-1].elapsed == 104 and row.goals[-1].period_elapsed == 55
    assert row.exposures[-1].physical_off - row.exposures[-1].physical_on == 55
    assert row.exposures[-1].credited_minutes == 45
    assert score_input_digest(fixture) == before
    assert row.final_home_goals == 1 and row.final_away_goals == 2
    assert row.input is fixture


def test_physical_own_goal_and_final_fpl_credit_are_separate_accounting():
    row = read_outcomes()
    own = row.goals[1]
    assert own.own_goal and own.scorer_club_code == 10 and own.beneficiary_club_code == 20
    assert row.fpl_credits[1].scorer_player_code is None
    assert row.fpl_credits[1].assist_player_code == 4
    assert sum(c.scorer_player_code is not None for c in row.fpl_credits) == 2
    assert row.final_home_goals + row.final_away_goals == 3


def test_own_goal_with_unknown_scorer_still_requires_opposing_scorer_club():
    row = training()
    own = replace(
        row.goals[1], scorer_player_code=None, scorer_club_code=row.goals[1].beneficiary_club_code
    )
    with pytest.raises(ValueError, match="Own goals must benefit the opposing"):
        validate_training_score_fixture(replace(row, goals=(row.goals[0], own, row.goals[2])))


def test_physical_period_elapsed_binds_the_cumulative_goal_clock():
    row = training()
    altered = replace(row.goals[1], period_elapsed=row.goals[1].period_elapsed + 1)
    with pytest.raises(ValueError, match="period clock contradicts"):
        validate_training_score_fixture(replace(row, goals=(row.goals[0], altered, row.goals[2])))


def test_normal_substitution_and_full_time_have_separately_recorded_horizons():
    row = read_outcomes()
    assert row.exposures[1].exit_policy == "normal_substitution"
    assert row.exposures[1].physical_off == 100 < row.actual_duration
    assert row.exposures[0].exit_policy == "full_time"
    assert row.exposures[0].physical_off == row.actual_duration


def test_zero_goal_fixture_and_verified_nonappearance_remain_explicit():
    fixture = read_fixture()
    document = outcome_document(fixture)
    document["outcome"].update(goals=[], fpl_credits=[], final_home_goals=0, final_away_goals=0)
    document["outcome"]["exposures"][-1].update(
        physical_on=0, physical_off=0, credited_minutes=0, starts=0, exit_policy="not_playing"
    )
    row = read_outcomes(document, fixture)
    assert row.goals == () and row.fpl_credits == ()
    assert row.exposures[-1].credited_minutes == 0


def test_equal_elapsed_events_keep_original_ordinal_and_pre_event_updates():
    row = training()
    second = replace(row.goals[1], elapsed=20, period=1, period_elapsed=20)
    validate_training_score_fixture(replace(row, goals=(row.goals[0], second, row.goals[2])))
    with pytest.raises(ValueError, match="chronology"):
        validate_training_score_fixture(replace(row, goals=(second, row.goals[0], row.goals[2])))


def test_source_clocks_use_utc_equivalent_declared_dst_offsets():
    document = snapshot_document()
    document["projection"]["decision_at"] = "2024-10-05T13:00:00+03:00"
    document["projection"]["deadline_at"] = "2024-10-05T12:00:00+01:00"
    document["projection"]["kickoff"] = "2024-10-05T15:00:00+03:00"
    for side in document["calendar"]:
        side["kickoff"] = "2024-10-05T13:00:00+01:00"
    assert score_input_digest(read_fixture(document)) != score_input_digest(read_fixture())
    original = read_fixture()
    shifted = replace(
        original, decision_at="2024-10-05T13:00:00+03:00", kickoff="2024-10-05T13:00:00+01:00"
    )
    assert score_input_digest(original) == score_input_digest(shifted)


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "unknown"),
        ("captured_at", DECISION),
        ("published_at", DECISION),
        ("captured_at", "2024-10-05T09:30:00Z"),
        ("published_at", "2024-10-05T09:00:00Z"),
        ("captured_at", "2024-10-05T09:00:00"),
    ],
)
def test_original_snapshot_version_and_availability_clocks_refuse(field, value):
    document = snapshot_document()
    document[field] = value
    with pytest.raises(ValueError):
        read_fixture(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("season", "2023-24"),
        ("gameweek", True),
        ("fixture_id", "101"),
        ("native_basis_sha256", "d" * 64),
        ("native_model_version", "unproven_v1"),
        ("native_basis_kind", "in_sample"),
        ("native_basis_fit_cutoff", DECISION),
        ("clock_version", "fpl_credited_minutes"),
        ("forecast_duration", None),
        ("forecast_duration", True),
        ("native_home_goals", -0.1),
        ("native_away_goals", float("inf")),
        ("home_club_code", 20),
        ("kickoff", DEADLINE),
        ("kickoff", "2028-10-05T12:00:00Z"),
        ("decision_at", DEADLINE),
    ],
)
def test_native_header_identity_physical_clock_and_original_version_refuse(field, value):
    document = snapshot_document()
    document["projection"][field] = value
    with pytest.raises(ValueError):
        read_fixture(document)


@pytest.mark.parametrize(
    "kind",
    [
        "permission",
        "permission-ref",
        "native-future",
        "native-order",
        "native-after-parent",
        "fit-after-native",
        "coverage",
        "clock-known",
        "exit-known",
        "missing-player",
        "duplicate-player",
        "coverage-ref",
    ],
)
def test_native_receipt_permission_and_complete_coverage_refuse(kind):
    document = snapshot_document()
    if kind == "permission":
        document["rights"]["model_use_claim"] = False
    elif kind == "permission-ref":
        document["rights"]["evidence_ref"] = None
    elif kind == "native-future":
        document["native_basis_clock"]["published_at"] = DECISION
    elif kind == "native-order":
        document["native_basis_clock"]["published_at"] = "2024-10-05T08:59:00Z"
    elif kind == "native-after-parent":
        document["native_basis_clock"].update(
            captured_at="2024-10-05T09:11:00Z", published_at="2024-10-05T09:12:00Z"
        )
    elif kind == "fit-after-native":
        document["projection"]["native_basis_fit_cutoff"] = "2024-10-05T09:01:00Z"
    elif kind in ("coverage", "clock-known", "exit-known"):
        document["coverage"][
            {
                "coverage": "complete",
                "clock-known": "physical_clock_known",
                "exit-known": "exit_policies_known",
            }[kind]
        ] = None
    elif kind == "missing-player":
        document["coverage"]["player_codes"].pop()
    elif kind == "duplicate-player":
        document["coverage"]["player_codes"].append(1)
    else:
        document["coverage"]["evidence_ref"] = "wrong"
    with pytest.raises(ValueError):
        read_fixture(document)


@pytest.mark.parametrize(
    "kind",
    [
        "person-provider",
        "person-duplicate",
        "person-club",
        "person-late",
        "person-missing",
        "club-provider",
        "club-duplicate",
        "club-missing",
        "club-late",
        "calendar-duplicate",
        "calendar-side",
        "calendar-late",
        "calendar-kickoff",
        "calendar-fixture",
        "calendar-missing",
    ],
)
def test_persistent_person_club_and_paired_calendar_refuse(kind):
    document = snapshot_document()
    if kind == "person-provider":
        document["person_mapping"][1]["provider_id"] = document["person_mapping"][0]["provider_id"]
    elif kind == "person-duplicate":
        document["person_mapping"][1]["player_code"] = 1
    elif kind == "person-club":
        document["person_mapping"][0]["club_code"] = 20
    elif kind == "person-late":
        document["person_mapping"][0]["available_at"] = DECISION
    elif kind == "person-missing":
        document["person_mapping"].pop()
    elif kind == "club-provider":
        document["club_mapping"][1]["provider_id"] = "club:10"
    elif kind == "club-duplicate":
        document["club_mapping"][1]["club_code"] = 10
    elif kind == "club-missing":
        document["club_mapping"].pop()
    elif kind == "club-late":
        document["club_mapping"][0]["available_at"] = DECISION
    elif kind == "calendar-duplicate":
        document["calendar"][1] = copy.deepcopy(document["calendar"][0])
    elif kind == "calendar-side":
        document["calendar"][1]["home"] = 1
    elif kind == "calendar-late":
        document["calendar"][0]["available_at"] = DECISION
    elif kind == "calendar-kickoff":
        document["calendar"][1]["kickoff"] = "2024-10-05T12:01:00Z"
    elif kind == "calendar-fixture":
        document["calendar"][0]["fixture_id"] = 102
    else:
        document["calendar"].pop()
    with pytest.raises(ValueError):
        read_fixture(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("probabilities", (0.2,) * 7),
        ("probabilities", (True, 0, 0, 0, 0, 0, 0)),
        ("probabilities", (0.2, 0.1, -0.25, 0.7, 0.1, 0.1, 0.05)),
        ("probabilities", ("0.2", 0.1, 0.25, 0.2, 0.1, 0.1, 0.05)),
        ("credited_minutes", (0, 60, 75, 90, 20, 65, 90)),
        ("credited_minutes", (0, 40, 90, 90, 20, 65, 90)),
        ("physical_on", (0, 1, 0, 0, 60, 30, 5)),
        ("physical_off", (0, 39, 75, 100, 80, 95, 100)),
        ("physical_off", (0, 40, 75, 99, 80, 95, 100)),
        (
            "exit_policies",
            (
                "not_playing",
                "dismissal",
                "normal_substitution",
                "full_time",
                "normal_substitution",
                "normal_substitution",
                "full_time",
            ),
        ),
        ("minute_representation", "unknown"),
        ("player_code", True),
        ("club_code", 30),
        ("position", "WING"),
    ],
)
def test_declared_role_support_and_physical_exit_policy_refuse(field, value):
    fixture = read_fixture()
    changed = replace(fixture.players[0], **{field: value})
    with pytest.raises(ValueError):
        validate_score_fixture(replace(fixture, players=(changed, *fixture.players[1:])))


def test_native_representation_is_explicit_not_guessed_from_support_length():
    fixture = projection("four_bins")
    validate_score_fixture(fixture)
    with pytest.raises(ValueError, match="four-bin"):
        validate_score_fixture(replace(projection(), native_model_version="football_team_share_v1"))
    with pytest.raises(ValueError, match=r"four-bin|representation"):
        validate_score_fixture(
            replace(
                fixture,
                players=(
                    replace(fixture.players[0], minute_representation="seven_roles"),
                    *fixture.players[1:],
                ),
            )
        )
    fallback = replace(fixture, native_model_version="football_joint_role_minutes_v1")
    validate_score_fixture(fallback)


def test_immutable_digest_binds_every_forecast_interval_and_native_total():
    original = read_fixture()
    changed = replace(
        original,
        players=(
            replace(original.players[0], physical_off=(0, 41, 75, 100, 80, 95, 100)),
            *original.players[1:],
        ),
    )
    assert score_input_digest(changed) != score_input_digest(original)
    assert score_input_digest(replace(original, native_home_goals=1.9)) != score_input_digest(
        original
    )
    with pytest.raises(ValueError, match="immutable"):
        validate_score_fixture(replace(original, players=list(original.players)))


@pytest.mark.parametrize(
    "season,gameweek", [("2025-26", 1), ("2024-25", 11), ("2024-25", 12), ("2026-27", 1)]
)
def test_protected_target_and_future_headers_refuse_before_any_outcome_bytes(
    season, gameweek, monkeypatch
):
    fixture = projection()
    year = season[:4]
    fixture = replace(fixture, season=season, gameweek=gameweek, kickoff=f"{year}-10-05T12:00:00Z")
    decoded = []

    def forbidden(*args, **kwargs):
        decoded.append(True)
        raise AssertionError("Outcome decode must not be reached")

    monkeypatch.setattr(source, "_json", forbidden)
    with pytest.raises(ValueError):
        read_score_outcomes(
            b"not-outcomes",
            sha256="e" * 64,
            fixture=fixture,
            fit_cutoff=CUTOFF,
            target_season="2024-25",
            target_gameweeks=(11,),
        )
    assert decoded == []


def test_header_preflight_does_not_inspect_goal_or_player_outcomes():
    row = training()
    poisoned = replace(row, goals=object(), exposures=object(), actual_duration=object())
    validate_training_score_header(
        poisoned, fit_cutoff=CUTOFF, target_season="2024-25", target_gameweeks=(11,)
    )
    with pytest.raises(ValueError, match="settlement"):
        validate_training_score_header(
            replace(poisoned, settled_at=CUTOFF),
            fit_cutoff=CUTOFF,
            target_season="2024-25",
            target_gameweeks=(11,),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("actual_duration", 100),
        ("actual_duration", None),
        ("periods", (PhysicalPeriod(2, 49), PhysicalPeriod(1, 55))),
        ("periods", (PhysicalPeriod(1, 49),)),
        ("periods", (PhysicalPeriod(1, 49), PhysicalPeriod(2, True))),
        ("settled_at", KICKOFF),
        ("settled_at", "2024-10-05T13:00:00Z"),
        ("final_home_goals", 2),
        ("final_away_goals", True),
    ],
)
def test_final_actual_clock_periods_and_physical_score_refuse(field, value):
    with pytest.raises(ValueError):
        validate_training_score_fixture(replace(training(), **{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", "goal:1"),
        ("ordinal", 4),
        ("ordinal", True),
        ("elapsed", 19),
        ("elapsed", 105),
        ("period_elapsed", 27),
        ("period", 3),
        ("scorer_club_code", 20),
        ("beneficiary_club_code", 30),
        ("own_goal", False),
        ("scorer_player_code", 4),
        ("own_goal", "true"),
    ],
)
def test_ordered_unique_physical_events_and_own_goal_identity_refuse(field, value):
    row = training()
    altered = replace(row.goals[1], **{field: value})
    with pytest.raises(ValueError):
        validate_training_score_fixture(replace(row, goals=(row.goals[0], altered, row.goals[2])))


def test_period_endpoints_need_original_first_then_second_period_order():
    row = training()
    first = replace(row.goals[0], elapsed=49, period=2, period_elapsed=0)
    second = replace(row.goals[1], elapsed=49, period=1, period_elapsed=49)
    with pytest.raises(ValueError, match="backwards"):
        validate_training_score_fixture(replace(row, goals=(first, second, row.goals[2])))


@pytest.mark.parametrize("kind", ["before-entry", "after-exit", "not-playing"])
def test_known_physical_scorer_requires_observed_goal_time_exposure(kind):
    row = training()
    exposures = list(row.exposures)
    scorer = exposures[1]
    if kind == "before-entry":
        scorer = replace(scorer, physical_on=80, credited_minutes=10, starts=0)
    elif kind == "after-exit":
        scorer = replace(scorer, physical_off=10, credited_minutes=10)
    else:
        scorer = replace(
            scorer,
            physical_on=0,
            physical_off=0,
            credited_minutes=0,
            starts=0,
            exit_policy="not_playing",
        )
    exposures[1] = scorer
    with pytest.raises(ValueError, match="on the pitch"):
        validate_training_score_fixture(replace(row, exposures=tuple(exposures)))


def test_unplayed_assister_cannot_receive_a_final_credit():
    row = training()
    exposures = list(row.exposures)
    exposures[0] = replace(
        exposures[0],
        physical_on=0,
        physical_off=0,
        credited_minutes=0,
        starts=0,
        exit_policy="not_playing",
    )
    with pytest.raises(ValueError, match="positive observed"):
        validate_training_score_fixture(replace(row, exposures=tuple(exposures)))


@pytest.mark.parametrize(
    "kind",
    [
        "own-positive",
        "unknown-scorer",
        "wrong-scorer",
        "self-assist",
        "wrong-assist-club",
        "duplicate",
        "missing",
        "wrong-event",
        "bool-player",
    ],
)
def test_final_fpl_credits_have_separate_scope_and_no_self_assist(kind):
    row = training()
    credits = list(row.fpl_credits)
    if kind == "own-positive":
        credits[1] = replace(credits[1], scorer_player_code=2)
    elif kind == "unknown-scorer":
        credits[0] = replace(credits[0], scorer_player_code=None)
    elif kind == "wrong-scorer":
        credits[0] = replace(credits[0], scorer_player_code=1)
    elif kind == "self-assist":
        credits[0] = replace(credits[0], assist_player_code=2)
    elif kind == "wrong-assist-club":
        credits[1] = replace(credits[1], assist_player_code=1)
    elif kind == "duplicate":
        credits[1] = credits[0]
    elif kind == "missing":
        credits.pop()
    elif kind == "wrong-event":
        credits[0] = replace(credits[0], goal_event_id="not-a-goal")
    else:
        credits[1] = replace(credits[1], assist_player_code=True)
    with pytest.raises(ValueError):
        validate_training_score_fixture(replace(row, fpl_credits=tuple(credits)))


@pytest.mark.parametrize(
    "field,value",
    [
        ("player_code", 99),
        ("club_code", 20),
        ("physical_on", 1),
        ("physical_off", 104),
        ("credited_minutes", None),
        ("credited_minutes", 101),
        ("starts", None),
        ("starts", True),
        ("exit_policy", "dismissal"),
    ],
)
def test_final_exposure_recorded_starts_and_exit_policy_are_not_inferred(field, value):
    row = training()
    exposure = replace(row.exposures[1], **{field: value})
    with pytest.raises(ValueError):
        validate_training_score_fixture(
            replace(row, exposures=(row.exposures[0], exposure, *row.exposures[2:]))
        )


@pytest.mark.parametrize(
    "kind",
    [
        "missing-exposure",
        "duplicate-exposure",
        "dismissal",
        "not-final",
        "wrong-fpl-scope",
        "future-publication",
        "before-settlement",
        "wrong-input",
        "wrong-fixture",
        "permission",
        "extra-target-label",
    ],
)
def test_complete_outcomes_finalization_and_input_receipts_refuse(kind):
    fixture = read_fixture()
    document = outcome_document(fixture)
    if kind == "missing-exposure":
        document["outcome"]["exposures"].pop()
    elif kind == "duplicate-exposure":
        document["outcome"]["exposures"][1] = copy.deepcopy(document["outcome"]["exposures"][0])
    elif kind == "dismissal":
        document["outcome"]["dismissal_events"] = [{"event_id": "red:1"}]
    elif kind == "not-final":
        document["coverage"]["physical_events_complete"] = None
    elif kind == "wrong-fpl-scope":
        document["coverage"]["fpl_credit_scope"] = "generic_provider_assists"
    elif kind == "future-publication":
        document["published_at"] = CUTOFF
    elif kind == "before-settlement":
        document["captured_at"] = "2024-10-05T14:59:00Z"
    elif kind == "wrong-input":
        document["input_sha256"] = "f" * 64
    elif kind == "wrong-fixture":
        document["fixture_id"] = 102
    elif kind == "permission":
        document["rights"]["model_use_claim"] = False
    else:
        document["outcome"]["future_target_score"] = 4
    with pytest.raises(ValueError):
        read_outcomes(document, fixture)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"version":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":-Infinity}',
        b"[]",
        b"null",
        b"\xff",
    ],
)
def test_strict_original_json_refuses_duplicate_nonfinite_and_encoding(raw):
    with pytest.raises(ValueError):
        read_score_snapshot(
            raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            season="2024-25",
            gameweek=10,
            fixture_id=101,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_basis_sha256=BASE_SHA,
        )


def test_source_hash_exact_fields_and_bounded_immutable_bytes_are_enforced(monkeypatch):
    raw, digest = encode(snapshot_document())
    for payload, stated in ((raw, "0" * 64), (bytearray(raw), digest), (b"", digest)):
        with pytest.raises(ValueError):
            read_score_snapshot(
                payload,
                sha256=stated,
                season="2024-25",
                gameweek=10,
                fixture_id=101,
                decision_at=DECISION,
                deadline_at=DEADLINE,
                native_basis_sha256=BASE_SHA,
            )
    document = snapshot_document()
    document["projection"]["actual_duration"] = 104
    with pytest.raises(ValueError, match="exact field"):
        read_fixture(document)
    document = snapshot_document()
    del document["projection"]["players"][0]["physical_off"]
    with pytest.raises(ValueError, match="exact field"):
        read_fixture(document)
    monkeypatch.setattr(source, "MAX_SOURCE_BYTES", len(raw) - 1)
    with pytest.raises(ValueError, match="bounded"):
        read_fixture()


def test_oversized_native_numbers_are_refused_as_source_validation_errors():
    with pytest.raises(ValueError, match="finite"):
        validate_score_fixture(replace(projection(), native_home_goals=10**1000))
