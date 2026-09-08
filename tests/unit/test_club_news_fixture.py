"""Tests for the club-news provider seam and its committed synthetic fixture.

Nothing here reaches a network, and one of these tests asserts that nothing on this path
*can*: the provider module must not import a network library at all, which is what makes
the whole of the identity join, the evidence artifact and the weekly step buildable with
no key and no connection.
"""

import ast
import json
from pathlib import Path

import pytest
from scripts.generate_club_news_fixture import FIXTURE_FILE
from tests.fixtures.synthetic_club_news import (
    ARSENAL_URL,
    CLAIMS,
    UNITED_UPDATE_URL,
    UNITED_URL,
    make_club_news_fixture,
    make_response_text,
)

from squadopt.data.errors import InvalidValueError
from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    CLUB_NEWS_FIXTURE_CONTRACT_VERSION,
    PUBLISHED_PRECISIONS,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_DISPOSITIONS,
    ClaimResponse,
    ClubNewsError,
    ClubNewsProvider,
    FixtureClubNewsProvider,
    RawDocument,
    RosterPlayer,
)

PROVIDER_MODULE = (
    Path(__file__).resolve().parents[2] / "src" / "squadopt" / "data" / "sources" / "club_news.py"
)

#: Libraries that would put a request on this path. `urllib` is how the existing capture
#: adapter reaches the platform, so it is the one most likely to arrive here by habit.
NETWORK_MODULES = frozenset(
    {"urllib", "urllib.request", "http", "http.client", "socket", "requests", "httpx", "aiohttp"}
)


@pytest.fixture(name="provider")
def _provider() -> FixtureClubNewsProvider:
    return FixtureClubNewsProvider(FIXTURE_FILE)


# --- the committed fixture --------------------------------------------------


def test_the_fixture_is_committed() -> None:
    assert FIXTURE_FILE.is_file()


def test_the_committed_fixture_matches_its_generator() -> None:
    """Guards against the committed file drifting away from the code that makes it."""

    committed = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))

    assert committed == make_club_news_fixture()


def test_the_generator_is_deterministic_across_calls() -> None:
    assert make_club_news_fixture() == make_club_news_fixture()


def test_the_fixture_says_it_is_synthetic() -> None:
    """The directory's rule, asserted rather than remembered: no club's bytes are here."""

    document = make_club_news_fixture()

    assert document["synthetic"] is True
    assert document["contract_version"] == CLUB_NEWS_FIXTURE_CONTRACT_VERSION
    assert document["response_contract_version"] == ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION


# --- the hard cases the fixture exists to carry -----------------------------


def test_all_three_dateline_precisions_are_present() -> None:
    """A day is a day and an absent dateline is absent; neither becomes an instant."""

    response = json.loads(make_response_text())
    by_url = {entry["url"]: entry for entry in response["documents"]}

    assert by_url[ARSENAL_URL]["published_precision"] == "instant"
    assert by_url[ARSENAL_URL]["published_at_utc"] == "2026-09-11T14:00:00Z"
    assert by_url[UNITED_URL]["published_precision"] == "day"
    assert by_url[UNITED_URL]["published_at_utc"] == "2026-09-11"
    assert by_url[UNITED_UPDATE_URL]["published_precision"] == "unknown"
    assert by_url[UNITED_UPDATE_URL]["published_at_utc"] is None
    assert {entry["published_precision"] for entry in response["documents"]} == set(
        PUBLISHED_PRECISIONS
    )


def test_a_fetch_instant_is_never_offered_as_a_dateline() -> None:
    """The document with no dateline must not carry the instant we looked at it."""

    document = make_club_news_fixture()
    fetched = {entry["fetched_at_utc"] for entry in document["documents"]}
    response = json.loads(make_response_text())
    datelines = {entry["published_at_utc"] for entry in response["documents"]}

    assert fetched.isdisjoint(datelines)


def test_a_player_the_model_says_nothing_about_is_in_the_roster_and_not_in_the_claims() -> None:
    """The absent-vs-zero separator. Without this row it is untested."""

    document = make_club_news_fixture()
    named = {claim["player_name"] for claim in CLAIMS}
    silent = [entry["web_name"] for entry in document["roster"] if entry["web_name"] not in named]

    assert "Rice" in silent


def test_a_player_whose_club_was_never_read_is_a_different_state() -> None:
    """Never asked is not asked-and-silent, and the two may never collapse."""

    document = make_club_news_fixture()
    covered = set(document["clubs_covered"])
    declared = set(document["clubs_declared"])
    uncovered = declared - covered

    assert uncovered == {"Everton"}
    assert any(entry["team_name"] in uncovered for entry in document["roster"])
    # And that club is named by no document, so the state is real rather than declared.
    assert uncovered.isdisjoint({entry["club"] for entry in document["documents"]})


def test_a_covered_club_with_no_statement_about_a_player_is_a_third_state() -> None:
    dispositions = {claim["disposition"] for claim in CLAIMS}

    assert "no_statement" in dispositions


def test_every_disposition_except_not_addressed_is_claimed() -> None:
    """``not_addressed`` is expressed by absence, which is the whole point of it."""

    claimed = {claim["disposition"] for claim in CLAIMS}

    assert claimed == set(ROTATION_DISPOSITIONS) - {"not_addressed"}


def test_every_speaker_role_is_a_declared_one() -> None:
    assert {claim["speaker"] for claim in CLAIMS} <= set(CLAIM_SPEAKERS)


def test_a_quotable_span_carrying_a_per_cent_sign_is_present() -> None:
    """The published-surface guard on that character is absolute, so this case must exist."""

    provider = FixtureClubNewsProvider(FIXTURE_FILE)
    content = provider.fetch(ARSENAL_URL).content
    spans = [
        content[claim["span_start"] : claim["span_end"]].decode("utf-8")
        for claim in CLAIMS
        if claim["source_url"] == ARSENAL_URL
    ]

    assert any("%" in span for span in spans)


def test_a_paraphrase_carrying_a_per_cent_sign_is_present() -> None:
    """A different case from the span: this is our sentence, and it is refused, not fixed."""

    assert any("%" in claim["paraphrase"] for claim in CLAIMS)


def test_a_paraphrase_carrying_a_likelihood_word_is_present() -> None:
    assert any("likely" in claim["paraphrase"] for claim in CLAIMS)


def test_a_surname_two_players_in_one_club_share_is_present() -> None:
    """The join must refuse on this rather than pick the more famous player."""

    document = make_club_news_fixture()
    united = [entry for entry in document["roster"] if entry["team_name"] == "Man Utd"]
    surnames = [entry["web_name"].split(".")[-1] for entry in united]
    colliding = {name for name in surnames if surnames.count(name) > 1}

    assert colliding
    assert any(claim["player_name"] in colliding for claim in CLAIMS)


def test_a_claim_naming_nobody_on_the_roster_is_present() -> None:
    document = make_club_news_fixture()
    names = {entry["web_name"] for entry in document["roster"]}

    assert any(claim["player_name"] not in names for claim in CLAIMS)


def test_every_span_points_at_the_sentence_it_claims(provider: FixtureClubNewsProvider) -> None:
    """Offsets are computed from the assembled text, so this holds by construction."""

    for claim in CLAIMS:
        content = provider.fetch(claim["source_url"]).content
        span = content[claim["span_start"] : claim["span_end"]].decode("utf-8")
        assert span
        assert span == span.strip()


def test_the_unparseable_responses_break_the_format_four_different_ways(
    provider: FixtureClubNewsProvider,
) -> None:
    """A parser that guessed at one of these would guess at a real malformed answer."""

    responses = provider.unparseable_responses()

    assert len(responses) == 4
    assert len({response.text for response in responses}) == 4


# --- the shapes -------------------------------------------------------------


def test_a_document_whose_declared_length_disagrees_with_its_bytes_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="declares 5 bytes"):
        RawDocument(
            requested_url="https://club.example/a",
            final_url="https://club.example/a",
            http_status=200,
            content_type="text/plain",
            byte_length=5,
            fetched_at_utc="2026-09-12T14:05:00Z",
            content=b"abc",
        )


def test_a_document_with_a_local_fetch_instant_is_rejected() -> None:
    with pytest.raises(Exception, match="fetched_at_utc"):
        RawDocument(
            requested_url="https://club.example/a",
            final_url="https://club.example/a",
            http_status=200,
            content_type="text/plain",
            byte_length=3,
            fetched_at_utc="2026-09-12 14:05:00",
            content=b"abc",
        )


def test_a_response_with_no_model_identity_cannot_be_replayed() -> None:
    with pytest.raises(InvalidValueError, match="name the model"):
        ClaimResponse(text="{}", model_identifier="", model_version="1")


def test_an_empty_response_is_not_a_response() -> None:
    with pytest.raises(InvalidValueError, match="no text"):
        ClaimResponse(text="   ", model_identifier="m", model_version="1")


# --- the stub ---------------------------------------------------------------


def test_the_stub_satisfies_the_protocol(provider: FixtureClubNewsProvider) -> None:
    reader: ClubNewsProvider = provider

    assert reader.fetch(ARSENAL_URL).http_status == 200


def test_a_fetched_document_declares_the_page_that_was_actually_read(
    provider: FixtureClubNewsProvider,
) -> None:
    """A redirect changes which words were read, so a citation must name the final URL."""

    document = provider.fetch(UNITED_URL)

    assert document.requested_url == UNITED_URL
    assert document.final_url == UNITED_URL + "/full"


def test_the_declared_length_is_the_bytes_that_arrived(provider: FixtureClubNewsProvider) -> None:
    document = provider.fetch(ARSENAL_URL)

    assert document.byte_length == len(document.content)


def test_an_unknown_url_is_refused_rather_than_served_empty(
    provider: FixtureClubNewsProvider,
) -> None:
    """An empty document would be indistinguishable from a club that published nothing."""

    with pytest.raises(ClubNewsError, match="no document for"):
        provider.fetch("https://club.example/spurs/team-news")


def test_the_stub_returns_the_canned_response(provider: FixtureClubNewsProvider) -> None:
    response = provider.code([provider.fetch(ARSENAL_URL)], provider.roster())

    assert response.text == make_response_text()
    assert response.model_identifier == "synthetic-stub"


def test_the_stub_does_not_vary_its_answer_with_its_arguments(
    provider: FixtureClubNewsProvider,
) -> None:
    """A stub that varied would be a second implementation of the thing it stands in for."""

    one = provider.code([provider.fetch(ARSENAL_URL)], provider.roster())
    many = provider.code([provider.fetch(url) for url in provider.urls], provider.roster())

    assert one == many


def test_coding_nothing_is_refused(provider: FixtureClubNewsProvider) -> None:
    with pytest.raises(ClubNewsError, match="no document was read"):
        provider.code([], provider.roster())


def test_coding_against_an_empty_roster_is_refused(provider: FixtureClubNewsProvider) -> None:
    with pytest.raises(ClubNewsError, match="roster is empty"):
        provider.code([provider.fetch(ARSENAL_URL)], [])


def test_the_roster_keys_on_the_persistent_code(provider: FixtureClubNewsProvider) -> None:
    roster = provider.roster()

    assert len(roster) == 14
    assert all(isinstance(player, RosterPlayer) for player in roster)
    assert len({player.player_id for player in roster}) == 14


def test_a_fixture_of_another_contract_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"contract_version": "club_news_fixture_v0"}), encoding="utf-8")

    with pytest.raises(ClubNewsError, match="declares contract"):
        FixtureClubNewsProvider(path)


def test_a_missing_fixture_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ClubNewsError, match="Cannot read"):
        FixtureClubNewsProvider(tmp_path / "absent.json")


def test_a_fixture_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ClubNewsError, match="not valid JSON"):
        FixtureClubNewsProvider(path)


# --- the property that makes all of the above possible ----------------------


def test_the_provider_module_imports_no_network_library() -> None:
    """The seam is offline by construction, not by discipline.

    Asserted against the module's own syntax tree rather than by importing it: an import
    guarded behind a function would still put a request on this path, and a runtime check
    would not see it until something called that function.
    """

    tree = ast.parse(PROVIDER_MODULE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert imported.isdisjoint(NETWORK_MODULES), sorted(imported & NETWORK_MODULES)
    assert not any(name.split(".")[0] in {"urllib", "http"} for name in imported)
