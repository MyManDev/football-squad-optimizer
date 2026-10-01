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
        "He will miss this match.",
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
    assert first["model"]["participation_version"] == "football_participation_evidence_v2"
    assert first["model"]["fingerprint"] == forecast.fingerprint
    assert switch_identity(before, model="current") == switch_identity(after, model="current") == {}


@pytest.mark.parametrize("disposition", ["stated_expected_absent", "stated_minutes_limited"])
def test_new_producer_scopes_manager_override_to_its_week_before_model_prediction(
    monkeypatch, disposition
):
    _, inputs, words = _world()
    words = replace(words, words=(replace(words.words[0], disposition=disposition),))
    roster = inputs.players.assign(club=inputs.players.team_id)
    roster, _ = bind_football_context(
        roster,
        inputs.availability,
        season=inputs.season,
        gameweek=6,
        cutoff=AS_OF,
        manager_words=words,
    )
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
            inputs.players,
            inputs.availability,
            season=inputs.season,
            gameweek=6,
            cutoff=AS_OF,
            manager_words=replace(words, words=statements),
        )
        assert roster.set_index("player_id").loc[1, "availability_probability"] == 0.75
        assert not roster.set_index("player_id").loc[1, "minutes_limited"]
        assert all(row["reason"] == "conflicting_sources" for row in audit)
