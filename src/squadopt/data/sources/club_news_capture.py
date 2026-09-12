"""The durable layout of one week's club news: the bytes read, and what a model said of them.

A week's rotation evidence has to be reproducible after the fact, and "reproducible" here
means something narrow: the same documents and the same model response go in, the same
claims and the same digests come out, with no network and no second call to a model that
would not answer the same way twice. That requires the bytes to survive the run, so this
module is the layout they survive in.

**One capture holds both halves.** The documents and the responses coded from them are the
same week's record, and a store that let one be replaced without the other would let a
claim cite bytes that no longer exist. They are written together, and the snapshot store
refuses to touch an existing capture directory, so a week is written once.

**The index carries only what cannot be derived.** Digests are not in it: the store
checksums every payload and recomputes the fingerprint on read, so repeating them here
would be a second copy of an existing mechanism and a second thing to keep in step. Byte
lengths are not in it either -- the bytes are right there. What is in it is what the bytes
cannot say about themselves: which club, which URL was asked for, which was served, the
status and content type, when we looked, and what the transport claimed about publication.

**Payload names are positional, and the index maps them.** A club cannot name a payload:
the store requires lowercase names of digits, letters and separators, while clubs are
spelled ``Man Utd`` and ``Nott'm Forest``. Positions are assigned in the order the sources
were read, so two runs over one registry produce the same names.

Nothing here reaches a network or calls a model. This is where the results of both are put
down, and where they are picked back up.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata, write_snapshot
from squadopt.data.sources.club_news import (
    CLUB_NEWS_SOURCE,
    ClaimResponse,
    ClubNewsError,
    RawDocument,
)
from squadopt.data.sources.club_news_readable import READABLE_TEXT_CONTRACT_VERSION

#: The capture layout's own contract. Bumped when the payload names or the index shape
#: move, because a capture written under one layout is not readable under another -- and
#: being readable years later is the only reason it is written at all.
CLUB_NEWS_CAPTURE_CONTRACT_VERSION: Final = "club_news_capture_v2"

#: The index payload. Named so a person listing the directory can see where to start.
INDEX_PAYLOAD: Final = "index.json"

_DOCUMENT_PREFIX: Final = "document"
_RESPONSE_PREFIX: Final = "response"
#: The extracted text beside the served bytes. Both are kept: the served bytes are what the
#: host sent and what makes the extraction auditable, the extracted ones are what the model
#: was shown and what a claim's offsets index.
_READABLE_PREFIX: Final = "readable"


@dataclass(frozen=True, slots=True)
class CodedClub:
    """One club's model response, and the question it was an answer to.

    The prompt identity travels with the response because a response is only interpretable
    against the question that produced it. ``model_identifier`` on the response is what was
    *asked for* and ``model_version`` is what *answered*; both are kept because a request
    naming an alias can be served by a snapshot, and "which model produced this claim" has
    to survive that.

    This is deliberately a ``data``-layer record rather than the evidence table's
    ``ModelProvenance``. That type lives in ``features``, which this layer may not import,
    and the caller builds it from these -- so the capture can be read by anything, and only
    the evidence path needs to know what an evidence manifest wants.
    """

    club: str
    response: ClaimResponse
    prompt_contract_version: str
    prompt_sha256: str

    def __post_init__(self) -> None:
        if not self.club.strip():
            raise InvalidValueError("A coded club must be named.")
        for name in ("prompt_contract_version", "prompt_sha256"):
            if not str(getattr(self, name)).strip():
                raise InvalidValueError(
                    f"A coded club must carry {name}; a response with no question behind it "
                    "cannot be read again."
                )


def _document_payload(position: int) -> str:
    return f"{_DOCUMENT_PREFIX}-{position:02d}"


def _response_payload(position: int) -> str:
    return f"{_RESPONSE_PREFIX}-{position:02d}"


def _readable_payload(position: int) -> str:
    return f"{_READABLE_PREFIX}-{position:02d}"


def capture_payloads(
    documents: Sequence[RawDocument],
    coded: Sequence[CodedClub],
    *,
    clubs_declared: Sequence[str],
    clubs_covered: Sequence[str],
) -> dict[str, bytes]:
    """Lay one week's documents and responses out as named payloads plus an index.

    ``clubs_declared`` and ``clubs_covered`` are in the index rather than inferred from the
    documents, because the difference between them is a fact the documents cannot state: a
    club that was read and said nothing looks identical, from the payloads alone, to a club
    that was never read. That distinction is the one this whole lane exists to keep, so it
    is recorded at the moment it is still known.
    """

    if not documents:
        raise ClubNewsError(
            "A capture with no document is not a week's club news; it is a week in which "
            "nothing was read, and that is recorded by declaring clubs and covering none."
        )
    if not clubs_declared:
        raise ClubNewsError("A capture must declare the clubs the week set out to read.")
    uncovered = sorted(set(clubs_covered) - set(clubs_declared))
    if uncovered:
        raise ClubNewsError(
            f"Clubs {uncovered!r} are covered but were never declared; coverage cannot "
            "exceed what the week set out to read."
        )

    payloads: dict[str, bytes] = {}
    document_index: list[dict[str, object]] = []
    for position, document in enumerate(documents, start=1):
        name = _document_payload(position)
        readable_name = _readable_payload(position)
        payloads[name] = document.content
        payloads[readable_name] = document.readable
        document_index.append(
            {
                "payload": name,
                "readable_payload": readable_name,
                "club": document.club,
                "requested_url": document.requested_url,
                "final_url": document.final_url,
                "http_status": document.http_status,
                "content_type": document.content_type,
                "fetched_at_utc": document.fetched_at_utc,
                "last_modified_utc": document.last_modified_utc,
            }
        )

    response_index: list[dict[str, object]] = []
    for position, entry in enumerate(coded, start=1):
        name = _response_payload(position)
        payloads[name] = entry.response.text.encode("utf-8")
        response_index.append(
            {
                "payload": name,
                "club": entry.club,
                "model_identifier": entry.response.model_identifier,
                "model_version": entry.response.model_version,
                "prompt_contract_version": entry.prompt_contract_version,
                "prompt_sha256": entry.prompt_sha256,
            }
        )

    payloads[INDEX_PAYLOAD] = (
        json.dumps(
            {
                "contract_version": CLUB_NEWS_CAPTURE_CONTRACT_VERSION,
                "readable_text_contract_version": READABLE_TEXT_CONTRACT_VERSION,
                "clubs_declared": sorted(set(clubs_declared)),
                "clubs_covered": sorted(set(clubs_covered)),
                "documents": document_index,
                "responses": response_index,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return payloads


def write_club_news_capture(
    root: Path | str,
    *,
    documents: Sequence[RawDocument],
    coded: Sequence[CodedClub],
    clubs_declared: Sequence[str],
    clubs_covered: Sequence[str],
    captured_at_utc: str,
) -> SnapshotMetadata:
    """Write one week's club news as a snapshot, once.

    A thin wrapper on purpose. The store already refuses an existing directory, checksums
    every payload, writes metadata last so an interrupted capture reads as incomplete, and
    derives an identifier from the bytes -- so this adds a layout and nothing else.
    """

    return write_snapshot(
        root,
        source=CLUB_NEWS_SOURCE,
        captured_at_utc=captured_at_utc,
        payloads=capture_payloads(
            documents,
            coded,
            clubs_declared=clubs_declared,
            clubs_covered=clubs_covered,
        ),
    )


def _index(snapshot: CapturedSnapshot) -> Mapping[str, object]:
    payload = snapshot.payloads.get(INDEX_PAYLOAD)
    if payload is None:
        raise DataSourceError(
            f"{snapshot.metadata.snapshot_id} carries no {INDEX_PAYLOAD!r}, so its payloads "
            "cannot be told apart. A capture without its index is bytes without a record."
        )
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataSourceError(f"{INDEX_PAYLOAD} is not readable JSON: {error}.") from error
    if not isinstance(document, dict):
        raise DataSourceError(f"{INDEX_PAYLOAD} must be a JSON object.")
    version = document.get("contract_version")
    if version != CLUB_NEWS_CAPTURE_CONTRACT_VERSION:
        raise DataSourceError(
            f"{snapshot.metadata.snapshot_id} declares capture contract {version!r}, not "
            f"{CLUB_NEWS_CAPTURE_CONTRACT_VERSION!r}."
        )
    return document


def _entries(document: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    value = document.get(key)
    if not isinstance(value, list):
        raise DataSourceError(f"{INDEX_PAYLOAD} field {key!r} must be an array.")
    entries: list[Mapping[str, object]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise DataSourceError(f"{INDEX_PAYLOAD} lists {entry!r} under {key!r}.")
        entries.append(entry)
    return entries


def _text(entry: Mapping[str, object], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip():
        raise DataSourceError(f"{INDEX_PAYLOAD} entry field {key!r} must be text, got {value!r}.")
    return value


def _payload_bytes(snapshot: CapturedSnapshot, name: str) -> bytes:
    content = snapshot.payloads.get(name)
    if content is None:
        raise DataSourceError(
            f"{INDEX_PAYLOAD} names payload {name!r}, which {snapshot.metadata.snapshot_id} "
            "does not carry. An index that describes bytes nobody stored is worse than no "
            "index: it makes a citation look resolvable."
        )
    return content


def _require_every_payload_is_indexed(snapshot: CapturedSnapshot, named: Sequence[str]) -> None:
    """Refuse a capture holding bytes its index does not describe.

    Checked both ways round. An unindexed payload is a document or a response nobody can
    attribute, and a capture that quietly held one would let a later reader believe the
    index was the whole record.
    """

    stored = set(snapshot.payloads) - {INDEX_PAYLOAD}
    unindexed = sorted(stored - set(named))
    if unindexed:
        raise DataSourceError(
            f"{snapshot.metadata.snapshot_id} holds payload(s) {unindexed!r} that "
            f"{INDEX_PAYLOAD} does not describe, so they belong to no club and no request."
        )


def read_captured_documents(snapshot: CapturedSnapshot) -> tuple[RawDocument, ...]:
    """Rebuild the fetched documents from the capture, in the order they were read.

    The reconstruction is exact rather than approximate: a span located against these bytes
    has to land where it landed on the day, so the bytes come from the payload and every
    field that describes them comes from the index. ``byte_length`` is recomputed from the
    payload -- it is derivable, and a stored copy could disagree with the bytes it describes.
    """

    document = _index(snapshot)
    documents: list[RawDocument] = []
    for entry in _entries(document, "documents"):
        name = _text(entry, "payload")
        content = _payload_bytes(snapshot, name)
        readable = _payload_bytes(snapshot, _text(entry, "readable_payload"))
        status = entry.get("http_status")
        if isinstance(status, bool) or not isinstance(status, int):
            raise DataSourceError(f"{INDEX_PAYLOAD} entry {name!r} has no integer status.")
        modified = entry.get("last_modified_utc")
        if modified is not None and not isinstance(modified, str):
            raise DataSourceError(
                f"{INDEX_PAYLOAD} entry {name!r} carries a non-text publication claim."
            )
        documents.append(
            RawDocument(
                club=_text(entry, "club"),
                requested_url=_text(entry, "requested_url"),
                final_url=_text(entry, "final_url"),
                http_status=status,
                content_type=_text(entry, "content_type"),
                byte_length=len(content),
                fetched_at_utc=_text(entry, "fetched_at_utc"),
                content=content,
                readable=readable,
                last_modified_utc=modified,
            )
        )
    return tuple(documents)


def read_captured_responses(snapshot: CapturedSnapshot) -> tuple[CodedClub, ...]:
    """Rebuild what the model said, and the question it answered, from the capture."""

    document = _index(snapshot)
    coded: list[CodedClub] = []
    for entry in _entries(document, "responses"):
        name = _text(entry, "payload")
        text = _payload_bytes(snapshot, name).decode("utf-8")
        coded.append(
            CodedClub(
                club=_text(entry, "club"),
                response=ClaimResponse(
                    text=text,
                    model_identifier=_text(entry, "model_identifier"),
                    model_version=_text(entry, "model_version"),
                ),
                prompt_contract_version=_text(entry, "prompt_contract_version"),
                prompt_sha256=_text(entry, "prompt_sha256"),
            )
        )
    return tuple(coded)


def read_captured_coverage(snapshot: CapturedSnapshot) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The clubs the week set out to read, and the ones it read.

    Returned as a pair rather than one list, because collapsing them is exactly the mistake
    the evidence table's two columns exist to prevent.
    """

    document = _index(snapshot)
    declared = _entries_of_names(document, "clubs_declared")
    covered = _entries_of_names(document, "clubs_covered")
    return declared, covered


def _entries_of_names(document: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list) or (not value and key == "clubs_declared"):
        raise DataSourceError(f"{INDEX_PAYLOAD} field {key!r} must be a non-empty array.")
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise DataSourceError(f"{INDEX_PAYLOAD} lists {entry!r} in {key!r}; a club is a name.")
        names.append(entry)
    return tuple(names)


def read_club_news_capture(
    snapshot: CapturedSnapshot,
) -> tuple[tuple[RawDocument, ...], tuple[CodedClub, ...], tuple[str, ...], tuple[str, ...]]:
    """Read a whole capture: documents, responses, declared clubs, covered clubs.

    One entry point for the replay path, so a caller cannot read the documents and forget
    the coverage lists -- which would leave it unable to tell a club that said nothing from
    a club nobody read.
    """

    if snapshot.metadata.source != CLUB_NEWS_SOURCE:
        raise DataSourceError(
            f"{snapshot.metadata.snapshot_id} was captured from "
            f"{snapshot.metadata.source!r}, not {CLUB_NEWS_SOURCE!r}."
        )
    documents = read_captured_documents(snapshot)
    coded = read_captured_responses(snapshot)
    described = _entries(_index(snapshot), "documents")
    _require_every_payload_is_indexed(
        snapshot,
        [_text(entry, "payload") for entry in described]
        + [_text(entry, "readable_payload") for entry in described]
        + [_text(entry, "payload") for entry in _entries(_index(snapshot), "responses")],
    )
    declared, covered = read_captured_coverage(snapshot)
    return documents, coded, declared, covered


__all__ = [
    "CLUB_NEWS_CAPTURE_CONTRACT_VERSION",
    "INDEX_PAYLOAD",
    "CodedClub",
    "capture_payloads",
    "read_captured_coverage",
    "read_captured_documents",
    "read_captured_responses",
    "read_club_news_capture",
    "write_club_news_capture",
]
