"""Synthetic official facts and sourced coach evidence reach an auditable decision.

The provider transport is a canned response. Capture, HTML extraction, publication
attestation, rotation export/replay, component loading and participation binding are
production functions. No network, outcome archive, model fit or solver is used.
"""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.integration.test_openai_news_minute_chain import (
    CLUB,
    DEADLINE,
    FAKE_KEY,
    FETCHED_AT,
    PUBLISHED_AT,
    URL,
    _captured_world,
    _Transport,
)
from tests.unit.test_football_minute_integration import world

from squadopt.application.football_participation import (
    bind_football_participation,
    participation_summary,
)
from squadopt.application.manager_words import SOURCE_CHECK_CITED_DOCUMENTS_HELD, load_manager_words
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import RawDocument, RosterPlayer
from squadopt.data.sources.club_news_capture import read_club_news_capture, write_club_news_capture
from squadopt.data.sources.club_news_coding import ROTATION_CLAIM_CODING_CONTRACT_VERSION
from squadopt.data.sources.club_news_readable import extract_readable_text
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence import CONTRACT_VERSION
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.live import read_inputs
from squadopt.live.football_artifact import forecast_digest
from squadopt.platform.club_news_openai import OpenAIClubNewsProvider
from squadopt.platform.club_news_provider import code_week_by_club, resolve_provider_config
from squadopt.platform.football_minute_basis import (
    football_components_path,
    load_football_minute_basis,
)


def _official_world(tmp_path: Path, *, intervening_fixture=False):
    football, original_inputs, original_basis, snapshots, _ = _captured_world(tmp_path / "basis")
    old = read_snapshot(snapshots, original_inputs.snapshot_id)
    bootstrap = json.loads(old.payloads[BOOTSTRAP_PAYLOAD])
    # Stated 75, stated zero, unknown and stated 100 remain distinct official facts.
    values = {3: 75, 4: 0, 5: None, 6: 100}
    for row in bootstrap["elements"]:
        player = row["code"]
        row["chance_of_playing_this_round"] = 50 if player == 3 else None
        row["chance_of_playing_next_round"] = values.get(player, 100)
        row["status"] = "d" if player == 3 else "i" if player == 4 else "a"
        row["news"] = "Knock, assessed daily." if player == 3 else ""
        row["news_added"] = "2026-09-21T09:00:00Z" if player in (3, 6) else None
    fixtures = json.loads(old.payloads[FIXTURES_PAYLOAD])
    if intervening_fixture:
        bootstrap["events"].insert(
            0, {"id": 5, "deadline_time": "2026-09-21T12:00:00Z", "finished": True}
        )
        fixtures.append(
            {
                **fixtures[1],
                "id": 52,
                "event": 5,
                "kickoff_time": "2026-09-21T15:00:00Z",
                "finished": True,
            }
        )
    metadata = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=old.metadata.captured_at_utc,
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
        },
    )
    capture = read_snapshot(snapshots, metadata.snapshot_id)
    inputs = read_inputs(capture, season="2026-27")
    served, companion = deepcopy(original_basis.served), deepcopy(original_basis.companion)
    for document in (served, companion):
        document.update(
            source_snapshot_id=metadata.snapshot_id,
            captured_at_utc=metadata.captured_at_utc,
            source_fingerprint=metadata.fingerprint,
        )
    for entry in companion["captured_availability"]["multipliers"]:
        chance = values.get(entry["player_code"], 100)
        entry["multiplier"] = 1.0 if chance is None else chance / 100
    served["fingerprint"] = forecast_digest(served)
    companion["forecast_fingerprint"] = served["fingerprint"]
    companion["fingerprint"] = forecast_digest(companion)
    clubs = {row["code"]: row["team"] - 100 for row in bootstrap["elements"]}
    calendar = original_basis.fixture_rows[
        ["fixture", "club", "opponent", "home", "GW", "kickoff"]
    ].drop_duplicates()
    football, _, _, _ = world((served, companion, calendar, clubs))
    artifacts = tmp_path / "components"
    component_path = football_components_path(artifacts, inputs.snapshot_id)
    component_path.parent.mkdir(parents=True)
    component_path.write_text(json.dumps(companion), encoding="utf-8")
    component_path.with_name(inputs.snapshot_id + ".json").write_text(
        json.dumps(served), encoding="utf-8"
    )
    loaded = load_football_minute_basis(
        artifact_root=artifacts, snapshot_root=snapshots, inputs=inputs, football=football
    )
    assert loaded.reason is None and loaded.basis is not None
    roster = tuple(
        RosterPlayer(int(row["code"]), row["web_name"], f"Synthetic Club {clubs[row['code']]}")
        for row in bootstrap["elements"]
    )
    return football, inputs, loaded.basis, snapshots, roster


def _news_capture(snapshots, roster, *, quote, disposition, published=True, old_publication=False):
    instant = "2026-09-20T10:00:00Z" if old_publication else PUBLISHED_AT
    metadata = f'<meta property="article:published_time" content="{instant}">' if published else ""
    content = (
        f"<!doctype html><html><head>{metadata}</head><body>"
        f"<article><p>{quote}</p></article></body></html>"
    ).encode()
    source = RawDocument(
        club=CLUB,
        requested_url=URL,
        final_url=URL,
        http_status=200,
        content_type="text/html",
        byte_length=len(content),
        fetched_at_utc=FETCHED_AT,
        content=content,
        readable=extract_readable_text(content, "text/html"),
    )
    assert quote.encode() in source.readable and b"<meta" not in source.readable
    answer = json.dumps(
        {
            "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            "documents": [
                {"url": URL, "published_at_utc": instant, "published_precision": "instant"}
            ],
            "claims": [
                {
                    "player_name": "Player 3",
                    "team_name": CLUB,
                    "disposition": disposition,
                    "speaker": "manager",
                    "source_url": URL,
                    "quote": quote,
                    "paraphrase": "The source describes participation.",
                    # A model claim alone cannot verify competition or publication.
                    "fixture_scope": "upcoming_premier_league",
                }
            ],
        }
    )
    config = resolve_provider_config(
        {
            "SQUADOPT_LLM_PROVIDER": "openai",
            "SQUADOPT_LLM_MODEL": "synthetic-model",
            "SQUADOPT_LLM_API_KEY": FAKE_KEY,
        }
    )
    transport = _Transport(answer, "synthetic-model-revision")
    provider = OpenAIClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        base_url=config.base_url,
        response_format=config.response_format,
        max_completion_tokens=config.max_completion_tokens,
        transport=transport,
    )
    coded, refused = code_week_by_club(provider, config, (source,), roster)
    assert not refused and len(coded) == len(transport.calls) == 1
    news = write_club_news_capture(
        snapshots,
        documents=(source,),
        coded=coded,
        clubs_declared=(CLUB,),
        clubs_covered=(CLUB,),
        captured_at_utc=FETCHED_AT,
    )
    capture = read_snapshot(snapshots, news.snapshot_id)
    _, held, _, _, _ = read_club_news_capture(capture)
    assert held[0].response.text == answer
    assert held[0].prompt_contract_version == "rotation_claim_coding_v3"
    assert FAKE_KEY not in capture.payloads["index.json"].decode()
    return news, source, transport


@pytest.mark.parametrize(
    "quote,disposition,publication,intervening,applied,reason",
    [
        (
            "Player 3 cannot complete the full upcoming Premier League match.",
            "stated_full_match_unavailable",
            True,
            False,
            True,
            "explicit_full_match_restriction",
        ),
        (
            "Player 3 will miss the next Premier League match.",
            "stated_expected_absent",
            True,
            False,
            True,
            "explicit_evidence",
        ),
        (
            "Player 3 missed the previous league match.",
            "stated_expected_absent",
            True,
            False,
            False,
            "upcoming_league_scope_unverified",
        ),
        (
            "Player 3 will miss the cup match.",
            "stated_expected_absent",
            True,
            False,
            False,
            "upcoming_league_scope_unverified",
        ),
        (
            "Player 3 will miss the national team game.",
            "stated_expected_absent",
            True,
            False,
            False,
            "upcoming_league_scope_unverified",
        ),
        (
            "Player 3 cannot complete the full upcoming Premier League match.",
            "stated_full_match_unavailable",
            False,
            False,
            False,
            "source_time_or_citation_missing",
        ),
        (
            "Player 3 will miss the next Premier League match.",
            "stated_expected_absent",
            True,
            True,
            False,
            "upcoming_league_scope_unverified",
        ),
    ],
)
def test_source_to_public_decision_preserves_official_facts_and_only_applies_bound_evidence(
    tmp_path, quote, disposition, publication, intervening, applied, reason
):
    football, inputs, basis, snapshots, roster = _official_world(
        tmp_path, intervening_fixture=intervening
    )
    assert inputs.official_information is not None
    official = inputs.official_information.public_record((3, 4, 5, 6))
    official_players = {row["player_id"]: row for row in official["players"]}
    assert {player: row["source_chance_percent"] for player, row in official_players.items()} == {
        3: 75,
        4: 0,
        5: None,
        6: 100,
    }
    assert {player: row["news_state"] for player, row in official_players.items()} == {
        3: "present",
        4: "not_reported",
        5: "not_reported",
        6: "cleared",
    }
    availability_before = inputs.availability.copy(deep=True)
    original = football.horizon.table.copy(deep=True)
    news, source, transport = _news_capture(
        snapshots,
        roster,
        quote=quote,
        disposition=disposition,
        published=publication,
        old_publication=intervening,
    )
    request = RotationExportRequest(
        "2026-27",
        6,
        DEADLINE,
        inputs.snapshot_id,
        snapshots,
        None,
        tmp_path / "rotation",
        club_news_snapshot=news.snapshot_id,
    )
    exported = export_rotation_evidence(request, repository_commit="0" * 40)
    table = read_rotation_evidence_artifact(exported["table_path"], exported["manifest_path"])
    assert CONTRACT_VERSION == "rotation_evidence_v4"
    observed = table.loc[table.rotation_claim_observed]
    assert len(observed) == 1
    words = load_manager_words(
        exported["table_path"],
        club_news_source=snapshots / news.snapshot_id,
        snapshot_root=snapshots,
    )
    assert words.source_check == SOURCE_CHECK_CITED_DOCUMENTS_HELD
    (word,) = words.words
    assert word.player_id == 3 and word.disposition == disposition and word.words == quote
    assert word.source_sha256 == hashlib.sha256(source.readable).hexdigest()
    assert source.readable[word.span_start : word.span_end].decode() == quote
    if applied:
        assert word.publication_verified and word.scope_verified
        assert word.publication_source_sha256 == hashlib.sha256(source.content).hexdigest()
    result = bind_football_participation(
        football,
        inputs,
        manager_words=words,
        rotation_table_sha256=exported["table_sha256"],
        minute_basis=basis,
    )
    summary = participation_summary(result.projection.diagnostics)
    assert summary["manager_statement_count"] == 1
    assert summary["applied_player_count"] == int(applied)
    (outcome,) = summary["statement_outcomes"]
    assert outcome == {
        "player_id": 3,
        "disposition": disposition,
        "applied": applied,
        "reason": reason,
        "source_url": URL,
        "source_published_at": word.published_at_utc,
    }
    assert inputs.official_information.public_record((3, 4, 5, 6)) == official
    assert_frame_equal(inputs.availability, availability_before, check_exact=True)
    assert_frame_equal(football.horizon.table, original, check_exact=True)
    assert_frame_equal(
        result.horizon.table.query("gameweek == 7"),
        original.query("gameweek == 7"),
        check_exact=True,
    )
    before = football.projection.table.set_index("player_id")
    after = result.projection.table.set_index("player_id")
    if applied and disposition == "stated_full_match_unavailable":
        assert_series_equal(
            result.horizon.table.appearance_probability,
            original.appearance_probability,
            check_exact=True,
        )
        assert after.loc[3, "expected_points"] < before.loc[3, "expected_points"]
        assert after.loc[9, "expected_points"] > before.loc[9, "expected_points"]
        assert "declared_minute_intervention_not_calibration" in summary["assumptions"]
    elif applied:
        assert after.loc[3, "expected_points"] == after.loc[3, "appearance_probability"] == 0
    else:
        assert_frame_equal(result.horizon.table, original, check_exact=True)
    # Replay uses held source and response bytes; the injected provider edge remains at one call.
    assert len(transport.calls) == 1
