"""Synthetic capture integration; no network, producer, optimizer or live stores."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.unit.test_minute_evidence import BENCH, XI, basis_from, documents

from squadopt.application.football_participation import (
    bind_football_participation,
    participation_summary,
)
from squadopt.application.manager_words import (
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    ManagerWord,
    ManagerWords,
)
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, GameweekDeadline
from squadopt.live import Projection, RecommendationInputs
from squadopt.live.football_artifact import FootballForecast, forecast_digest
from squadopt.planning.horizon import APPEARANCE_HORIZON_CONTRACT_VERSION, ProjectionHorizon
from squadopt.platform.football_minute_basis import (
    football_components_path,
    load_football_minute_basis,
)
from squadopt.scenarios.expected_lineup import expected_lineup_score


def world(parts=None):
    parts = documents(eligibility=0.5) if parts is None else parts
    basis = basis_from(parts)
    served = parts[0]
    frame = basis.weekly_rows
    first = frame.loc[frame.gameweek.eq(6)].copy()
    roster = first[["player_id", "name", "team_id", "position", "price_tenths"]].copy()
    multiplier = parts[1]["captured_availability"]["multipliers"]
    availability = pd.DataFrame(
        {
            "player_id": [row["player_code"] for row in multiplier],
            "status": "d",
            "chance_of_playing": [row["multiplier"] * 100 for row in multiplier],
        }
    )
    inputs = RecommendationInputs(
        served["source_snapshot_id"],
        served["captured_at_utc"],
        served["season"],
        GameweekDeadline(6, "2026-09-23T12:00:00+00:00", False),
        roster,
        availability,
    )
    horizon = ProjectionHorizon(
        frame,
        inputs.season,
        inputs.snapshot_id,
        "fixture_football_candidate",
        served["model_version"],
        "synthetic-features",
        "synthetic-processing",
        contract_version=APPEARANCE_HORIZON_CONTRACT_VERSION,
    )
    football = FootballForecast(horizon, Projection(first, (), {}), served["fingerprint"])
    word = ManagerWord(
        player_id=3,
        disposition="stated_full_match_unavailable",
        speaker="Manager",
        published_at_utc="2026-09-22T10:00:00+00:00",
        published_precision="instant",
        club="Synthetic Club",
        source_url="https://club.example/full-match",
        fetched_at_utc="2026-09-22T11:00:00+00:00",
        words="He cannot play a full match.",
        source_sha256="c" * 64,
        span_start=0,
        span_end=27,
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
    return football, inputs, words, basis


def bind(football, inputs, words, basis, reason=None):
    return bind_football_participation(
        football,
        inputs,
        manager_words=words,
        rotation_table_sha256="d" * 64,
        minute_basis=basis,
        minute_basis_reason=reason,
    )


def test_verified_minute_restriction_updates_teammates_not_q_or_future():
    football, inputs, words, basis = world()
    before = football.horizon.table.copy(deep=True)
    result = bind(football, inputs, words, basis)
    after = result.horizon.table
    assert_series_equal(
        after.appearance_probability, before.appearance_probability, check_exact=True
    )
    assert_frame_equal(
        after.loc[after.gameweek.eq(7)], before.loc[before.gameweek.eq(7)], check_exact=True
    )
    old = before.loc[before.gameweek.eq(6)].set_index("player_id")
    new = result.projection.table.set_index("player_id")
    assert new.loc[3, "expected_points"] < old.loc[3, "expected_points"]
    assert new.loc[9, "expected_points"] > old.loc[9, "expected_points"]
    assert new.loc[9, "expected_points"] / new.loc[9, "appearance_probability"] > (
        old.loc[9, "expected_points"] / old.loc[9, "appearance_probability"]
    )
    # The captured 50% multiplier appears once, not once more during binding.
    raw = basis.fixture_rows.query("player_code == 9 and GW == 6").expected_points.sum()
    assert new.loc[9, "expected_points"] > 0.5 * raw
    assert football.fingerprint == result.fingerprint
    assert_frame_equal(football.horizon.table, before, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["minutes_reestimated"] is True
    assert audit["starts_reestimated"] is False
    summary = participation_summary(result.projection.diagnostics)
    assert summary["version"] == "football_participation_evidence_v1"
    assert summary["applied_player_count"] == 1
    assert summary["manager_statement_count"] == 1
    assert "no_start_or_minutes_reestimate" not in summary["assumptions"]
    assert "declared_minute_intervention_not_calibration" in summary["assumptions"]


def test_no_evidence_is_exact_original_horizon_even_with_optional_basis():
    football, inputs, _, basis = world()
    without = bind(football, inputs, None, None)
    with_basis = bind(football, inputs, None, basis)
    assert_frame_equal(with_basis.horizon.table, football.horizon.table, check_exact=True)
    assert_frame_equal(without.horizon.table, with_basis.horizon.table, check_exact=True)


@pytest.mark.parametrize("reason", ["missing_components", "invalid_components_or_source"])
def test_optional_companion_refusal_preserves_football_and_reports_label(reason):
    football, inputs, words, _ = world()
    result = bind(football, inputs, words, None, reason)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["minute_basis"]["reason"] == reason
    assert audit["unapplied_statements"][0]["reason"] == reason
    summary = participation_summary(result.projection.diagnostics)
    assert summary["unapplied_statement_count"] == 1
    assert "minute_evidence_not_applied" in summary["assumptions"]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"fetched_at_utc": "2026-09-22T13:00:00+00:00"}, "future_evidence"),
        ({"published_precision": "day"}, "source_time_or_citation_missing"),
        (
            {"source_sha256": None, "span_start": None, "span_end": None},
            "verified_source_span_missing",
        ),
        ({"disposition": "stated_minutes_limited"}, "categorical_statement_has_no_probability"),
    ],
)
def test_uncaptured_unverified_or_vague_statement_never_changes_minutes(changes, reason):
    football, inputs, words, basis = world()
    words = replace(words, words=(replace(words.words[0], **changes),))
    result = bind(football, inputs, words, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    records = audit["unapplied_statements"] + audit["manager_statements"]
    assert any(row["reason"] == reason for row in records)


@pytest.mark.parametrize(
    "options,reason",
    [
        ({"dgw": True}, "ambiguous_current_week_fixture"),
        ({"full_only_player": 3}, "no_learned_positive_sub90_support"),
    ],
)
def test_ambiguous_fixture_or_missing_learned_support_is_unapplied(options, reason):
    football, inputs, words, basis = world(documents(**options))
    result = bind(football, inputs, words, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    assert (
        result.projection.diagnostics["participation_evidence"]["unapplied_statements"][0]["reason"]
        == reason
    )


def test_absence_supersedes_minute_restriction_without_teammate_redistribution():
    football, inputs, words, basis = world()
    absence = replace(
        words.words[0],
        disposition="stated_expected_absent",
        source_url="https://club.example/absence",
    )
    words = replace(words, words=(words.words[0], absence))
    result = bind(football, inputs, words, basis)
    table = result.projection.table.set_index("player_id")
    assert table.loc[3, "appearance_probability"] == 0
    assert table.loc[3, "expected_points"] == 0
    assert (
        table.loc[9, "expected_points"]
        == football.projection.table.set_index("player_id").loc[9, "expected_points"]
    )
    audit = result.projection.diagnostics["participation_evidence"]
    assert (
        audit["unapplied_statements"][0]["reason"]
        == "explicit_absence_supersedes_minute_restriction"
    )


def test_zero_captured_eligibility_cannot_redistribute_teammates_for_redundant_minute_claim():
    parts = documents()
    for row in parts[1]["captured_availability"]["multipliers"]:
        if row["player_code"] == 3:
            row["multiplier"] = 0.0
    parts[1]["fingerprint"] = forecast_digest(parts[1])
    football, inputs, words, basis = world(parts)
    result = bind(football, inputs, words, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"][0]["reason"] == "zero_effective_appearance_basis"


def test_existing_contradictory_absence_and_start_also_blocks_minute_intervention():
    football, inputs, words, basis = world()
    absence = replace(
        words.words[0],
        disposition="stated_expected_absent",
        source_url="https://club.example/absence",
    )
    starting = replace(
        words.words[0],
        disposition="stated_expected_to_start",
        source_url="https://club.example/start",
    )
    words = replace(words, words=(words.words[0], absence, starting))
    result = bind(football, inputs, words, basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"] == []
    assert audit["manager_statements"][0]["reason"] == "conflicting_sources"


def test_duplicate_minute_sources_are_withheld():
    football, inputs, words, basis = world()
    result = bind(football, inputs, replace(words, words=words.words * 2), basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["unapplied_statements"] == []
    assert audit["manager_statements"][0]["reason"] == "duplicate_evidence_or_source"
    assert participation_summary(result.projection.diagnostics)["unapplied_statement_count"] == 2


def test_mixed_minute_and_absence_from_same_source_cannot_escape_duplicate_guard():
    football, inputs, words, basis = world()
    absence = replace(words.words[0], disposition="stated_expected_absent")
    result = bind(football, inputs, replace(words, words=(words.words[0], absence)), basis)
    assert_frame_equal(result.horizon.table, football.horizon.table, check_exact=True)
    audit = result.projection.diagnostics["participation_evidence"]
    assert audit["manager_statements"][0]["reason"] == "duplicate_evidence_or_source"
    assert audit["minutes_reestimated"] is False
    summary = participation_summary(result.projection.diagnostics)
    assert summary["manager_statement_count"] == 2
    assert summary["unapplied_statement_count"] == 2


def test_synthetic_source_to_public_points_changes_a_legal_lineup_ordering():
    # Offline end-to-end hook: captured evidence -> horizon -> official lineup score.
    # No planner invocation, solver budget, LLM output, archive or real-data gain claim.
    football, inputs, words, basis = world(documents())
    result = bind(football, inputs, words, basis)
    before = football.projection.table.query("player_id <= 15")
    after = result.projection.table.query("player_id <= 15")
    swap_xi = tuple(6 if player == 3 else player for player in XI)
    swap_bench = tuple(3 if player == 6 else player for player in BENCH)

    def difference(frame):
        return (
            expected_lineup_score(frame, swap_xi, swap_bench, 13, 8).expected_net_points
            - expected_lineup_score(frame, XI, BENCH, 13, 8).expected_net_points
        )

    assert difference(before) < 0
    assert difference(after) > 0


def test_overlapping_minute_claims_do_not_block_another_players_supported_restriction():
    football, inputs, words, basis = world()
    repeated = replace(words.words[0], source_url="https://club.example/second-source")
    separate = replace(words.words[0], player_id=4, source_url="https://club.example/other-player")
    result = bind(
        football, inputs, replace(words, words=(words.words[0], repeated, separate)), basis
    )
    original = football.projection.table.set_index("player_id")
    revised = result.projection.table.set_index("player_id")
    assert revised.loc[3, "expected_points"] == original.loc[3, "expected_points"]
    assert revised.loc[4, "expected_points"] < original.loc[4, "expected_points"]
    audit = result.projection.diagnostics["participation_evidence"]
    assert len(audit["unapplied_statements"]) == 2
    assert all(
        row["reason"] == "overlapping_minute_statements" for row in audit["unapplied_statements"]
    )


def captured_files(tmp_path):
    served, companion, calendar, clubs = deepcopy(documents(eligibility=0.5))
    bootstrap = {
        "teams": [{"id": 100 + club, "code": club} for club in sorted(set(clubs.values()))],
        "elements": [{"code": player, "team": 100 + club} for player, club in clubs.items()],
    }
    fixtures = [
        {
            "id": int(row.fixture),
            "event": int(row.GW),
            "team_h": 100 + int(row.club),
            "team_a": 100 + int(row.opponent),
            "kickoff_time": row.kickoff,
        }
        for row in calendar.loc[calendar.home.eq(1)].itertuples()
    ]
    # Real bootstrap fixture lists can include an unassigned match. Its null event
    # coerces the full pandas column to float, including the selected known weeks.
    fixtures.append({"id": 999, "event": None, "team_h": 101, "team_a": 102, "kickoff_time": None})
    snapshots = tmp_path / "snapshots"
    metadata = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=served["captured_at_utc"],
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
        },
    )
    for document in (served, companion):
        document.update(
            source_snapshot_id=metadata.snapshot_id,
            captured_at_utc=metadata.captured_at_utc,
            source_fingerprint=metadata.fingerprint,
        )
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    football, inputs, words, _ = world((served, companion, calendar, clubs))
    artifacts = tmp_path / "artifacts"
    path = football_components_path(artifacts, inputs.snapshot_id)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(companion), encoding="utf-8")
    path.with_name(inputs.snapshot_id + ".json").write_text(json.dumps(served), encoding="utf-8")
    return artifacts, snapshots, inputs, football, words, path


def load_case(case):
    artifacts, snapshots, inputs, football, _, _ = case
    return load_football_minute_basis(
        artifact_root=artifacts,
        snapshot_root=snapshots,
        inputs=inputs,
        football=football,
    )


def test_loader_verifies_captured_calendar_persistent_clubs_and_loaded_scaling(tmp_path):
    case = captured_files(tmp_path)
    loaded = load_case(case)
    assert loaded.reason is None
    assert loaded.basis is not None
    assert loaded.components_sha256 == hashlib.sha256(case[-1].read_bytes()).hexdigest()
    result = bind(case[3], case[2], case[4], loaded.basis)
    assert result.projection.diagnostics["participation_evidence"]["minutes_reestimated"] is True


@pytest.mark.parametrize(
    "kind", ["missing", "malformed", "wrong_header", "wrong_loaded_q", "wrong_source"]
)
def test_optional_loader_refuses_bad_basis_without_mutation(tmp_path, kind):
    case = captured_files(tmp_path)
    path = case[-1]
    before = case[3].horizon.table.copy(deep=True)
    if kind == "missing":
        path.unlink()
    elif kind == "malformed":
        path.write_text("{invalid", encoding="utf-8")
    elif kind == "wrong_header":
        document = json.loads(path.read_text())
        document["captured_availability"]["multipliers"][0]["multiplier"] = 0.75
        document["fingerprint"] = forecast_digest(document)
        path.write_text(json.dumps(document))
    elif kind == "wrong_loaded_q":
        case[3].horizon.table.loc[0, "appearance_probability"] *= 0.5
        before = case[3].horizon.table.copy(deep=True)
    else:
        document = json.loads(path.read_text())
        document["source_fingerprint"] = "f" * 64
        document["fingerprint"] = forecast_digest(document)
        path.write_text(json.dumps(document))
    loaded = load_case(case)
    assert loaded.basis is None
    assert loaded.reason == (
        "missing_components" if kind == "missing" else "invalid_components_or_source"
    )
    assert_frame_equal(case[3].horizon.table, before, check_exact=True)
