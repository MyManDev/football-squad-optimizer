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

from squadopt.data.claim_identity import UnresolvedClaim, resolve_claim_player
from squadopt.data.sources.club_news import ClubNewsError, RawDocument, RosterPlayer
from squadopt.data.sources.club_news_coding import (
    CODING_MODEL_IDENTIFIER,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    coding_prompt_sha256,
    locate_claim_response,
    response_schema,
)
from squadopt.platform.club_news_gemini import (
    DEFAULT_GEMINI_MODEL,
    DOCUMENTATION_READ_ON,
    DOCUMENTED_MODELS,
    GEMINI_PROVIDER,
    KEY_HEADER,
    MODELS_PAGE,
    ClubNewsGeminiError,
    GeminiClubNewsProvider,
    gemini_schema,
)
from squadopt.platform.club_news_provider import (
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    CodingProviderConfig,
    build_coding_provider,
    code_week_by_club,
    registered_providers,
)

ANSWER = json.dumps(
    {
        "contract_version": "rotation_claim_coding_v1",
        "documents": [],
        "claims": [],
    }
)
#: A key no service would issue, so that every assertion about where it does not appear is
#: an assertion about a value that is actually there to leak.
SENTINEL_KEY = "sentinel-key-0123456789"

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
    """A provider holding a real key and a transport that never leaves the process."""

    transport = _Transport(reply)
    return GeminiClubNewsProvider(api_key=SENTINEL_KEY, transport=transport), transport


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
    assert transport.headers[KEY_HEADER] == SENTINEL_KEY
    # The key travels in the header and nowhere else: not in the URL, where a proxy or a
    # server log would keep it, and not in the body.
    assert SENTINEL_KEY not in transport.url
    assert SENTINEL_KEY not in json.dumps(transport.body)
    assert transport.body["systemInstruction"] == {"parts": [{"text": SYSTEM_PROMPT}]}
    generation = transport.body["generationConfig"]
    assert isinstance(generation, dict)
    assert generation["responseMimeType"] == "application/json"
    assert generation["temperature"] == 0.0
    assert generation["responseSchema"] == gemini_schema(response_schema())
    # Stated rather than left to the server, and off: on these models a thinking budget is
    # spent out of the same ceiling the claims need.
    assert generation["thinkingConfig"] == {"thinkingBudget": 0}


def test_a_player_the_roster_does_not_hold_reaches_the_resolver_and_is_unresolved() -> None:
    """The adapter passes it through; ``claim_identity`` is what decides, and it does not raise.

    Run the returned bytes through the real chain rather than asserting they came back
    unchanged, which was the earlier version of this test and tested nothing the first case
    did not. A claim naming somebody who is not in the game resolves to ``no_match``, one of
    the three unresolved reasons, and the caller drops that claim and counts it. If the
    adapter refused instead, one unplaceable name would cost the club's whole read.
    """

    said = json.dumps(
        {
            "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            "documents": [],
            "claims": [
                {
                    "player_name": "Nobody At All",
                    "team_name": "Arsenal",
                    "disposition": "stated_expected_absent",
                    "speaker": "the manager",
                    "source_url": DOCUMENTS[0].final_url,
                    "quote": "Saka trained fully.",
                    "paraphrase": "He is out.",
                }
            ],
        }
    )
    provider, _ = _provider(_answered(said))

    response = provider.code(DOCUMENTS, ROSTER)
    located = locate_claim_response(response, DOCUMENTS)
    claim = json.loads(located.text)["claims"][0]

    assert resolve_claim_player(claim["player_name"], claim["team_name"], ROSTER) == (
        UnresolvedClaim(reason="no_match")
    )


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
        {PROVIDER_ENVIRONMENT_VARIABLE: GEMINI_PROVIDER, KEY_ENVIRONMENT_VARIABLE: SENTINEL_KEY}
    )
    # A real client was built here, so this test closes it rather than leaving a socket pool
    # to a garbage collector that runs whenever it likes.
    provider.close()

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


# --- the key, which is the thing that must not travel -----------------------


def test_a_key_that_cannot_travel_in_a_header_is_refused_without_being_quoted() -> None:
    """A two-line key file is the usual cause, and the refusal must not repeat the secret.

    Left unchecked, a key with an interior line break reaches the HTTP layer and is rejected
    there by an exception whose message quotes the whole header value. That exception is not
    one of the types `club_news_acquire` catches, so it escapes as a traceback and prints the
    key into the run log.
    """

    leaky = f"{SENTINEL_KEY}\nX-Injected: yes"

    with pytest.raises(ClubNewsGeminiError) as refusal:
        GeminiClubNewsProvider(api_key=leaky)

    assert "cannot travel in an HTTP header" in str(refusal.value)
    assert SENTINEL_KEY not in str(refusal.value)


@pytest.mark.parametrize(
    "reply",
    [
        _Reply(429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}),
        _Reply(403, {"error": {"status": "PERMISSION_DENIED", "message": "bad key"}}),
        _Reply(200, "<html>gateway</html>", text="<html>gateway</html>"),
        _Reply(200, {"promptFeedback": {"blockReason": "SAFETY"}}),
        _Reply(200, {"candidates": []}),
        _Reply(
            200,
            {
                "candidates": [{"content": {"parts": []}, "finishReason": "STOP"}],
                "modelVersion": "gemini-2.5-flash-002",
            },
        ),
    ],
)
def test_no_refusal_message_carries_the_key(reply: _Reply) -> None:
    """Every way this can fail, checked against the one string that must never be in it."""

    provider, _ = _provider(reply)

    with pytest.raises(ClubNewsError) as refusal:
        provider.code(DOCUMENTS, ROSTER)

    assert SENTINEL_KEY not in str(refusal.value)


def test_a_failure_is_quoted_by_its_status_and_never_by_its_sentence() -> None:
    """The service's own message is free text from a remote system, and it can name the key.

    This is the second review's finding and it is the sharpest one in the file: a real
    ``PERMISSION_DENIED`` reads "Consumer 'api_key:...' has been suspended", and that sentence
    lands in the refused tuple `club_news_acquire` prints. The status says what to do about
    the failure; the sentence after it is not ours to vouch for.
    """

    provider, _ = _provider(
        _Reply(
            403,
            {
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": f"Consumer 'api_key:{SENTINEL_KEY}' has been suspended.",
                },
                "requestEcho": {"headers": {KEY_HEADER: SENTINEL_KEY}},
            },
        )
    )

    with pytest.raises(ClubNewsGeminiError) as refusal:
        provider.code(DOCUMENTS, ROSTER)

    assert "403" in str(refusal.value)
    assert "PERMISSION_DENIED" in str(refusal.value)
    assert "suspended" not in str(refusal.value)
    assert "requestEcho" not in str(refusal.value)
    assert SENTINEL_KEY not in str(refusal.value)


def test_the_key_is_taken_out_even_if_a_refusal_puts_it_in() -> None:
    """The second layer, tested on its own rather than trusted because the first one holds.

    The scrubber exists for the case the rule above is broken later, so the test breaks the
    rule on purpose: a refusal assembled with the key in it comes out without it.
    """

    provider, _ = _provider(_answered())
    leaky = ClubNewsGeminiError(f"the service said {SENTINEL_KEY} is bad")

    scrubbed = provider._scrubbed(leaky)

    assert SENTINEL_KEY not in str(scrubbed)
    assert "[key withheld]" in str(scrubbed)


def test_the_lane_does_not_print_the_key_when_a_club_is_refused() -> None:
    """What is printed is the refused tuple, so that is what the assertion has to read.

    `code_week_by_club` turns a club's failure into `(club, str(error))` and
    `club_news_acquire` prints it line by line. A refusal that is clean in the exception and
    dirty in the tuple would be clean in the wrong place.
    """

    provider, _ = _provider(
        _Reply(
            403,
            {
                "error": {
                    "status": "PERMISSION_DENIED",
                    "message": f"Consumer 'api_key:{SENTINEL_KEY}' has been suspended.",
                }
            },
        )
    )
    config = CodingProviderConfig(
        provider=GEMINI_PROVIDER, model_identifier=DEFAULT_GEMINI_MODEL, api_key=SENTINEL_KEY
    )

    coded, refused = code_week_by_club(provider, config, DOCUMENTS, ROSTER)

    assert coded == ()
    assert [club for club, _reason in refused] == ["Arsenal"]
    assert all(SENTINEL_KEY not in reason for _club, reason in refused)


def test_a_model_identifier_that_cannot_be_a_url_is_refused_here() -> None:
    """``httpx2.InvalidURL`` is not an ``HTTPError``, so it would escape the catch entirely.

    A newline in ``SQUADOPT_LLM_MODEL`` would then cost the whole week its capture instead of
    costing one club its answer, which is the opposite of how this lane fails.
    """

    with pytest.raises(ClubNewsGeminiError, match="not a model identifier"):
        GeminiClubNewsProvider(api_key=SENTINEL_KEY, model_identifier="gemini\n2.5-flash")


def test_a_transport_failure_is_named_by_type_and_costs_one_club() -> None:
    """A timeout used to escape as itself, and its message can quote the request's headers.

    ``code_week_by_club`` catches ``ClubNewsError`` only, so an uncaught transport error was
    a traceback and no capture at all: one reset on club seven of twenty lost the week.
    """

    import httpx2

    class _Broken:
        def post(self, url: str, **_: object) -> _Reply:
            raise httpx2.ConnectTimeout(f"connecting to {url} with {SENTINEL_KEY}")

    provider = GeminiClubNewsProvider(api_key=SENTINEL_KEY, transport=_Broken())

    with pytest.raises(ClubNewsGeminiError) as refusal:
        provider.code(DOCUMENTS, ROSTER)

    assert "ConnectTimeout" in str(refusal.value)
    assert SENTINEL_KEY not in str(refusal.value)


def test_a_thinking_part_is_not_part_of_the_answer() -> None:
    """The model working is not the model answering, and the parser reads only the answer."""

    reply = _Reply(
        200,
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "let me consider the squad", "thought": True},
                            {"text": ANSWER},
                        ]
                    },
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "gemini-2.5-flash-002",
        },
    )
    provider, _ = _provider(reply)

    assert provider.code(DOCUMENTS, ROSTER).text == ANSWER


def test_the_configuration_does_not_print_the_key() -> None:
    """A dataclass prints itself into any log line or traceback that touches it."""

    built, config = build_coding_provider(
        {PROVIDER_ENVIRONMENT_VARIABLE: GEMINI_PROVIDER, KEY_ENVIRONMENT_VARIABLE: SENTINEL_KEY}
    )
    built.close()

    assert SENTINEL_KEY not in repr(config)
    assert config.api_key == SENTINEL_KEY


# --- which models, and what each is sent --------------------------------------


def test_the_default_is_a_model_a_new_key_can_ask() -> None:
    """The first real run found the old default refused with a 404 for a new key.

    The provider's models page limits the 2.5 models to keys that used them before, so a
    default from that family is a default the 9 October run could not use. The default has to
    be in the checked list too, or an unconfigured run would refuse itself.
    """

    assert DEFAULT_GEMINI_MODEL in DOCUMENTED_MODELS
    assert not DEFAULT_GEMINI_MODEL.startswith("gemini-2.")


def test_each_model_is_sent_the_thinking_setting_its_row_names_and_only_one() -> None:
    """Pinned, because a row edited here changes the instrument without changing the digest.

    3.6 Flash and 2.5 Flash keep the budget of zero this adapter always sent: the first is the
    model the first real run was answered by with exactly that request, the second is where the
    provider documents a zero budget as thinking off. The rest have never been asked by this
    adapter and get the lowest level their documentation lists. Never both parameters in one
    request: the provider answers that with a 400.
    """

    assert {name: dict(setting) for name, setting in DOCUMENTED_MODELS.items()} == {
        "gemini-3.8-flash": {"thinkingLevel": "low"},
        "gemini-3.7-flash": {"thinkingLevel": "low"},
        "gemini-3.6-flash": {"thinkingBudget": 0},
        "gemini-3.5-flash": {"thinkingLevel": "minimal"},
        "gemini-3.5-flash-lite": {"thinkingLevel": "minimal"},
        "gemini-2.5-flash": {"thinkingBudget": 0},
    }
    for model, setting in DOCUMENTED_MODELS.items():
        transport = _Transport(_answered())
        provider = GeminiClubNewsProvider(
            api_key=SENTINEL_KEY, model_identifier=model, transport=transport
        )

        provider.code(DOCUMENTS, ROSTER)

        assert f"/models/{model}:generateContent" in transport.url
        thinking = transport.body["generationConfig"]["thinkingConfig"]
        assert thinking == dict(setting)
        assert len(thinking) == 1


@pytest.mark.parametrize(
    "model",
    [
        # Shut down on 1 June 2026 by the deprecations page.
        "gemini-2.0-flash",
        # A preview the same page shut down on 9 March 2026.
        "gemini-3-pro-preview",
        # A plausible typing slip: no such model is listed.
        "gemini-3.6-flash-lite",
        # The other adapter's model, put in the wrong variable.
        CODING_MODEL_IDENTIFIER,
    ],
)
def test_a_model_outside_the_documented_list_is_refused_before_any_request(model: str) -> None:
    """Refused when the adapter is built, so no club is ever sent to a name nobody checked.

    The refusal says where the list came from and when it was read, and names the models it
    would accept, because the remedy is one environment variable.
    """

    transport = _Transport(_answered())

    with pytest.raises(ClubNewsGeminiError) as refusal:
        GeminiClubNewsProvider(api_key=SENTINEL_KEY, model_identifier=model, transport=transport)

    message = str(refusal.value)
    assert repr(model) in message
    assert MODELS_PAGE in message and DOCUMENTATION_READ_ON in message
    assert DEFAULT_GEMINI_MODEL in message
    assert "SQUADOPT_LLM_MODEL" in message
    assert SENTINEL_KEY not in message
    assert transport.url == ""


def test_an_unlisted_model_named_by_the_environment_refuses_the_whole_configuration() -> None:
    """The variable the runbook tells the operator to set is the one that is checked."""

    with pytest.raises(ClubNewsError, match="not in the provider's model list"):
        build_coding_provider(
            {
                PROVIDER_ENVIRONMENT_VARIABLE: GEMINI_PROVIDER,
                MODEL_ENVIRONMENT_VARIABLE: "gemini-2.0-flash",
                KEY_ENVIRONMENT_VARIABLE: SENTINEL_KEY,
            }
        )
