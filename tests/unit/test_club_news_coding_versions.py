"""Versioned club-news labels preserve old bytes and require explicit cited scope."""

import hashlib
import json
from dataclasses import fields
from pathlib import Path

import pytest

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import (
    LEGACY_ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    PREVIOUS_ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ClaimResponse,
    ClubNewsError,
    RawDocument,
)
from squadopt.data.sources.club_news_capture import (
    CodedClub,
    read_club_news_capture,
    write_club_news_capture,
)
from squadopt.data.sources.club_news_claims import ParsedClaim, parse_claim_response, resolve_span
from squadopt.data.sources.club_news_coding import (
    LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    LEGACY_SYSTEM_PROMPT,
    PREVIOUS_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    coding_prompt_sha256,
    locate_claim_response,
    locate_claims_reporting,
    require_requested_coding_contract,
    response_schema,
)

LABEL = "stated_full_match_unavailable"
QUOTE = "Saka cannot complete the full upcoming league match."
URL = "https://club.example/arsenal/news"


def _document(quote: str = QUOTE) -> RawDocument:
    content = ("Published: 2026-09-12T13:00:00Z\n" + quote).encode("utf-8")
    return RawDocument(
        club="Arsenal",
        requested_url=URL,
        final_url=URL,
        http_status=200,
        content_type="text/plain",
        byte_length=len(content),
        fetched_at_utc="2026-09-12T14:00:00Z",
        content=content,
        readable=content,
    )


def _response(
    *,
    version: str = ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    label: str = LABEL,
    quote: str = QUOTE,
    speaker: str = "manager",
) -> ClaimResponse:
    text = json.dumps(
        {
            "contract_version": version,
            "documents": [
                {
                    "url": URL,
                    "published_at_utc": "2026-09-12T13:00:00Z",
                    "published_precision": "instant",
                }
            ],
            "claims": [
                {
                    "player_name": "Saka",
                    "team_name": "Arsenal",
                    "disposition": label,
                    "speaker": speaker,
                    "source_url": URL,
                    "quote": quote,
                    "paraphrase": "The source reports a limit for this league match.",
                    **(
                        {"fixture_scope": "upcoming_premier_league"}
                        if version == ROTATION_CLAIM_CODING_CONTRACT_VERSION
                        else {}
                    ),
                }
            ],
        }
    )
    return ClaimResponse(text=text, model_identifier="synthetic-stub", model_version="fixture-2")


def test_old_prompt_schema_and_digest_remain_exactly_available() -> None:
    legacy = LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
    assert (
        coding_prompt_sha256(contract_version=legacy)
        == "e755c70b96cef2dda4523d04e46292913bf3f8638d6b39261ee4ebd144ffbf5d"
    )
    assert LABEL not in LEGACY_SYSTEM_PROMPT
    assert LABEL not in json.dumps(response_schema(legacy))
    assert LABEL in SYSTEM_PROMPT
    assert LABEL in json.dumps(response_schema())
    assert "Vague managed minutes" in SYSTEM_PROMPT
    assert "probability" in SYSTEM_PROMPT
    assert coding_prompt_sha256() != coding_prompt_sha256(contract_version=legacy)
    assert (
        coding_prompt_sha256(contract_version=PREVIOUS_ROTATION_CLAIM_CODING_CONTRACT_VERSION)
        == "932de6f6bc43ba10042d38e50450215cfa0d7258b4b19afc2e3f8b12ab975b19"
    )


@pytest.mark.parametrize(
    "version,expected",
    [
        (
            LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            LEGACY_ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
        ),
        (ROTATION_CLAIM_CODING_CONTRACT_VERSION, ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION),
        (
            PREVIOUS_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            PREVIOUS_ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
        ),
    ],
)
def test_locator_preserves_response_generation_and_prior_labels(
    version: str, expected: str
) -> None:
    quote = "Saka will not travel."
    document = _document(quote)
    response = _response(version=version, label="stated_expected_absent", quote=quote)
    located = locate_claim_response(response, (document,))
    assert json.loads(located.text)["contract_version"] == expected
    claims = parse_claim_response(located, (document,))
    assert claims[0].disposition == "stated_expected_absent"
    assert resolve_span(document.readable, claims[0]) == quote.encode()


def test_old_contract_cannot_smuggle_in_the_new_label() -> None:
    document = _document()
    response = _response(version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION)
    with pytest.raises(ClubNewsError, match="disposition"):
        parse_claim_response(locate_claim_response(response, (document,)), (document,))


@pytest.mark.parametrize(
    "quote",
    [
        QUOTE,
        "In the next league match, Saka cannot play the full 90 minutes.",
        "Saka won't be able to complete the whole next Premier League game.",
        "Saka cannot complete the full next Premier League fixture.",
    ],
)
def test_explicit_upcoming_full_match_limit_remains_categorical_and_cited(quote: str) -> None:
    document = _document(quote)
    response = _response(quote=quote)
    claims = parse_claim_response(locate_claim_response(response, (document,)), (document,))
    claim = claims[0]
    assert claim.disposition == LABEL
    assert claim.speaker == "manager"
    assert claim.published_at_utc == "2026-09-12T13:00:00Z"
    assert claim.scope_verified and claim.publication_verified
    assert claim.source_sha256 == hashlib.sha256(document.readable).hexdigest()
    assert resolve_span(document.readable, claim) == quote.encode()
    assert not {"probability", "confidence", "expected_minutes"} & {
        field.name for field in fields(ParsedClaim)
    }


@pytest.mark.parametrize(
    "quote",
    [
        "Saka's minutes will be managed in the next league match.",
        "Saka has limited involvement in the next league match.",
        "Saka might not complete the full upcoming league match.",
        "Saka cannot complete the full cup match.",
        "Saka could not complete the full previous league match.",
        "Saka cannot complete the full match.",
        "If he is injured, Saka cannot complete the full upcoming league match.",
        "It is not true that Saka cannot complete the full upcoming league match.",
    ],
)
def test_vague_past_wrong_competition_and_conditional_quotes_do_not_authorize_new_label(
    quote: str,
) -> None:
    document = _document(quote)
    response = _response(quote=quote)
    with pytest.raises(ClubNewsError, match="explicit, unconditional"):
        parse_claim_response(locate_claim_response(response, (document,)), (document,))


GOOD = "Odegaard will not travel."


def _beside_a_good_claim(response: ClaimResponse, **saka: str) -> ClaimResponse:
    """Saka's claim, changed as given, followed by a claim nobody would refuse."""

    document = json.loads(response.text)
    document["claims"][0].update(saka)
    document["claims"].append(
        {
            **document["claims"][0],
            "player_name": "Odegaard",
            "disposition": "stated_expected_absent",
            "quote": GOOD,
            "fixture_scope": "upcoming_premier_league",
        }
    )
    return ClaimResponse(
        text=json.dumps(document),
        model_identifier=response.model_identifier,
        model_version=response.model_version,
    )


@pytest.mark.parametrize(
    "quote,scope,why",
    [
        (
            "Saka's minutes will be managed in the next league match.",
            "upcoming_premier_league",
            "explicit, unconditional",
        ),
        (QUOTE, "next_week", "fixture_scope"),
    ],
)
def test_a_claim_the_parser_refuses_alone_is_set_aside_and_the_rest_kept(
    quote: str, scope: str, why: str
) -> None:
    documents = (_document(f"{quote}\n{GOOD}"),)
    response = _beside_a_good_claim(_response(quote=quote), fixture_scope=scope)
    located, dropped = locate_claims_reporting(response, documents)
    (claim,) = parse_claim_response(located, documents)
    assert claim.player_name == "Odegaard"
    (refused,) = dropped
    assert (refused.player_name, refused.team_name, refused.source_url) == ("Saka", "Arsenal", URL)
    assert why in refused.why
    with pytest.raises(ClubNewsError, match=why):
        parse_claim_response(locate_claim_response(response, documents), documents)


def test_a_fault_of_the_whole_response_still_refuses_it_rather_than_every_claim() -> None:
    document = json.loads(_beside_a_good_claim(_response()).text)
    document["documents"][0]["published_at_utc"] = None
    response = ClaimResponse(
        text=json.dumps(document), model_identifier="synthetic-stub", model_version="fixture-2"
    )
    with pytest.raises(ClubNewsError, match="no dateline"):
        locate_claims_reporting(response, (_document(f"{QUOTE}\n{GOOD}"),))


def test_two_claims_about_one_player_are_still_refused_and_not_set_aside() -> None:
    documents = (_document(f"{QUOTE}\n{GOOD}"),)
    document = json.loads(_beside_a_good_claim(_response()).text)
    document["claims"][1]["player_name"] = "Saka"
    response = ClaimResponse(
        text=json.dumps(document), model_identifier="synthetic-stub", model_version="fixture-2"
    )
    located, dropped = locate_claims_reporting(response, documents)
    assert dropped == ()
    with pytest.raises(ClubNewsError, match="twice"):
        parse_claim_response(located, documents)


@pytest.mark.parametrize("label", ["stated_minutes_limited", "ambiguous", "no_statement"])
def test_existing_vague_labels_are_not_promoted_or_refused(label: str) -> None:
    quote = "Saka's involvement will be managed."
    document = _document(quote)
    response = _response(label=label, quote=quote)
    claims = parse_claim_response(locate_claim_response(response, (document,)), (document,))
    assert claims[0].disposition == label


@pytest.mark.parametrize("speaker", ["manager", "club_official", "club_statement", "unattributed"])
def test_existing_source_role_vocabulary_is_preserved(speaker: str) -> None:
    document = _document()
    response = _response(speaker=speaker)
    claim = parse_claim_response(locate_claim_response(response, (document,)), (document,))[0]
    assert claim.speaker == speaker


@pytest.mark.parametrize(
    "version,label",
    [
        (LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION, "stated_minutes_limited"),
        (ROTATION_CLAIM_CODING_CONTRACT_VERSION, LABEL),
    ],
)
def test_capture_roundtrip_keeps_prompt_raw_response_and_citation_provenance(
    tmp_path: Path,
    version: str,
    label: str,
) -> None:
    document = _document()
    response = _response(version=version, label=label)
    prompt_hash = coding_prompt_sha256(response.model_identifier, contract_version=version)
    coded = CodedClub(
        club="Arsenal",
        response=response,
        prompt_contract_version=version,
        prompt_sha256=prompt_hash,
        provider="fixture",
    )
    metadata = write_club_news_capture(
        tmp_path,
        documents=(document,),
        coded=(coded,),
        clubs_declared=("Arsenal",),
        clubs_covered=("Arsenal",),
        captured_at_utc="2026-09-12T14:30:00Z",
    )
    stored_documents, stored, *_ = read_club_news_capture(
        read_snapshot(tmp_path, metadata.snapshot_id)
    )
    assert stored_documents == (document,)
    assert stored == (coded,)
    assert stored[0].response.text.encode() == response.text.encode()
    assert stored[0].prompt_sha256 == prompt_hash
    first = parse_claim_response(locate_claim_response(response, (document,)), (document,))
    replay = parse_claim_response(
        locate_claim_response(stored[0].response, stored_documents), stored_documents
    )
    assert replay == first


def test_unknown_contract_does_not_use_current_schema_as_a_fallback() -> None:
    with pytest.raises(ClubNewsError, match="Unsupported"):
        response_schema("rotation_claim_coding_v99")
    with pytest.raises(ClubNewsError, match="Unsupported"):
        coding_prompt_sha256(contract_version="rotation_claim_coding_v99")
    with pytest.raises(ClubNewsError, match="contract"):
        locate_claim_response(_response(version="rotation_claim_coding_v99"), (_document(),))


@pytest.mark.parametrize(
    "text",
    [
        '{"contract_version":"rotation_claim_coding_v1"}',
        '{"contract_version":"rotation_claim_coding_v99"}',
        '{"contract_version":"untrusted-sentinel-secret"}',
        "{}",
        "[]",
        "untrusted-sentinel-secret is not JSON",
    ],
)
def test_acquisition_contract_guard_refuses_legacy_missing_unknown_or_malformed_response(
    text: str,
) -> None:
    response = ClaimResponse(text=text, model_identifier="chosen", model_version="returned")
    with pytest.raises(ClubNewsError) as error:
        require_requested_coding_contract(response)
    assert "untrusted-sentinel-secret" not in str(error.value)


def test_acquisition_contract_guard_does_not_rewrite_a_current_response() -> None:
    response = _response()
    original = response.text.encode("utf-8")
    require_requested_coding_contract(response)
    assert response.text.encode("utf-8") == original


def test_legacy_capture_stays_readable_even_when_it_is_not_a_new_response() -> None:
    document = _document()
    response = _response(
        version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION, label="stated_minutes_limited"
    )
    with pytest.raises(ClubNewsError, match="requested coding contract"):
        require_requested_coding_contract(response)
    claims = parse_claim_response(locate_claim_response(response, (document,)), (document,))
    assert claims[0].disposition == "stated_minutes_limited"
