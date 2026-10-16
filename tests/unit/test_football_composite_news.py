"""Source eligibility selects whole-law interventions without scalar point updates."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_minute_integration import world

from squadopt.application.football_composite_news import select_composite_news
from squadopt.application.football_context import FULL_MATCH_UNAVAILABLE
from squadopt.platform.advice_switches import (
    AdviceSwitchInputs,
    SwitchInputUnavailable,
    switch_identity,
)
from squadopt.prediction.football_capabilities import COMPOSITE_MODEL_VERSION
from squadopt.prediction.participation_updates import ParticipationEvidence


def selection(*, claims=(FULL_MATCH_UNAVAILABLE,), edits=None, fixture_edits=None):
    football, inputs, manager, basis = world()
    word = manager.words[0]
    first = inputs.deadline.gameweek
    base = football.horizon.table.loc[football.horizon.table.gameweek.eq(first)].copy()
    original = base.copy(deep=True)
    deadline = pd.Timestamp(inputs.deadline.deadline_utc)
    items, words = [], {}
    for i, claim in enumerate(claims):
        identity = f"claim-{i}"
        source = replace(word, disposition=claim, source_url=f"https://club.example/source/{i}")
        words[identity] = source
        item = ParticipationEvidence(
            evidence_id=identity,
            player_id=word.player_id,
            season=inputs.season,
            gameweek=first,
            deadline=deadline,
            published_at=pd.Timestamp(word.published_at_utc),
            captured_at=pd.Timestamp(word.fetched_at_utc),
            valid_until=deadline,
            source_id=str(source.source_url),
            source_url=source.source_url,
            kind="source_statement",
            disposition=claim,
        )
        items.append(replace(item, **(edits or {})))
    fixtures = basis.fixture_rows.copy(deep=True)
    if fixture_edits is not None:
        fixtures = fixture_edits(fixtures)
    result = select_composite_news(
        base,
        items,
        words,
        fixtures,
        season=inputs.season,
        first_gameweek=first,
        as_of=pd.Timestamp(inputs.captured_at_utc),
        deadline=deadline,
        base_revision=football.fingerprint,
    )
    assert_frame_equal(base, original, check_exact=True)
    return result


def test_verified_minute_claim_binds_exact_fixture_and_source_bundle():
    selected = selection()
    assert len(selected.evidence) == 1
    item = selected.evidence[0]
    assert (item.kind, item.player_code, item.gameweek) == ("no_full_match", 3, 6)
    assert len(item.fixture_ids) == 1
    assert item.source_sha256 == selected.decisions[0]["source_bundle_sha256"]
    assert selected.decisions[0]["evidence"][0]["source_sha256"] == "c" * 64
    assert selected.decisions[0]["starts_reestimated"] is False
    assert selected.withheld == ()
    assert selection() == selected


@pytest.mark.parametrize(
    "edits,reason",
    [
        ({"captured_at": pd.Timestamp("2026-09-22T13:00:00Z")}, "future_evidence"),
        ({"published_at": pd.Timestamp("2026-09-01T10:00:00Z")}, "expired_evidence"),
        ({"season": "2025-26"}, "season_mismatch"),
        ({"deadline": pd.Timestamp("2026-09-24T12:00:00Z")}, "deadline_mismatch"),
        ({"source_url": None}, "missing_source_citation"),
        ({"player_id": 999999}, "outside_projection"),
    ],
)
def test_ineligible_source_cannot_enter_joint_law(edits, reason):
    result = selection(edits=edits)
    assert not result.evidence
    assert result.withheld[0]["reason"] == reason


def test_agreeing_absences_share_one_intervention_with_all_sources_bound():
    result = selection(claims=("stated_expected_absent",) * 2)
    assert len(result.evidence) == 1
    assert result.evidence[0].kind == "absence"
    assert len(result.decisions[0]["evidence"]) == 2
    assert result.decisions[0]["starts_reestimated"] is True
    assert (
        result.evidence[0].source_sha256
        != selection(claims=("stated_expected_absent",)).evidence[0].source_sha256
    )


def test_duplicate_sources_refuse_absence_and_restriction_together():
    result = selection(
        claims=("stated_expected_absent", FULL_MATCH_UNAVAILABLE),
        edits={"source_id": "same"},
    )
    assert not result.evidence
    assert {r["reason"] for r in result.withheld} == {"duplicate_evidence_or_source"}


def test_conflicting_start_and_absence_refuse_all_sources():
    result = selection(claims=("stated_expected_absent", "stated_expected_to_start"))
    assert not result.evidence
    assert {r["reason"] for r in result.withheld} == {"conflicting_sources"}


def test_absence_supersedes_full_match_claim_without_numerical_compounding():
    result = selection(claims=("stated_expected_absent", FULL_MATCH_UNAVAILABLE))
    assert [item.kind for item in result.evidence] == ["absence"]
    assert len(result.decisions[0]["evidence"]) == 1
    assert result.withheld[0]["reason"] == "explicit_absence_supersedes_minute_restriction"


@pytest.mark.parametrize("claim", ["stated_minutes_limited", "stated_expected_to_start"])
def test_categorical_words_do_not_invent_a_numeric_intervention(claim):
    result = selection(claims=(claim,))
    assert not result.evidence
    assert result.withheld[0]["reason"] == "categorical_statement_has_no_probability"


def test_double_week_requires_source_explicit_fixture_scope():
    def duplicate(frame):
        extra = frame.loc[frame.GW.eq(6) & frame.player_code.eq(3)].copy()
        extra["fixture"] = 999
        return pd.concat([frame, extra], ignore_index=True)

    result = selection(fixture_edits=duplicate)
    assert not result.evidence
    assert result.withheld[0]["reason"] == "ambiguous_current_week_fixture"


def test_repeated_minute_claims_do_not_apply_twice():
    result = selection(claims=(FULL_MATCH_UNAVAILABLE,) * 2)
    assert not result.evidence
    assert {r["reason"] for r in result.withheld} == {"overlapping_minute_statements"}


def test_no_news_has_no_interventions_or_audit_changes():
    result = selection(claims=())
    assert result.evidence == result.decisions == result.withheld == ()


def addressed(fingerprint):
    football, _, _, _ = world()
    football = replace(
        football,
        horizon=replace(football.horizon, model_version=COMPOSITE_MODEL_VERSION),
        projection=replace(
            football.projection,
            diagnostics={"composite_reprojection_fingerprint": fingerprint},
        ),
    )
    return AdviceSwitchInputs(
        football=football,
        football_components_sha256="c" * 64,
        football_components_bound=True,
        football_bundle_sha256="d" * 64,
    )


def test_reprojection_changes_cache_and_displayed_decision_revision():
    left, right = addressed("a" * 64), addressed("b" * 64)
    assert switch_identity(left, model="football") != switch_identity(right, model="football")
    assert left.decision_information("capture") != right.decision_information("capture")
    assert switch_identity(left) == switch_identity(right) == {}
    assert switch_identity(left, model="football") == switch_identity(
        addressed("a" * 64), model="football"
    )


@pytest.mark.parametrize("fingerprint", [None, "", "x" * 64, "A" * 64, "0" * 63, 123])
def test_unbound_or_malformed_reprojection_cannot_address_an_answer(fingerprint):
    inputs = addressed(fingerprint)
    with pytest.raises(SwitchInputUnavailable, match="unbound"):
        switch_identity(inputs, model="football")
    with pytest.raises(SwitchInputUnavailable, match="unbound"):
        inputs.decision_information("capture")
