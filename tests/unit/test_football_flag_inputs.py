"""Synthetic source contracts: exact bindings, nullable facts and causal refusal."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, fields, replace
from typing import Any

import pytest

from squadopt.data.errors import DataError
from squadopt.features import football_flag_inputs
from squadopt.features.football_flag_inputs import (
    MAX_SOURCE_BYTES,
    RAW_FLAG_CAPTURE_VERSION,
    RAW_FLAG_OUTCOME_VERSION,
    MinuteFixture,
    PlayerWeekInput,
    TrainingWeek,
    input_digest,
    read_flag_outcome_source,
    read_flag_week_source,
    validate_training_week,
    validate_week_input,
)

DECISION = "2024-10-04T12:00:00Z"
DEADLINE = "2024-10-05T10:00:00Z"
FIT_CUTOFF = "2024-10-11T12:00:00Z"
BASIS = "b" * 64


def native_fixtures(count: int = 1) -> tuple[MinuteFixture, ...]:
    return tuple(
        MinuteFixture(
            fixture=101 + index,
            kickoff=f"2024-10-{5 + index * 2:02d}T15:00:00Z",
            club=20,
            opponent=30 + index,
            home=index % 2,
            probabilities=(0.2, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05),
            minutes=(0.0, 40.0, 75.0, 90.0, 12.0, 65.0, 90.0),
        )
        for index in range(count)
    )


def capture_document(count: int = 1) -> dict[str, Any]:
    captures = [
        {
            "captured_at": "2024-10-03T10:00:00Z",
            "published_at": "2024-10-03T10:01:00Z",
            "element_id": 123,
            "player_code": 1001,
            "club_code": 20,
            "current_event_id": 9,
            "next_event_id": 10,
            "status": "d",
            "chance_of_playing_this_round": 25,
            "chance_of_playing_next_round": 75,
            "news": "Synthetic minor complaint",
            "news_added": "2024-10-03T09:00:00Z",
        },
        {
            "captured_at": "2024-10-04T10:00:00Z",
            "published_at": "2024-10-04T10:01:00Z",
            "element_id": 123,
            "player_code": 1001,
            "club_code": 20,
            "current_event_id": 9,
            "next_event_id": 10,
            "status": "d",
            "chance_of_playing_this_round": 25,
            "chance_of_playing_next_round": 50,
            "news": "Synthetic minor complaint",
            "news_added": "2024-10-03T09:00:00Z",
        },
    ]
    return {
        "version": RAW_FLAG_CAPTURE_VERSION,
        "season": "2024-25",
        "gameweek": 10,
        "player_code": 1001,
        "position": "DEF",
        "mapping_verified": True,
        "mapping_evidence_ref": "synthetic-exact-player-mapping",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-permission",
        "calendar_complete": True,
        "covered_gameweeks": [10],
        "fixture_ids": [fixture.fixture for fixture in native_fixtures(count)],
        "calendar_evidence_ref": "synthetic-complete-club-calendar",
        "history_covered": True,
        "history_start_at": captures[0]["captured_at"],
        "history_end_at": captures[-1]["captured_at"],
        "expected_capture_count": 2,
        "history_evidence_ref": "synthetic-complete-capture-inventory",
        "captures": captures,
        "native_basis_sha256": BASIS,
        "native_basis_evidence_ref": "synthetic-held-fold",
        "native_basis_kind": "out_of_fold",
        "native_basis_fit_cutoff": "2024-10-01T00:00:00Z",
    }


def encoded(document: dict[str, Any]) -> tuple[bytes, str]:
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def read_week(document: dict[str, Any] | None = None, count: int = 1) -> PlayerWeekInput:
    raw, sha = encoded(capture_document(count) if document is None else document)
    return read_flag_week_source(
        raw,
        sha256=sha,
        season="2024-25",
        gameweek=10,
        player_code=1001,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        native_fixtures=native_fixtures(count),
        native_basis_sha256=BASIS,
    )


def outcome_document(week: PlayerWeekInput) -> dict[str, Any]:
    return {
        "version": RAW_FLAG_OUTCOME_VERSION,
        "season": week.season,
        "gameweek": week.gameweek,
        "player_code": week.player_code,
        "input_sha256": input_digest(week),
        "settled_at": "2024-10-10T00:00:00Z",
        "captured_at": "2024-10-10T01:00:00Z",
        "published_at": "2024-10-10T01:01:00Z",
        "mapping_verified": True,
        "mapping_evidence_ref": "synthetic-exact-outcome-mapping",
        "model_use_approved": True,
        "model_use_evidence_ref": "synthetic-permission",
        "calendar_complete": True,
        "covered_gameweeks": list(week.covered_gameweeks),
        "fixture_ids": [fixture.fixture for fixture in week.fixtures],
        "observations": [
            {
                "fixture": fixture.fixture,
                "kickoff": fixture.kickoff,
                "club": fixture.club,
                "opponent": fixture.opponent,
                "home": fixture.home,
                "minutes": 90,
                "starts": 1,
                "state": 3,
            }
            for fixture in week.fixtures
        ],
    }


def read_outcome(document: dict[str, Any], week: PlayerWeekInput) -> TrainingWeek:
    raw, sha = encoded(document)
    return read_flag_outcome_source(
        raw,
        sha256=sha,
        week=week,
        fit_cutoff=FIT_CUTOFF,
        target_season="2024-25",
        target_gameweeks=(11,),
    )


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_sgw_dgw_three_fixture_and_explicit_bgw_sources(count: int) -> None:
    week = read_week(count=count)
    assert week.label == 50
    assert week.news_state == "flagged"
    assert week.news_age_hours == 27
    assert week.capture_age_hours == 2
    assert week.label_changed is True
    assert len(week.fixtures) == count
    row = read_outcome(outcome_document(week), week)
    assert row.observed_states == (3,) * count
    assert len(input_digest(week)) == 64


def test_current_and_next_labels_are_never_substituted() -> None:
    document = capture_document()
    for capture in document["captures"]:
        capture["current_event_id"] = 10
        capture["next_event_id"] = 11
        capture["chance_of_playing_this_round"] = 75
        capture["chance_of_playing_next_round"] = 0
    week = read_week(document)
    assert week.label == 75
    assert week.legacy_next_round_label == 0
    assert week.label_changed is False


@pytest.mark.parametrize("legacy_label", [75, None])
def test_target_current_label_keeps_original_latest_legacy_next_label(
    legacy_label: int | None,
) -> None:
    document = capture_document()
    for capture in document["captures"]:
        capture["current_event_id"] = 10
        capture["next_event_id"] = 11
        capture["chance_of_playing_this_round"] = 25
        capture["chance_of_playing_next_round"] = 0
    document["captures"][-1]["chance_of_playing_next_round"] = legacy_label
    week = read_week(document)
    assert week.label == 25
    assert week.legacy_next_round_label == legacy_label
    assert week.label_changed is False


def test_direct_week_constructor_defaults_legacy_next_label_to_null() -> None:
    recorded = read_week()
    values = {
        field.name: getattr(recorded, field.name)
        for field in fields(PlayerWeekInput)
        if field.name != "legacy_next_round_label"
    }
    week = PlayerWeekInput(**values)
    assert week.legacy_next_round_label is None
    validate_week_input(week)


@pytest.mark.parametrize("label", [0, 25, 50, 75, 100])
def test_editorial_labels_do_not_modify_the_supplied_native_distribution(label: int) -> None:
    document = capture_document()
    document["captures"][-1]["chance_of_playing_next_round"] = label
    week = read_week(document)
    assert week.label == label
    assert week.fixtures == native_fixtures()


def test_same_instant_capture_and_archive_publication_is_valid() -> None:
    document = capture_document()
    for capture in document["captures"]:
        capture["published_at"] = capture["captured_at"]
    assert read_week(document).capture_age_hours == 2


@pytest.mark.parametrize(
    ("news", "stamp", "state", "age"),
    [
        (None, None, "unknown", None),
        ("", None, "never_flagged", None),
        ("", "2024-10-03T09:00:00Z", "cleared", 27.0),
        ("Synthetic note", None, "flagged", None),
    ],
)
def test_explicit_null_and_cleared_news_keep_distinct_states(
    news: str | None,
    stamp: str | None,
    state: str,
    age: float | None,
) -> None:
    document = capture_document()
    latest = document["captures"][-1]
    latest.update(news=news, news_added=stamp, chance_of_playing_next_round=None, status=None)
    week = read_week(document)
    assert week.news_state == state
    assert week.news_age_hours == age
    assert week.status is None and week.label is None and week.label_changed is None


def test_uncovered_history_does_not_invent_an_unchanged_label() -> None:
    document = capture_document()
    document.update(
        history_covered=False, history_start_at=None, history_end_at=None, history_evidence_ref=None
    )
    assert read_week(document).label_changed is None


def test_native_and_source_identity_are_bound_in_digest_and_frozen() -> None:
    week = read_week()
    changed = replace(week, native_basis_evidence_ref="different-proof")
    assert input_digest(changed) != input_digest(week)
    assert input_digest(replace(week, label=75)) != input_digest(week)
    assert input_digest(replace(week, legacy_next_round_label=75)) != input_digest(week)
    with pytest.raises(FrozenInstanceError):
        week.label = 75  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        week.fixtures[0].home = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", "unknown"),
        ("mapping_verified", False),
        ("model_use_approved", False),
        ("mapping_verified", 1),
        ("model_use_evidence_ref", ""),
        ("calendar_complete", False),
        ("covered_gameweeks", [11]),
        ("covered_gameweeks", [10, 10]),
        ("fixture_ids", []),
        ("native_basis_sha256", "c" * 64),
        ("native_basis_kind", "in_sample"),
        ("native_basis_fit_cutoff", DECISION),
        ("legacy_next_round_label", True),
        ("legacy_next_round_label", "75"),
        ("legacy_next_round_label", 75.0),
        ("legacy_next_round_label", 80),
        ("native_basis_evidence_ref", ""),
        ("expected_capture_count", 3),
        ("history_end_at", "2024-10-04T11:00:00Z"),
        ("position", "STRIKER"),
        ("player_code", True),
        ("gameweek", "10"),
    ],
)
def test_source_header_refusals(field: str, value: object) -> None:
    document = capture_document()
    document[field] = value
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("captured_at", "2024-10-04T12:01:00Z"),
        ("published_at", DECISION),
        ("published_at", "2024-10-04T09:00:00Z"),
        ("news_added", "2024-10-04T11:00:00Z"),
        ("captured_at", "2024-10-04T10:00:00"),
        ("captured_at", "2024-10-04T13:00:00+03:00"),
        ("chance_of_playing_next_round", True),
        ("chance_of_playing_next_round", "75"),
        ("chance_of_playing_next_round", 80),
        ("chance_of_playing_this_round", -1),
        ("current_event_id", 10),
        ("next_event_id", 11),
        ("status", "unknown"),
        ("news", 1),
        ("element_id", 456),
        ("player_code", 1002),
        ("club_code", 99),
    ],
)
def test_original_capture_values_and_clocks_are_strict(field: str, value: object) -> None:
    document = capture_document()
    document["captures"][-1][field] = value
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize("kind", ["reverse", "duplicate", "missing", "extra"])
def test_capture_inventory_refuses_reordering_duplicates_and_schema_changes(kind: str) -> None:
    document = capture_document()
    if kind == "reverse":
        document["captures"].reverse()
    elif kind == "duplicate":
        document["captures"][-1] = dict(document["captures"][0])
    elif kind == "missing":
        del document["captures"][-1]["news"]
    else:
        document["captures"][-1]["guessed_injury"] = False
    with pytest.raises(DataError):
        read_week(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("probabilities", (0.1,) * 7),
        ("probabilities", (float("nan"),) + (0.0,) * 6),
        ("probabilities", (float("inf"),) + (0.0,) * 6),
        ("probabilities", (True,) + (0.0,) * 6),
        ("probabilities", [0.2, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05]),
        ("minutes", (0.0, 60.0, 75.0, 90.0, 12.0, 65.0, 90.0)),
        ("minutes", (0.0, 40.0, 90.0, 90.0, 12.0, 65.0, 90.0)),
        ("minutes", (0.0, 40.0, 75.0, 89.0, 12.0, 65.0, 90.0)),
        ("minutes", (0.0,) * 6),
        ("home", True),
        ("club", 0),
        ("opponent", 20),
        ("fixture", "101"),
        ("kickoff", "2024-10-05T09:00:00Z"),
    ],
)
def test_native_minute_support_and_identity_are_validated(field: str, value: Any) -> None:
    week = read_week()
    fixture = replace(week.fixtures[0], **{field: value})
    with pytest.raises(DataError):
        validate_week_input(replace(week, fixtures=(fixture,)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("season", "2024-26"),
        ("gameweek", True),
        ("decision_at", DEADLINE),
        ("news_age_hours", float("nan")),
        ("capture_age_hours", -1),
        ("label_changed", "false"),
        ("source_sha256", "F" * 64),
        ("calendar_complete", 1),
        ("covered_gameweeks", (11,)),
        ("native_basis_fit_cutoff", DECISION),
    ],
)
def test_manual_week_inputs_cannot_bypass_receipts(field: str, value: Any) -> None:
    with pytest.raises(DataError):
        validate_week_input(replace(read_week(), **{field: value}))


def test_duplicate_fixture_club_and_bounded_support_refusals() -> None:
    week = read_week(count=2)
    for fixtures in (
        (week.fixtures[0], week.fixtures[0]),
        (week.fixtures[0], replace(week.fixtures[1], club=21)),
        native_fixtures(4),
    ):
        with pytest.raises(DataError):
            validate_week_input(replace(week, fixtures=fixtures))


@pytest.mark.parametrize("full_minutes", [90.0, 91.0, 120.0])
def test_native_full_support_includes_recorded_duration_through_120(full_minutes: float) -> None:
    week = read_week()
    fixture = replace(
        week.fixtures[0], minutes=(0.0, 40.0, 75.0, full_minutes, 12.0, 65.0, full_minutes)
    )
    validate_week_input(replace(week, fixtures=(fixture,)))


@pytest.mark.parametrize("state", [3, 6])
def test_native_full_support_refuses_duration_over_120(state: int) -> None:
    week = read_week()
    minutes = list(week.fixtures[0].minutes)
    minutes[state] = 121.0
    fixture = replace(week.fixtures[0], minutes=tuple(minutes))
    with pytest.raises(DataError, match="full minute states"):
        validate_week_input(replace(week, fixtures=(fixture,)))


@pytest.mark.parametrize(
    ("minutes", "starts", "state"),
    [
        (0, 0, 0),
        (1, 1, 1),
        (59, 1, 1),
        (60, 1, 2),
        (89, 1, 2),
        (90, 1, 3),
        (91, 1, 3),
        (120, 1, 3),
        (1, 0, 4),
        (59, 0, 4),
        (60, 0, 5),
        (89, 0, 5),
        (90, 0, 6),
        (91, 0, 6),
        (120, 0, 6),
    ],
)
def test_observed_states_use_recorded_starts_and_all_minute_boundaries(
    minutes: int,
    starts: int,
    state: int,
) -> None:
    week = read_week()
    document = outcome_document(week)
    document["observations"][0].update(minutes=minutes, starts=starts, state=state)
    assert read_outcome(document, week).observed_states == (state,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("starts", None),
        ("starts", True),
        ("starts", "1"),
        ("starts", 2),
        ("minutes", 90.0),
        ("minutes", -1),
        ("minutes", 121),
        ("state", 2),
        ("fixture", 102),
        ("club", 21),
        ("opponent", 31),
        ("home", 1),
        ("kickoff", "2024-10-06T15:00:00Z"),
    ],
)
def test_observation_labels_are_explicit_not_inferred(field: str, value: object) -> None:
    week = read_week()
    document = outcome_document(week)
    document["observations"][0][field] = value
    with pytest.raises(DataError):
        read_outcome(document, week)


def test_zero_minutes_cannot_be_a_recorded_start() -> None:
    week = read_week()
    document = outcome_document(week)
    document["observations"][0].update(minutes=0, starts=1, state=0)
    with pytest.raises(DataError, match="recorded start"):
        read_outcome(document, week)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_sha256", "c" * 64),
        ("settled_at", "2024-10-05T14:59:00Z"),
        ("published_at", FIT_CUTOFF),
        ("captured_at", "2024-10-09T23:59:00Z"),
        ("fixture_ids", []),
        ("observations", []),
        ("calendar_complete", False),
        ("covered_gameweeks", [10, 11]),
        ("mapping_verified", False),
        ("model_use_approved", False),
        ("gameweek", 11),
        ("version", "unknown"),
    ],
)
def test_outcome_identity_calendar_admission_and_cutoff_refusals(field: str, value: object) -> None:
    week = read_week()
    document = outcome_document(week)
    document[field] = value
    with pytest.raises(DataError):
        read_outcome(document, week)


@pytest.mark.parametrize("protected", [True, False])
def test_protected_and_target_gw_refused_before_decoding_bytes(protected: bool) -> None:
    week = replace(read_week(), season="2025-26") if protected else read_week()
    with pytest.raises(DataError, match=r"Protected|target gameweek"):
        read_flag_outcome_source(
            b"not JSON",
            sha256="not a hash",
            week=week,
            fit_cutoff=FIT_CUTOFF,
            target_season="2024-25",
            target_gameweeks=(10,),
        )


def test_protected_capture_source_is_refused_before_hash_or_json() -> None:
    with pytest.raises(DataError, match="Protected"):
        read_flag_week_source(
            b"not JSON",
            sha256="bad",
            season="2025-26",
            gameweek=10,
            player_code=1001,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_fixtures=native_fixtures(),
            native_basis_sha256=BASIS,
        )


@pytest.mark.parametrize(
    ("season", "gameweek", "message"),
    [
        ("2024-25", 11, "target gameweek"),
        ("2024-25", 12, "target gameweek"),
        ("2024-25", 38, "target gameweek"),
        ("2026-27", 1, "Future seasons"),
        ("2025-26", 1, "Protected"),
    ],
)
def test_future_and_target_headers_never_decode_outcome_bytes(
    monkeypatch: pytest.MonkeyPatch,
    season: str,
    gameweek: int,
    message: str,
) -> None:
    week = replace(read_week(), season=season, gameweek=gameweek)

    def forbidden_decode(*args: object, **kwargs: object) -> dict[str, object]:
        pytest.fail("Excluded outcome bytes reached the JSON decoder.")

    monkeypatch.setattr(football_flag_inputs, "_json", forbidden_decode)
    with pytest.raises(DataError, match=message):
        read_flag_outcome_source(
            b"unread outcome bytes",
            sha256="not a hash",
            week=week,
            fit_cutoff=FIT_CUTOFF,
            target_season="2024-25",
            target_gameweeks=(11, 13),
        )


def test_unknown_target_inventory_is_refused_before_outcome_decoding() -> None:
    with pytest.raises(DataError, match="nonempty target"):
        read_flag_outcome_source(
            b"not JSON",
            sha256="bad",
            week=read_week(),
            fit_cutoff=FIT_CUTOFF,
            target_season="2024-25",
            target_gameweeks=(),
        )


def test_mutable_native_fixture_records_are_refused_before_source_decoding() -> None:
    with pytest.raises(DataError, match="frozen MinuteFixture"):
        read_flag_week_source(
            b"not JSON",
            sha256="bad",
            season="2024-25",
            gameweek=10,
            player_code=1001,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_fixtures=({},),
            native_basis_sha256=BASIS,  # type: ignore[arg-type]
        )


def test_oversized_numeric_native_minutes_are_refused_cleanly() -> None:
    week = read_week()
    fixture = replace(week.fixtures[0], minutes=(0, 10**400, 75, 90, 12, 65, 90))
    with pytest.raises(DataError, match="finite number"):
        validate_week_input(replace(week, fixtures=(fixture,)))


@pytest.mark.parametrize("kind", ["hash", "duplicate", "nan", "utf16", "root", "oversized"])
def test_strict_raw_bytes_and_json_refusals(kind: str) -> None:
    raw, sha = encoded(capture_document())
    if kind == "hash":
        sha = "a" * 64
    elif kind == "duplicate":
        raw = raw[:-1] + b',"gameweek":10}'
    elif kind == "nan":
        raw = raw.replace(b'"gameweek":10', b'"gameweek":NaN')
    elif kind == "utf16":
        raw = raw.decode().encode("utf-16")
    elif kind == "root":
        raw = b"[]"
    else:
        raw = b" " * (MAX_SOURCE_BYTES + 1)
    if kind != "hash":
        sha = hashlib.sha256(raw).hexdigest()
    with pytest.raises(DataError):
        read_flag_week_source(
            raw,
            sha256=sha,
            season="2024-25",
            gameweek=10,
            player_code=1001,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_fixtures=native_fixtures(),
            native_basis_sha256=BASIS,
        )


def test_training_dataclass_has_strict_states_and_settlement() -> None:
    week = read_week()
    valid = TrainingWeek(week, (3,), "2024-10-10T00:00:00Z", "c" * 64)
    validate_training_week(
        valid, fit_cutoff=FIT_CUTOFF, target_season="2024-25", target_gameweeks=(11,)
    )
    for row in (
        replace(valid, observed_states=(True,)),
        replace(valid, observed_states=()),
        replace(valid, settled_at=FIT_CUTOFF),
        replace(valid, observed_states=(7,)),
    ):
        with pytest.raises(DataError):
            validate_training_week(
                row, fit_cutoff=FIT_CUTOFF, target_season="2024-25", target_gameweeks=(11,)
            )
