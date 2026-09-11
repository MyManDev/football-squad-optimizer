"""A week's club news, written to disk once and read back byte for byte.

R07 is explicit that an in-memory fixture replay is not evidence of durable replay, and it
is right: objects handed from one function to another prove that the functions agree, not
that a week survives the process that produced it. So every test here goes through the
snapshot store on a real temporary directory -- written, then read from the identifier
alone, with the writing objects out of scope.

The property under test is narrow and load-bearing: the documents and the response that
come back out are the ones that went in, closely enough that locating and parsing them
produces the same claims and the same digests. That is what makes a decision defensible
after the fact, and it is the only reason a model is allowed anywhere near this pipeline.
"""

import json
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import (
    SnapshotExistsError,
    list_snapshot_ids,
    read_snapshot,
    write_snapshot,
)
from squadopt.data.sources.club_news import (
    CLUB_NEWS_SOURCE,
    ClaimResponse,
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_capture import (
    CLUB_NEWS_CAPTURE_CONTRACT_VERSION,
    INDEX_PAYLOAD,
    CodedClub,
    capture_payloads,
    read_captured_coverage,
    read_captured_documents,
    read_captured_responses,
    read_club_news_capture,
    write_club_news_capture,
)
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION as CODING_CONTRACT,
)
from squadopt.data.sources.club_news_coding import (
    CodingFixture,
    coding_prompt_sha256,
    locate_claim_response,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE = SAMPLE / "club_news_v1.fixture.json"
CODING_FIXTURE = SAMPLE / "club_news_coding_v1.fixture.json"
CAPTURED_AT = "2026-09-12T09:30:00Z"


def _documents() -> tuple[RawDocument, ...]:
    provider = FixtureClubNewsProvider(FIXTURE)
    return tuple(provider.fetch(url) for url in provider.urls)


def _coded() -> tuple[CodedClub, ...]:
    response = CodingFixture(CODING_FIXTURE).response()
    # One response covering every covered club is what the fixture actually does, and the
    # capture records that rather than inventing a call per club.
    return tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=CODING_CONTRACT,
            prompt_sha256=coding_prompt_sha256(),
        )
        for club in FixtureClubNewsProvider(FIXTURE).clubs_covered()
    )


def _write(root: Path) -> str:
    provider = FixtureClubNewsProvider(FIXTURE)
    metadata = write_club_news_capture(
        root,
        documents=_documents(),
        coded=_coded(),
        clubs_declared=provider.clubs_declared(),
        clubs_covered=provider.clubs_covered(),
        captured_at_utc=CAPTURED_AT,
    )
    return metadata.snapshot_id


# --- the capture survives the process ---------------------------------------


def test_the_documents_come_back_byte_for_byte(tmp_path: Path) -> None:
    """Exactly, not closely. A span located against these bytes must land where it landed."""

    written = _documents()
    identifier = _write(tmp_path)

    read = read_captured_documents(read_snapshot(tmp_path, identifier))

    assert [document.content for document in read] == [document.content for document in written]
    assert [document.club for document in read] == [document.club for document in written]


def test_every_field_the_bytes_cannot_state_survives(tmp_path: Path) -> None:
    """Both URLs, the status, the type, the fetch instant and the transport's own claim."""

    written = _documents()
    identifier = _write(tmp_path)

    read = read_captured_documents(read_snapshot(tmp_path, identifier))

    assert read == written


def test_a_redirected_document_keeps_both_urls(tmp_path: Path) -> None:
    """The fixture carries one, and a citation names the page that was read."""

    identifier = _write(tmp_path)

    read = read_captured_documents(read_snapshot(tmp_path, identifier))

    redirected = [d for d in read if d.requested_url != d.final_url]
    assert redirected, "the fixture's redirect case should survive the capture"


def test_the_response_and_its_question_come_back(tmp_path: Path) -> None:
    """A response is only interpretable against the prompt that produced it."""

    identifier = _write(tmp_path)

    coded = read_captured_responses(read_snapshot(tmp_path, identifier))

    assert {entry.club for entry in coded} == set(FixtureClubNewsProvider(FIXTURE).clubs_covered())
    assert {entry.prompt_sha256 for entry in coded} == {coding_prompt_sha256()}
    assert {entry.prompt_contract_version for entry in coded} == {CODING_CONTRACT}


def test_what_was_asked_for_and_what_answered_both_survive(tmp_path: Path) -> None:
    """A request naming an alias can be served by a snapshot, and that has to be readable."""

    identifier = _write(tmp_path)

    coded = read_captured_responses(read_snapshot(tmp_path, identifier))

    assert {entry.response.model_identifier for entry in coded} == {"synthetic-stub"}
    assert {entry.response.model_version for entry in coded} == {"fixture-1"}


def test_declared_and_covered_stay_apart(tmp_path: Path) -> None:
    """The one distinction this lane exists to keep, recorded while it is still known.

    From the payloads alone a club that was read and said nothing is indistinguishable
    from a club nobody read. The index is where that difference is written down.
    """

    identifier = _write(tmp_path)

    declared, covered = read_captured_coverage(read_snapshot(tmp_path, identifier))

    assert set(covered) < set(declared)
    assert "Everton" in declared
    assert "Everton" not in covered


# --- the replay, from disk, with nothing in memory --------------------------


def test_the_evidence_replays_from_the_capture_alone(tmp_path: Path) -> None:
    """The delivery's own acceptance test, and the reason the capture exists.

    Nothing from the writing side is reachable here: the capture is read back from its
    identifier, and the claims are produced from those bytes by pure code. No network, no
    model, no fixture object -- which is the difference R07 draws between this and handing
    objects between two functions in one process.
    """

    identifier = _write(tmp_path)

    documents, coded, _declared, _covered = read_club_news_capture(
        read_snapshot(tmp_path, identifier)
    )
    located = locate_claim_response(coded[0].response, documents)
    claims = parse_claim_response(located, documents)

    assert claims, "the capture should yield the week's claims"
    assert all(claim.source_sha256 for claim in claims)


def test_two_replays_of_one_capture_agree(tmp_path: Path) -> None:
    """Determinism, measured rather than asserted in prose."""

    identifier = _write(tmp_path)

    first = read_club_news_capture(read_snapshot(tmp_path, identifier))
    second = read_club_news_capture(read_snapshot(tmp_path, identifier))
    first_claims = parse_claim_response(
        locate_claim_response(first[1][0].response, first[0]), first[0]
    )
    second_claims = parse_claim_response(
        locate_claim_response(second[1][0].response, second[0]), second[0]
    )

    assert first_claims == second_claims


def test_the_replayed_claims_match_the_in_memory_ones(tmp_path: Path) -> None:
    """The capture is a faithful record, not merely a self-consistent one.

    Round-tripping through disk could be internally consistent and still wrong -- a lost
    byte would give a stable answer that is not the week's answer. So the claims from the
    capture are compared against the claims from the objects that were written.
    """

    written_documents = _documents()
    written_response = _coded()[0].response
    expected = parse_claim_response(
        locate_claim_response(written_response, written_documents), written_documents
    )
    identifier = _write(tmp_path)

    documents, coded, _declared, _covered = read_club_news_capture(
        read_snapshot(tmp_path, identifier)
    )

    assert (
        parse_claim_response(locate_claim_response(coded[0].response, documents), documents)
        == expected
    )


def test_the_capture_is_found_by_source(tmp_path: Path) -> None:
    """Written under the club-news source, so a week can be located without being named."""

    identifier = _write(tmp_path)

    assert list_snapshot_ids(tmp_path, source=CLUB_NEWS_SOURCE) == (identifier,)


def test_a_week_is_written_once(tmp_path: Path) -> None:
    """The store refuses an existing capture, and that refusal is what makes it a record."""

    _write(tmp_path)

    with pytest.raises(SnapshotExistsError, match="already exists"):
        _write(tmp_path)


# --- the refusals -----------------------------------------------------------


def test_a_capture_with_no_document_is_refused() -> None:
    """A week in which nothing was read is declared clubs and no coverage, not an empty capture."""

    with pytest.raises(ClubNewsError, match="no document"):
        capture_payloads((), _coded(), clubs_declared=("Arsenal",), clubs_covered=())


def test_coverage_may_not_exceed_what_was_declared() -> None:
    """A club covered but never declared is a coverage list that describes another week."""

    with pytest.raises(ClubNewsError, match="covered but were never declared"):
        capture_payloads(
            _documents(), _coded(), clubs_declared=("Arsenal",), clubs_covered=("Arsenal", "Spurs")
        )


def test_a_capture_from_another_source_is_refused(tmp_path: Path) -> None:
    """A live payload set read as club news would be misread field by field."""

    metadata = write_snapshot(
        tmp_path, source="fpl-live", captured_at_utc=CAPTURED_AT, payloads={"bootstrap": b"{}"}
    )

    with pytest.raises(DataSourceError, match="not 'club-news'"):
        read_club_news_capture(read_snapshot(tmp_path, metadata.snapshot_id))


def test_a_capture_without_its_index_is_refused(tmp_path: Path) -> None:
    """Bytes without a record: nothing says which club or which URL they came from."""

    metadata = write_snapshot(
        tmp_path,
        source=CLUB_NEWS_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={"document-01": b"<p>words</p>"},
    )

    with pytest.raises(DataSourceError, match=r"carries no 'index\.json'"):
        read_club_news_capture(read_snapshot(tmp_path, metadata.snapshot_id))


def test_a_capture_under_another_layout_is_refused(tmp_path: Path) -> None:
    """A capture written under one layout is not readable under another.

    ``club_news_capture_v1`` is the real case rather than an invented one: v1 stored one
    payload per document and v2 stores the served bytes and the extracted text side by
    side, so a v1 capture has no readable payload for its offsets to index. Re-extracting
    it here would resolve stored offsets into bytes produced by a later extractor, which is
    the failure the digest check exists to prevent -- so it is refused instead.
    """

    index = json.dumps(
        {"contract_version": "club_news_capture_v1", "documents": [], "responses": []}
    ).encode("utf-8")
    metadata = write_snapshot(
        tmp_path,
        source=CLUB_NEWS_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={INDEX_PAYLOAD: index},
    )

    with pytest.raises(DataSourceError, match="capture contract"):
        read_club_news_capture(read_snapshot(tmp_path, metadata.snapshot_id))


def test_an_index_naming_a_payload_nobody_stored_is_refused(tmp_path: Path) -> None:
    """Worse than no index: it makes a citation look resolvable when it is not."""

    index = json.dumps(
        {
            "contract_version": CLUB_NEWS_CAPTURE_CONTRACT_VERSION,
            "clubs_declared": ["Arsenal"],
            "clubs_covered": ["Arsenal"],
            "documents": [
                {
                    "payload": "document-09",
                    "club": "Arsenal",
                    "requested_url": "https://club.example/a",
                    "final_url": "https://club.example/a",
                    "http_status": 200,
                    "content_type": "text/html",
                    "fetched_at_utc": CAPTURED_AT,
                    "last_modified_utc": None,
                }
            ],
            "responses": [],
        }
    ).encode("utf-8")
    metadata = write_snapshot(
        tmp_path,
        source=CLUB_NEWS_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={INDEX_PAYLOAD: index},
    )

    with pytest.raises(DataSourceError, match="does not carry"):
        read_club_news_capture(read_snapshot(tmp_path, metadata.snapshot_id))


def test_a_capture_holding_unindexed_bytes_is_refused(tmp_path: Path) -> None:
    """A document nobody can attribute, in a store whose index looks complete."""

    payloads = capture_payloads(
        _documents(),
        _coded(),
        clubs_declared=FixtureClubNewsProvider(FIXTURE).clubs_declared(),
        clubs_covered=FixtureClubNewsProvider(FIXTURE).clubs_covered(),
    )
    payloads["document-99"] = b"<p>whose words are these</p>"
    metadata = write_snapshot(
        tmp_path, source=CLUB_NEWS_SOURCE, captured_at_utc=CAPTURED_AT, payloads=payloads
    )

    with pytest.raises(DataSourceError, match="does not describe"):
        read_club_news_capture(read_snapshot(tmp_path, metadata.snapshot_id))


def test_a_coded_club_must_carry_its_prompt() -> None:
    """A response with no question behind it cannot be read again."""

    response = ClaimResponse(text="{}", model_identifier="m", model_version="1")

    with pytest.raises(Exception, match="prompt_sha256"):
        CodedClub(
            club="Arsenal",
            response=response,
            prompt_contract_version=CODING_CONTRACT,
            prompt_sha256="   ",
        )
