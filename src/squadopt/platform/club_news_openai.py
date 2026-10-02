"""One club-news coding call through OpenAI or a compatible Chat Completions endpoint.

The operator supplies the model; no model, schema downgrade or paid retry is
chosen here. Compatibility requires messages, max_completion_tokens and the
explicit response format. json_object is an operator-selected alternative to
strict json_schema; both keep the same prompt and downstream local citation checks.

As with other adapters, the response text stays unchanged until the pure locator
and parser validate it. Endpoint and token settings are outside the existing
prompt digest: changing them changes the instrument and must be recorded.

Construction and validation never create a client. The existing HTTP transport
uses one request, no redirects/retries or ambient proxy credentials, a byte cap,
I/O timeouts and an elapsed deadline checked between raw body chunks. This is not
an OS process watchdog and cannot promise to interrupt a blocking DNS lookup.
"""

import ipaddress
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.parse import urlsplit, urlunsplit

from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    SYSTEM_PROMPT,
    build_user_content,
    require_requested_coding_contract,
    response_schema,
)

OPENAI_PROVIDER: Final = "openai"
OPENAI_COMPATIBLE_PROVIDER: Final = "openai-compatible"
DEFAULT_OPENAI_BASE_URL: Final = "https://api.openai.com/v1"
DEFAULT_MAX_COMPLETION_TOKENS: Final = 16_000
MAX_COMPLETION_TOKENS: Final = 16_000
REQUEST_TIMEOUT_SECONDS: Final = 180.0
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024


class ClubNewsOpenAIError(ClubNewsError):
    """Configuration or a single coding attempt could not be accepted."""


def _model_identifier_valid(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 256
        and all(33 <= ord(character) <= 126 for character in value)
    )


def validate_openai_configuration(
    *,
    model_identifier: str,
    base_url: str = DEFAULT_OPENAI_BASE_URL,
    response_format: str = "json_schema",
    max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    allow_local_http: bool = False,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> str:
    """Validate without a key, client or network; return the normalized base URL.

    The config layer additionally requires an explicit URL for compatible servers.
    This validates structure, not model context size, entitlement or API support.
    """
    if not _model_identifier_valid(model_identifier):
        raise ClubNewsOpenAIError("An explicit, nonblank model identifier is required.")
    if response_format not in ("json_schema", "json_object"):
        raise ClubNewsOpenAIError("Response format must be json_schema or json_object.")
    if (
        isinstance(max_completion_tokens, bool)
        or not isinstance(max_completion_tokens, int)
        or not 1 <= max_completion_tokens <= MAX_COMPLETION_TOKENS
    ):
        raise ClubNewsOpenAIError("Completion token limit must be an integer from 1 to 16000.")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, int | float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= REQUEST_TIMEOUT_SECONDS
    ):
        raise ClubNewsOpenAIError("Request timeout must be finite and between 0 and 180 seconds.")
    if not isinstance(allow_local_http, bool):
        raise ClubNewsOpenAIError("The local HTTP permission must be a boolean.")
    if (
        not isinstance(base_url, str)
        or not base_url
        or any(ord(character) < 33 or ord(character) > 126 for character in base_url)
        or any(character in base_url for character in "?#\\")
    ):
        raise ClubNewsOpenAIError("The endpoint must be a URL without query or fragment.")
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname
        port = parsed.port
        invalid = (
            parsed.scheme not in ("https", "http")
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or "%" in parsed.netloc
            or any(segment in (".", "..") for segment in parsed.path.split("/"))
            or (port is not None and port == 0)
        )
    except ValueError:
        raise ClubNewsOpenAIError("The endpoint URL is invalid.") from None
    if invalid or host is None:
        raise ClubNewsOpenAIError("The endpoint URL is invalid or contains credentials.")
    if parsed.scheme == "http":
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not allow_local_http or not is_loopback:
            raise ClubNewsOpenAIError("HTTP requires explicit permission and a loopback endpoint.")
    normalized_host = f"[{host.lower()}]" if ":" in host else host.lower()
    default_port = 443 if parsed.scheme == "https" else 80
    authority = normalized_host if port in (None, default_port) else f"{normalized_host}:{port}"
    return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))


@dataclass(frozen=True, slots=True)
class OpenAIReply:
    """The bounded wire response; error bodies need never be retained."""

    status_code: int
    body: bytes


class Transport(Protocol):
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> OpenAIReply: ...


class _HttpxTransport:
    def post(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object],
        timeout: float,
    ) -> OpenAIReply:
        try:
            import httpx2
        except ImportError:
            raise ClubNewsOpenAIError(
                "The llm extra is required for the coding transport."
            ) from None

        deadline = time.monotonic() + timeout
        with (
            httpx2.Client(
                transport=httpx2.HTTPTransport(retries=0, trust_env=False),
                follow_redirects=False,
                trust_env=False,
                timeout=httpx2.Timeout(timeout),
            ) as client,
            client.stream("POST", url, headers=headers, json=json) as response,
        ):
            if response.status_code != 200:
                return OpenAIReply(status_code=response.status_code, body=b"")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ClubNewsOpenAIError("Compressed coding responses are not accepted.")
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                try:
                    length = int(declared_length)
                except ValueError:
                    raise ClubNewsOpenAIError("Invalid coding response length.") from None
                if not 0 <= length <= MAX_RESPONSE_BYTES:
                    raise ClubNewsOpenAIError("Coding response exceeds the byte limit.")
            body = bytearray()
            for chunk in response.iter_raw():
                if time.monotonic() > deadline:
                    raise ClubNewsOpenAIError("Coding response exceeded the time limit.")
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ClubNewsOpenAIError("Coding response exceeds the byte limit.")
                body.extend(chunk)
            if time.monotonic() > deadline:
                raise ClubNewsOpenAIError("Coding response exceeded the time limit.")
            return OpenAIReply(status_code=200, body=bytes(body))


class OpenAIClubNewsProvider:
    """One call per club, preserving requested and returned model identities."""

    def __init__(
        self,
        *,
        api_key: str,
        model_identifier: str,
        target_context: Mapping[str, object] | None = None,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        response_format: str = "json_schema",
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
        allow_local_http: bool = False,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        base = validate_openai_configuration(
            model_identifier=model_identifier,
            base_url=base_url,
            response_format=response_format,
            max_completion_tokens=max_completion_tokens,
            allow_local_http=allow_local_http,
            timeout=timeout,
        )
        key = api_key.strip() if isinstance(api_key, str) else ""
        if not key or any(not 33 <= ord(character) <= 126 for character in key):
            raise ClubNewsOpenAIError(
                "A nonblank, header-safe API key must be supplied explicitly."
            )
        self._api_key = key
        self._target_context = target_context
        self._model_identifier = model_identifier
        self._endpoint = base + "/chat/completions"
        self._response_format = response_format
        self._max_completion_tokens = max_completion_tokens
        self._timeout = timeout
        self._transport: Transport = transport if transport is not None else _HttpxTransport()

    def fetch(self, url: str) -> RawDocument:
        raise ClubNewsOpenAIError("The coding adapter does not fetch club documents.")

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        if len({document.club for document in documents}) != 1:
            raise ClubNewsOpenAIError("A coding call requires documents from exactly one club.")
        output_format: dict[str, object] = {"type": self._response_format}
        if self._response_format == "json_schema":
            output_format["json_schema"] = {
                "name": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                "strict": True,
                "schema": response_schema(),
            }
        body: dict[str, object] = {
            "model": self._model_identifier,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": build_user_content(
                        documents, roster, target_context=self._target_context
                    ),
                },
            ],
            "response_format": output_format,
            "max_completion_tokens": self._max_completion_tokens,
        }
        try:
            reply = self._transport.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
                json=body,
                timeout=self._timeout,
            )
        except Exception:
            # Transport text and chained exceptions can echo an Authorization header.
            raise ClubNewsOpenAIError("The coding request failed; it was not retried.") from None
        if reply.status_code != 200:
            raise ClubNewsOpenAIError(
                f"The coding endpoint returned HTTP {reply.status_code}; no retry or fallback."
            )
        if len(reply.body) > MAX_RESPONSE_BYTES:
            raise ClubNewsOpenAIError("Coding response exceeds the byte limit.")
        if self._api_key.encode("ascii") in reply.body:
            raise ClubNewsOpenAIError("The coding response contained credential material.")
        try:
            payload = json.loads(reply.body)
        except (ValueError, UnicodeError, RecursionError):
            raise ClubNewsOpenAIError("The coding endpoint did not return valid JSON.") from None
        if not isinstance(payload, dict):
            raise ClubNewsOpenAIError("The coding response envelope must be an object.")
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
            raise ClubNewsOpenAIError("The coding response must contain exactly one choice.")
        choice = choices[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ClubNewsOpenAIError("The coding response has no message.")
        if message.get("refusal") is not None:
            raise ClubNewsOpenAIError("The model declined the coding request.")
        if choice.get("finish_reason") != "stop":
            raise ClubNewsOpenAIError(
                "The coding response was truncated or did not finish normally."
            )
        if message.get("tool_calls") or message.get("function_call"):
            raise ClubNewsOpenAIError("The coding response requested an unsupported tool.")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ClubNewsOpenAIError("The coding response has no text.")
        version = payload.get("model")
        if not _model_identifier_valid(version):
            raise ClubNewsOpenAIError("The coding response does not name a valid returned model.")
        assert isinstance(version, str)
        response = ClaimResponse(
            text=text,
            model_identifier=self._model_identifier,
            model_version=version,
        )
        require_requested_coding_contract(response)
        return response
