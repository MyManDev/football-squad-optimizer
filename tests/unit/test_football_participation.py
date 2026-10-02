"""The supplied source contract reaches football advice without a producer rerun."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.application.football_context import bind_football_context
from squadopt.application.football_participation import (
    bind_football_participation,
    participation_summary,
)
from squadopt.application.manager_words import (
    MANAGERS_WORD_RULE_VERSION,
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    ManagerWord,
    ManagerWords,
)
from squadopt.data.sources.fpl_live import GameweekDeadline
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.football_artifact import FootballForecast
from squadopt.live.football_horizon import build_football_horizon
from squadopt.planning.horizon import (
    APPEARANCE_HORIZON_CONTRACT_VERSION,
    PROJECTION_HORIZON_CONTRACT_VERSION,
    ProjectionHorizon,
)
from squadopt.platform.advice_switches import AdviceSwitchInputs, switch_identity

AS_OF = pd.Timestamp("2026-10-01T10:00:00Z")
DEADLINE = pd.Timestamp("2026-10-02T10:00:00Z")


def _world():
    roster = pd.DataFrame(
        {
            "player_id": [1, 2],
            "name": ["Synthetic A", "Synthetic B"],
            "team_id": [1, 2],
            "position": ["MID", "DEF"],
            "price_tenths": [50, 50],
        }
    )
    availability = pd.DataFrame(
        {"player_id": [1, 2], "status": ["d", "a"], "chance_of_playing": [75, 100]}
    )
    inputs = RecommendationInputs(
        "synthetic-capture",
        AS_OF.isoformat(),
        "2026-27",
        GameweekDeadline(6, DEADLINE.isoformat(), False),
        roster,
        availability,
    )
    frames = [
        roster.assign(
            gameweek=week,
            expected_points=[4.8, 8.0],
            appearance_probability=[0.6, 0.8],
            fixture_count=1,
            home_fixture_count=0,
        )
        for week in (6, 7)
    ]
    horizon = ProjectionHorizon(
        pd.concat(frames, ignore_index=True),
        inputs.season,
        inputs.snapshot_id,
        "fixture_football_candidate",
        "football_contextual_v3",
        "synthetic-features",
        "synthetic-processing",
        contract_version=APPEARANCE_HORIZON_CONTRACT_VERSION,
    )
    forecast = FootballForecast(
        horizon,
        Projection(frames[0], (), {"model_name": "fixture_football_candidate"}),
        "synthetic-forecast-v1",
    )
    word = ManagerWord(
        1,
        "stated_expected_absent",
        "Manager",
        (AS_OF - pd.Timedelta(hours=2)).isoformat(),
        "instant",
        "Synthetic Club",
        "https://example.test/club/captured-statement",
        (AS_OF - pd.Timedelta(hours=1)).isoformat(),
        "He will miss the next Premier League match.",
        source_sha256="a" * 64,
        span_start=0,
        span_end=42,
        fixture_scope="upcoming_premier_league",
        scope_verified=True,
        publication_verified=True,
        publication_source="html_publication_meta",
        publication_source_sha256="b" * 64,
    )
    words = ManagerWords(
        inputs.season,
        6,
        "synthetic_fixture",
        "Synthetic source",
        "synthetic-table",
        ("Synthetic Club",),
        (word,),
        source_check=SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    )
    return forecast, inputs, words


def _bind(forecast, inputs, words):
    return bind_football_participation(
        forecast, inputs, manager_words=words, rotation_table_sha256="synthetic-table-digest"
    )


def test_cited_absence_reaches_projection_and_first_horizon_week_without_double_scaling():
    forecast, inputs, words = _world()
    before = forecast.horizon.table.copy(deep=True)
    result = _bind(forecast, inputs, words)
    first = result.projection.table.set_index("player_id")
    assert first.loc[1, "expected_points"] == 0
    assert first.loc[1, "appearance_probability"] == 0
    assert result.projection.unavailable_players == (1,)
    assert first.loc[2, "expected_points"] == 8
    assert_frame_equal(result.horizon.table.query("gameweek == 7"), before.query("gameweek == 7"))
    assert_frame_equal(forecast.horizon.table, before)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["captured_percentages"][0]["appearance_probability"] == pytest.approx(0.6)
    assert audit["manager_statements"][0]["appearance_probability"] == 0
    assert audit["future_rows_recovered"] is False
    assert result.fingerprint == forecast.fingerprint
    summary = participation_summary(result.projection.diagnostics)
    assert summary["applied_player_count"] == 1
    assert summary["manager_statement_count"] == 1
    assert summary["captured_percentage_count"] == 2
    assert summary["unapplied_statement_count"] == 0
    assert "source_snapshot_id" not in summary
    assert "base_revision" not in summary
    assert "rotation_table_sha256" not in summary
    assert "future_values_not_recovered" not in summary["assumptions"]


def test_no_manager_source_keeps_existing_captured_percentages_once():
    forecast, inputs, _ = _world()
    result = _bind(forecast, inputs, None)
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    assert result.projection.diagnostics["participation_evidence"]["manager_statements"] == []


def test_legacy_handoff_without_appearance_contract_stays_usable_and_explicitly_unadjusted():
    forecast, inputs, words = _world()
    forecast = replace(
        forecast,
        horizon=replace(
            forecast.horizon,
            table=forecast.horizon.table.drop(columns="appearance_probability"),
            contract_version=PROJECTION_HORIZON_CONTRACT_VERSION,
        ),
    )
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    assert_frame_equal(result.projection.table, forecast.projection.table)
    assert (
        result.projection.diagnostics["participation_evidence"]["reason"] == "unsupported_contract"
    )


@pytest.mark.parametrize("disposition", ["stated_rotation_risk", "stated_minutes_limited"])
def test_uncalibrated_manager_labels_are_explicitly_unapplied(disposition):
    forecast, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition=disposition),))
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["manager_statements"][0]["reason"] == "categorical_statement_has_no_probability"
    assert audit["external_calibration_supplied"] is False
    summary = participation_summary(result.projection.diagnostics)
    assert summary["applied_player_count"] == 0
    assert summary["unapplied_statement_count"] == 1


@pytest.mark.parametrize("source_check", [None, "nothing_cited"])
def test_unverified_news_cannot_zero_a_player(source_check):
    forecast, inputs, words = _world()
    result = _bind(forecast, inputs, replace(words, source_check=source_check))
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"][0]["reason"] == "source_documents_unverified"


def test_a_resolved_source_with_unknown_instant_cannot_invent_a_timestamp():
    forecast, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], published_precision="day"),))
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"][0]["reason"] == "source_time_or_citation_missing"


def test_future_or_different_week_news_is_not_applied():
    forecast, inputs, words = _world()
    wrong_week = _bind(forecast, inputs, replace(words, gameweek=7))
    assert_frame_equal(wrong_week.horizon.table, forecast.horizon.table)
    future = replace(words.words[0], fetched_at_utc=(AS_OF + pd.Timedelta(minutes=1)).isoformat())
    result = _bind(forecast, inputs, replace(words, words=(future,)))
    assert_frame_equal(result.horizon.table, forecast.horizon.table)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["manager_statements"][0]["reason"] == "future_evidence"


def test_old_artifact_zero_is_not_recovered_without_conditional_forecast():
    forecast, inputs, words = _world()
    old = forecast.horizon.table.copy()
    old.loc[old.player_id.eq(1), ["expected_points", "appearance_probability"]] = 0
    forecast = replace(forecast, horizon=replace(forecast.horizon, table=old))
    result = _bind(forecast, inputs, words)
    assert (
        result.horizon.table.loc[result.horizon.table.player_id.eq(1), "expected_points"]
        .eq(0)
        .all()
    )
    assert result.projection.diagnostics["participation_evidence"]["future_rows_recovered"] is False
    summary = participation_summary(result.projection.diagnostics)
    assert "future_values_not_recovered" in summary["assumptions"]


def test_football_cache_identity_includes_news_even_when_manager_constraint_switch_is_off():
    forecast, _, words = _world()
    before = AdviceSwitchInputs(football=forecast, manager_words=words, rotation_table_sha256="a")
    after = replace(before, rotation_table_sha256="b")
    first = switch_identity(before, model="football")
    second = switch_identity(after, model="football")
    assert first != second
    assert first["model"]["participation_version"] == "football_participation_evidence_v3"
    assert first["model"]["fingerprint"] == forecast.fingerprint
    assert switch_identity(before, model="current") == switch_identity(after, model="current") == {}


def test_football_cache_identity_names_the_news_rule_only_where_news_is_bound():
    """The same table read under a different rule is a different input to the forecast.

    A football answer with no news bound keeps the key it was written under.
    """

    forecast, _, words = _world()
    bound = AdviceSwitchInputs(football=forecast, manager_words=words, rotation_table_sha256="a")
    unbound = AdviceSwitchInputs(football=forecast)

    assert (
        switch_identity(bound, model="football")["model"]["news_rule_version"]
        == MANAGERS_WORD_RULE_VERSION
    )
    assert "news_rule_version" not in switch_identity(unbound, model="football")["model"]


@pytest.mark.parametrize("disposition", ["stated_expected_absent", "stated_full_match_unavailable"])
def test_new_producer_scopes_manager_override_to_its_week_before_model_prediction(
    monkeypatch, disposition
):
    _, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition=disposition),))
    roster = inputs.players.assign(club=inputs.players.team_id)
    fixtures = pd.DataFrame(
        {
            "fixture": [1, 1, 2, 2],
            "club": [1, 2, 1, 2],
            "opponent": [2, 1, 2, 1],
            "home": [1, 0, 1, 0],
            "GW": [6, 6, 7, 7],
            "kickoff": [DEADLINE + pd.Timedelta(hours=3)] * 2
            + [DEADLINE + pd.Timedelta(days=7, hours=3)] * 2,
        }
    )
    roster, _ = bind_football_context(
        roster,
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
        fixture_calendar=fixtures,
    )
    seen = []

    class CapturingModel:
        cutoff = AS_OF
        model_version = "football_contextual_v3"

        def predict(self, target, *, role_steps):
            seen.append(target.copy())
            return pd.DataFrame(
                {
                    "expected_points": target.availability_probability * 10,
                    "appearance_probability": target.availability_probability * 0.8,
                    "availability_multiplier": target.availability_probability,
                },
                index=target.index,
            )

    monkeypatch.setattr(
        "squadopt.live.football_horizon.football_features",
        lambda history, target, cutoff: pd.DataFrame({"home": target.home}, index=target.index),
    )
    build_football_horizon(
        CapturingModel(),
        pd.DataFrame(),
        roster,
        fixtures,
        gameweeks=(6, 7),
        season=inputs.season,
        source_snapshot_id=inputs.snapshot_id,
        captured_at=AS_OF,
    )
    targets = pd.concat(seen).set_index(["player_code", "GW"])
    assert targets.loc[(1, 7), "availability_probability"] == 0.75
    assert not targets.loc[(1, 7), "minutes_limited"]
    if disposition == "stated_expected_absent":
        assert targets.loc[(1, 6), "availability_probability"] == 0
    else:
        assert targets.loc[(1, 6), "minutes_limited"]


@pytest.mark.parametrize("positive", ["stated_expected_to_start", "stated_minutes_limited"])
def test_new_producer_preserves_captured_eligibility_for_conflicting_valid_sources(positive):
    _, inputs, words = _world()
    other = replace(
        words.words[0],
        disposition=positive,
        source_url="https://example.test/another-cited-source",
    )
    for statements in ((words.words[0], other), (other, words.words[0])):
        roster, audit = bind_football_context(
            inputs.players.assign(club=inputs.players.team_id),
            inputs.availability,
            season=inputs.season,
            gameweek=6,
            cutoff=AS_OF,
            manager_words=replace(words, words=statements),
            fixture_calendar=_calendar(),
        )
        assert roster.set_index("player_id").loc[1, "availability_probability"] == 0.75
        assert not roster.set_index("player_id").loc[1, "minutes_limited"]
        assert all(row["reason"] == "conflicting_sources" for row in audit)


def _calendar(*, double=False):
    calendar = pd.DataFrame(
        {
            "fixture": [61, 61],
            "club": [1, 2],
            "GW": [6, 6],
            "kickoff": [DEADLINE + pd.Timedelta(hours=3)] * 2,
        }
    )
    return (
        pd.concat([calendar, calendar.assign(fixture=62)], ignore_index=True)
        if double
        else calendar
    )


@pytest.mark.parametrize(
    "disposition",
    ["stated_expected_absent", "stated_full_match_unavailable", "stated_minutes_limited"],
)
@pytest.mark.parametrize(
    "damage,reason",
    [
        ({"publication_verified": False}, "publication_unverified"),
        (
            {"scope_verified": False, "fixture_scope": "other_competition"},
            "upcoming_league_scope_unverified",
        ),
        ({"scope_verified": False, "fixture_scope": "past"}, "upcoming_league_scope_unverified"),
        (
            {"scope_verified": False, "fixture_scope": "ambiguous"},
            "upcoming_league_scope_unverified",
        ),
    ],
)
def test_both_consumers_refuse_unverified_or_wrong_fixture_claims(disposition, damage, reason):
    forecast, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition=disposition, **damage),))
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, forecast.horizon.table, check_exact=True)
    summary = participation_summary(result.projection.diagnostics)
    assert summary["statement_outcomes"][0]["reason"] == reason
    assert summary["statement_outcomes"][0]["applied"] is False
    context, audit = bind_football_context(
        inputs.players.assign(club=inputs.players.team_id),
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
        fixture_calendar=_calendar(),
    )
    assert context.availability_probability.tolist() == [0.75, 1.0]
    assert not context.minutes_limited.any()
    assert audit[0]["reason"] == reason


@pytest.mark.parametrize("disposition", ["stated_expected_absent", "stated_full_match_unavailable"])
def test_both_consumers_refuse_ambiguous_double_gameweek(disposition):
    forecast, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition=disposition),))
    table = forecast.horizon.table.assign(fixture_count=2)
    forecast = replace(forecast, horizon=replace(forecast.horizon, table=table))
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, table, check_exact=True)
    assert (
        participation_summary(result.projection.diagnostics)["statement_outcomes"][0]["reason"]
        == "ambiguous_current_week_fixture"
    )
    context, audit = bind_football_context(
        inputs.players.assign(club=inputs.players.team_id),
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
        fixture_calendar=_calendar(double=True),
    )
    assert not context.minutes_limited.any()
    assert context.availability_probability.tolist() == [0.75, 1.0]
    assert audit[0]["reason"] == "ambiguous_current_week_fixture"


def test_vague_minutes_cannot_restrict_contextual_full_match_support():
    _, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition="stated_minutes_limited"),))
    context, audit = bind_football_context(
        inputs.players.assign(club=inputs.players.team_id),
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
        fixture_calendar=_calendar(),
    )
    assert context.availability_probability.tolist() == [0.75, 1.0]
    assert not context.minutes_limited.any()
    assert context.manager_context_fixture.isna().all()
    assert audit[0]["reason"] == "categorical_statement_has_no_probability"


@pytest.mark.parametrize(
    "other,applied", [("stated_full_match_unavailable", True), ("stated_expected_to_start", False)]
)
def test_public_outcomes_identify_only_the_applied_source_and_hide_internal_provenance(
    other, applied
):
    forecast, inputs, words = _world()
    second = replace(words.words[0], disposition=other, source_url="https://example.test/second")
    result = _bind(forecast, inputs, replace(words, words=(words.words[0], second)))
    summary = participation_summary(result.projection.diagnostics)
    outcomes = summary["statement_outcomes"]
    assert [row["applied"] for row in outcomes] == [applied, False]
    assert summary["manager_statement_count"] == 2
    assert summary["unapplied_statement_count"] == 1 + int(not applied)
    assert summary["applied_player_count"] == int(applied)
    assert outcomes[1]["reason"] == (
        "explicit_absence_supersedes_minute_restriction" if applied else "conflicting_sources"
    )
    for row in outcomes:
        assert set(row) == {
            "player_id",
            "disposition",
            "applied",
            "reason",
            "source_url",
            "source_published_at",
        }
        assert row["source_published_at"] == words.words[0].published_at_utc


def test_public_duplicate_source_outcomes_do_not_claim_an_applied_absence():
    forecast, inputs, words = _world()
    result = _bind(forecast, inputs, replace(words, words=words.words * 2))
    assert_frame_equal(result.horizon.table, forecast.horizon.table, check_exact=True)
    summary = participation_summary(result.projection.diagnostics)
    assert len(summary["statement_outcomes"]) == 2
    assert all(
        not row["applied"] and row["reason"] == "duplicate_evidence_or_source"
        for row in summary["statement_outcomes"]
    )


@pytest.mark.parametrize(
    "dispositions,same_source,reason",
    [
        (("stated_expected_absent", "stated_rotation_risk"), True, "duplicate_evidence_or_source"),
        (
            ("stated_full_match_unavailable", "stated_full_match_unavailable"),
            False,
            "overlapping_minute_statements",
        ),
    ],
)
def test_contextual_and_runtime_consumers_refuse_the_same_whole_source_set(
    dispositions, same_source, reason
):
    forecast, inputs, words = _world()
    claims = tuple(
        replace(
            words.words[0],
            disposition=disposition,
            source_url=words.words[0].source_url if same_source else f"https://example.test/{i}",
        )
        for i, disposition in enumerate(dispositions)
    )
    words = replace(words, words=claims)
    result = _bind(forecast, inputs, words)
    assert_frame_equal(result.horizon.table, forecast.horizon.table, check_exact=True)
    outcomes = participation_summary(result.projection.diagnostics)["statement_outcomes"]
    assert all(not row["applied"] and row["reason"] == reason for row in outcomes)
    context, audit = bind_football_context(
        inputs.players.assign(club=inputs.players.team_id),
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
        fixture_calendar=_calendar(),
    )
    assert not context.minutes_limited.any()
    assert context.availability_probability.tolist() == [0.75, 1.0]
    assert all(row["reason"] == reason for row in audit)


def test_each_refused_source_keeps_its_own_reason_when_none_is_actionable():
    forecast, inputs, words = _world()
    stale = replace(words.words[0], published_at_utc=(AS_OF - pd.Timedelta(days=8)).isoformat())
    vague = replace(
        words.words[0],
        disposition="stated_minutes_limited",
        source_url="https://example.test/vague",
    )
    result = _bind(forecast, inputs, replace(words, words=(stale, vague)))
    outcomes = participation_summary(result.projection.diagnostics)["statement_outcomes"]
    assert [row["reason"] for row in outcomes] == [
        "expired_evidence",
        "categorical_statement_has_no_probability",
    ]
    assert all(not row["applied"] for row in outcomes)
