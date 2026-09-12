"""The frozen question, and the quote that becomes a citation.

Two properties carry this module and both are checked here rather than described.

**The chain replays.** Locating a stored coding response is pure: the same bytes in, the
same bytes out, the same digest. That is what makes a week's evidence reproducible with the
network unplugged, and it is the only reason a model may be in this pipeline at all.

**The two fixture halves agree.** The coding fixture is derived from the located one, so
locating it must reproduce the claims the located fixture already carries -- including the
byte offsets, which nobody typed. If either file is edited in a way that breaks the
agreement, the round trip below fails instead of the pair drifting quietly.
"""

import json
from pathlib import Path

import pytest
from tests.fixtures.synthetic_club_news_coding import make_club_news_coding_fixture

from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_DISPOSITIONS,
    ClaimResponse,
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import (
    CODING_BYTES_PER_TOKEN,
    CODING_CONTEXT_TOKENS,
    CODING_DISPOSITIONS,
    CODING_EFFORT,
    CODING_MODEL_IDENTIFIER,
    MAXIMUM_USER_CONTENT_BYTES,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    CodingFixture,
    build_user_content,
    coding_prompt_sha256,
    locate_claim_response,
    locate_quote,
    response_schema,
)

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE_PATH = SAMPLE_DIR / "club_news_v1.fixture.json"
CODING_FIXTURE_PATH = SAMPLE_DIR / "club_news_coding_v1.fixture.json"

#: The digest of the instrument, pinned. This is not a checksum of a computation -- it is a
#: tripwire on the prompt itself. Editing the prompt, the schema, the effort or the model
#: name changes this number, and a response coded under the old wording is not comparable
#: with one coded under the new. Failing here is the reminder to bump
#: ``ROTATION_CLAIM_CODING_CONTRACT_VERSION`` deliberately rather than to update a constant.
PINNED_PROMPT_SHA256 = "e755c70b96cef2dda4523d04e46292913bf3f8638d6b39261ee4ebd144ffbf5d"


def _documents() -> tuple[RawDocument, ...]:
    provider = FixtureClubNewsProvider(FIXTURE_PATH)
    return tuple(provider.fetch(url) for url in provider.urls)


def _coding_fixture() -> CodingFixture:
    return CodingFixture(CODING_FIXTURE_PATH)


def test_the_committed_coding_fixture_matches_its_generator() -> None:
    """The file on disk is what the builder produces, or the two have drifted."""

    committed = json.loads(CODING_FIXTURE_PATH.read_text(encoding="utf-8"))

    assert committed == make_club_news_coding_fixture()


def test_the_generator_is_deterministic() -> None:
    """A fixture that differed between two runs could not be committed at all."""

    assert make_club_news_coding_fixture() == make_club_news_coding_fixture()


def test_the_coding_fixture_names_the_documents_its_quotes_came_from() -> None:
    """A quote is verbatim only with respect to particular bytes."""

    assert _coding_fixture().documents_fixture == FIXTURE_PATH.name


def test_locating_the_coding_fixture_reproduces_the_located_fixture() -> None:
    """The round trip, and the strongest offline check on this pair.

    The located fixture's canned response was written independently of the coding one; the
    coding one's quotes were cut from the same document bytes. Locating the second has to
    produce the first, offsets included, or one of the two files is wrong.
    """

    documents = _documents()
    provider = FixtureClubNewsProvider(FIXTURE_PATH)

    located = locate_claim_response(_coding_fixture().response(), documents)

    assert parse_claim_response(located, documents) == parse_claim_response(
        provider.code(documents, provider.roster()), documents
    )


def test_locating_is_pure() -> None:
    """Same response, same documents, same bytes -- the replay property, stated as a test."""

    documents = _documents()
    response = _coding_fixture().response()

    first = locate_claim_response(response, documents)
    second = locate_claim_response(response, documents)

    assert first.text == second.text


def test_the_located_response_declares_the_parsers_contract() -> None:
    """It is a rendering into the parser's format, so it must claim that format."""

    located = locate_claim_response(_coding_fixture().response(), _documents())

    assert json.loads(located.text)["contract_version"] == ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION


def test_the_located_response_carries_no_quote() -> None:
    """The quote is the input to the location, never an output of it.

    A quote surviving into the located response would be free text one hop away from the
    artifact, and the artifact may not carry any. The pointer replaces the words; it does
    not accompany them.
    """

    located = json.loads(locate_claim_response(_coding_fixture().response(), _documents()).text)

    for claim in located["claims"]:
        assert "quote" not in claim
        assert {"span_start", "span_end"} <= set(claim)


def test_the_model_identity_travels_through_unchanged() -> None:
    """The located response is a rendering of what a model said, not a second opinion."""

    response = _coding_fixture().response()

    located = locate_claim_response(response, _documents())

    assert located.model_identifier == response.model_identifier
    assert located.model_version == response.model_version


@pytest.mark.parametrize("index", range(5))
def test_every_declared_unlocatable_response_is_refused(index: int) -> None:
    """Each hazard the fixture documents is still caught, and says which one is not."""

    cases = _coding_fixture().unlocatable_responses()
    case = cases[index]

    with pytest.raises(ClubNewsError):
        locate_claim_response(case.response, _documents())


def test_the_fixture_documents_five_hazards() -> None:
    """A parametrised test that silently ran over an empty list would pass forever."""

    cases = _coding_fixture().unlocatable_responses()

    assert len(cases) == 5
    assert all(case.why.strip() for case in cases)


def test_a_quote_that_is_not_in_the_document_is_refused() -> None:
    """The refusal this whole design exists for.

    A model that tidies a quote has written a sentence the document does not contain. There
    is no such thing as an approximately located citation: the offsets would land somewhere,
    and ``resolve_span`` would hand a member those other words with a digest behind them.
    """

    with pytest.raises(ClubNewsError, match="verbatim"):
        locate_quote(b"Saka trained fully on Thursday.", "Saka trained on Thursday.", "A claim")


def test_a_quote_that_appears_twice_is_refused() -> None:
    """A span that might point at either of two places is not a span."""

    with pytest.raises(ClubNewsError, match=r"starts at \[3, 16\]"):
        locate_quote(b"He trained. She trained.", "trained", "A claim")


def test_a_quote_whose_occurrences_overlap_is_refused() -> None:
    """``bytes.count`` cannot see this, and the whole uniqueness claim rests on it.

    It counts non-overlapping matches, so ``b"aaa".count(b"aa")`` is 1 while ``b"aa"`` in
    fact starts at both 0 and 1. The old check called that unique and took the first, which
    is a citation silently chosen between two candidates -- the one thing this function
    exists to prevent. Not a corner case dressed up as one either: the prose below is the
    kind of sentence a club actually publishes.
    """

    with pytest.raises(ClubNewsError, match=r"starts at \[10, 13\]"):
        locate_quote(b"They said ha ha ha about it.", "ha ha", "A claim")


def test_the_minimal_overlapping_case_is_refused() -> None:
    """The defect in its smallest form, so the regression cannot come back disguised."""

    assert b"aaa".count(b"aa") == 1  # what the old check believed

    with pytest.raises(ClubNewsError, match=r"starts at \[0, 1\]"):
        locate_quote(b"aaa", "aa", "A claim")


def test_a_quote_occurring_three_times_names_all_three_starts() -> None:
    """The refusal says where, because "somewhere else too" is not actionable."""

    with pytest.raises(ClubNewsError, match=r"starts at \[0, 2, 4\]"):
        locate_quote(b"ababab", "ab", "A claim")


def test_an_empty_quote_is_refused() -> None:
    """An empty needle is found everywhere, which is the same as nowhere."""

    with pytest.raises(ClubNewsError, match="empty quote"):
        locate_quote(b"anything at all", "", "A claim")


def test_a_quote_is_located_in_bytes_not_characters() -> None:
    """The offsets are byte offsets, so a multi-byte character must move them.

    Not a hypothetical: a club writing "Ødegaard" or a curly apostrophe puts two bytes where
    a character index would count one, and a span measured in characters would cut a
    citation off mid-character.
    """

    content = "Kanté is fit. Kante is not the same man.".encode()

    start, end = locate_quote(content, "Kanté is fit.", "A claim")

    assert content[start:end].decode("utf-8") == "Kanté is fit."
    assert (start, end) == (0, len("Kanté is fit.".encode()))
    assert end - start == 14  # thirteen characters, fourteen bytes


def test_locating_needs_the_documents() -> None:
    """A quote becomes a span only inside the bytes it was copied from."""

    with pytest.raises(ClubNewsError, match="needs the fetched documents"):
        locate_claim_response(_coding_fixture().response(), ())


def test_a_response_that_is_not_json_is_refused_rather_than_read_as_prose() -> None:
    """A model that answers in sentences has not answered in the format."""

    response = ClaimResponse(text="He should be fine.", model_identifier="m", model_version="1")

    with pytest.raises(ClubNewsError, match="not JSON"):
        locate_claim_response(response, _documents())


def test_the_prompt_digest_is_pinned() -> None:
    """The instrument is frozen, and this is what says so out loud."""

    assert coding_prompt_sha256() == PINNED_PROMPT_SHA256


def test_the_prompt_digest_is_stable_across_calls() -> None:
    """Canonical JSON with sorted keys, so nothing depends on dictionary order."""

    assert coding_prompt_sha256() == coding_prompt_sha256()


def test_the_coding_vocabulary_is_the_parsers_minus_the_one_a_model_cannot_observe() -> None:
    """``not_addressed`` is a statement about documents that never arrived.

    The model only ever sees the documents it was handed, so it cannot distinguish "nobody
    wrote about him" from "his club was never read". The pipeline computes that absence from
    the roster and the coverage lists; asking a model for it would be asking it to report a
    silence it is not in a position to hear.
    """

    assert set(CODING_DISPOSITIONS) == set(ROTATION_DISPOSITIONS) - {"not_addressed"}
    assert "not_addressed" in ROTATION_DISPOSITIONS


def test_the_prompt_asks_for_every_disposition_it_may_receive() -> None:
    """A vocabulary entry the prompt never mentions is one no answer will use."""

    for disposition in CODING_DISPOSITIONS:
        assert f'"{disposition}"' in SYSTEM_PROMPT


def test_the_prompt_tells_the_model_not_to_return_the_computed_disposition() -> None:
    """Silence about it would leave the closed list looking complete."""

    assert 'Do not return "not_addressed"' in SYSTEM_PROMPT


def test_the_schema_enumerations_are_generated_from_the_source_tuples() -> None:
    """Two copies of a closed vocabulary is one copy too many.

    A disposition added to the tuple and forgotten in a hand-written schema would come back
    as a refused week -- the model answering correctly and the request rejecting it -- which
    is a hard failure to read. Generating the enumerations makes that impossible.
    """

    schema = response_schema()
    claim = schema["properties"]["claims"]["items"]["properties"]  # type: ignore[index]
    document = schema["properties"]["documents"]["items"]["properties"]  # type: ignore[index]

    assert claim["disposition"]["enum"] == list(CODING_DISPOSITIONS)
    assert claim["speaker"]["enum"] == list(CLAIM_SPEAKERS)
    assert document["published_precision"]["enum"] == list(PUBLISHED_PRECISIONS)


def test_the_schema_forbids_fields_nobody_declared() -> None:
    """An extra key is a field the parser will not read and nobody agreed to store."""

    schema = response_schema()

    assert schema["additionalProperties"] is False
    assert schema["properties"]["claims"]["items"]["additionalProperties"] is False  # type: ignore[index]


def test_the_schema_asks_for_a_quote_and_not_for_offsets() -> None:
    """The counting is this repository's job, and the schema has to say so."""

    claim = response_schema()["properties"]["claims"]["items"]  # type: ignore[index]

    assert "quote" in claim["required"]
    assert "span_start" not in claim["properties"]
    assert "span_end" not in claim["properties"]


def test_the_contract_names_the_model_and_the_effort_it_was_written_against() -> None:
    """Both are in the digest, so both have to be values and not defaults."""

    assert CODING_MODEL_IDENTIFIER == "claude-opus-5"
    assert CODING_EFFORT == "high"
    assert ROTATION_CLAIM_CODING_CONTRACT_VERSION == "rotation_claim_coding_v1"


def test_the_user_content_is_deterministic() -> None:
    """Two calls a week apart must differ only where the inputs differ."""

    documents = _documents()
    provider = FixtureClubNewsProvider(FIXTURE_PATH)
    roster = provider.roster()

    assert build_user_content(documents, roster) == build_user_content(documents, roster)


def test_the_roster_order_is_not_part_of_the_question() -> None:
    """A reshuffled squad list is the same question, so it must produce the same bytes."""

    documents = _documents()
    roster = FixtureClubNewsProvider(FIXTURE_PATH).roster()

    assert build_user_content(documents, roster) == build_user_content(
        documents, tuple(reversed(roster))
    )


def test_every_roster_player_reaches_the_prompt() -> None:
    """A player left out of the request cannot be coded, and would look uncovered."""

    documents = _documents()
    roster = FixtureClubNewsProvider(FIXTURE_PATH).roster()

    content = build_user_content(documents, roster)

    for player in roster:
        assert f"{player.web_name} ({player.team_name})" in content


def test_every_document_reaches_the_prompt_under_the_url_that_was_read() -> None:
    """A citation names the page we read, so that is the address the model is shown."""

    documents = _documents()
    roster = FixtureClubNewsProvider(FIXTURE_PATH).roster()

    content = build_user_content(documents, roster)

    for document in documents:
        assert document.final_url in content
        assert document.content.decode("utf-8") in content


def test_coding_with_no_document_is_refused() -> None:
    """Nothing to code is not an empty answer."""

    roster = FixtureClubNewsProvider(FIXTURE_PATH).roster()

    with pytest.raises(ClubNewsError, match="no document was read"):
        build_user_content((), roster)


def test_coding_with_no_roster_is_refused() -> None:
    """A claim has to be joined to somebody."""

    with pytest.raises(ClubNewsError, match="roster is empty"):
        build_user_content(_documents(), ())


def test_a_document_that_is_not_utf8_is_refused_rather_than_decoded_lossily() -> None:
    """A quote from a lossy decoding would not be in the bytes it is matched against.

    Replacing an undecodable byte with a question mark would show the model a character the
    document does not contain; every quote covering it would then fail to locate, and the
    week would look like a coding failure rather than an encoding one.
    """

    document = RawDocument(
        club="Chelsea",
        requested_url="https://club.example/latin1",
        final_url="https://club.example/latin1",
        http_status=200,
        content_type="text/plain; charset=iso-8859-1",
        byte_length=13,
        fetched_at_utc="2026-09-11T12:00:00Z",
        content="Kant\xe9 is fit.".encode("latin-1"),
        readable="Kant\xe9 is fit.".encode("latin-1"),
    )
    roster = (RosterPlayer(player_id=1, web_name="Kante", team_name="Chelsea"),)

    with pytest.raises(ClubNewsError, match="not UTF-8"):
        build_user_content((document,), roster)


def _oversized_document(byte_length: int) -> RawDocument:
    """One document whose readable bytes come to ``byte_length``, and nothing clever."""

    return RawDocument(
        club="Chelsea",
        requested_url="https://club.example/long",
        final_url="https://club.example/long",
        http_status=200,
        content_type="text/plain; charset=utf-8",
        byte_length=byte_length,
        fetched_at_utc="2026-09-11T12:00:00Z",
        content=b"a" * byte_length,
        readable=b"a" * byte_length,
    )


def test_a_call_within_the_budget_is_assembled() -> None:
    """The guard is a ceiling, not a tax: an ordinary week must pass it untouched."""

    documents = _documents()
    roster = FixtureClubNewsProvider(FIXTURE_PATH).roster()

    content = build_user_content(documents, roster)

    assert len(content.encode("utf-8")) <= MAXIMUM_USER_CONTENT_BYTES


def test_a_call_over_the_budget_is_refused_before_anything_is_sent() -> None:
    """The whole value of this refusal is where it happens.

    A week's pages are fetched on a deadline. A request that cannot fit the context window
    is rejected by the API *after* every page has been read and the clock spent, and the
    rejection says nothing about which club to drop. Refusing during assembly costs one
    pure function call and names the remedy.
    """

    document = _oversized_document(MAXIMUM_USER_CONTENT_BYTES + 1)
    roster = (RosterPlayer(player_id=1, web_name="Kante", team_name="Chelsea"),)

    with pytest.raises(ClubNewsError, match="over the"):
        build_user_content((document,), roster)


def test_the_budget_refusal_names_the_size_the_budget_and_the_documents() -> None:
    """An operator on a deadline needs to know whether to drop a club or a page."""

    document = _oversized_document(MAXIMUM_USER_CONTENT_BYTES + 1)
    roster = (RosterPlayer(player_id=1, web_name="Kante", team_name="Chelsea"),)

    with pytest.raises(ClubNewsError) as refusal:
        build_user_content((document,), roster)

    message = str(refusal.value)
    assert str(MAXIMUM_USER_CONTENT_BYTES) in message
    assert str(CODING_CONTEXT_TOKENS) in message
    assert "1 document(s)" in message
    assert "fewer clubs" in message


def test_the_budget_counts_the_whole_call_and_not_one_document() -> None:
    """The hazard this guard exists for is twenty clubs in one call, not one long page.

    Each of these documents is comfortably inside the fetch adapter's own per-response cap,
    and inside this budget on its own. Together they are not, which is exactly the case the
    per-document cap cannot see.
    """

    half = MAXIMUM_USER_CONTENT_BYTES // 2 + 1
    documents = (_oversized_document(half), _oversized_document(half))
    roster = (RosterPlayer(player_id=1, web_name="Kante", team_name="Chelsea"),)

    for document in documents:
        assert len(document.content) < MAXIMUM_USER_CONTENT_BYTES

    with pytest.raises(ClubNewsError, match="2 document"):
        build_user_content(documents, roster)


def test_the_budget_is_derived_from_the_window_and_a_pessimistic_ratio() -> None:
    """The number is arithmetic over two stated facts, not a figure someone liked.

    Pinned so that moving the window or the ratio without moving the budget fails here,
    rather than silently leaving a budget whose stated basis is no longer its basis.
    """

    assert MAXIMUM_USER_CONTENT_BYTES == CODING_CONTEXT_TOKENS * CODING_BYTES_PER_TOKEN
    assert CODING_BYTES_PER_TOKEN < 4


def test_the_input_budget_does_not_move_the_prompt_digest() -> None:
    """A guard on the request's size is not a change to the question asked.

    The instrument's digest covers the contract version, the effort, the model, the prompt
    and the schema. If adding a budget had moved it, every stored response would have been
    filed under a prompt version that no longer exists.
    """

    assert (
        coding_prompt_sha256() == "e755c70b96cef2dda4523d04e46292913bf3f8638d6b39261ee4ebd144ffbf5d"
    )
