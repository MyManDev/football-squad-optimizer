"""Offline source-to-lineup chain; synthetic inputs, no model or football gain claim.

Only the HTTP edge is mocked. All captures, source-span checks, replay, optional
component loading and minute binding use their production entry points. The
fixture's learned minute components are synthetic and never saved under data/.
"""

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from json import dumps as encode_json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.unit.test_football_minute_integration import world
from tests.unit.test_minute_evidence import BENCH, XI, documents

from squadopt.application.football_participation import bind_football_participation
from squadopt.application.manager_words import (
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    WORDS_SHOWN,
    load_manager_words,
)
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import RawDocument, RosterPlayer
from squadopt.data.sources.club_news_capture import read_club_news_capture, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.live.football_artifact import forecast_digest
from squadopt.platform.club_news_openai import OpenAIClubNewsProvider, OpenAIReply
from squadopt.platform.club_news_provider import code_week_by_club, resolve_provider_config
from squadopt.platform.football_minute_basis import (
    football_components_path,
    load_football_minute_basis,
)
from squadopt.scenarios.expected_lineup import expected_lineup_score

CLUB = "Synthetic Club 3"
URL = "https://club.example/synthetic/coach"
QUOTE = "Player 3 cannot complete the full upcoming league match."
VAGUE_QUOTE = "Player 3 will have managed minutes in the upcoming league match."
LABEL = "stated_full_match_unavailable"
PUBLISHED_AT = "2026-09-22T10:00:00Z"
FETCHED_AT = "2026-09-22T11:00:00Z"
DEADLINE = "2026-09-23T12:00:00Z"
FAKE_KEY = "offline-integration-sentinel-never-a-real-key"


class _Transport:
    """A canned Chat Completions edge; it cannot access a network."""

    def __init__(self, answer: str, returned_model: str) -> None:
        self.answer = answer
        self.returned_model = returned_model
        self.calls: list[Mapping[str, object]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> OpenAIReply:
        assert url == "https://api.openai.com/v1/chat/completions"
        assert headers["Authorization"] == f"Bearer {FAKE_KEY}"
        assert timeout > 0
        assert "tools" not in json
        self.calls.append(json)
        envelope = {
            "model": self.returned_model,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": self.answer,
                        "refusal": None,
                    },
                }
            ],
        }
        # The parameter deliberately has the wire protocol's name.
        body = encode_json(envelope).encode("utf-8")
        return OpenAIReply(status_code=200, body=body)


def _captured_world(tmp_path: Path):
    """Bind the existing synthetic component fixture to a complete synthetic capture."""
    parts = deepcopy(documents())
    served, companion, calendar, clubs = parts
    football, _, _, _ = world(parts)
    players = football.projection.table
    positions = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4}
    bootstrap = {
        "teams": [
            {"id": 100 + club, "code": club, "name": f"Synthetic Club {club}"}
            for club in sorted(set(clubs.values()))
        ],
        "elements": [
            {
                "id": 1000 + int(row.player_id),
                "code": int(row.player_id),
                "team": 100 + clubs[int(row.player_id)],
                "web_name": str(row.name),
                "first_name": "Synthetic",
                "second_name": str(row.name),
                "element_type": positions[str(row.position)],
                "now_cost": 50,
                "status": "a",
                "chance_of_playing_next_round": 100,
                "news": "",
                "news_added": None,
                "scout_risks": [],
                "scout_news_link": None,
            }
            for row in players.itertuples()
        ],
        "events": [
            {"id": 6, "deadline_time": DEADLINE, "finished": False},
            {"id": 7, "deadline_time": "2026-09-30T12:00:00Z", "finished": False},
        ],
    }
    fixtures = [
        {
            "id": int(row.fixture),
            "event": int(row.GW),
            "team_h": 100 + int(row.club),
            "team_a": 100 + int(row.opponent),
            "kickoff_time": row.kickoff,
            "team_h_difficulty": 3,
            "team_a_difficulty": 3,
            "finished": False,
            "provisional_start_time": False,
        }
        for row in calendar.loc[calendar.home.eq(1)].itertuples()
    ]
    snapshots = tmp_path / "snapshots"
    metadata = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=served["captured_at_utc"],
        payloads={
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode("utf-8"),
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
    football, inputs, _, _ = world(parts)
    artifacts = tmp_path / "artifacts"
    components_path = football_components_path(artifacts, inputs.snapshot_id)
    components_path.parent.mkdir(parents=True)
    components_path.write_text(json.dumps(companion), encoding="utf-8")
    components_path.with_name(inputs.snapshot_id + ".json").write_text(
        json.dumps(served),
        encoding="utf-8",
    )
    loaded = load_football_minute_basis(
        artifact_root=artifacts,
        snapshot_root=snapshots,
        inputs=inputs,
        football=football,
    )
    assert loaded.reason is None and loaded.basis is not None
    assert loaded.components_sha256 == hashlib.sha256(components_path.read_bytes()).hexdigest()
    roster = tuple(
        RosterPlayer(
            player_id=int(row.player_id),
            web_name=str(row.name),
            team_name=f"Synthetic Club {clubs[int(row.player_id)]}",
        )
        for row in players.itertuples()
    )
    return football, inputs, loaded.basis, snapshots, roster


def _capture_reply(
    snapshots,
    roster,
    *,
    requested: str,
    returned: str,
    source_quote: str = QUOTE,
    reply_quote: str | None = None,
    disposition: str = LABEL,
    fetched_at: str = FETCHED_AT,
):
    content = (f"Published: {PUBLISHED_AT}\nCoach: {source_quote}\n").encode()
    source = RawDocument(
        club=CLUB,
        requested_url=URL,
        final_url=URL,
        http_status=200,
        content_type="text/plain",
        byte_length=len(content),
        fetched_at_utc=fetched_at,
        content=content,
        readable=content,
    )
    answer = json.dumps(
        {
            "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            "documents": [
                {"url": URL, "published_at_utc": PUBLISHED_AT, "published_precision": "instant"}
            ],
            "claims": [
                {
                    "player_name": "Player 3",
                    "team_name": CLUB,
                    "disposition": disposition,
                    "speaker": "manager",
                    "source_url": URL,
                    "quote": source_quote if reply_quote is None else reply_quote,
                    "paraphrase": "The coach described participation in the next league match.",
                }
            ],
        }
    )
    config = resolve_provider_config(
        {
            "SQUADOPT_LLM_PROVIDER": "openai",
            "SQUADOPT_LLM_MODEL": requested,
            "SQUADOPT_LLM_API_KEY": FAKE_KEY,
        }
    )
    assert config.base_url is not None
    transport = _Transport(answer, returned)
    provider = OpenAIClubNewsProvider(
        api_key=config.api_key,
        model_identifier=config.model_identifier,
        base_url=config.base_url,
        response_format=config.response_format,
        max_completion_tokens=config.max_completion_tokens,
        allow_local_http=config.allow_local_http,
        transport=transport,
    )
    coded, refused = code_week_by_club(provider, config, (source,), roster)
    assert refused == () and len(coded) == 1
    assert len(transport.calls) == 1
    assert transport.calls[0]["model"] == requested
    assert coded[0].prompt_contract_version == ROTATION_CLAIM_CODING_CONTRACT_VERSION
    assert coded[0].prompt_sha256 == coding_prompt_sha256(requested)
    news = write_club_news_capture(
        snapshots,
        documents=(source,),
        coded=coded,
        clubs_declared=(CLUB,),
        clubs_covered=(CLUB,),
        captured_at_utc=fetched_at,
    )
    captured = read_snapshot(snapshots, news.snapshot_id)
    _, stored, _, _, _ = read_club_news_capture(captured)
    assert stored[0].response.model_identifier == requested
    assert stored[0].response.model_version == returned
    assert stored[0].response.text == answer
    assert stored[0].request_configuration == coded[0].request_configuration
    assert stored[0].request_configuration is not None
    assert stored[0].request_configuration["protocol"] == "openai_chat_completions_v1"
    assert FAKE_KEY not in captured.payloads["index.json"].decode("utf-8")
    return news, source, transport


def _export(snapshots, inputs, news, output):
    return export_rotation_evidence(
        RotationExportRequest(
            season=inputs.season,
            target_gameweek=inputs.deadline.gameweek,
            deadline_utc=DEADLINE,
            snapshot=inputs.snapshot_id,
            snapshot_root=snapshots,
            club_news_fixture=None,
            club_news_snapshot=news.snapshot_id,
            output_dir=output,
        ),
        repository_commit="0" * 40,
    )


def _bind(football, inputs, basis, words, table_sha256):
    return bind_football_participation(
        football,
        inputs,
        manager_words=words,
        rotation_table_sha256=table_sha256,
        minute_basis=basis,
        minute_basis_reason=None,
    )


def _best_of_two_legal_roles(frame: pd.DataFrame):
    """A declared two-option decision, not a claim of global optimizer optimality."""
    squad = frame.loc[frame.player_id.le(15)].copy()
    assert squad.groupby("team_id").size().max() <= 3
    swapped_xi = tuple(6 if player == 3 else player for player in XI)
    swapped_bench = tuple(3 if player == 6 else player for player in BENCH)
    choices = [
        expected_lineup_score(squad, starters, bench, 13, 8)
        for starters, bench in ((XI, BENCH), (swapped_xi, swapped_bench))
    ]
    best = max(choices, key=lambda score: score.expected_net_points)
    assert len(best.starting_xi) == 11 and len(best.ordered_bench) == 4
    assert set(best.starting_xi).isdisjoint(best.ordered_bench)
    assert set(best.starting_xi) | set(best.ordered_bench) == set(squad.player_id)
    position = squad.set_index("player_id").position
    counts = position.loc[list(best.starting_xi)].value_counts()
    assert counts["GK"] == 1 and 3 <= counts["DEF"] <= 5
    assert 2 <= counts["MID"] <= 5 and 1 <= counts["FWD"] <= 3
    assert best.captain_id == 13 and best.vice_captain_id == 8
    return best


def test_mocked_openai_source_capture_replay_changes_only_supported_minute_decision(tmp_path):
    football, inputs, basis, snapshots, roster = _captured_world(tmp_path)
    original = football.horizon.table.copy(deep=True)
    before = _best_of_two_legal_roles(football.projection.table)
    assert 3 in before.starting_xi and 6 in before.ordered_bench
    accepted = []
    manifests: list[dict[str, Any]] = []
    for suffix in ("a", "b"):
        requested, returned = f"synthetic-model-{suffix}", f"synthetic-revision-{suffix}"
        news, source, transport = _capture_reply(
            snapshots,
            roster,
            requested=requested,
            returned=returned,
        )
        first = _export(snapshots, inputs, news, tmp_path / f"rotation-{suffix}")
        replay = _export(snapshots, inputs, news, tmp_path / f"replay-{suffix}")
        assert first["table_sha256"] == replay["table_sha256"]
        assert len(transport.calls) == 1, "capture replay must not call the model again"
        table = Path(first["table_path"])
        manifest = json.loads(Path(first["manifest_path"]).read_text(encoding="utf-8"))
        assert manifest["model_identifier"] == requested
        assert manifest["model_version"] == returned
        assert manifest["prompt_sha256"] == coding_prompt_sha256(requested)
        manifests.append(manifest)
        words = load_manager_words(
            table,
            club_news_source=snapshots / news.snapshot_id,
            snapshot_root=snapshots,
        )
        assert words.source_check == SOURCE_CHECK_CITED_DOCUMENTS_HELD
        assert len(words.words) == 1
        claim = words.words[0]
        assert (claim.player_id, claim.disposition, claim.words_status) == (3, LABEL, WORDS_SHOWN)
        assert claim.words == QUOTE
        assert claim.source_sha256 == hashlib.sha256(source.readable).hexdigest()
        assert source.readable[claim.span_start : claim.span_end].decode("utf-8") == QUOTE
        result = _bind(football, inputs, basis, words, first["table_sha256"])
        assert_series_equal(
            result.horizon.table.appearance_probability,
            original.appearance_probability,
            check_exact=True,
        )
        assert_frame_equal(
            result.horizon.table.loc[result.horizon.table.gameweek.eq(7)],
            original.loc[original.gameweek.eq(7)],
            check_exact=True,
        )
        after = _best_of_two_legal_roles(result.projection.table)
        assert 6 in after.starting_xi and 3 in after.ordered_bench
        audit = result.projection.diagnostics["participation_evidence"]
        assert audit["minutes_reestimated"] is True and audit["starts_reestimated"] is False
        accepted.append(result)
    assert manifests[0]["prompt_sha256"] != manifests[1]["prompt_sha256"]
    assert manifests[0]["document_sha256s"] == manifests[1]["document_sha256s"]
    assert_frame_equal(accepted[0].horizon.table, accepted[1].horizon.table, check_exact=True)

    # Replies are durable even when their evidence cannot support a minute update.
    for bad in ("missing_quote", "late", "vague"):
        options: dict[str, Any] = {}
        if bad == "missing_quote":
            options["reply_quote"] = "Player 3 cannot finish the whole next league match."
        elif bad == "late":
            options["fetched_at"] = "2026-09-22T13:00:00Z"
        else:
            options.update(source_quote=VAGUE_QUOTE, disposition="stated_minutes_limited")
        news, _, transport = _capture_reply(
            snapshots,
            roster,
            requested=f"synthetic-{bad}",
            returned="synthetic-refused",
            **options,
        )
        if bad == "late":
            with pytest.raises(DataError):
                _export(snapshots, inputs, news, tmp_path / bad)
            # Export refuses before the late source can become current decision evidence.
            result = _bind(football, inputs, basis, None, None)
        else:
            exported = _export(snapshots, inputs, news, tmp_path / bad)
            words = load_manager_words(
                Path(exported["table_path"]),
                club_news_source=snapshots / news.snapshot_id,
                snapshot_root=snapshots,
            )
            assert not any(
                word.disposition == LABEL and word.words_status == WORDS_SHOWN
                for word in words.words
            )
            result = _bind(football, inputs, basis, words, exported["table_sha256"])
        assert len(transport.calls) == 1
        assert_frame_equal(result.horizon.table, original, check_exact=True)
        assert _best_of_two_legal_roles(result.projection.table).starting_xi == before.starting_xi
    assert_frame_equal(football.horizon.table, original, check_exact=True)
