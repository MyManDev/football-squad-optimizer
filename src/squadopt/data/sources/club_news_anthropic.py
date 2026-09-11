"""The one place in this repository that calls a model, and everything it refuses to do.

A5 built the whole rotation lane behind a stub, so the identity join, the evidence artifact
and the weekly step were all finished and tested before a key existed. This module is the
other half of that seam: it implements ``ClubNewsProvider.code`` against the real API and
changes nothing else. Every test downstream of it still runs offline, because none of them
go through here.

**What it does not do, listed because each one is a decision:**

- *No tools.* No web search, no fetch, no code execution. The request carries no ``tools``
  key at all, so the model answers from the documents it was handed and nothing else. A
  model that could fetch the page itself would make the digest in the manifest a fiction:
  the bytes we hashed would no longer be the bytes it read.
- *No fallback model.* A policy decline is recorded as "no disposition for these players",
  which is a state this lane already carries honestly all the way to the card. Quietly
  re-running the week on a second model would make one week's claims a mixture while the
  manifest names a single model.
- *No credential guessing.* The SDK resolves a key, an auth token or a saved login profile
  on its own; this reads one named variable and passes it explicitly. Which credential
  answered is part of a week's provenance, and it should not depend on what happened to be
  in the environment.
- *No retry on a refused response.* A response the parser rejects is a finding, not a
  transport failure. Asking again until the answer parses is how a pipeline starts selecting
  its own evidence.
- *No prompt caching.* One call per club per week is not a cache-hit pattern worth the
  request-shape change, and the shape has to be replayable byte for byte.

**The SDK is an optional install.** ``anthropic`` is declared in the ``llm`` extra (and in
``dev``, so the gates typecheck this file), not in the runtime dependencies. It is imported
inside the constructor and a missing install is reported as a club-news problem naming the
extra, following ``load_parquet``'s handling of an absent Parquet engine.
"""

import os
from collections.abc import Mapping, Sequence
from typing import Any, Final, Protocol

from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import (
    CODING_EFFORT,
    CODING_MODEL_IDENTIFIER,
    SYSTEM_PROMPT,
    build_user_content,
    response_schema,
)

#: The one variable read. The SDK's own default name, so an operator who has already set it
#: needs nothing further -- but read here rather than left to the SDK, because implicit
#: resolution has three sources and a week's provenance should not depend on which one won.
API_KEY_ENVIRONMENT_VARIABLE: Final = "ANTHROPIC_API_KEY"

#: Output ceiling for one club's coding, and the reason the call does not stream. A club's
#: page plus a squad list is a few thousand input tokens and its claims a few thousand out,
#: so neither end is long; sixteen thousand is the documented ceiling below which a single
#: request will not hit an HTTP timeout, and one unstreamed request is a far simpler shape to
#: freeze and to replay than a stream. A response that reaches this limit is refused below
#: rather than parsed as far as it got: half a JSON document is not a partial answer.
MAX_OUTPUT_TOKENS: Final = 16_000

#: Transport retries only, and left to the SDK: it already backs off on connection errors,
#: 429 and 5xx. Four rather than the default two because this call sits on a deadline and a
#: rate limit an hour before it is not a reason to lose the week.
MAX_TRANSPORT_RETRIES: Final = 4

#: Seconds allowed for one attempt, written down because **retries multiply it**. The SDK's
#: default is ten minutes and a timeout is itself retried, so the four retries above would
#: have made the worst case fifty minutes of wall clock -- on a call whose whole reason for
#: having extra retries is that it sits in front of a deadline. Three minutes times five
#: attempts is fifteen, which is a delay an operator can absorb and still act on. It is
#: generous for the work itself: one club's page and a squad list is a few thousand tokens
#: in and a few thousand out.
REQUEST_TIMEOUT_SECONDS: Final = 180.0


class ClubNewsModelError(ClubNewsError):
    """The model could not be asked, or did not answer in a form worth storing."""


class MessagesResource(Protocol):
    """The one method this module calls, named so a test can stand in for it.

    Narrow on purpose. The SDK's own resource satisfies it structurally -- that is what makes
    it a usable annotation rather than a description -- and a recorder in a test satisfies it
    too, which is how the assembled request is asserted on with no key and no network. The
    argument types are deliberately loose: this protocol exists to pin down *which* arguments
    are passed, and the SDK's generated parameter types are what check that they are
    well-formed.
    """

    def create(
        self,
        *,
        model: str,
        max_tokens: int,
        system: Any,
        messages: Any,
        output_config: Any,
    ) -> Any: ...


class CodingClient(Protocol):
    """A client that can be asked to code, whether it is the SDK's or a test's."""

    @property
    def messages(self) -> MessagesResource: ...


def read_api_key(environ: Mapping[str, str] | None = None) -> str:
    """Return the API key, or refuse by name.

    ``environ`` is injectable so tests never touch the real environment. The refusal names
    the variable and says what it is for, in the house style of ``BackendConfig``'s reader --
    which this deliberately does not reuse: that reader lives in ``squadopt.platform`` and
    ``squadopt.data`` is the bottom layer, so importing it would invert the layering the
    import contract exists to hold.
    """

    source = os.environ if environ is None else environ
    key = source.get(API_KEY_ENVIRONMENT_VARIABLE, "").strip()
    if not key:
        raise ClubNewsModelError(
            f"{API_KEY_ENVIRONMENT_VARIABLE} is unset. The key is read from the environment "
            "and is never committed, so a checkout alone cannot code a week's club news; "
            "the fixture provider is what runs without one."
        )
    return key


class AnthropicClubNewsProvider:
    """Codes club documents by calling the model named in the coding contract.

    ``fetch`` is not implemented here. Reading a club's page is its own deliverable with its
    own terms-of-use question, and a provider that quietly acquired that ability would let a
    caller reach the open internet by asking for a model call. The two halves of the protocol
    are composed by the caller, not merged here.
    """

    _client: CodingClient

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        client: CodingClient | None = None,
    ) -> None:
        """Build a client, or accept one.

        ``client`` exists so the request this class assembles can be inspected offline: the
        tests pass a recorder and assert on what would have been sent -- that the prompt is
        the frozen constant, that no tools are attached, that the model is the one the
        contract names. Handing in a client skips the key entirely, which is the point; a
        test that needed a key would not be an offline test.
        """

        if client is not None:
            self._client = client
            return
        api_key = read_api_key(environ)
        try:
            import anthropic
        except ImportError as error:
            raise ClubNewsModelError(
                "Coding club news needs the anthropic SDK, which is not a runtime dependency "
                "of this project (install it with the 'llm' extra: pip install -c "
                f"constraints.txt -e '.[llm]'): {error}"
            ) from error
        self._client = anthropic.Anthropic(
            api_key=api_key,
            max_retries=MAX_TRANSPORT_RETRIES,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def fetch(self, url: str) -> RawDocument:
        """Refuse: this provider codes documents, it does not go and get them."""

        raise ClubNewsModelError(
            f"This provider does not fetch {url!r}. It implements coding only; fetching a "
            "club's page is a separate provider with a separate terms-of-use record, and "
            "merging the two would let a model call reach the open internet."
        )

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        """Ask the model to code these documents, and return what it said, unparsed.

        The text comes back verbatim. It is not located, not validated against the closed
        vocabularies and not turned into claims here: those are
        ``locate_claim_response`` and ``parse_claim_response``, both pure and both replayable
        over the bytes this returns. Anything this method interpreted would be an
        interpretation that only ever happened once, at a moment with a network.

        ``model_identifier`` is what was asked for and ``model_version`` is what answered.
        They are recorded separately because a request naming an alias can be served by a
        snapshot, and "which model produced this claim" has to survive that.
        """

        user_content = build_user_content(documents, roster)
        message = self._client.messages.create(
            model=CODING_MODEL_IDENTIFIER,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_config={
                "effort": CODING_EFFORT,
                "format": {"type": "json_schema", "schema": response_schema()},
            },
        )
        return _claim_response(message)


def _claim_response(message: object) -> ClaimResponse:
    """Read one finished message into a :class:`ClaimResponse`, or refuse it.

    Three refusals, in the order they can arise. A declined request has no claims in it and
    must not be recorded as a week in which nobody was mentioned. A response stopped at the
    output ceiling is truncated JSON, and parsing as much of it as arrived would silently
    drop the players the model had not reached yet. A response with no text at all is not an
    empty answer -- an empty answer is a document with an empty ``claims`` array, and the
    difference between those two is the difference this whole lane is built on.
    """

    stop_reason = getattr(message, "stop_reason", None)
    if stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        raise ClubNewsModelError(
            f"The model declined to code these documents (category {category!r}). The week "
            "records no disposition for these players rather than being re-run somewhere "
            "else until it answers."
        )
    if stop_reason == "max_tokens":
        raise ClubNewsModelError(
            f"The response reached the {MAX_OUTPUT_TOKENS}-token ceiling and is truncated. "
            "Truncated JSON is refused rather than parsed as far as it got, which would drop "
            "whichever players came last."
        )
    text = "".join(
        block.text
        for block in getattr(message, "content", ())
        if getattr(block, "type", None) == "text"
    )
    if not text.strip():
        raise ClubNewsModelError(
            f"The response carries no text (stop reason {stop_reason!r}). A week in which "
            "the model said nothing at all is not a week in which it said nobody was "
            "mentioned; the empty answer has a shape and this is not it."
        )
    served = getattr(message, "model", None)
    if not isinstance(served, str) or not served.strip():
        raise ClubNewsModelError(
            "The response does not name the model that produced it, so the claim could not "
            "be replayed against the same model later."
        )
    return ClaimResponse(
        text=text,
        model_identifier=CODING_MODEL_IDENTIFIER,
        model_version=served,
    )


__all__ = [
    "API_KEY_ENVIRONMENT_VARIABLE",
    "MAX_OUTPUT_TOKENS",
    "MAX_TRANSPORT_RETRIES",
    "REQUEST_TIMEOUT_SECONDS",
    "AnthropicClubNewsProvider",
    "ClubNewsModelError",
    "CodingClient",
    "MessagesResource",
    "read_api_key",
]
