"""The second adapter: one REST call, and every way an answer can fail to be one.

Offline throughout. The transport is handed in, so no test reads a key and none opens a
socket. What these hold is the rule the lane is built on: a response that does not parse is a
refusal and never a guess, and the four ways a model can fail to answer stay four different
facts rather than collapsing into "no claims this week".
"""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from squadopt.data.sources.club_news import ClubNewsError, RawDocument, RosterPlayer
from squadopt.data.sources.club_news_coding import (
    CODING_MODEL_IDENTIFIER,
    SYSTEM_PROMPT,
    coding_prompt_sha256,
    response_schema,
)
from squadopt.platform.club_news_gemini import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_PROVIDER,
    KEY_HEADER,
    ClubNewsGeminiError,
    GeminiClubNewsProvider,
    gemini_schema,
)
from squadopt.platform.club_news_provider import (
    KEY_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    build_coding_provider,
    registered_providers,
)

ANSWER = json.dumps(
    {
        "contract_version": "rotation_claim_coding_v1",
        "documents": [],
        "claims": [],
    }
)
ROSTER = (RosterPlayer(player_id=1, web_name="Saka", team_name="Arsenal"),)
DOCUMENTS = (
    RawDocument(
        club="Arsenal",
        requested_url="https://club.example/arsenal/news",
        final_url="https://club.example/arsenal/news",
        http_status=200,
        content_type="text/html; charset=utf-8",
        byte_length=26,
        fetched_at_utc="2026-09-12T14:00:00Z",
        content=b"<p>Saka trained fully.</p>",
        readable=b"Saka trained fully.",
    ),
)


class _Reply:
    def __init__(self, status: int, body: object, *, text: str | None = None) -> None:
        self.status_code = status
        self._body = body
        self.text = text if text is not None else json.dumps(body)

    def json(self) -> object:
        if isinstance(self._body, str):
            raise ValueError("not json")
        return self._body


class _Transport:
    """Records the one request this adapter makes, and answers with what a test decides."""

    def __init__(self, reply: _Reply) -> None:
        self._reply = reply
        self.url: str = ""
        self.headers: Mapping[str, str] = {}
        self.body: Mapping[str, Any] = {}

    def post(
        self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object], timeout: float
    ) -> _Reply:
        self.url, self.headers, self.body = url, headers, dict(json)
        return self._reply


def _answered(text: str = ANSWER, *, model: str = "gemini-2.5-flash-002") -> _Reply:
    return _Reply(
        200,
        {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "modelVersion": model,
        },
    )


def _provider(reply: _Reply) -> tuple[GeminiClubNewsProvider, _Transport]:
    transport = _Transport(reply)
    return GeminiClubNewsProvider(transport=transport), transport


# --- what a good answer looks like ------------------------------------------


def test_a_well_formed_answer_comes_back_verbatim_with_both_identities() -> None:
    """The text is not parsed here, and the two identities are kept apart on purpose.

    ``model_identifier`` is what was asked for and ``model_version`` is what answered; a
    request naming an alias can be served by a snapshot, and which model produced a claim has
    to survive that.
    """

    provider, _ = _provider(_answered())

    response = provider.code(DOCUMENTS, ROSTER)

    assert response.text == ANSWER
    assert response.model_identifier == DEFAULT_GEMINI_MODEL
    assert response.model_version == "gemini-2.5-flash-002"


def test_the_request_carries_the_frozen_prompt_the_schema_and_the_key_in_a_header() -> None:
    """Inspected offline, which is the whole reason the transport is a parameter."""

    provider, transport = _provider(_answered())

    provider.code(DOCUMENTS, ROSTER)

    assert DEFAULT_GEMINI_MODEL in transport.url
    assert transport.headers[KEY_HEADER] == ""
    # The key never travels in the URL, where a proxy or a server log would keep it.
    assert "key=" not in transport.url
    assert transport.body["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    generation = transport.body["generationConfig"]
    assert isinstance(generation, dict)
    assert generation["responseMimeType"] == "application/json"
    assert generation["temperature"] == 0.0
    assert generation["responseSchema"] == gemini_schema(response_schema())


def test_a_player_the_roster_does_not_hold_is_passed_through_rather_than_judged() -> None:
    """Resolving a name is ``data/claim_identity``'s job and it does not raise.

    A claim naming somebody who is not in the game is one of that module's three unresolved
    reasons: the caller drops the claim and counts it. If this adapter refused the response,
    one unplaceable name would cost the club's whole read.
    """

    said = json.dumps(
        {
            "contract_version": "rotation_claim_coding_v1",
            "documents": [],
            "claims": [{"player_web_name": "Nobody", "club": "Arsenal"}],
        }
    )
    provider, _ = _provider(_answered(said))

    assert provider.code(DOCUMENTS, ROSTER).text == said


# --- the four ways an answer is not one -------------------------------------


def test_a_rate_limited_answer_is_refused_and_named_as_the_limit() -> None:
    """A free tier's limit is a fact about the run, not a transient to paper over."""

    provider, _ = _provider(_Reply(429, {"error": {"message": "quota"}}))

    with pytest.raises(ClubNewsGeminiError, match="rate limit"):
        provider.code(DOCUMENTS, ROSTER)


def test_a_body_that_is_not_json_is_refused_with_what_arrived() -> None:
    provider, _ = _provider(_Reply(200, "<html>gateway</html>", text="<html>gateway</html>"))

    with pytest.raises(ClubNewsGeminiError, match="not JSON"):
        provider.code(DOCUMENTS, ROSTER)


def test_a_truncated_answer_is_refused_rather_than_parsed_as_far_as_it_got() -> None:
    """Parsing it would silently drop whichever players the model had not reached."""

    reply = _Reply(
        200,
        {
            "candidates": [
                {"content": {"parts": [{"text": '{"claims": ['}]}, "finishReason": "MAX_TOKENS"}
            ],
            "modelVersion": "gemini-2.5-flash-002",
        },
    )
    provider, _ = _provider(reply)

    with pytest.raises(ClubNewsGeminiError, match="truncated"):
        provider.code(DOCUMENTS, ROSTER)


def test_an_answer_with_no_text_is_not_an_answer_that_mentioned_nobody() -> None:
    """The empty answer has a shape: a document with an empty ``claims`` array. This is not it."""

    reply = _Reply(
        200,
        {
            "candidates": [{"content": {"parts": []}, "finishReason": "STOP"}],
            "modelVersion": "gemini-2.5-flash-002",
        },
    )
    provider, _ = _provider(reply)

    with pytest.raises(ClubNewsGeminiError, match="no text"):
        provider.code(DOCUMENTS, ROSTER)


def test_a_declined_request_is_refused_by_its_own_name() -> None:
    provider, _ = _provider(_Reply(200, {"promptFeedback": {"blockReason": "SAFETY"}}))

    with pytest.raises(ClubNewsGeminiError, match="declined"):
        provider.code(DOCUMENTS, ROSTER)


def test_an_answer_that_will_not_say_which_model_produced_it_is_refused() -> None:
    reply = _Reply(
        200,
        {"candidates": [{"content": {"parts": [{"text": ANSWER}]}, "finishReason": "STOP"}]},
    )
    provider, _ = _provider(reply)

    with pytest.raises(ClubNewsGeminiError, match="does not name the model"):
        provider.code(DOCUMENTS, ROSTER)


def test_fetching_is_refused_because_coding_is_not_a_licence_to_browse() -> None:
    provider, _ = _provider(_answered())

    with pytest.raises(ClubNewsGeminiError, match="does not fetch"):
        provider.fetch("https://club.example/arsenal/news")


# --- the schema, translated rather than copied ------------------------------


def test_the_schema_is_translated_into_the_subset_this_api_accepts() -> None:
    """Computed from the contract's own schema, so a new disposition needs no second edit."""

    translated = json.dumps(gemini_schema(response_schema()))

    assert "additionalProperties" not in translated
    assert '"type": [' not in translated
    assert '"nullable": true' in translated
    # The vocabularies still travel: the request constrains the answer's shape.
    assert "contract_version" in translated


def test_a_type_union_with_no_single_concrete_type_is_refused() -> None:
    with pytest.raises(ClubNewsGeminiError, match="no single concrete type"):
        gemini_schema({"type": ["string", "integer"]})


# --- selection, which is the point of the registry --------------------------


def test_the_free_provider_is_selected_by_environment_variable_alone() -> None:
    """A second model is a registration, not a rewrite. This is that claim, exercised."""

    assert GEMINI_PROVIDER in registered_providers()

    provider, config = build_coding_provider(
        {PROVIDER_ENVIRONMENT_VARIABLE: GEMINI_PROVIDER, KEY_ENVIRONMENT_VARIABLE: "not-a-key"}
    )

    assert isinstance(provider, GeminiClubNewsProvider)
    assert config.provider == GEMINI_PROVIDER
    assert config.model_identifier == DEFAULT_GEMINI_MODEL


def test_a_week_coded_here_stays_distinguishable_from_one_coded_by_the_other_model() -> None:
    """The same words asked of a different model are a different question, and the digest
    says so."""

    assert coding_prompt_sha256(DEFAULT_GEMINI_MODEL) != coding_prompt_sha256(
        CODING_MODEL_IDENTIFIER
    )


def test_a_provider_built_without_a_key_refuses_before_any_call() -> None:
    with pytest.raises(ClubNewsError, match="needs an API key"):
        GeminiClubNewsProvider(api_key="   ")
