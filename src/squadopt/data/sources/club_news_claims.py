"""Turn one stored model response into coded claims, offline and byte for byte.

A6 will call a model; this module never does. It reads the text a response already carries
-- from the snapshot store, from the fixture, from anywhere -- and returns the claims it
declares, or refuses it. That separation is the whole point: re-running this over the same
stored bytes reproduces the same rows, whereas asking a model twice does not.

**No text survives the parse.** :class:`ParsedClaim` deliberately has no paraphrase, quote
or summary field. The response format carries a ``paraphrase`` and this module *validates*
it -- a response that omits it is a different shape and is refused -- but the value is
dropped rather than returned, because the artifact downstream may not carry free text and a
field that exists in memory is a field that ends up in a column eventually. What travels
instead is a **resolvable pointer**: the source document's digest and a byte span into it.
The card resolves those against the locally held snapshot bytes at render time, so a member
sees the club's own words while nothing derived from them stores any.

**The span is checked against the bytes it points into.** A span reaching past the end of
the document it cites would make the citation unresolvable, and an unresolvable citation is
indistinguishable from an invented one. So the documents are required here, not optional.

**Two claims about one player are refused, not resolved.** The artifact has one disposition
per player, and no priority rule between two statements has been declared. Picking the later
dateline, or collapsing a disagreement to ``ambiguous``, would be this module inventing a
rule; refusing names the problem where someone can decide it.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from squadopt.data.sources.club_news import (
    CLAIM_SPEAKERS,
    PUBLISHED_PRECISIONS,
    ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION,
    ROTATION_DISPOSITIONS,
    ClaimResponse,
    ClubNewsError,
    RawDocument,
)
from squadopt.data.timestamps import normalize_utc_timestamp

#: This parser's own contract, separate from the response format's. The response format is
#: what a model is asked to produce; this is what the parser produces from it, and the two
#: can move independently.
CLAIM_PARSE_CONTRACT_VERSION: Final = "rotation_claim_parse_v1"

#: Keys a claim must carry. ``paraphrase`` is required and then discarded -- see the module
#: docstring. A response missing any of these is a different format, not a sparse one.
_CLAIM_KEYS: Final[tuple[str, ...]] = (
    "player_name",
    "team_name",
    "disposition",
    "speaker",
    "source_url",
    "span_start",
    "span_end",
    "paraphrase",
)

#: Keys a declared source document must carry in the response.
_DOCUMENT_KEYS: Final[tuple[str, ...]] = ("url", "published_at_utc", "published_precision")

_INSTANT_PRECISION: Final = "instant"
#: The precision that means "the source dated itself to a day and no finer". Recorded as the
#: bare date, never widened to an instant.
_DAY_PRECISION: Final = "day"
_UNKNOWN_PRECISION: Final = "unknown"


@dataclass(frozen=True, slots=True)
class ParsedClaim:
    """One coded claim, and everything needed to cite it without storing its words.

    ``source_sha256`` is the digest of the document's bytes as fetched, and the span is a
    byte offset pair into those same bytes. Together they are the citation.

    ``published_at_utc`` is what the *source* said about itself, and is ``None`` when it said
    nothing. It is never filled in from the fetch instant: when we looked is our fact, not
    the source's, and substituting one for the other would manufacture a claim about when
    something was known.
    """

    player_name: str
    team_name: str
    disposition: str
    speaker: str
    source_url: str
    source_sha256: str
    span_start: int
    span_end: int
    published_at_utc: str | None
    published_precision: str


@dataclass(frozen=True, slots=True)
class _Dateline:
    """One document's own statement about when it was published."""

    published_at_utc: str | None
    published_precision: str


def _object(text: str) -> Mapping[str, object]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ClubNewsError(
            f"The response is not the declared JSON format: {error}. A response that cannot "
            "be parsed is refused rather than read as prose."
        ) from error
    if not isinstance(parsed, dict):
        raise ClubNewsError(f"The response must be a JSON object, got {type(parsed).__name__}.")
    return parsed


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ClubNewsError(f"{label} must be a JSON object, got {type(value).__name__}.")
    return value


def _list(document: Mapping[str, object], key: str) -> list[object]:
    value = document.get(key)
    if not isinstance(value, list):
        raise ClubNewsError(
            f"The response field {key!r} must be an array, got {type(value).__name__}."
        )
    return value


def _text(record: Mapping[str, object], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ClubNewsError(f"{label} field {key!r} must be non-empty text, got {value!r}.")
    return value.strip()


def _offset(record: Mapping[str, object], key: str, label: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClubNewsError(f"{label} field {key!r} must be an integer offset, got {value!r}.")
    return value


def _one_of(value: str, allowed: Sequence[str], label: str) -> str:
    if value not in allowed:
        raise ClubNewsError(
            f"{label} is {value!r}, which is outside the closed vocabulary {list(allowed)!r}. "
            "A value not in the list is refused rather than mapped to the nearest one."
        )
    return value


def _require_keys(record: Mapping[str, object], keys: Sequence[str], label: str) -> None:
    missing = [key for key in keys if key not in record]
    if missing:
        raise ClubNewsError(f"{label} is missing required field(s) {missing!r}.")


def _dateline(record: Mapping[str, object], url: str) -> _Dateline:
    """Read one document's dateline, holding precision and value to the same story.

    The three precisions are not interchangeable and the pairing is checked both ways: an
    ``unknown`` precision must carry no value, and a value must carry a precision that
    describes it. A ``day`` dateline is validated as a bare calendar date and kept verbatim
    -- it is never sent through the instant normaliser, because that would require inventing
    a time the source did not publish.
    """

    precision = _one_of(
        _text(record, "published_precision", f"Document {url!r}"),
        PUBLISHED_PRECISIONS,
        f"Document {url!r} published_precision",
    )
    raw = record.get("published_at_utc")
    if precision == _UNKNOWN_PRECISION:
        if raw is not None:
            raise ClubNewsError(
                f"Document {url!r} declares an unknown publication precision but carries "
                f"{raw!r}. Unknown means the source dated itself not at all."
            )
        return _Dateline(published_at_utc=None, published_precision=precision)
    if raw is None:
        raise ClubNewsError(
            f"Document {url!r} declares {precision!r} precision but carries no dateline. "
            "Absent is its own precision and is spelled 'unknown'."
        )
    if precision == _DAY_PRECISION:
        if not isinstance(raw, str):
            raise ClubNewsError(f"Document {url!r} day dateline must be text, got {raw!r}.")
        try:
            date.fromisoformat(raw.strip())
        except ValueError as error:
            raise ClubNewsError(
                f"Document {url!r} day dateline {raw!r} is not a calendar date: {error}."
            ) from error
        return _Dateline(published_at_utc=raw.strip(), published_precision=precision)
    return _Dateline(
        published_at_utc=normalize_utc_timestamp(raw, label=f"Document {url!r} published_at_utc"),
        published_precision=_INSTANT_PRECISION,
    )


def _declared_datelines(document: Mapping[str, object]) -> dict[str, _Dateline]:
    datelines: dict[str, _Dateline] = {}
    for entry in _list(document, "documents"):
        record = _mapping(entry, "A declared source document")
        _require_keys(record, _DOCUMENT_KEYS, "A declared source document")
        url = _text(record, "url", "A declared source document")
        if url in datelines:
            raise ClubNewsError(
                f"The response declares {url!r} twice; one document has one dateline."
            )
        datelines[url] = _dateline(record, url)
    return datelines


def _fetched_bytes(documents: Sequence[RawDocument]) -> dict[str, bytes]:
    """Index the fetched documents by every URL a response may legitimately cite.

    Both the requested and the final URL are keys, because a redirect means the page we
    asked for and the page we read have different addresses and a response may name either.
    """

    indexed: dict[str, bytes] = {}
    for document in documents:
        for url in (document.requested_url, document.final_url):
            existing = indexed.get(url)
            if existing is not None and existing != document.readable:
                raise ClubNewsError(
                    f"Two fetched documents answer for {url!r} with different bytes; the "
                    "citation would be ambiguous."
                )
            indexed[url] = document.readable
    return indexed


def parse_claim_response(
    response: ClaimResponse, documents: Sequence[RawDocument]
) -> tuple[ParsedClaim, ...]:
    """Return the claims a stored response declares, or refuse it.

    ``documents`` are the fetched bytes the response was produced from. They are required
    rather than optional: the digest and the span are the citation, and neither can be
    produced -- let alone checked -- without the bytes they point into.

    Order of refusals is deliberate. Each claim's own fields, including both closed
    vocabularies, are checked before it is cross-referenced against the documents, so a
    response that breaks the format in one place is refused for that reason rather than for
    a downstream consequence of it.
    """

    if not documents:
        raise ClubNewsError(
            "Parsing needs the fetched documents: a claim's citation is a digest and a byte "
            "span into them, and neither exists without the bytes."
        )
    document = _object(response.text)
    version = document.get("contract_version")
    if version != ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION:
        raise ClubNewsError(
            f"The response declares contract {version!r}, not "
            f"{ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION!r}. A response stored under one "
            "version is not readable under another."
        )
    datelines = _declared_datelines(document)
    available = _fetched_bytes(documents)

    claims: list[ParsedClaim] = []
    seen: dict[tuple[str, str], str] = {}
    for entry in _list(document, "claims"):
        record = _mapping(entry, "A claim")
        _require_keys(record, _CLAIM_KEYS, "A claim")
        player_name = _text(record, "player_name", "A claim")
        team_name = _text(record, "team_name", "A claim")
        # Validated and then dropped. See the module docstring: the format carries it, the
        # artifact may not, and a field kept "just in case" is a text column waiting to happen.
        _text(record, "paraphrase", f"The claim about {player_name!r}")
        disposition = _one_of(
            _text(record, "disposition", f"The claim about {player_name!r}"),
            ROTATION_DISPOSITIONS,
            f"The disposition for {player_name!r}",
        )
        speaker = _one_of(
            _text(record, "speaker", f"The claim about {player_name!r}"),
            CLAIM_SPEAKERS,
            f"The speaker for {player_name!r}",
        )
        source_url = _text(record, "source_url", f"The claim about {player_name!r}")
        span_start = _offset(record, "span_start", f"The claim about {player_name!r}")
        span_end = _offset(record, "span_end", f"The claim about {player_name!r}")

        key = (player_name.casefold(), team_name.casefold())
        if key in seen:
            raise ClubNewsError(
                f"The response codes {player_name!r} of {team_name!r} twice, as "
                f"{seen[key]!r} and {disposition!r}. The artifact carries one disposition "
                "per player and no rule between two statements has been declared, so this "
                "is refused rather than resolved."
            )
        seen[key] = disposition

        dateline = datelines.get(source_url)
        if dateline is None:
            raise ClubNewsError(
                f"The claim about {player_name!r} cites {source_url!r}, which the response "
                "does not declare among its own source documents."
            )
        content = available.get(source_url)
        if content is None:
            raise ClubNewsError(
                f"The claim about {player_name!r} cites {source_url!r}, which is not among "
                "the fetched documents; its citation could never be resolved."
            )
        if not 0 <= span_start < span_end <= len(content):
            raise ClubNewsError(
                f"The claim about {player_name!r} spans [{span_start}, {span_end}) of "
                f"{source_url!r}, which holds {len(content)} bytes. A span outside the bytes "
                "it cites is an unresolvable citation."
            )
        claims.append(
            ParsedClaim(
                player_name=player_name,
                team_name=team_name,
                disposition=disposition,
                speaker=speaker,
                source_url=source_url,
                source_sha256=hashlib.sha256(content).hexdigest(),
                span_start=span_start,
                span_end=span_end,
                published_at_utc=dateline.published_at_utc,
                published_precision=dateline.published_precision,
            )
        )
    return tuple(claims)


def resolve_span(content: bytes, claim: ParsedClaim) -> bytes:
    """Return the bytes a claim cites, refusing bytes that are not the ones it was coded on.

    This is the render-time half of the citation and the reason the artifact needs no text.
    The digest is checked first: a document that has since changed would resolve the same
    offsets to different words, and showing those as the source's own would be a fabrication
    with a checksum's worth of confidence behind it.
    """

    digest = hashlib.sha256(content).hexdigest()
    if digest != claim.source_sha256:
        raise ClubNewsError(
            f"The bytes offered for {claim.source_url!r} hash to {digest[:12]}…, not the "
            f"{claim.source_sha256[:12]}… this claim was coded on. The span would point into "
            "different words."
        )
    if claim.span_end > len(content):
        raise ClubNewsError(
            f"The span [{claim.span_start}, {claim.span_end}) exceeds the {len(content)} "
            "bytes offered."
        )
    return content[claim.span_start : claim.span_end]


__all__ = [
    "CLAIM_PARSE_CONTRACT_VERSION",
    "ParsedClaim",
    "parse_claim_response",
    "resolve_span",
]
