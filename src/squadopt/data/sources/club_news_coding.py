"""What a model is asked for, and how its answer becomes a citation it cannot have written.

A5 left ``ClubNewsProvider.code`` unimplemented and its parser reading a response that
carries **byte offsets** into the fetched document. That is the right shape for a citation
and the wrong thing to ask a model for: a span is arithmetic over UTF-8 bytes, a model
cannot do it reliably, and an off-by-forty span still points *inside* the document, so
``resolve_span`` would happily hand a member the club's words about a different player.
A digest's worth of confidence behind the wrong sentence is worse than no citation.

So the model is never asked to count. It is asked for the sentence, **verbatim**, and this
module finds it:

1. :data:`SYSTEM_PROMPT` asks for ``rotation_claim_coding_v1`` -- the same claims as the
   parser's format, except each one carries a ``quote`` instead of two offsets.
2. :func:`locate_claim_response` searches the fetched bytes for that quote and writes the
   offsets itself. A quote that is absent, or that occurs more than once, is refused.

The second step is pure and offline, so the chain replays: stored model bytes in, the same
located bytes out, the same digest. That is the property the whole lane rests on, and it is
why the model's own text is stored unparsed as its own payload -- asking a model twice does
not reproduce anything.

**Two digests, and what each is a digest of.** :func:`coding_prompt_sha256` fingerprints the
*instrument*: the contract version, the frozen prompt, and the response schema. The sample --
which documents, which roster -- is fingerprinted elsewhere and already in the manifest
(``document_sha256s``, ``roster_snapshot_id``). Mixing the two into one number would mean a
week's prompt digest changed because a club published a longer page, which tells a reader
nothing about whether the question changed.

Nothing here reaches a network or imports a network library. The provider that does lives in
``platform.club_news_model``; this module is what that provider says and what reads it back,
and it is testable with no key, no network and no SDK installed.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_DISPOSITIONS,
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)

#: The coding fixture's own contract, separate from the coding format's: the fixture carries
#: a good response and the ones the locator must refuse, and its shape can change without
#: the format a model is asked for moving.
CODING_FIXTURE_CONTRACT_VERSION: Final = "club_news_coding_fixture_v1"

#: The format the prompt asks for: the parser's format with ``quote`` in place of
#: ``span_start``/``span_end``. Bumped whenever the prompt or the schema below moves, because
#: a response stored under one version was produced by a different question.
ROTATION_CLAIM_CODING_CONTRACT_VERSION: Final = "rotation_claim_coding_v1"

#: The model this lane is written against. Recorded, not defaulted: a response coded by a
#: different model is a different measurement and the manifest has to be able to say so.
CODING_MODEL_IDENTIFIER: Final = "claude-opus-5"

#: How hard the model is asked to think. Sent explicitly rather than left to the server's
#: default, for the same reason the prompt is a constant: an instrument whose settings can be
#: changed underneath it is not frozen, and a week coded at one effort is not the same
#: measurement as a week coded at another.
CODING_EFFORT: Final = "high"

#: The context window of the model named above, in tokens. Written down here rather than
#: looked up at call time because the budget below is derived from it, and a budget whose
#: basis can move without anyone noticing is not a budget.
CODING_CONTEXT_TOKENS: Final = 1_000_000

#: Bytes assumed per input token, deliberately pessimistic. English prose runs nearer four
#: bytes to the token; markup, character entities and attribute soup tokenise far worse, and
#: a page's worst case is what a guard has to hold. The number this budget is honest about
#: estimating: an exact count is only knowable from the tokeniser, and the endpoint that
#: knows it is itself a network call, so it cannot be the thing that stops a request from
#: being made. Nothing is reserved for the output ceiling -- sixteen thousand tokens against
#: a million-token window is inside the rounding this estimate already carries.
CODING_BYTES_PER_TOKEN: Final = 2

#: The most one call's documents and roster may come to, in UTF-8 bytes. Refused by
#: :func:`build_user_content` **before** a request is assembled, which is the whole point:
#: a week's pages are fetched on a deadline, and discovering that the call cannot fit only
#: when the API rejects it spends the pages, the clock and nothing else.
#:
#: This is not the fetch adapter's ``MAXIMUM_DOCUMENT_BYTES`` and does not replace it. That
#: one caps a single response so an adapter cannot be made to read a stream of arbitrary
#: length; this one caps the *assembled call*, which is where the real hazard is: one call
#: carrying twenty clubs' pages is twenty times a document the other cap thought was fine.
MAXIMUM_USER_CONTENT_BYTES: Final = CODING_CONTEXT_TOKENS * CODING_BYTES_PER_TOKEN

#: The frozen question. A versioned constant in the repository, not a string assembled at
#: request time: the only thing that varies between two weeks' calls is the documents and the
#: roster, so the digest of this text is a fact about the instrument rather than about a week.
#:
#: Every rule here exists because something downstream refuses without it. The closed
#: vocabularies are the parser's. "One entry per player" is the parser's refusal of two
#: claims about one player, turned into an instruction so a genuine format breach stays
#: distinguishable from a model listing two sentences about the same man. The ban on
#: percentages, likelihoods and scores is the lane's: there is no probability in this
#: pipeline, not even internally, so there is nowhere for one to be written down.
SYSTEM_PROMPT: Final = """\
You are coding football club announcements into a fixed, closed set of statements about \
whether named players are expected to play. You are not predicting anything and you are not \
being asked to. You report only what the supplied documents say.

You will be given one or more documents, each with a URL, and a roster of players with their \
club. Read only those documents. You have no other sources, no search and no browsing; if a \
document does not say something, it is not said.

Return one JSON object in the rotation_claim_coding_v1 format and nothing else.

For each document, report its own dateline -- what the document says about when it was \
published:
- published_precision "instant" with published_at_utc as an ISO-8601 UTC timestamp, when the \
document gives a time of day.
- published_precision "day" with published_at_utc as a bare calendar date (YYYY-MM-DD), when \
the document dates itself to a day and no finer. Never invent a time of day.
- published_precision "unknown" with published_at_utc null, when the document does not date \
itself. Absent is a precision; do not fill it in from anything else.

For each roster player a document says something about, return exactly one claim. One entry \
per player, never two: if the documents carry statements that pull in different directions \
about the same player, code that player once as "ambiguous". Use the player_name and \
team_name exactly as the roster spells them, so the claim can be joined back to him.

The disposition vocabulary is closed. Choose the one that fits; never invent a value and \
never pick the nearest sounding one for something the document did not say:
- "stated_expected_to_start" -- the document says he is expected to play or start.
- "stated_expected_absent" -- the document says he will not play, is out, or will not travel.
- "stated_rotation_risk" -- the document says he may be rested or rotated.
- "stated_returning_from_injury" -- the document says he is back in training or available \
again after an injury, without saying he will start.
- "stated_minutes_limited" -- the document says his involvement will be partial or managed.
- "no_statement" -- the document mentions him or the question was raised, and no disposition \
was given.
- "ambiguous" -- the document addresses him but the statements do not settle on one of the \
above, or they conflict.
Do not return "not_addressed"; a player no document mentions is simply left out, and the \
pipeline records that absence itself.

The speaker vocabulary is closed and is a role, never a person's name: "manager", \
"club_official", "club_statement", "unattributed".

Every claim must carry:
- source_url: the URL of the document it came from, exactly as given.
- quote: a span of the document copied **verbatim**, character for character, including its \
punctuation and any per-cent sign or quotation mark inside it. It must appear in that \
document exactly once, so prefer a whole sentence to a fragment. Do not normalise, \
translate, correct, shorten or paraphrase it. This string is matched against the document's \
bytes and a quote that is not found there, or is found twice, is rejected outright.
- paraphrase: one short sentence in your own words. It is used for review and is discarded \
before anything is stored.

Never write a probability, percentage, likelihood, chance, confidence or score, in any \
field, in any form -- not as a number, not in words. If a document itself contains a figure, \
it may appear inside a verbatim quote and nowhere else. There is no numeric output in this \
format.

If the documents support no claim at all, return the object with an empty claims array. An \
empty answer is a real answer; a guess is not.
"""

_CODING_CLAIM_KEYS: Final[tuple[str, ...]] = (
    "player_name",
    "team_name",
    "disposition",
    "speaker",
    "source_url",
    "quote",
    "paraphrase",
)

#: The dispositions the prompt may return. ``not_addressed`` is the pipeline's own word for a
#: player nobody wrote about, so a model that returns it is describing a silence it cannot
#: observe -- it only ever saw the documents that arrived.
CODING_DISPOSITIONS: Final[tuple[str, ...]] = tuple(
    disposition for disposition in ROTATION_DISPOSITIONS if disposition != "not_addressed"
)


def response_schema() -> dict[str, object]:
    """The JSON Schema the request enforces, built from the vocabularies it must agree with.

    Generated rather than written out, so the enumerations cannot drift from the tuples the
    parser validates against: a disposition added in one place and forgotten in the other
    would show up as a refused week instead of a failed import.

    Structured output is a second belt, not the buckle. It constrains the shape; it cannot
    know whether a quote is in the document or whether a dateline was invented, which is what
    :func:`locate_claim_response` and the parser are for.
    """

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["contract_version", "documents", "claims"],
        "properties": {
            "contract_version": {
                "type": "string",
                "enum": [ROTATION_CLAIM_CODING_CONTRACT_VERSION],
            },
            "documents": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["url", "published_at_utc", "published_precision"],
                    "properties": {
                        "url": {"type": "string"},
                        "published_at_utc": {"type": ["string", "null"]},
                        "published_precision": {
                            "type": "string",
                            "enum": list(PUBLISHED_PRECISIONS),
                        },
                    },
                },
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(_CODING_CLAIM_KEYS),
                    "properties": {
                        "player_name": {"type": "string"},
                        "team_name": {"type": "string"},
                        "disposition": {"type": "string", "enum": list(CODING_DISPOSITIONS)},
                        "speaker": {"type": "string", "enum": list(CLAIM_SPEAKERS)},
                        "source_url": {"type": "string"},
                        "quote": {"type": "string"},
                        "paraphrase": {"type": "string"},
                    },
                },
            },
        },
    }


def coding_prompt_sha256() -> str:
    """Fingerprint the instrument: the contract, the frozen prompt and the schema.

    Canonical JSON with sorted keys, because a digest that moved when a dictionary happened
    to iterate differently would be recording nothing. The model identifier is in here too:
    the same words put to a different model are a different question.
    """

    envelope = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "effort": CODING_EFFORT,
        "model_identifier": CODING_MODEL_IDENTIFIER,
        "system_prompt": SYSTEM_PROMPT,
        "response_schema": response_schema(),
    }
    canonical = json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_user_content(documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]) -> str:
    """Lay out one call's documents and roster, deterministically.

    Deterministic in the strong sense: the same documents and roster produce the same bytes,
    so two calls a week apart differ only where the inputs differ. Documents keep the order
    they were fetched in -- that order is the caller's decision and reordering them here
    would make the request depend on this function's taste -- while the roster is sorted by
    the identity a claim is joined on, so a reshuffled squad list is not a changed question.

    The document is inserted as decoded text. A document whose bytes are not UTF-8 is refused
    rather than replaced with question marks: the model would be quoting characters that are
    not in the bytes the quote is later matched against.

    A call larger than :data:`MAXIMUM_USER_CONTENT_BYTES` is refused here, before anything is
    sent. The refusal names the size, the budget and the documents, because the remedy is the
    caller's -- ask about fewer clubs in one call -- and an operator on a deadline needs to
    know which of the two it is.
    """

    if not documents:
        raise ClubNewsError("Nothing to code: no document was read.")
    if not roster:
        raise ClubNewsError("Nothing to code against: the roster is empty.")

    parts: list[str] = ["# Roster", ""]
    for player in sorted(roster, key=lambda entry: (entry.team_name, entry.web_name)):
        parts.append(f"- {player.web_name} ({player.team_name})")
    parts.append("")
    parts.append("# Documents")
    for document in documents:
        try:
            text = document.content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ClubNewsError(
                f"{document.requested_url} is not UTF-8 ({error}). It is not offered to the "
                "model, because a quote taken from a lossy decoding would not be found in "
                "the bytes it has to be matched against."
            ) from error
        parts.append("")
        parts.append(f"## {document.final_url}")
        parts.append("")
        parts.append(text)
    content = "\n".join(parts) + "\n"

    size = len(content.encode("utf-8"))
    if size > MAXIMUM_USER_CONTENT_BYTES:
        raise ClubNewsError(
            f"One call's {len(documents)} document(s) and {len(roster)} roster entries come "
            f"to {size} UTF-8 bytes, over the {MAXIMUM_USER_CONTENT_BYTES}-byte budget for a "
            f"{CODING_CONTEXT_TOKENS}-token window. Refused before the request is sent: ask "
            "about fewer clubs in one call rather than spending the week's pages on a "
            "request that cannot fit."
        )
    return content


def _object(text: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ClubNewsError(
            f"The coding response is not JSON: {error}. It is refused rather than read as prose."
        ) from error
    if not isinstance(parsed, dict):
        raise ClubNewsError(
            f"The coding response must be a JSON object, got {type(parsed).__name__}."
        )
    return parsed


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ClubNewsError(f"{label} must be a JSON object, got {type(value).__name__}.")
    return value


def _list(document: Mapping[str, object], key: str) -> list[object]:
    value = document.get(key)
    if not isinstance(value, list):
        raise ClubNewsError(
            f"The coding response field {key!r} must be an array, got {type(value).__name__}."
        )
    return value


def _text(record: Mapping[str, object], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ClubNewsError(f"{label} field {key!r} must be non-empty text, got {value!r}.")
    return value


def _quoted_bytes(documents: Sequence[RawDocument]) -> dict[str, bytes]:
    """Index the fetched bytes by every URL a coding response may name.

    Both URLs per document, for the same reason the parser does it: a redirect gives the page
    two addresses and the model was shown the final one while the caller asked for the other.
    """

    indexed: dict[str, bytes] = {}
    for document in documents:
        for url in (document.requested_url, document.final_url):
            existing = indexed.get(url)
            if existing is not None and existing != document.content:
                raise ClubNewsError(
                    f"Two fetched documents answer for {url!r} with different bytes; a quote "
                    "could be located in either."
                )
            indexed[url] = document.content
    return indexed


def locate_quote(content: bytes, quote: str, label: str) -> tuple[int, int]:
    """Return the byte span of ``quote`` in ``content``, or refuse.

    Exactly one occurrence is required, and that is the whole discipline. Zero means the
    model did not copy the document -- it normalised a dash, dropped a comma, or wrote the
    sentence it remembered -- and a claim whose citation cannot be found is not weakened, it
    is unfounded. More than one means the offsets would be a coin toss between two places in
    the page, and a citation that might point at either is not a citation.

    Searched as bytes so that a quote containing anything outside ASCII lands on the same
    offsets the artifact stores and ``resolve_span`` later re-reads.

    **Occurrences are counted with overlap, and ``bytes.count`` cannot do it.** It counts
    non-overlapping matches, so ``b"aaa".count(b"aa")`` is 1 while ``b"aa"`` in fact starts
    at both 0 and 1. That is not a corner case dressed up as one: a club writing "he was
    laughing, ha ha ha" gives ``"ha ha"`` two starts, and the old check called that unique
    and took the first. A citation silently chosen between two candidates is exactly what
    this function exists to refuse, so the scan advances one byte past each hit rather than
    one match length.
    """

    needle = quote.encode("utf-8")
    if not needle:
        raise ClubNewsError(f"{label} carries an empty quote; there is nothing to locate.")
    starts: list[int] = []
    position = content.find(needle)
    while position != -1:
        starts.append(position)
        position = content.find(needle, position + 1)
    occurrences = len(starts)
    if occurrences == 0:
        raise ClubNewsError(
            f"{label} quotes {quote[:60]!r}, which does not appear in the document it cites. "
            "The quote has to be verbatim: a citation that cannot be found in the bytes is "
            "not a weaker citation, it is an unfounded one."
        )
    if occurrences > 1:
        raise ClubNewsError(
            f"{label} quotes {quote[:60]!r}, which starts at {starts} in the document it "
            "cites. The span would be a choice between them, so it is refused rather than "
            "taken from the first. Overlapping starts count: two of these may share bytes."
        )
    start = starts[0]
    return start, start + len(needle)


def locate_claim_response(
    response: ClaimResponse, documents: Sequence[RawDocument]
) -> ClaimResponse:
    """Turn one stored coding response into the parser's format, byte for byte.

    Pure: same response, same documents, same output text, same digest. That is what lets
    the week be replayed from the stored payloads with the network unplugged.

    The identity travels through unchanged. The located response is a *rendering* of what the
    model said, not a second opinion about it, so it must not be able to claim a different
    model produced it.

    What this does **not** do is check the claims. The dateline pairing, the closed
    vocabularies, the duplicate-player refusal and the span bounds all belong to
    ``parse_claim_response``, which owns them for every response however it arrived. Checking
    them here as well would put the same rule in two places and let the copies disagree.
    """

    if not documents:
        raise ClubNewsError(
            "Locating needs the fetched documents: a quote becomes a span only inside the "
            "bytes it was copied from."
        )
    document = _object(response.text)
    version = document.get("contract_version")
    if version != ROTATION_CLAIM_CODING_CONTRACT_VERSION:
        raise ClubNewsError(
            f"The coding response declares contract {version!r}, not "
            f"{ROTATION_CLAIM_CODING_CONTRACT_VERSION!r}. A response produced under one "
            "prompt version is not readable under another."
        )
    available = _quoted_bytes(documents)

    located: list[dict[str, object]] = []
    for entry in _list(document, "claims"):
        record = _mapping(entry, "A coded claim")
        missing = [key for key in _CODING_CLAIM_KEYS if key not in record]
        if missing:
            raise ClubNewsError(f"A coded claim is missing required field(s) {missing!r}.")
        player_name = _text(record, "player_name", "A coded claim")
        label = f"The claim about {player_name!r}"
        source_url = _text(record, "source_url", label)
        content = available.get(source_url)
        if content is None:
            raise ClubNewsError(
                f"{label} cites {source_url!r}, which is not among the fetched documents; "
                "there are no bytes to locate its quote in."
            )
        span_start, span_end = locate_quote(content, _text(record, "quote", label), label)
        located.append(
            {
                "player_name": player_name,
                "team_name": _text(record, "team_name", label),
                "disposition": _text(record, "disposition", label),
                "speaker": _text(record, "speaker", label),
                "source_url": source_url,
                "span_start": span_start,
                "span_end": span_end,
                "paraphrase": _text(record, "paraphrase", label),
            }
        )

    parsed_text = json.dumps(
        {
            "contract_version": ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
            "documents": _list(document, "documents"),
            "claims": located,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return ClaimResponse(
        text=parsed_text,
        model_identifier=response.model_identifier,
        model_version=response.model_version,
    )


@dataclass(frozen=True, slots=True)
class UnlocatableCase:
    """One coding response the locator must refuse, and why it must.

    The reason travels with the response so a failing test can say which hazard stopped
    being caught, rather than only that one of five did.
    """

    response: ClaimResponse
    why: str


class CodingFixture:
    """The committed synthetic coding response, and the ones that must be refused.

    Authored against ``club_news_v1.fixture.json``: every quote here is a verbatim span of a
    document in that file, and locating this response reproduces the claims that file already
    carries in located form. That is the strongest offline check there is on this pair --
    the two halves of the fixture agree, and neither was written to match the other by hand.

    The refusals live beside the good response for the same reason A5's unparseable ones do:
    "the shape the locator does not accept" is a property of the format, and a copy of it
    inside a test file would drift away from the format it is meant to violate. The five here
    are the ones a real model actually produces -- a quote it tidied, a fragment that matches
    twice, a page it did not read, a version bump, a missing field.
    """

    def __init__(self, fixture_path: Path | str) -> None:
        self._path = Path(fixture_path)
        self._document = self._load()

    def _load(self) -> Mapping[str, object]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise ClubNewsError(
                f"Cannot read the coding fixture at {self._path}: {error}"
            ) from error
        document = _object(raw)
        version = document.get("contract_version")
        if version != CODING_FIXTURE_CONTRACT_VERSION:
            raise ClubNewsError(
                f"{self._path} declares contract {version!r}, not "
                f"{CODING_FIXTURE_CONTRACT_VERSION!r}."
            )
        _mapping(document.get("response"), f"{self._path} 'response'")
        return document

    @property
    def documents_fixture(self) -> str:
        """The fixture whose documents these quotes were copied from, by file name.

        Named in the data rather than assumed by the reader: a quote is only verbatim with
        respect to particular bytes, and a coding fixture pointed at the wrong document set
        would fail as a mystery instead of as a mismatch.
        """

        return _text(self._document, "documents_fixture", str(self._path))

    def response(self) -> ClaimResponse:
        """The coding response a model would have produced for those documents."""

        record = _mapping(self._document.get("response"), "The coding fixture response")
        label = "The coding fixture response"
        return ClaimResponse(
            text=_text(record, "text", label),
            model_identifier=_text(record, "model_identifier", label),
            model_version=_text(record, "model_version", label),
        )

    def unlocatable_responses(self) -> tuple[UnlocatableCase, ...]:
        """Every response the locator must refuse, each with the reason it must."""

        declared = self._document.get("unlocatable_responses")
        if not isinstance(declared, list) or not declared:
            raise ClubNewsError(
                f"{self._path} must declare a non-empty 'unlocatable_responses' array; a "
                "fixture that documents no refusal documents half a format."
            )
        cases: list[UnlocatableCase] = []
        for entry in declared:
            record = _mapping(entry, "A coding fixture refusal")
            label = "A coding fixture refusal"
            cases.append(
                UnlocatableCase(
                    response=ClaimResponse(
                        text=_text(record, "text", label),
                        model_identifier="synthetic-stub",
                        model_version="fixture-1",
                    ),
                    why=_text(record, "why", label),
                )
            )
        return tuple(cases)


__all__ = [
    "CODING_BYTES_PER_TOKEN",
    "CODING_CONTEXT_TOKENS",
    "CODING_DISPOSITIONS",
    "CODING_EFFORT",
    "CODING_FIXTURE_CONTRACT_VERSION",
    "CODING_MODEL_IDENTIFIER",
    "MAXIMUM_USER_CONTENT_BYTES",
    "ROTATION_CLAIM_CODING_CONTRACT_VERSION",
    "SYSTEM_PROMPT",
    "CodingFixture",
    "UnlocatableCase",
    "build_user_content",
    "coding_prompt_sha256",
    "locate_claim_response",
    "locate_quote",
    "response_schema",
]
