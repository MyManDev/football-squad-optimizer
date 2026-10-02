"""Coding configuration survives replay without publishing the credential destination."""

import hashlib
import json
from dataclasses import replace

import pytest

from squadopt.data.errors import InvalidValueError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument, RosterPlayer
from squadopt.data.sources.club_news_capture import (
    INDEX_PAYLOAD,
    CodedClub,
    capture_payloads,
    read_captured_responses,
    write_club_news_capture,
)
from squadopt.data.sources.club_news_coding import ROTATION_CLAIM_CODING_CONTRACT_VERSION
from squadopt.platform.club_news_provider import CodingProviderConfig, code_week_by_club

SETTINGS = {
    "protocol": "openai_chat_completions_v1",
    "endpoint_sha256": "a" * 64,
    "response_format": "json_schema",
    "max_completion_tokens": 1000,
}


def _world():
    raw = b"The coach said the synthetic player will miss the next league match."
    document = RawDocument(
        "Synthetic Club",
        "https://example.test/news/one",
        "https://example.test/news/one",
        200,
        "text/plain",
        len(raw),
        "2026-10-01T10:00:00Z",
        raw,
        raw,
    )
    response = ClaimResponse(
        json.dumps({"contract_version": "rotation_claim_coding_v2", "documents": [], "claims": []}),
        "chosen-model",
        "returned-model",
    )
    return document, CodedClub(
        "Synthetic Club",
        response,
        "rotation_claim_coding_v2",
        "b" * 64,
        "openai-compatible",
        SETTINGS,
    )


def test_new_request_configuration_roundtrips_and_old_record_remains_readable(tmp_path):
    document, coded = _world()
    for configured, root in (
        (coded, tmp_path / "new"),
        (replace(coded, request_configuration=None), tmp_path / "old"),
    ):
        captured = write_club_news_capture(
            root,
            documents=(document,),
            coded=(configured,),
            clubs_declared=(document.club,),
            clubs_covered=(document.club,),
            captured_at_utc="2026-10-01T10:01:00Z",
        )
        snapshot = read_snapshot(root, captured.snapshot_id)
        result = read_captured_responses(snapshot)[0]
        assert result.request_configuration == configured.request_configuration
        assert result.response == configured.response
        index = json.loads(snapshot.payloads[INDEX_PAYLOAD])
        assert ("request_configuration" in index["responses"][0]) == (root.name == "new")


def test_configuration_is_copied_and_cannot_be_mutated_after_capture_is_prepared():
    document, original = _world()
    settings = dict(SETTINGS)
    coded = replace(original, request_configuration=settings)
    settings["max_completion_tokens"] = 2
    with pytest.raises(TypeError):
        coded.request_configuration["max_completion_tokens"] = 3
    payload = capture_payloads(
        (document,), (coded,), clubs_declared=(document.club,), clubs_covered=(document.club,)
    )
    assert json.loads(payload[INDEX_PAYLOAD])["responses"][0]["request_configuration"] == SETTINGS


@pytest.mark.parametrize(
    "change",
    [
        {"api_key": "synthetic-secret"},
        {"endpoint_sha256": "https://private.example"},
        {"max_completion_tokens": True},
        {"max_completion_tokens": 0},
        {"response_format": "silent-fallback"},
        {"protocol": "unknown"},
    ],
)
def test_unknown_fields_and_unbounded_values_are_not_retained(change):
    _, coded = _world()
    with pytest.raises(InvalidValueError):
        replace(coded, request_configuration={**SETTINGS, **change})


def test_provider_records_settings_but_not_key_or_private_endpoint():
    document, coded = _world()

    class Provider:
        def code(self, documents, roster):
            # Archived v2 stays readable above; a new call must answer the current question.
            return replace(
                coded.response,
                text=json.dumps(
                    {
                        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                        "documents": [],
                        "claims": [],
                    }
                ),
            )

    endpoint = "https://private.example/v1"
    config = CodingProviderConfig(
        "openai-compatible", "chosen-model", "synthetic-secret", endpoint, "json_object", 1234
    )
    values, refused = code_week_by_club(
        Provider(), config, (document,), (RosterPlayer(1, "Synthetic Player", document.club),)
    )
    assert not refused
    record = values[0].request_configuration
    assert record == {
        "protocol": "openai_chat_completions_v1",
        "endpoint_sha256": hashlib.sha256((endpoint + "/chat/completions").encode()).hexdigest(),
        "response_format": "json_object",
        "max_completion_tokens": 1234,
    }
    payload = capture_payloads(
        (document,), values, clubs_declared=(document.club,), clubs_covered=(document.club,)
    )
    assert b"synthetic-secret" not in payload[INDEX_PAYLOAD]
    assert endpoint.encode() not in payload[INDEX_PAYLOAD]
