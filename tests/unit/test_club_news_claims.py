"""The parser, against the fixture that is the specification of its hard cases.

The fixture is the input on purpose. Its documents carry the three dateline precisions, a
redirect, a name that matches nobody, two surnames that collide, a literal per-cent sign
inside a cited span, and six responses that must be refused -- and it is committed, so these
tests measure the format rather than a copy of the format made up in this file.
"""

import hashlib
import json
from pathlib import Path

import pytest

from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_DISPOSITIONS,
    ClaimResponse,
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_claims import (
    ParsedClaim,
    parse_claim_response,
    resolve_span,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "sample" / "club_news_v1.fixture.json"


@pytest.fixture(name="provider")
def _provider() -> FixtureClubNewsProvider:
    return FixtureClubNewsProvider(FIXTURE_PATH)


@pytest.fixture(name="documents")
def _documents(provider: FixtureClubNewsProvider) -> tuple[RawDocument, ...]:
    return tuple(provider.fetch(url) for url in provider.urls)


@pytest.fixture(name="claims")
def _claims(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> tuple[ParsedClaim, ...]:
    response = provider.code(documents, provider.roster())
    return parse_claim_response(response, documents)


def _by_name(claims: tuple[ParsedClaim, ...], name: str) -> ParsedClaim:
    matched = [claim for claim in claims if claim.player_name == name]
    assert len(matched) == 1, name
    return matched[0]


def _rewritten(response: ClaimResponse, document: dict[str, object]) -> ClaimResponse:
    """The fixture's response with a hand-edited body, for the one-field cases."""

    return ClaimResponse(
        text=json.dumps(document, indent=2, sort_keys=True),
        model_identifier=response.model_identifier,
        model_version=response.model_version,
    )


# --- what the fixture's good response yields --------------------------------


def test_every_declared_claim_is_parsed(
    provider: FixtureClubNewsProvider,
    documents: tuple[RawDocument, ...],
    claims: tuple[ParsedClaim, ...],
) -> None:
    """Nothing is dropped quietly: the count comes from the response's own array."""

    declared = json.loads(provider.code(documents, provider.roster()).text)

    assert len(claims) == len(declared["claims"])
    assert len(claims) == len({(claim.player_name, claim.team_name) for claim in claims})


def test_every_claim_uses_only_the_closed_vocabularies(claims: tuple[ParsedClaim, ...]) -> None:
    for claim in claims:
        assert claim.disposition in ROTATION_DISPOSITIONS
        assert claim.speaker in CLAIM_SPEAKERS
        assert claim.published_precision in PUBLISHED_PRECISIONS


def test_no_parsed_claim_carries_any_text_from_the_source(
    claims: tuple[ParsedClaim, ...],
) -> None:
    """The reason the artifact can cite a manager without storing a word he said.

    ``paraphrase`` is required by the format and validated, then dropped. If it ever
    reappears as a field, this fails -- which is the point: a field kept in memory is a text
    column waiting to happen.
    """

    fields = set(ParsedClaim.__dataclass_fields__)

    assert not fields & {"paraphrase", "quote", "text", "snippet", "summary", "notes"}


def test_a_span_resolves_to_the_bytes_it_was_coded_on(
    claims: tuple[ParsedClaim, ...], documents: tuple[RawDocument, ...]
) -> None:
    content = {document.requested_url: document.content for document in documents}
    saka = _by_name(claims, "Saka")

    quoted = resolve_span(content[saka.source_url], saka).decode("utf-8")

    assert "Saka" in quoted
    assert quoted == quoted.strip()
    assert saka.source_sha256 == hashlib.sha256(content[saka.source_url]).hexdigest()


# --- the three dateline precisions ------------------------------------------


def test_an_instant_dateline_is_kept_to_the_second(claims: tuple[ParsedClaim, ...]) -> None:
    saka = _by_name(claims, "Saka")

    assert saka.published_precision == "instant"
    assert saka.published_at_utc == "2026-09-11T14:00:00Z"


def test_a_day_dateline_is_kept_as_a_day_and_never_rounded_up(
    claims: tuple[ParsedClaim, ...],
) -> None:
    """A time-of-knowledge claim nobody published must not be manufactured here."""

    mount = _by_name(claims, "Mount")

    assert mount.published_precision == "day"
    assert mount.published_at_utc == "2026-09-11"


def test_an_absent_dateline_stays_absent_and_is_not_the_fetch_instant(
    claims: tuple[ParsedClaim, ...], documents: tuple[RawDocument, ...]
) -> None:
    dalot = _by_name(claims, "Dalot")
    fetch_instants = {document.fetched_at_utc for document in documents}

    assert dalot.published_precision == "unknown"
    assert dalot.published_at_utc is None
    assert None not in fetch_instants


def test_a_dateline_without_a_precision_that_describes_it_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    response = provider.code(documents, provider.roster())
    document = json.loads(response.text)
    document["documents"][0]["published_precision"] = "unknown"

    with pytest.raises(ClubNewsError, match="Unknown means the source dated itself not at all"):
        parse_claim_response(_rewritten(response, document), documents)


def test_a_precision_with_no_dateline_behind_it_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    response = provider.code(documents, provider.roster())
    document = json.loads(response.text)
    document["documents"][0]["published_at_utc"] = None

    with pytest.raises(ClubNewsError, match="Absent is its own precision"):
        parse_claim_response(_rewritten(response, document), documents)


def test_a_day_dateline_that_is_not_a_calendar_date_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    response = provider.code(documents, provider.roster())
    document = json.loads(response.text)
    document["documents"][1]["published_at_utc"] = "2026-09-31"

    with pytest.raises(ClubNewsError, match="is not a calendar date"):
        parse_claim_response(_rewritten(response, document), documents)


# --- the refusals the fixture itself specifies ------------------------------


def test_every_response_the_fixture_declares_unparseable_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    """Driven off the fixture, so a case added there is covered without touching this file."""

    responses = provider.unparseable_responses()

    assert responses
    for response in responses:
        with pytest.raises(ClubNewsError):
            parse_claim_response(response, documents)


def test_each_unparseable_case_is_refused_for_its_own_reason(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    """The order of checks is load-bearing, not incidental.

    A response with an unknown disposition also declares no documents; if the document
    cross-check ran first, that case would be refused for the wrong reason and the
    vocabulary guard would never be exercised by it. Each message is pinned so the ordering
    cannot drift.
    """

    expected = {
        "The response is not the declared JSON format",
        "not 'rotation_claim_response_v1'",
        "outside the closed vocabulary",
        "must be an array, got str",
        "does not declare among its own source documents",
        "is an unresolvable citation",
    }
    observed: set[str] = set()
    for response in provider.unparseable_responses():
        with pytest.raises(ClubNewsError) as raised:
            parse_claim_response(response, documents)
        message = str(raised.value)
        observed.update(fragment for fragment in expected if fragment in message)

    assert observed == expected


def test_a_response_that_codes_one_player_twice_is_refused_rather_than_resolved(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    """The artifact has one disposition per player and no priority rule is declared."""

    response = provider.code(documents, provider.roster())
    document = json.loads(response.text)
    duplicate = dict(document["claims"][0])
    duplicate["disposition"] = "stated_expected_absent"
    document["claims"].append(duplicate)

    with pytest.raises(ClubNewsError, match="refused rather than resolved"):
        parse_claim_response(_rewritten(response, document), documents)


def test_parsing_without_the_fetched_documents_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    response = provider.code(documents, provider.roster())

    with pytest.raises(ClubNewsError, match="needs the fetched documents"):
        parse_claim_response(response, [])


def test_a_document_declared_twice_in_one_response_is_refused(
    provider: FixtureClubNewsProvider, documents: tuple[RawDocument, ...]
) -> None:
    response = provider.code(documents, provider.roster())
    document = json.loads(response.text)
    document["documents"].append(dict(document["documents"][0]))

    with pytest.raises(ClubNewsError, match="twice; one document has one dateline"):
        parse_claim_response(_rewritten(response, document), documents)


# --- the redirect, and what a citation may name -----------------------------


def test_a_claim_may_cite_the_url_that_was_requested_across_a_redirect(
    claims: tuple[ParsedClaim, ...], documents: tuple[RawDocument, ...]
) -> None:
    """The page we asked for and the page we read have different addresses.

    The fixture's United document redirects. Its claims cite the requested URL, and the span
    still resolves, because the bytes are indexed under both names.
    """

    redirected = [
        document for document in documents if document.final_url != document.requested_url
    ]
    assert redirected, "the fixture is supposed to carry a redirect"

    mount = _by_name(claims, "Mount")
    assert mount.source_url == redirected[0].requested_url
    assert resolve_span(redirected[0].content, mount)


def test_a_span_resolved_against_changed_bytes_is_refused(
    claims: tuple[ParsedClaim, ...], documents: tuple[RawDocument, ...]
) -> None:
    """Offsets into a document that has since changed would show different words as quoted."""

    saka = _by_name(claims, "Saka")
    edited = documents[0].content.replace(b"Saka", b"Saks")

    with pytest.raises(ClubNewsError, match="would point into"):
        resolve_span(edited, saka)


def test_a_percent_sign_inside_a_cited_span_survives_untouched(
    claims: tuple[ParsedClaim, ...], documents: tuple[RawDocument, ...]
) -> None:
    """A literal per-cent in a manager's own words is not a published probability.

    The honesty rule forbids *generating* a likelihood, not quoting a sentence that happens
    to contain a number. The parser stores no text either way -- what this pins is that the
    span still resolves rather than being sanitised somewhere along the path.
    """

    content = {document.requested_url: document.content for document in documents}
    spans = [resolve_span(content[claim.source_url], claim).decode("utf-8") for claim in claims]

    assert any("%" in span for span in spans)


def test_the_contract_version_of_the_response_is_the_one_the_fixture_declares() -> None:
    committed = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert committed["response_contract_version"] == ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION
