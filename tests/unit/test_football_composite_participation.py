"""Composite application dispatch with synthetic arithmetic, not a model-math oracle."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import replace
from types import SimpleNamespace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_minute_integration import world
from tests.unit.test_minute_evidence import documents

from squadopt.application import football_participation as module
from squadopt.application.football_composite_news import select_composite_news
from squadopt.application.manager_words import WORDS_UNRESOLVED
from squadopt.prediction.football_capabilities import COMPOSITE_MODEL_VERSION


def dispatch_case(monkeypatch, *, dgw=False):
    football, inputs, words, basis = world(documents(dgw=dgw, eligibility=0.5))
    football = replace(
        football, horizon=replace(football.horizon, model_version=COMPOSITE_MODEL_VERSION)
    )
    state = SimpleNamespace(calls=[], outputs=[], selections=[], fingerprints=[], failure=None)

    def recompose_stub(received_football, received_inputs, news, source_words, received_basis):
        """Keep real source selection; stand in only for the downstream joint projector."""
        assert received_football is football
        assert received_inputs is inputs
        assert received_basis is basis
        state.calls.append((tuple(news), dict(source_words)))
        if state.failure is not None:
            raise ValueError(state.failure)
        first = int(inputs.deadline.gameweek)
        selected = select_composite_news(
            football.horizon.table.loc[football.horizon.table.gameweek.eq(first)],
            news,
            source_words,
            basis.fixture_rows,
            season=inputs.season,
            first_gameweek=first,
            as_of=pd.Timestamp(inputs.captured_at_utc),
            deadline=pd.Timestamp(inputs.deadline.deadline_utc),
            base_revision=football.fingerprint,
        )
        adjusted = football.horizon.table.copy(deep=True)
        if selected.evidence:
            # Deliberate dispatch markers on every first-week player, including the
            # opposing club. These are not fitted points or intervention mathematics.
            current = adjusted.gameweek.eq(first)
            adjusted.loc[current, "expected_points"] += 0.125
            for item in selected.evidence:
                if item.kind == "absence":
                    absent = current & adjusted.player_id.eq(item.player_code)
                    adjusted.loc[absent, ["expected_points", "appearance_probability"]] = 0.0
        fingerprint = (
            hashlib.sha256(
                json.dumps([item.evidence_id for item in selected.evidence]).encode()
            ).hexdigest()
            if selected.evidence
            else football.fingerprint
        )
        metadata = {
            "available": True,
            "reason": None,
            "components_fingerprint": basis.companion["fingerprint"],
            "forecast_fingerprint": football.fingerprint,
            "intervention_fingerprint": fingerprint,
            "joint_recomposition": True,
            "role_estimates": [],
        }
        state.outputs.append(adjusted.copy(deep=True))
        state.selections.append(selected)
        state.fingerprints.append(fingerprint)
        return adjusted, list(selected.decisions), list(selected.withheld), metadata

    # This is the sole patched production symbol. All surrounding input checks,
    # source selection, summary construction and returned-frame assembly are real.
    monkeypatch.setattr(module, "recompose_composite_news", recompose_stub)
    return football, inputs, words, basis, state, recompose_stub


def bind(football, inputs, words, basis, *, rotation="d" * 64):
    return module.bind_football_participation(
        football,
        inputs,
        manager_words=words,
        rotation_table_sha256=rotation,
        minute_basis=basis,
    )


def test_composite_dispatch_keeps_final_table_and_audits_captured_feed_only_once(monkeypatch):
    football, inputs, words, basis, state, stub = dispatch_case(monkeypatch)
    before = football.horizon.table.copy(deep=True)
    events, audits = [], []

    def profile(frame, event, _argument):
        if event != "call":
            return
        if frame.f_code is stub.__code__:
            events.append("composite_dispatch")
        elif frame.f_code is module.apply_participation_updates.__code__:
            caller = frame.f_back.f_code
            if caller is module.bind_football_participation.__code__:
                events.append("captured_audit")
                audits.append(
                    (list(frame.f_locals["evidence"]), frame.f_locals["base"].copy(deep=True))
                )
            elif caller is select_composite_news.__code__:
                events.append("selector_source_audit")
            else:
                events.append("unexpected_scalar_update")
        elif frame.f_code is module._minute_updates.__code__:
            events.append("legacy_minute_path")

    previous_profile = sys.getprofile()
    sys.setprofile(profile)
    try:
        result = bind(football, inputs, words, basis)
    finally:
        sys.setprofile(previous_profile)
    assert events == ["captured_audit", "composite_dispatch", "selector_source_audit"]
    assert len(audits) == 1
    assert audits[0][0] == []
    assert audits[0][1].availability_multiplier.eq(1.0).all()
    assert inputs.availability.chance_of_playing.eq(50.0).any()
    assert_frame_equal(result.horizon.table, state.outputs[0], check_exact=True)
    assert_frame_equal(
        result.projection.table,
        state.outputs[0].loc[state.outputs[0].gameweek.eq(6)],
        check_exact=True,
    )
    assert_frame_equal(
        result.horizon.table.loc[result.horizon.table.gameweek.eq(7)],
        before.loc[before.gameweek.eq(7)],
        check_exact=True,
    )
    assert_frame_equal(football.horizon.table, before, check_exact=True)
    assert result.fingerprint == football.fingerprint
    assert (
        result.projection.diagnostics["composite_reprojection_fingerprint"] == state.fingerprints[0]
    )
    assert result.projection.diagnostics["participation_evidence"]["captured_percentages"] == []
    assert "availability_multiplier" not in result.horizon.table


@pytest.mark.parametrize("disposition", ["stated_full_match_unavailable", "stated_expected_absent"])
def test_public_joint_summary_and_statement_outcomes_follow_dispatch(monkeypatch, disposition):
    football, inputs, words, basis, state, _ = dispatch_case(monkeypatch)
    word = replace(words.words[0], disposition=disposition)
    result = bind(football, inputs, replace(words, words=(word,)), basis)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["joint_recomposition"] is True
    assert audit["minutes_reestimated"] is True
    assert audit["starts_reestimated"] is (disposition == "stated_expected_absent")
    summary = module.participation_summary(result.projection.diagnostics)
    assert summary["captured_percentage_count"] == 0
    assert summary["applied_player_count"] == summary["manager_statement_count"] == 1
    assert summary["unapplied_statement_count"] == 0
    assert summary["assumptions"] == [
        "source_verified_joint_law_intervention",
        "fixture_families_recomputed",
        "declared_intervention_not_calibration",
        "no_external_calibration",
    ]
    outcome = summary["statement_outcomes"][0]
    assert outcome == {
        "player_id": word.player_id,
        "disposition": disposition,
        "applied": True,
        "reason": "explicit_full_match_restriction"
        if disposition == "stated_full_match_unavailable"
        else "explicit_evidence",
        "source_url": word.source_url,
        "source_published_at": word.published_at_utc,
    }
    assert_frame_equal(result.horizon.table, state.outputs[0], check_exact=True)
    if disposition == "stated_expected_absent":
        assert result.projection.unavailable_players == (3,)
    else:
        assert result.projection.unavailable_players == ()


def test_composite_future_zero_does_not_claim_missing_conditional_provenance(monkeypatch):
    football, inputs, words, basis, _, _ = dispatch_case(monkeypatch)
    future = football.horizon.table.gameweek.ne(inputs.deadline.gameweek)
    assert future.any()
    football.horizon.table.loc[future, "appearance_probability"] = 0.0
    football.horizon.table.loc[future, "expected_points"] = 0.0
    result = bind(football, inputs, words, basis)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["inherited_future_zero"] is False
    assert (
        "future_values_not_recovered"
        not in module.participation_summary(result.projection.diagnostics)["assumptions"]
    )
    assert_frame_equal(
        result.horizon.table.loc[future], football.horizon.table.loc[future], check_exact=True
    )


@pytest.mark.parametrize(
    "changes,reason,forwarded",
    [
        ({"publication_verified": False}, "publication_unverified", False),
        ({"scope_verified": False}, "upcoming_league_scope_unverified", False),
        ({"published_precision": "day"}, "source_time_or_citation_missing", False),
        (
            {
                "words": None,
                "words_status": WORDS_UNRESOLVED,
                "source_sha256": None,
                "span_start": None,
                "span_end": None,
                "scope_verified": False,
                "publication_verified": False,
            },
            "source_span_unresolved",
            False,
        ),
        ({"fetched_at_utc": "2026-09-22T13:00:00+00:00"}, "future_evidence", True),
        ({"published_at_utc": "2026-09-01T10:00:00+00:00"}, "expired_evidence", True),
        (
            {"disposition": "stated_minutes_limited"},
            "categorical_statement_has_no_probability",
            True,
        ),
        (
            {"disposition": "stated_expected_to_start"},
            "categorical_statement_has_no_probability",
            True,
        ),
    ],
)
def test_actual_attestation_and_source_timing_refusals_reach_public_summary(
    monkeypatch, changes, reason, forwarded
):
    football, inputs, words, basis, state, _ = dispatch_case(monkeypatch)
    word = replace(words.words[0], **changes)
    result = bind(football, inputs, replace(words, words=(word,)), basis)
    assert bool(state.calls[0][0]) is forwarded
    assert bool(state.calls[0][1]) is forwarded
    assert state.selections[0].evidence == ()
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    summary = module.participation_summary(result.projection.diagnostics)
    assert summary["applied_player_count"] == 0
    assert summary["manager_statement_count"] == summary["unapplied_statement_count"] == 1
    assert summary["statement_outcomes"][0]["applied"] is False
    assert summary["statement_outcomes"][0]["reason"] == reason
    assert "source_verified_joint_law_intervention" not in summary["assumptions"]
    assert "fixture_families_recomputed" not in summary["assumptions"]
    assert "retained_joint_baseline_unchanged" in summary["assumptions"]
    assert (
        result.projection.diagnostics["composite_reprojection_fingerprint"] == football.fingerprint
    )


@pytest.mark.parametrize("failure", ["missing_rotation", "wrong_week", "unverified_source", "dgw"])
def test_container_and_ambiguous_week_checks_happen_before_dispatch(monkeypatch, failure):
    football, inputs, words, basis, state, _ = dispatch_case(monkeypatch, dgw=failure == "dgw")
    rotation = "d" * 64
    reason = "source_documents_unverified"
    if failure == "missing_rotation":
        rotation = None
    elif failure == "wrong_week":
        words = replace(words, gameweek=7)
        reason = "decision_week_mismatch"
    elif failure == "unverified_source":
        words = replace(words, source_check="synthetic_unverified")
    else:
        reason = "ambiguous_current_week_fixture"
    result = bind(football, inputs, words, basis, rotation=rotation)
    assert state.calls[0] == ((), {})
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    summary = module.participation_summary(result.projection.diagnostics)
    assert summary["statement_outcomes"][0]["reason"] == reason
    assert summary["statement_outcomes"][0]["applied"] is False


def test_no_news_keeps_complete_original_horizon_and_binds_diagnostic_identity(monkeypatch):
    football, inputs, _, basis, state, _ = dispatch_case(monkeypatch)
    result = bind(football, inputs, None, basis, rotation=None)
    assert state.calls == [((), {})]
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    assert module.participation_summary(result.projection.diagnostics) is None
    assert (
        result.projection.diagnostics["composite_reprojection_fingerprint"] == football.fingerprint
    )


def test_dispatch_failure_propagates_without_a_scalar_fallback(monkeypatch):
    football, inputs, words, basis, state, _ = dispatch_case(monkeypatch)
    state.failure = "Synthetic unavailable composite source basis."
    with pytest.raises(ValueError, match="Synthetic unavailable"):
        bind(football, inputs, words, basis)
    assert len(state.calls) == 1
    assert state.outputs == []


def test_repeated_calls_dispatch_original_basis_without_compounding(monkeypatch):
    football, inputs, words, basis, state, _ = dispatch_case(monkeypatch)
    first = bind(football, inputs, words, basis)
    second = bind(football, inputs, words, basis)
    reset = bind(football, inputs, None, basis, rotation=None)
    assert_frame_equal(first.horizon.table, second.horizon.table, check_exact=True)
    assert_frame_equal(reset.horizon.table, football.horizon.table, check_exact=True)
    assert state.fingerprints[0] == state.fingerprints[1]
    assert state.fingerprints[2] == football.fingerprint
