"""The real model call, asserted without a key, a network or the SDK installed.

Every test here runs offline. The provider takes a client, so what it *would have sent* is
recorded and checked: the frozen prompt verbatim, the model the contract names, the schema,
and -- the one that matters most -- no tool of any kind. A model that could search or fetch
would make the manifest's document digests a fiction, because the bytes we hashed would no
longer be the bytes it read. That prohibition is structural rather than instructed: the
request has no ``tools`` key, and this file is what keeps it that way.

The four refusals on the reading side are here too. Each one is a state that must not become
"the model produced no disposition for these players", because that sentence is a finding
this pipeline publishes and it has to be true when it appears.
"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from squadopt.data.sources.club_news import (
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import (
    CODING_EFFORT,
    CODING_MODEL_IDENTIFIER,
    SYSTEM_PROMPT,
    CodingFixture,
    locate_claim_response,
    response_schema,
)
from squadopt.platform.club_news_model import (
    API_KEY_ENVIRONMENT_VARIABLE,
    MAX_OUTPUT_TOKENS,
    MAX_TRANSPORT_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    AnthropicClubNewsProvider,
    ClubNewsModelError,
    read_api_key,
)

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE_PATH = SAMPLE_DIR / "club_news_v1.fixture.json"
CODING_FIXTURE_PATH = SAMPLE_DIR / "club_news_coding_v1.fixture.json"

SERVED_MODEL = "claude-opus-5-20260501"


@dataclass
class _Block:
    """One content block, as much of one as this module reads."""

    type: str
    text: str = ""


@dataclass
class _Message:
    """A finished message, assembled by a test instead of by the API."""

    content: list[_Block]
    model: str | None = SERVED_MODEL
    stop_reason: str | None = "end_turn"
    stop_details: Any = None


@dataclass
class _Details:
    category: str


@dataclass
class _Recorder:
    """A client that records the request and returns a prepared message.

    Satisfies ``CodingClient`` structurally, which is the whole reason that protocol is
    narrow: the seam a test needs and the seam the SDK fills are the same one.
    """

    message: _Message
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def messages(self) -> "_Recorder":
        return self

    def create(self, **kwargs: Any) -> _Message:
        self.calls.append(kwargs)
        return self.message


def _documents() -> tuple[RawDocument, ...]:
    provider = FixtureClubNewsProvider(FIXTURE_PATH)
    return tuple(provider.fetch(url) for url in provider.urls)


def _roster() -> tuple[Any, ...]:
    return FixtureClubNewsProvider(FIXTURE_PATH).roster()


def _coding_text() -> str:
    return CodingFixture(CODING_FIXTURE_PATH).response().text


def _provider(message: _Message) -> tuple[AnthropicClubNewsProvider, _Recorder]:
    recorder = _Recorder(message=message)
    return AnthropicClubNewsProvider(client=recorder), recorder


def _coded_message() -> _Message:
    return _Message(content=[_Block(type="text", text=_coding_text())])


def test_a_missing_key_is_refused_by_name() -> None:
    """The refusal has to name the variable, or an operator cannot act on it."""

    with pytest.raises(ClubNewsModelError, match=API_KEY_ENVIRONMENT_VARIABLE):
        read_api_key({})


def test_a_blank_key_is_the_same_as_no_key() -> None:
    """A variable set to spaces is set in the shell and unset in every useful sense."""

    with pytest.raises(ClubNewsModelError, match=API_KEY_ENVIRONMENT_VARIABLE):
        read_api_key({API_KEY_ENVIRONMENT_VARIABLE: "   "})


def test_a_key_is_returned_trimmed() -> None:
    """A trailing newline from a copied secret is not part of the secret."""

    assert read_api_key({API_KEY_ENVIRONMENT_VARIABLE: " sk-test \n"}) == "sk-test"


def test_the_refusal_points_at_the_provider_that_needs_no_key() -> None:
    """Nobody should conclude from a missing key that this lane cannot be run at all."""

    with pytest.raises(ClubNewsModelError, match="fixture provider"):
        read_api_key({})


def test_building_a_provider_without_a_key_or_a_client_is_refused() -> None:
    """It refuses before it constructs anything, so no request can be attempted."""

    with pytest.raises(ClubNewsModelError, match=API_KEY_ENVIRONMENT_VARIABLE):
        AnthropicClubNewsProvider(environ={})


def test_the_request_attaches_no_tool_of_any_kind() -> None:
    """The prohibition, as a test.

    Not "the prompt says not to search" -- the request has no tool to search with. If a
    later edit adds one, this fails, and it should: a model that fetched the page itself
    would leave the manifest hashing bytes nobody read.
    """

    provider, recorder = _provider(_coded_message())

    provider.code(_documents(), _roster())

    sent = recorder.calls[0]
    assert "tools" not in sent
    assert "tool_choice" not in sent
    assert "betas" not in sent
    assert not any("search" in key or "fetch" in key for key in sent)


def test_the_request_carries_the_frozen_prompt_verbatim() -> None:
    """The prompt is a constant in the repository; the request must be that constant."""

    provider, recorder = _provider(_coded_message())

    provider.code(_documents(), _roster())

    assert recorder.calls[0]["system"] == SYSTEM_PROMPT


def test_the_request_names_the_model_and_settings_the_contract_pinned() -> None:
    """Everything in the prompt digest has to actually be sent, or the digest is a story."""

    provider, recorder = _provider(_coded_message())

    provider.code(_documents(), _roster())

    sent = recorder.calls[0]
    assert sent["model"] == CODING_MODEL_IDENTIFIER
    assert sent["max_tokens"] == MAX_OUTPUT_TOKENS
    assert sent["output_config"]["effort"] == CODING_EFFORT
    assert sent["output_config"]["format"] == {
        "type": "json_schema",
        "schema": response_schema(),
    }


def test_the_request_carries_the_documents_and_the_roster() -> None:
    """One user turn, assembled deterministically, with everything the coding needs."""

    documents = _documents()
    provider, recorder = _provider(_coded_message())

    provider.code(documents, _roster())

    messages = recorder.calls[0]["messages"]
    assert [message["role"] for message in messages] == ["user"]
    for document in documents:
        assert document.content.decode("utf-8") in messages[0]["content"]


def test_the_response_text_comes_back_unparsed() -> None:
    """Verbatim, because the stored bytes are what everything downstream replays from."""

    provider, _ = _provider(_coded_message())

    response = provider.code(_documents(), _roster())

    assert response.text == _coding_text()


def test_what_was_asked_for_and_what_answered_are_recorded_separately() -> None:
    """A request naming an alias can be served by a snapshot, and that has to survive."""

    provider, _ = _provider(_coded_message())

    response = provider.code(_documents(), _roster())

    assert response.model_identifier == CODING_MODEL_IDENTIFIER
    assert response.model_version == SERVED_MODEL


def test_several_text_blocks_are_joined_in_order() -> None:
    """A response split across blocks is one document, and half of it is not JSON."""

    text = _coding_text()
    half = len(text) // 2
    message = _Message(
        content=[
            _Block(type="thinking", text="not part of the answer"),
            _Block(type="text", text=text[:half]),
            _Block(type="text", text=text[half:]),
        ]
    )
    provider, _ = _provider(message)

    response = provider.code(_documents(), _roster())

    assert response.text == text


def test_the_whole_chain_replays_offline_from_the_returned_bytes() -> None:
    """The done criterion of this deliverable, end to end with no network.

    What the provider returns is located and parsed by pure code, and the claims that come
    out are the ones the committed fixture pair already agrees on. Nothing in this path
    asks a model anything a second time.
    """

    documents = _documents()
    provider, _ = _provider(_coded_message())

    response = provider.code(documents, _roster())
    claims = parse_claim_response(locate_claim_response(response, documents), documents)

    assert len(claims) == len(json.loads(_coding_text())["claims"])
    assert all(claim.source_sha256 for claim in claims)


def test_a_declined_request_is_a_refusal_and_not_an_empty_week() -> None:
    """ "The model produced no disposition" is a finding, and it would be a false one."""

    message = _Message(
        content=[],
        stop_reason="refusal",
        stop_details=_Details(category="reasoning_extraction"),
    )
    provider, _ = _provider(message)

    with pytest.raises(ClubNewsModelError, match="declined"):
        provider.code(_documents(), _roster())


def test_a_decline_names_its_category() -> None:
    """Whoever reads the failure has to be able to tell why it was declined."""

    message = _Message(content=[], stop_reason="refusal", stop_details=_Details(category="cyber"))
    provider, _ = _provider(message)

    with pytest.raises(ClubNewsModelError, match="cyber"):
        provider.code(_documents(), _roster())


def test_a_truncated_response_is_refused_rather_than_parsed_as_far_as_it_got() -> None:
    """Parsing a cut-off document would drop whichever players came last, silently."""

    text = _coding_text()
    message = _Message(
        content=[_Block(type="text", text=text[: len(text) // 2])],
        stop_reason="max_tokens",
    )
    provider, _ = _provider(message)

    with pytest.raises(ClubNewsModelError, match="truncated"):
        provider.code(_documents(), _roster())


def test_a_response_with_no_text_is_not_an_empty_answer() -> None:
    """The empty answer has a shape: a document with an empty claims array."""

    provider, _ = _provider(_Message(content=[_Block(type="thinking", text="hmm")]))

    with pytest.raises(ClubNewsModelError, match="no text"):
        provider.code(_documents(), _roster())


def test_a_response_that_does_not_name_its_model_is_refused() -> None:
    """Without it the claim cannot be replayed against the model that produced it."""

    message = _Message(content=[_Block(type="text", text=_coding_text())], model=None)
    provider, _ = _provider(message)

    with pytest.raises(ClubNewsModelError, match="does not name the model"):
        provider.code(_documents(), _roster())


def test_this_provider_refuses_to_fetch() -> None:
    """Coding and fetching are separate deliverables with separate questions to answer."""

    provider, _ = _provider(_coded_message())

    with pytest.raises(ClubNewsModelError, match="does not fetch"):
        provider.fetch("https://club.example/arsenal/team-news-gw4")


def test_a_model_error_is_a_club_news_error() -> None:
    """Callers already handle the seam's error type; this must not slip past them."""

    assert issubclass(ClubNewsModelError, ClubNewsError)


def test_transport_retries_are_bounded_and_deliberate() -> None:
    """More than the SDK default because the call sits on a deadline, not unbounded."""

    assert MAX_TRANSPORT_RETRIES == 4


class _RecordingSdk:
    """A stand-in for the ``anthropic`` module, recording how the client was built."""

    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}

    def Anthropic(self, **kwargs: Any) -> object:
        self.kwargs = kwargs
        return _Recorder(message=_coded_message())


def test_the_client_is_built_with_the_key_the_retries_and_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three reach the SDK, and none of them is left to its defaults.

    The key is read from one named variable rather than resolved implicitly, the retries are
    raised above the SDK's two, and the timeout is set *because* they were raised: a timeout
    is itself retried, so leaving the ten-minute default beside four retries would have put
    fifty minutes of wall clock in front of a deadline.
    """

    sdk = _RecordingSdk()
    monkeypatch.setitem(sys.modules, "anthropic", sdk)

    AnthropicClubNewsProvider(environ={API_KEY_ENVIRONMENT_VARIABLE: "sk-test"})

    assert sdk.kwargs == {
        "api_key": "sk-test",
        "max_retries": MAX_TRANSPORT_RETRIES,
        "timeout": REQUEST_TIMEOUT_SECONDS,
    }


def test_the_worst_case_wall_clock_is_bounded_by_the_deadline_it_sits_in_front_of() -> None:
    """Retries multiply the timeout, so the two constants are only sound together.

    Pinned as one fact rather than two: raising the retries without lowering the timeout is
    the mistake this check exists to catch, and it cannot be seen in either constant alone.
    """

    attempts = MAX_TRANSPORT_RETRIES + 1

    assert REQUEST_TIMEOUT_SECONDS * attempts <= 15 * 60
