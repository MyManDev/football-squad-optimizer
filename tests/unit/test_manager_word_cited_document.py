"""The manager's word names the document its row cites, whichever document was held first.

A rotation row cites bytes by digest, not a page by address, so one article held under two
addresses (``/x`` and ``/x?ref=home``) answers the same digest twice (#1232). The reader used
to take the first one held: with the twin held first, a word the table verified lost its
publication and its role, under the wrong reason. These weeks are written through the
capture writer and exported through ``export_rotation_evidence``, the two calls the Friday
run makes, and read back with ``load_manager_words``, as the publish reads them.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
)

from squadopt.application import manager_words as module
from squadopt.application.football_context import (
    bind_football_context,
    manager_word_attestation_reason,
)
from squadopt.application.manager_words import (
    AMBIGUOUS_CITED_DOCUMENT,
    SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    WORDS_UNRESOLVED,
    ManagerWord,
    ManagerWords,
    ManagerWordsError,
    load_manager_words,
)
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD

PUBLISHED = "2026-09-12T13:00:00Z"
FETCHED = "2026-09-12T14:00:00Z"
NEWS_CAPTURED_AT = "2026-09-12T14:30:00Z"
MODEL = "synthetic-stub"
SAKA = 900001

CITED = "https://arsenal.example/team-news/saka"
TWIN = CITED + "?ref=home"
UNITED = "https://united.example/team-news/saka"
SENTENCE = "Saka will miss the next Premier League match."


def _page(url: str, *, club: str = "Arsenal", request: str = "") -> RawDocument:
    """The one article as the host served it at ``url``.

    The readable text is the same at every address. ``request`` stands for what a host
    prints per request, a nonce: it is in the bytes served and not in the text a person
    reads, so two fetches of one article differ in their raw bytes only.
    """

    readable = f"Published: {PUBLISHED}\n{SENTENCE}\n".encode()
    content = readable + (f"Request: {request}\n".encode() if request else b"")
    return RawDocument(
        club=club,
        requested_url=url,
        final_url=url,
        http_status=200,
        content_type="text/plain",
        byte_length=len(content),
        fetched_at_utc=FETCHED,
        content=content,
        readable=readable,
    )


def _answer() -> CodedClub:
    """Arsenal's stored answer: Saka will miss the match, citing the article at ``CITED``."""

    body = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "documents": [
            {"url": CITED, "published_at_utc": PUBLISHED, "published_precision": "instant"}
        ],
        "claims": [
            {
                "player_name": "Saka",
                "team_name": "Arsenal",
                "disposition": "stated_expected_absent",
                "speaker": "manager",
                "source_url": CITED,
                "quote": SENTENCE,
                "paraphrase": "A synthetic paraphrase.",
                "fixture_scope": "upcoming_premier_league",
            }
        ],
    }
    return CodedClub(
        "Arsenal",
        ClaimResponse(text=json.dumps(body), model_identifier=MODEL, model_version="fixture-2"),
        ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        coding_prompt_sha256(MODEL),
        provider="synthetic",
    )


def _read(tmp_path: Path, documents: tuple[RawDocument, ...]) -> ManagerWords:
    """Capture ``documents`` in this order, export the week, and read it as the publish does."""

    root = tmp_path / "snapshots"
    decision = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    ).snapshot_id
    clubs = tuple(sorted({document.club for document in documents}))
    news = write_club_news_capture(
        root,
        documents=documents,
        coded=(_answer(),),
        clubs_declared=clubs,
        clubs_covered=clubs,
        captured_at_utc=NEWS_CAPTURED_AT,
    ).snapshot_id
    result = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            None,
            tmp_path / "rotation",
            club_news_snapshot=news,
            table_name="table",
        ),
        repository_commit="0" * 40,
    )
    return load_manager_words(
        Path(str(result["table_path"])), club_news_source=root / news, snapshot_root=root
    )


def _both_orders(
    tmp_path: Path, cited: RawDocument, other: RawDocument
) -> tuple[ManagerWord, ManagerWord]:
    """Saka's word with the cited page held first, and with the other one held first."""

    first = _read(tmp_path / "cited-first", (cited, other))
    second = _read(tmp_path / "other-first", (other, cited))
    assert first.source_check == second.source_check == SOURCE_CHECK_CITED_DOCUMENTS_HELD
    ((word_first,), (word_second,)) = first.words, second.words
    return word_first, word_second


def test_twins_give_the_cited_word_in_either_holding_order(tmp_path: Path) -> None:
    """The row's publication digest names the cited page's raw bytes, and only it has them."""

    cited, twin = _page(CITED, request="a1"), _page(TWIN, request="b2")
    assert cited.readable == twin.readable and cited.content != twin.content

    word_first, word_second = _both_orders(tmp_path, cited, twin)

    assert word_first == word_second
    assert word_first.player_id == SAKA
    assert word_first.source_url == CITED
    assert word_first.words == SENTENCE
    assert word_first.publication_verified is True
    assert word_first.publication_source_sha256 == hashlib.sha256(cited.content).hexdigest()
    assert word_first.role == "not_starting"
    assert word_first.document_binding_reason is None
    assert manager_word_attestation_reason(word_first) is None


def test_twins_nothing_tells_apart_are_refused_with_their_reason(tmp_path: Path) -> None:
    """Byte for byte the same page at two addresses: the digests cannot say which was cited,
    so the word names neither, in either order, and every reader of it says why."""

    word_first, word_second = _both_orders(tmp_path, _page(CITED), _page(TWIN))

    assert word_first == word_second
    word = word_first
    assert word.document_binding_reason == AMBIGUOUS_CITED_DOCUMENT
    assert word.words is None and word.words_status == WORDS_UNRESOLVED
    assert (word.club, word.source_url, word.fetched_at_utc) == (None, None, None)
    assert word.publication_verified is False and word.scope_verified is False
    assert word.role is None
    assert manager_word_attestation_reason(word) == AMBIGUOUS_CITED_DOCUMENT

    words = ManagerWords(
        SEASON,
        TARGET_GAMEWEEK,
        "club_news_capture",
        "capture",
        "table.csv",
        ("Arsenal",),
        (word,),
        source_check=SOURCE_CHECK_CITED_DOCUMENTS_HELD,
    )
    roster = pd.DataFrame({"player_id": [SAKA], "club": [1]})
    feed = pd.DataFrame({"player_id": [SAKA], "status": ["a"], "chance_of_playing": [100]})
    bound, audit = bind_football_context(
        roster,
        feed,
        season=SEASON,
        gameweek=TARGET_GAMEWEEK,
        cutoff=pd.Timestamp(CAPTURED_AT),
        manager_words=words,
    )
    assert bound.availability_probability.tolist() == [1.0]
    assert [(row["reason"], row["status"]) for row in audit] == [
        (AMBIGUOUS_CITED_DOCUMENT, "unapplied")
    ]


def test_another_clubs_page_with_the_same_text_is_not_chosen(tmp_path: Path) -> None:
    """Saka is Arsenal's, so a Man Utd page with the same bytes is not his source, even
    held first; the publication digest alone could not have told the two apart."""

    cited, united = _page(CITED), _page(UNITED, club="Man Utd")
    assert cited.content == united.content

    word_first, word_second = _both_orders(tmp_path, cited, united)

    assert word_first == word_second
    assert (word_first.club, word_first.source_url) == ("Arsenal", CITED)
    assert word_first.role == "not_starting"


def _digest(document: RawDocument) -> str:
    return hashlib.sha256(document.content).hexdigest()


def test_a_row_without_a_publication_digest_cannot_choose_between_twins() -> None:
    """The publication digest is the one fact on the row that names raw bytes. Without it,
    two same-club pages with the same text are ambiguous; with it, the one it names is the
    cited one. Neither depends on the order the pages are given in."""

    cited, twin = _page(CITED, request="a1"), _page(TWIN, request="b2")
    digest = hashlib.sha256(cited.readable).hexdigest()
    start = cited.readable.index(SENTENCE.encode())
    end = start + len(SENTENCE)

    for documents in ((cited, twin), (twin, cited)):
        assert module._resolve(documents, digest, start, end, club="Arsenal") == (
            None,
            None,
            False,
            AMBIGUOUS_CITED_DOCUMENT,
        )
        assert module._resolve(
            documents, digest, start, end, club="Arsenal", publication_digest=_digest(cited)
        ) == (cited, SENTENCE, True, None)
        assert module._resolve(
            documents, digest, start, end, club="Arsenal", publication_digest=_digest(twin)
        ) == (twin, SENTENCE, True, None)


def test_a_citation_no_kept_page_answers_resolves_to_nothing() -> None:
    """As a digest no held page produces does: no page, no words, and no ambiguity."""

    cited = _page(CITED)
    digest = hashlib.sha256(cited.readable).hexdigest()
    nothing = (None, None, False, None)

    assert module._resolve((cited,), digest, 0, 5, club="Man Utd") == nothing
    assert module._resolve((cited,), digest, 0, 5, publication_digest="0" * 64) == nothing
    assert module._resolve((cited,), "0" * 64, 0, 5) == nothing


def test_pages_that_agree_on_everything_the_word_reads_are_one_answer() -> None:
    """The same page held twice, or under a second requested address that led to it, gives
    one word whichever is taken, so it is not refused as ambiguous."""

    cited = _page(CITED)
    redirected = replace(cited, requested_url=TWIN)
    digest = hashlib.sha256(cited.readable).hexdigest()

    document, words, _, reason = module._resolve((redirected, cited), digest, 0, 5)
    assert (document, words, reason) == (redirected, "Publi", None)
    document, words, _, reason = module._resolve((cited, cited), digest, 0, 5)
    assert (document, words, reason) == (cited, "Publi", None)


def test_an_ambiguous_word_can_name_no_page_and_no_words() -> None:
    word = ManagerWord(
        player_id=SAKA,
        disposition="stated_expected_absent",
        speaker="manager",
        published_at_utc=PUBLISHED,
        published_precision="instant",
        club=None,
        source_url=None,
        fetched_at_utc=None,
        words=None,
        document_binding_reason=AMBIGUOUS_CITED_DOCUMENT,
    )
    assert word.words_status == WORDS_UNRESOLVED

    with pytest.raises(ManagerWordsError, match="names no document"):
        replace(word, source_url=CITED)
    with pytest.raises(ManagerWordsError, match="names no document"):
        replace(word, club="Arsenal")
    with pytest.raises(ManagerWordsError, match="names no document"):
        replace(word, words=SENTENCE, words_status="shown")
    with pytest.raises(ManagerWordsError, match="Unknown document binding reason"):
        replace(word, document_binding_reason="first_held")
