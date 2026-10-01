"""Offline request, response and credential boundaries for Chat Completions coding."""

import json
import traceback
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, ClassVar

import pytest

from squadopt.data.sources.club_news import ClubNewsError, RawDocument, RosterPlayer
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    build_user_content,
    locate_claim_response,
    response_schema,
)
from squadopt.platform import club_news_openai as adapter
from squadopt.platform.club_news_openai import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    DEFAULT_OPENAI_BASE_URL,
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT_SECONDS,
    ClubNewsOpenAIError,
    OpenAIClubNewsProvider,
    OpenAIReply,
    validate_openai_configuration,
)

KEY = "offline-sentinel-key-00000000"
MODEL = "explicit-org/model:revision"
SOURCE = b"Saka will not travel."
DOCUMENTS = (
    RawDocument(
        club="Arsenal",
        requested_url="https://club.example/news",
        final_url="https://club.example/news",
        http_status=200,
        content_type="text/plain",
        byte_length=len(SOURCE),
        fetched_at_utc="2026-09-12T14:00:00Z",
        content=SOURCE,
        readable=SOURCE,
    ),
)
ROSTER = (RosterPlayer(player_id=1, web_name="Saka", team_name="Arsenal"),)
ANSWER = json.dumps(
    {"contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION, "documents": [], "claims": []}
)


class _Transport:
    def __init__(self, reply: OpenAIReply | Exception) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []

    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> OpenAIReply:
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def _envelope(text: object = ANSWER) -> dict[str, Any]:
    return {
        "model": "returned-concrete-revision",
        "choices": [{"finish_reason": "stop", "message": {"content": text, "refusal": None}}],
    }


def _reply(payload: object | None = None, *, status: int = 200) -> OpenAIReply:
    return OpenAIReply(
        status_code=status, body=json.dumps(_envelope() if payload is None else payload).encode()
    )


def _provider(
    reply: OpenAIReply | Exception | None = None, **options: Any
) -> tuple[OpenAIClubNewsProvider, _Transport]:
    transport = _Transport(_reply() if reply is None else reply)
    return (
        OpenAIClubNewsProvider(api_key=KEY, model_identifier=MODEL, transport=transport, **options),
        transport,
    )


def test_exact_request_contract_one_call_and_distinct_model_identities() -> None:
    provider, transport = _provider()
    response = provider.code(DOCUMENTS, ROSTER)
    assert response.text == ANSWER
    assert response.model_identifier == MODEL
    assert response.model_version == "returned-concrete-revision"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == "https://api.openai.com/v1/chat/completions"
    assert call["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    assert call["headers"]["Accept-Encoding"] == "identity"
    assert KEY not in call["url"]
    assert KEY not in json.dumps(call["json"])
    assert call["json"] == {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(DOCUMENTS, ROSTER)},
        ],
        "max_completion_tokens": DEFAULT_MAX_COMPLETION_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                "strict": True,
                "schema": response_schema(),
            },
        },
    }


def test_explicit_json_object_keeps_prompt_and_local_citation_contract() -> None:
    coded = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "documents": [
            {
                "url": DOCUMENTS[0].final_url,
                "published_at_utc": None,
                "published_precision": "unknown",
            }
        ],
        "claims": [
            {
                "player_name": "Saka",
                "team_name": "Arsenal",
                "disposition": "stated_expected_absent",
                "speaker": "manager",
                "source_url": DOCUMENTS[0].final_url,
                "quote": SOURCE.decode(),
                "paraphrase": "He will not travel.",
            }
        ],
    }
    provider, transport = _provider(
        _reply(_envelope(json.dumps(coded))), response_format="json_object"
    )
    response = provider.code(DOCUMENTS, ROSTER)
    claims = parse_claim_response(locate_claim_response(response, DOCUMENTS), DOCUMENTS)
    assert len(claims) == 1
    assert claims[0].disposition == "stated_expected_absent"
    assert transport.calls[0]["json"]["response_format"] == {"type": "json_object"}
    assert transport.calls[0]["json"]["messages"][0]["content"] == SYSTEM_PROMPT
    coded["claims"][0]["quote"] = "A sentence absent from the source."
    provider, _ = _provider(_reply(_envelope(json.dumps(coded))), response_format="json_object")
    with pytest.raises(ClubNewsError):
        locate_claim_response(provider.code(DOCUMENTS, ROSTER), DOCUMENTS)


@pytest.mark.parametrize("status", [301, 302, 307, 308, 400, 401, 403, 404, 429, 500, 503])
def test_http_error_never_retries_changes_model_or_echoes_body(status: int) -> None:
    provider, transport = _provider(_reply({"error": KEY + " private body"}, status=status))
    with pytest.raises(ClubNewsOpenAIError, match=f"HTTP {status}") as error:
        provider.code(DOCUMENTS, ROSTER)
    assert len(transport.calls) == 1
    assert KEY not in str(error.value)
    assert "private body" not in str(error.value)
    assert transport.calls[0]["json"]["model"] == MODEL


def test_transport_exception_and_traceback_do_not_expose_secret() -> None:
    provider, transport = _provider(RuntimeError("Authorization: Bearer " + KEY))
    with pytest.raises(ClubNewsOpenAIError, match="not retried") as error:
        provider.code(DOCUMENTS, ROSTER)
    rendered = "".join(traceback.format_exception(error.value))
    assert KEY not in rendered
    assert "Authorization: Bearer" not in rendered
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "finish", ["length", "content_filter", "tool_calls", "function_call", None]
)
def test_non_normal_finish_is_not_partial_evidence(finish: str | None) -> None:
    payload = _envelope()
    payload["choices"][0]["finish_reason"] = finish
    provider, _ = _provider(_reply(payload))
    with pytest.raises(ClubNewsOpenAIError, match="finish normally"):
        provider.code(DOCUMENTS, ROSTER)


def test_refusal_is_not_an_empty_claim_set() -> None:
    payload = _envelope()
    payload["choices"][0]["message"]["refusal"] = "untrusted refusal text " + KEY
    provider, _ = _provider(_reply(payload))
    with pytest.raises(ClubNewsOpenAIError) as error:
        provider.code(DOCUMENTS, ROSTER)
    assert KEY not in str(error.value)
    payload["choices"][0]["message"]["refusal"] = "declined"
    provider, _ = _provider(_reply(payload))
    with pytest.raises(ClubNewsOpenAIError, match="declined"):
        provider.code(DOCUMENTS, ROSTER)


@pytest.mark.parametrize("content", [None, "", "  ", [{"text": ANSWER}]])
def test_missing_or_non_string_content_is_refused(content: object) -> None:
    provider, _ = _provider(_reply(_envelope(content)))
    with pytest.raises(ClubNewsOpenAIError, match="no text"):
        provider.code(DOCUMENTS, ROSTER)


@pytest.mark.parametrize("model", [None, "", "bad\nmodel"])
def test_missing_returned_model_is_not_filled_with_requested_model(model: object) -> None:
    payload = _envelope()
    payload["model"] = model
    provider, _ = _provider(_reply(payload))
    with pytest.raises(ClubNewsOpenAIError, match="returned model"):
        provider.code(DOCUMENTS, ROSTER)


@pytest.mark.parametrize(
    "payload", [[], {}, {"choices": []}, {"choices": [{}, {}]}, {"choices": [None]}]
)
def test_invalid_envelopes_refused(payload: object) -> None:
    provider, _ = _provider(_reply(payload))
    with pytest.raises(ClubNewsOpenAIError):
        provider.code(DOCUMENTS, ROSTER)


def test_invalid_json_and_oversized_reply_are_bounded_and_sanitized() -> None:
    for body in (b"private not-json body", b"x" * (MAX_RESPONSE_BYTES + 1)):
        provider, _ = _provider(OpenAIReply(status_code=200, body=body))
        with pytest.raises(ClubNewsOpenAIError) as error:
            provider.code(DOCUMENTS, ROSTER)
        assert "private not-json body" not in str(error.value)


def test_key_echo_cannot_be_persisted_as_a_successful_raw_answer() -> None:
    provider, _ = _provider(_reply(_envelope(KEY)))
    with pytest.raises(ClubNewsOpenAIError, match="credential material"):
        provider.code(DOCUMENTS, ROSTER)


@pytest.mark.parametrize("key", ["", "  ", "a b", "a\nb", "a\tb", "café"])
def test_invalid_key_is_rejected_without_echo(key: str) -> None:
    with pytest.raises(ClubNewsOpenAIError, match="header-safe"):
        OpenAIClubNewsProvider(api_key=key, model_identifier=MODEL)


@pytest.mark.parametrize(
    "base",
    [
        "http://remote.example/v1",
        "https://user:secret@remote.example/v1",
        "https://remote.example/v1?key=secret",
        "https://remote.example/v1#secret",
        "https://remote.example/v1?",
        "https://remote.example/v1#",
        "https://remote.example:0/v1",
        "https://remote.example:99999/v1",
        "https://remote.example\\@other.example/v1",
        "https://remote.example/../v1",
        "ftp://remote.example/v1",
        "not a url",
        "https://remote.example/\n",
        "https://localhost.evil.example/v1?key=x",
    ],
)
def test_invalid_endpoint_is_rejected_without_echo(base: str) -> None:
    with pytest.raises(ClubNewsOpenAIError) as error:
        validate_openai_configuration(model_identifier=MODEL, base_url=base, allow_local_http=True)
    assert "secret" not in str(error.value)
    assert base not in str(error.value)


@pytest.mark.parametrize(
    "base", ["http://localhost:9000/v1", "http://127.0.0.1:9000/v1", "http://[::1]:9000/v1"]
)
def test_local_http_requires_explicit_permission(base: str) -> None:
    with pytest.raises(ClubNewsOpenAIError, match="explicit permission"):
        validate_openai_configuration(model_identifier=MODEL, base_url=base)
    assert (
        validate_openai_configuration(model_identifier=MODEL, base_url=base, allow_local_http=True)
        == base
    )


def test_normalized_endpoint_and_unlisted_model_need_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("No client at construction or preflight")

    monkeypatch.setattr(adapter._HttpxTransport, "post", forbidden)
    assert (
        validate_openai_configuration(
            model_identifier=MODEL, base_url="https://API.OPENAI.COM:443/v1/"
        )
        == DEFAULT_OPENAI_BASE_URL
    )
    provider = OpenAIClubNewsProvider(api_key=KEY, model_identifier=MODEL)
    assert KEY not in repr(provider)


@pytest.mark.parametrize(
    "options",
    [
        {"model_identifier": ""},
        {"model_identifier": "has whitespace"},
        {"response_format": "fallback"},
        {"max_completion_tokens": 0},
        {"max_completion_tokens": True},
        {"max_completion_tokens": 16001},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": 181},
        {"allow_local_http": "true"},
    ],
)
def test_invalid_request_options_refused_offline(options: dict[str, Any]) -> None:
    with pytest.raises(ClubNewsOpenAIError):
        validate_openai_configuration(**({"model_identifier": MODEL} | options))


def test_multiclub_and_empty_roster_refused_before_call() -> None:
    provider, transport = _provider()
    with pytest.raises(ClubNewsOpenAIError, match="one club"):
        provider.code((*DOCUMENTS, replace(DOCUMENTS[0], club="Liverpool")), ROSTER)
    with pytest.raises(ClubNewsError, match="roster is empty"):
        provider.code(DOCUMENTS, ())
    assert transport.calls == []


def test_coding_provider_cannot_fetch_arbitrary_urls() -> None:
    provider, transport = _provider()
    with pytest.raises(ClubNewsOpenAIError) as error:
        provider.fetch("https://private.example/?key=" + KEY)
    assert KEY not in str(error.value)
    assert transport.calls == []


def test_default_http_transport_disables_redirects_retries_and_reads_error_body_never(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx2

    captured: dict[str, Any] = {}

    class Response:
        status_code = 307
        headers: ClassVar[dict[str, str]] = {"location": "https://other.example/"}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def iter_raw(self) -> Any:
            raise AssertionError("Redirect/error body must not be read")

    class Client:
        def __init__(self, **options: Any) -> None:
            captured["client_options"] = options

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def stream(self, *args: object, **kwargs: object) -> Response:
            captured["request"] = (args, kwargs)
            return Response()

    def transport(**options: Any) -> object:
        captured["transport_options"] = options
        return object()

    monkeypatch.setattr(httpx2, "HTTPTransport", transport)
    monkeypatch.setattr(httpx2, "Client", Client)
    provider = OpenAIClubNewsProvider(api_key=KEY, model_identifier=MODEL)
    with pytest.raises(ClubNewsOpenAIError, match="HTTP 307"):
        provider.code(DOCUMENTS, ROSTER)
    assert captured["client_options"]["follow_redirects"] is False
    assert captured["client_options"]["trust_env"] is False
    assert captured["transport_options"] == {"retries": 0, "trust_env": False}


def test_raw_transport_stream_stops_at_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx2

    yielded: list[int] = []

    class Response:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def iter_raw(self) -> Any:
            for index in range(10):
                yielded.append(index)
                yield b"a" * 8

    class Client:
        def __init__(self, **options: Any) -> None:
            pass

        def __enter__(self) -> "Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def stream(self, *args: object, **kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(httpx2, "HTTPTransport", lambda **options: object())
    monkeypatch.setattr(httpx2, "Client", Client)
    monkeypatch.setattr(adapter, "MAX_RESPONSE_BYTES", 10)
    provider = OpenAIClubNewsProvider(api_key=KEY, model_identifier=MODEL)
    with pytest.raises(ClubNewsOpenAIError):
        provider.code(DOCUMENTS, ROSTER)
    assert yielded == [0, 1]


@pytest.mark.parametrize("response_format", ["json_schema", "json_object"])
def test_new_response_cannot_use_legacy_contract_as_a_silent_fallback(response_format: str) -> None:
    returned = json.dumps(
        {
            "contract_version": "rotation_claim_coding_v1",
            "documents": [],
            "claims": [],
        }
    )
    provider, transport = _provider(_reply(_envelope(returned)), response_format=response_format)
    with pytest.raises(ClubNewsError, match="requested coding contract"):
        provider.code(DOCUMENTS, ROSTER)
    assert len(transport.calls) == 1
    assert transport.calls[0]["json"]["response_format"]["type"] == response_format
