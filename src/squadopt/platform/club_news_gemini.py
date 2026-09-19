"""Coding club news with a hosted model over one REST call, no vendor SDK.

The lane was built so that a second model is a registration rather than a rewrite
(``club_news_provider.register_provider``), and until now only one adapter existed and it
had never been asked a real question. This is the second: Google's Generative Language API,
whose free tier is enough to prove the connection end to end without spending anything.

**One REST call, on the dependency already pinned.** ``httpx2`` is in ``constraints.txt``
because the API layer needs it, so a vendor SDK would be a new dependency bought for a single
POST. The request is assembled here and the response is read here, which also means the whole
exchange can be inspected offline: the tests hand in a transport and assert on what would
have been sent.

**The response is constrained by the contract's own schema**, translated into the subset this
API accepts. The translation is computed from :func:`response_schema` at call time rather than
written out beside it, so a disposition added to the vocabulary reaches the request without
anybody remembering to copy it.

**A response that does not parse is a refusal, never a guess.** That rule is the reason this
adapter is longer than the call it makes: a declined answer, a truncated one, an empty one and
one that will not say which model produced it are four different facts, and a week that
records the wrong one of them is worse than a week that records nothing.

**What the prompt digest covers here, and what it does not.**
:func:`~squadopt.data.sources.club_news_coding.coding_prompt_sha256` hashes the system prompt,
the response schema as the contract writes it, the effort setting and the model identifier. Of
those, this adapter sends the prompt and the model; it does not send an effort setting, and the
schema it sends is the translated one. Four settings it does send are outside the digest
altogether: the temperature, the thinking budget, the output ceiling and the endpoint version.
So two weeks coded by different models are distinguishable, which is what the digest exists
for, and two weeks coded by this adapter under different values of those four are not. Changing
any of them is therefore a change to the instrument that the digest will not announce, and the
place to announce it is the coding contract version.
"""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import (
    SYSTEM_PROMPT,
    build_user_content,
    response_schema,
)
from squadopt.platform.club_news_model import MAX_OUTPUT_TOKENS, REQUEST_TIMEOUT_SECONDS

#: The provider name this adapter is selected by, through ``SQUADOPT_LLM_PROVIDER``.
GEMINI_PROVIDER: Final = "gemini"

#: What an unconfigured run asks for. Flash is the model the free tier is generous with, and
#: naming a default here is what lets ``SQUADOPT_LLM_MODEL`` stay optional. A name this API
#: does not serve fails at the first call with its own 404 rather than quietly answering as
#: something else, so a wrong default is loud.
DEFAULT_GEMINI_MODEL: Final = "gemini-2.5-flash"

#: The key travels in a header rather than a query parameter so it cannot reach a server log
#: or a proxy's access line as part of the URL.
KEY_HEADER: Final = "x-goog-api-key"

#: What may travel in a header value: printable ASCII with no space and no control byte.
#:
#: This is checked rather than trusted because of where an unchecked key ends up. A key with
#: an interior newline, which is what a two-line key file or a bad paste produces, reaches the
#: HTTP layer and is rejected there by an exception **whose message quotes the whole header
#: value**. That exception is not one of the types the acquisition command catches, so it
#: escapes as a traceback and prints the key into the run log. Refusing here keeps the secret
#: inside the process, and the refusal below never echoes what it refused.
_HEADER_SAFE: Final = re.compile(r"[\x21-\x7e]+")

#: What a model identifier may hold. It is interpolated into the request path, and a URL
#: this client cannot build raises ``httpx2.InvalidURL``, which is not an ``HTTPError`` and
#: so escapes the catch below as a traceback: a stray newline in ``SQUADOPT_LLM_MODEL``
#: would cost the whole week its capture rather than one club its answer.
_MODEL_SAFE: Final = re.compile(r"[A-Za-z0-9._-]+")

_ENDPOINT: Final = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: Deterministic decoding. Two runs over one capture should ask the same question and, as far
#: as the service allows, get the same answer; the claims are then replayable from the stored
#: bytes rather than from a second call that may differ.
_TEMPERATURE: Final = 0.0

#: Thinking off, and stated rather than left to the server.
#:
#: Two reasons. The setting is part of what produced an answer, and a default that the vendor
#: can change underneath us is a setting this repository did not choose; naming it means a
#: week coded today and a week coded in March were asked the same way. And on these models
#: thinking tokens count against ``maxOutputTokens``, so an unstated budget spends the ceiling
#: that the claims need and turns a good answer into a truncation refusal.
_THINKING_BUDGET: Final = 0

#: Finish reasons that mean the model declined rather than answered. A declined request has no
#: claims in it and must not be recorded as a week in which nobody was mentioned.
_DECLINED: Final = frozenset({"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"})


class ClubNewsGeminiError(ClubNewsError):
    """This adapter could not turn one club's documents into a recorded answer."""


class Transport(Protocol):
    """The one call this adapter makes, narrow enough for a test to implement in ten lines."""

    def post(
        self, url: str, *, headers: Mapping[str, str], json: Mapping[str, object], timeout: float
    ) -> "Reply": ...


class Reply(Protocol):
    """What a transport returns: a status, and a body that may or may not be JSON."""

    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> object: ...


def gemini_schema(schema: Mapping[str, object]) -> dict[str, object]:
    """The contract's JSON Schema in the subset this API accepts.

    Two differences, both mechanical. The API's schema dialect has no ``additionalProperties``,
    so the closed-object constraint is dropped here and kept where it was always enforced: the
    parser refuses a key it does not know, whatever the request asked for. And a nullable field
    is ``nullable: true`` beside a single type rather than a union, so ``["string", "null"]``
    becomes ``{"type": "string", "nullable": true}``.

    Translating rather than maintaining a second copy is the point. The vocabularies are
    generated into ``response_schema`` so they cannot drift from the parser; a hand-written
    schema here would reintroduce exactly the drift that one avoids.
    """

    translated: dict[str, object] = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, list):
            types = [str(entry) for entry in value]
            concrete = [entry for entry in types if entry != "null"]
            if len(concrete) != 1:
                raise ClubNewsGeminiError(
                    f"A schema type of {types!r} has no single concrete type, so it cannot be "
                    "expressed as one type with a nullable flag."
                )
            translated["type"] = concrete[0]
            if "null" in types:
                translated["nullable"] = True
            continue
        if isinstance(value, Mapping):
            translated[key] = gemini_schema(value)
            continue
        if isinstance(value, list):
            translated[key] = [
                gemini_schema(entry) if isinstance(entry, Mapping) else entry for entry in value
            ]
            continue
        translated[key] = value
    return translated


def _checked_key(api_key: str) -> str:
    """The key, or a refusal that does not repeat it.

    Only the ends are stripped, because an interior space is as unsendable as a leading one
    and silently deleting it would change the secret rather than reject it. The refusal names
    the likely cause and quotes nothing: a message that echoed the key to explain why it was
    wrong would put it exactly where this check exists to keep it out of.
    """

    candidate = str(api_key).strip()
    if not candidate:
        return ""
    if not _HEADER_SAFE.fullmatch(candidate):
        raise ClubNewsGeminiError(
            "The API key holds a character that cannot travel in an HTTP header: a space, a "
            "line break or a byte outside printable ASCII. A key file with a trailing line "
            "break that was read whole, or a paste that wrapped, is the usual cause. The key "
            "is not quoted here on purpose."
        )
    return candidate


def _transport_error_types() -> tuple[type[BaseException], ...]:
    """The transport's own failures, looked up rather than imported at module load.

    ``httpx2`` is an optional install, so this returns nothing when it is absent and the
    ``except`` below simply catches nothing. A test that hands in its own transport can still
    raise a real ``httpx2`` error and be caught, which is what makes that test worth having.
    """

    try:
        import httpx2
    except ImportError:
        return ()
    return (httpx2.HTTPError,)


class GeminiClubNewsProvider:
    """Codes club documents by asking the Generative Language API.

    ``fetch`` is not implemented, for the reason the first adapter gives: reading a club's page
    is its own deliverable with its own terms-of-use question, and a provider that quietly
    acquired that ability would let a caller reach the open internet by asking for a model
    call.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_identifier: str = DEFAULT_GEMINI_MODEL,
        transport: Transport | None = None,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Build a transport, or accept one.

        A supplied ``transport`` skips the key entirely, which is what makes the tests offline:
        a test that needed a key would not be one. The key and the model identifier arrive as
        parameters rather than environment reads so this object states what it was given, and
        so the identifier recorded in the capture is the one actually asked for.
        """

        if not _MODEL_SAFE.fullmatch(str(model_identifier)):
            raise ClubNewsGeminiError(
                f"{model_identifier!r} is not a model identifier this adapter can ask for: it "
                "may hold letters, digits, dots, underscores and hyphens only. The name goes "
                "into the request path, and one this client cannot build would escape as a "
                "traceback rather than as a refused club."
            )
        self._model_identifier = model_identifier
        self._timeout = timeout
        self._api_key = "" if api_key is None else _checked_key(api_key)
        self._owns_transport = transport is None
        if transport is not None:
            self._transport: Transport = transport
            return
        if not self._api_key:
            raise ClubNewsGeminiError(
                "This provider needs an API key. It is read from the environment by "
                "`club_news_provider` and never committed, so a checkout alone cannot code a "
                "week's club news; the fixture provider is what runs without one."
            )
        try:
            import httpx2
        except ImportError as error:
            raise ClubNewsGeminiError(
                "Coding club news with this provider needs httpx2, which is not a runtime "
                "dependency of this project (install it with the 'llm' extra: pip install -c "
                f"constraints.txt -e '.[llm]'): {error}"
            ) from error

        self._transport = httpx2.Client(timeout=timeout)

    def close(self) -> None:
        """Release the HTTP client this provider built, if it built one.

        A supplied transport belongs to whoever supplied it and is left alone. A week's run
        codes twenty clubs through one provider and then ends, so the pool would be collected
        eventually; saying when is cheaper than relying on that, and a test that builds a real
        client can leave nothing behind.
        """

        closer = getattr(self._transport, "close", None)
        if self._owns_transport and callable(closer):
            closer()

    def fetch(self, url: str) -> RawDocument:
        """Refuse: this provider codes documents, it does not go and get them."""

        raise ClubNewsGeminiError(
            f"This provider does not fetch {url!r}. It implements coding only; fetching a "
            "club's page is a separate provider with a separate terms-of-use record, and "
            "merging the two would let a model call reach the open internet."
        )

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        """Ask the model to code these documents, and return what it said, unparsed.

        The text comes back verbatim. Locating the quotes and validating the vocabularies are
        ``locate_claim_response`` and ``parse_claim_response``, both pure and both replayable
        over these bytes. Anything interpreted here would be an interpretation that only ever
        happened once, at a moment with a network.
        """

        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {"role": "user", "parts": [{"text": build_user_content(documents, roster)}]}
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": gemini_schema(response_schema()),
                "maxOutputTokens": MAX_OUTPUT_TOKENS,
                "temperature": _TEMPERATURE,
                "thinkingConfig": {"thinkingBudget": _THINKING_BUDGET},
            },
        }
        try:
            return self._ask(body)
        except ClubNewsGeminiError as error:
            raise self._scrubbed(error) from None

    def _ask(self, body: Mapping[str, object]) -> ClaimResponse:
        """The call itself, so every refusal it can raise passes one scrubber on the way out."""

        try:
            reply = self._transport.post(
                _ENDPOINT.format(model=self._model_identifier),
                headers={KEY_HEADER: self._api_key, "Content-Type": "application/json"},
                json=body,
                timeout=self._timeout,
            )
        except _transport_error_types() as error:
            # The type only. A transport error's message can quote the request it failed on,
            # headers included, and one club's timeout must not be the thing that writes the
            # key into the run log. With no retry here the week loses this club and keeps the
            # rest, which is the failure the per-club unit exists for.
            raise ClubNewsGeminiError(
                f"The request did not complete ({type(error).__name__})."
            ) from None
        return _claim_response(reply, asked_for=self._model_identifier)

    def _scrubbed(self, error: ClubNewsGeminiError) -> ClubNewsGeminiError:
        """The same refusal with the key taken out of it, whatever put it there.

        A second layer rather than the only one. Every refusal this adapter raises is written
        not to carry the key, and this is here because one of them is assembled from text a
        remote service wrote: the first line of defence is a rule somebody has to keep, and
        this one holds even when they do not.
        """

        text = str(error)
        if self._api_key and self._api_key in text:
            return ClubNewsGeminiError(text.replace(self._api_key, "[key withheld]"))
        return error


def _why(reply: Reply) -> str:
    """The service's own status code, and nothing else it wrote.

    An earlier version quoted ``error.message`` as well, on the reasoning that a service
    describing itself is safer than a body a gateway may have filled. It is not. That message
    is free text from a remote system, it can name the credential it is complaining about
    ("Consumer 'api_key:...' has been suspended"), and it lands in the refused tuple that
    ``club_news_acquire`` prints. A status like ``PERMISSION_DENIED`` says what to do about it;
    the sentence after it is not ours to vouch for.
    """

    try:
        document = reply.json()
    except (ValueError, json.JSONDecodeError):
        return ""
    error = document.get("error") if isinstance(document, Mapping) else None
    if not isinstance(error, Mapping):
        return ""
    status = error.get("status")
    return f" ({status})" if isinstance(status, str) and status.strip() else ""


def _payload(reply: Reply) -> Mapping[str, Any]:
    """The reply's body as an object, or a refusal that quotes what arrived instead.

    A transport error and a service that answered with prose are different facts, and the
    second one is the one a rate limit or an expired key usually looks like.
    """

    status = reply.status_code
    if status == 429:
        raise ClubNewsGeminiError(
            "The service answered 429: the rate limit was reached. The week records no "
            "disposition for this club rather than being retried until it answers, because a "
            "free tier's limit is a fact about the run and not a transient to paper over."
        )
    if status != 200:
        raise ClubNewsGeminiError(f"The service answered {status} rather than 200{_why(reply)}.")
    try:
        document = reply.json()
    except (ValueError, json.JSONDecodeError):
        # The body is not quoted. A gateway can echo the request it rejected, headers and all,
        # and a refusal that pasted the first bytes of that into a log would defeat the point
        # of keeping the key out of the URL.
        raise ClubNewsGeminiError(
            "The response body is not JSON, so it carries no candidate to read."
        ) from None
    if not isinstance(document, Mapping):
        raise ClubNewsGeminiError(
            f"The response body is {type(document).__name__} rather than an object, so it "
            "carries no candidate to read."
        )
    return document


def _claim_response(reply: Reply, *, asked_for: str) -> ClaimResponse:
    """Read one answered request into a :class:`ClaimResponse`, or refuse it.

    The refusals are the first adapter's, in the shapes this API expresses them. A blocked
    prompt and a declined answer both mean the model did not code these documents. A response
    stopped at the output ceiling is truncated JSON, and parsing as much of it as arrived would
    silently drop the players it had not reached. A response with no text at all is not an
    empty answer: an empty answer is a document with an empty ``claims`` array, and the
    difference between those two is the difference this whole lane is built on.
    """

    document = _payload(reply)
    feedback = document.get("promptFeedback")
    if isinstance(feedback, Mapping) and feedback.get("blockReason"):
        raise ClubNewsGeminiError(
            f"The model declined to code these documents (block reason "
            f"{feedback.get('blockReason')!r}). The week records no disposition for these "
            "players rather than being re-run somewhere else until it answers."
        )
    candidates = document.get("candidates")
    if not isinstance(candidates, Sequence) or not candidates or isinstance(candidates, str):
        raise ClubNewsGeminiError(
            "The response carries no candidate, so there is nothing that could be a coded "
            "week; a refused request and an empty answer are different facts and this is "
            "neither."
        )
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        raise ClubNewsGeminiError("The response's first candidate is not an object.")
    finish = candidate.get("finishReason")
    if finish == "MAX_TOKENS":
        raise ClubNewsGeminiError(
            f"The response reached the {MAX_OUTPUT_TOKENS}-token ceiling and is truncated. "
            "Truncated JSON is refused rather than parsed as far as it got, which would drop "
            "whichever players came last."
        )
    if isinstance(finish, str) and finish in _DECLINED:
        raise ClubNewsGeminiError(
            f"The model stopped with {finish!r} rather than finishing its answer, so these "
            "documents were not coded."
        )
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, Mapping) else None
    text = ""
    if isinstance(parts, Sequence) and not isinstance(parts, str):
        # A thinking part is the model working, not the model answering, and folding it into
        # the claims would feed the parser prose it never agreed to read.
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, Mapping) and part.get("thought") is not True
        )
    if not text.strip():
        raise ClubNewsGeminiError(
            f"The response carries no text (finish reason {finish!r}). A week in which the "
            "model said nothing at all is not a week in which it said nobody was mentioned; "
            "the empty answer has a shape and this is not it."
        )
    served = document.get("modelVersion")
    if not isinstance(served, str) or not served.strip():
        raise ClubNewsGeminiError(
            "The response does not name the model that produced it, so the claim could not be "
            "replayed against the same model later."
        )
    return ClaimResponse(text=text, model_identifier=asked_for, model_version=served)


__all__ = [
    "DEFAULT_GEMINI_MODEL",
    "GEMINI_PROVIDER",
    "KEY_HEADER",
    "ClubNewsGeminiError",
    "GeminiClubNewsProvider",
    "Reply",
    "Transport",
    "gemini_schema",
]
