"""Original-capture identity, category, chronology and outcome binding checks."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from tests.fixtures.football_flag_fixtures import training_weeks

from squadopt.data.errors import DataError
from squadopt.features.football_flag_captures import captured_flag_outcome, captured_flag_weeks
from squadopt.features.football_flag_inputs import MinuteFixture
from squadopt.prediction.football_flag_minutes import FlagMinutesModel

CAPTURE = "2024-10-04T10:00:00Z"
DECISION = "2024-10-04T12:00:00Z"
DEADLINE = "2024-10-05T10:00:00Z"
SETTLED = "2024-10-07T12:00:00Z"
FIT = "2024-10-11T10:00:00Z"


def encoded(value: Any) -> bytes:
    return json.dumps(value).encode()


def source() -> tuple[dict[str, Any], list[dict[str, Any]], MinuteFixture]:
    boot = {
        "events": [
            {"id": 1, "deadline_time": "2024-08-01T12:00:00Z", "is_next": False},
            {"id": 10, "deadline_time": DEADLINE, "is_next": True},
        ],
        "teams": [{"id": 1, "code": 20}, {"id": 2, "code": 30}],
        "elements": [
            {
                "id": 123,
                "code": 1001,
                "element_type": 2,
                "team": 1,
                "status": "d",
                "chance_of_playing_next_round": 75,
                "chance_of_playing_this_round": 25,
                "news": "Synthetic knock",
                "news_added": "2024-10-03T10:00:00Z",
            }
        ],
    }
    fixtures = [
        {
            "id": 101,
            "event": 10,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2024-10-05T15:00:00Z",
            "finished": False,
        }
    ]
    support = MinuteFixture(
        101,
        fixtures[0]["kickoff_time"],
        20,
        30,
        1,
        (0.2, 0.1, 0.3, 0.2, 0.1, 0.05, 0.05),
        (0.0, 40.0, 75.0, 90.0, 12.0, 65.0, 90.0),
    )
    return boot, fixtures, support


def read(
    boot: dict[str, Any] | None = None, fixtures: list[dict[str, Any]] | None = None, **changes: Any
):
    original_boot, original_fixtures, support = source()
    options = dict(
        bootstrap=encoded(original_boot if boot is None else boot),
        fixtures=encoded(original_fixtures if fixtures is None else fixtures),
        season="2024-25",
        gameweek=10,
        captured_at=CAPTURE,
        decision_at=DECISION,
        native_fixtures={1001: (support,)},
        native_basis_sha256="b" * 64,
        native_fit_cutoff=CAPTURE,
        reconstructed=True,
    )
    options.update(changes)
    return captured_flag_weeks(**options)


def observed(week=None, *, minutes: Any = 75, starts: Any = 1, **changes: Any):
    boot, fixtures, _ = source()
    fixtures[0]["finished"] = True
    event = {
        "elements": [
            {
                "id": 123,
                "stats": {"minutes": minutes, "starts": starts},
                "explain": [{"fixture": 101}],
            }
        ]
    }
    options = dict(
        bootstrap=encoded(boot),
        fixtures=encoded(fixtures),
        event=encoded(event),
        captured_at=SETTLED,
        fit_cutoff=FIT,
        target_season="2024-25",
        target_gameweeks=(11,),
    )
    options.update(changes)
    return captured_flag_outcome(read()[0] if week is None else week, **options)


def test_original_next_round_category_and_actual_clock_are_retained():
    week = read()[0]
    assert week.label == week.legacy_next_round_label == 75
    assert week.capture_age_hours == (24 * 3600 - 1) / 3600
    assert week.news_age_hours == (48 * 3600 - 1) / 3600
    assert week.decision_at == DECISION
    assert week.native_basis_kind == "out_of_fold"
    assert week.history_covered is False and week.label_changed is None
    assert read(reconstructed=False)[0].native_basis_kind == "prospective"


def test_fitted_law_is_invariant_to_operator_clock_with_varied_training_ages():
    training = training_weeks(varied_ages=True)
    assert len({row.input.capture_age_hours for row in training}) == 20
    assert len({row.input.news_age_hours for row in training}) == 21
    model = FlagMinutesModel(
        training, fit_cutoff=CAPTURE, target_season="2024-25", target_gameweeks=(10,)
    )
    early = read(decision_at="2024-10-04T11:00:00Z", reconstructed=False)[0]
    late = read(decision_at="2024-10-05T09:59:59Z", reconstructed=False)[0]
    early_law, late_law = model.predict(early), model.predict(late)
    assert early.decision_at != late.decision_at
    assert early_law.input_sha256 != late_law.input_sha256  # Decision provenance remains bound.
    assert early_law.probabilities == late_law.probabilities
    assert early_law.fixture_probabilities == late_law.fixture_probabilities
    assert early_law.weekly_appearance == late_law.weekly_appearance
    old_early_clock = replace(early, capture_age_hours=1.0, news_age_hours=25.0)
    assert abs(model.predict(old_early_clock).weekly_appearance - late_law.weekly_appearance) > 0.01


def test_capture_inside_the_fixed_reference_second_is_refused():
    with pytest.raises(DataError, match="deadline minus one second"):
        read(captured_at="2024-10-05T09:59:59Z", decision_at="2024-10-05T09:59:59.5Z")


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_native_calendar_requires_all_and_only_captured_fixtures(change):
    _, _, support = source()
    supports = () if change == "missing" else (support, replace(support, fixture=102))
    with pytest.raises(DataError, match="complete club calendar"):
        read(native_fixtures={1001: supports})


@pytest.mark.parametrize(
    "changes",
    [{"club": 21}, {"opponent": 31}, {"home": 0}, {"kickoff": "2024-10-05T16:00:00Z"}],
)
def test_native_fixture_identity_requires_matching_clubs_side_and_kickoff(changes):
    _, _, support = source()
    with pytest.raises(DataError, match="captured fixture identity"):
        read(native_fixtures={1001: (replace(support, **changes),)})


@pytest.mark.parametrize(
    "field,value",
    [
        ("chance_of_playing_next_round", None),
        ("chance_of_playing_next_round", 0),
        ("chance_of_playing_next_round", 100),
    ],
)
def test_explicit_null_and_zero_are_distinct_categories(field, value):
    boot, _, _ = source()
    boot["elements"][0][field] = value
    assert read(boot)[0].label == value


@pytest.mark.parametrize(
    "changes",
    [
        {"gameweek": 11},
        {"decision_at": CAPTURE},
        {"decision_at": DEADLINE},
        {"native_fit_cutoff": DECISION},
        {"native_fixtures": {}},
        {"native_basis_sha256": "bad"},
    ],
)
def test_mismatched_source_and_native_basis_refuse(changes):
    with pytest.raises((DataError, ValueError)):
        read(**changes)


def test_newer_news_and_duplicate_persistent_identity_refuse():
    boot, _, _ = source()
    boot["elements"][0]["news_added"] = "2024-10-04T11:00:00Z"
    with pytest.raises(DataError, match="after"):
        read(boot)
    boot, _, _ = source()
    boot["elements"].append(dict(boot["elements"][0], id=124))
    with pytest.raises(DataError, match="Duplicate"):
        read(boot)


@pytest.mark.parametrize(
    "minutes,starts,state",
    [(0, 0, 0), (12, 1, 1), (75, 1, 2), (90, 1, 3), (12, 0, 4), (75, 0, 5), (90, 0, 6)],
)
def test_observed_role_uses_recorded_starts_even_for_long_cameos(minutes, starts, state):
    assert observed(minutes=minutes, starts=starts).observed_states == (state,)


@pytest.mark.parametrize(
    "minutes,starts", [(0, 1), (None, 1), (75, None), (True, 1), (75, 2), (121, 1)]
)
def test_missing_or_unrepresentable_outcomes_are_not_inferred(minutes, starts):
    with pytest.raises(DataError):
        observed(minutes=minutes, starts=starts)


def test_reused_fixture_id_with_other_clubs_cannot_supply_outcomes():
    _, fixtures, _ = source()
    fixtures[0].update(finished=True, team_h=2, team_a=1)
    with pytest.raises(DataError, match="clubs"):
        observed(fixtures=encoded(fixtures))


def test_outcome_identity_settlement_and_season_refuse():
    for changes in (
        {"event": encoded({"elements": []})},
        {"captured_at": FIT},
        {"captured_at": "2024-10-05T16:00:00Z"},
    ):
        with pytest.raises(DataError):
            observed(**changes)
    boot, _, _ = source()
    boot["events"][0]["deadline_time"] = "2023-08-01T12:00:00Z"
    with pytest.raises(DataError, match="season"):
        observed(bootstrap=encoded(boot))


def test_protected_target_future_and_double_outcomes_refuse_before_decoding():
    week = read()[0]
    bad = b"not JSON"
    for changed_week, target_season, target_weeks in (
        (replace(week, season="2025-26"), "2026-27", (7,)),
        (week, "2024-25", (10,)),
        (
            replace(
                week,
                fixtures=(
                    *week.fixtures,
                    replace(week.fixtures[0], fixture=102, kickoff="2024-10-07T15:00:00Z"),
                ),
            ),
            "2024-25",
            (11,),
        ),
    ):
        with pytest.raises(DataError) as error:
            observed(
                changed_week,
                bootstrap=bad,
                fixtures=bad,
                event=bad,
                target_season=target_season,
                target_gameweeks=target_weeks,
            )
        assert "JSON" not in str(error.value)
