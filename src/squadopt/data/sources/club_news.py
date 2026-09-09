"""The seam between this repository and a club's own words, and a stub that stands in for it.

Two methods, and the lane starts behind both of them: ``fetch`` reads one document and
``code`` asks a model what it says about who will start. Neither is implemented here.
What is here is the protocol, the shapes the two methods exchange, and a provider that
serves a **committed synthetic fixture** instead — so the identity join, the evidence
artifact and the weekly step can all be built, tested and demonstrated with no API key,
no network and no captured club bytes. Connecting the real thing later changes one
construction site.

Nothing in this module reaches a network, and nothing in it imports a network library.
That is not incidental: it is the property that lets every test on this path run offline
and lets the fixture, rather than a live page, be the specification of the hard cases.

**The response is text.** ``code`` returns what the model said, verbatim, plus the
identity to stamp it with — not parsed claims. Parsing is a separate, pure, offline step,
so re-running it over stored bytes reproduces the same rows. The shape the text is in is
documented by the fixture and read by that parser; this module carries the closed
vocabularies both ends have to agree on, and does not itself interpret a response.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.timestamps import normalize_utc_timestamp

#: Recorded in a snapshot's metadata as the source of captured club documents.
CLUB_NEWS_SOURCE: Final = "club-news"

#: The response format the prompt asks for and the parser reads. Bumped whenever either
#: end changes, because a response stored under one version is not readable under another.
ROTATION_CLAIM_RESPONSE_CONTRACT_VERSION: Final = "rotation_claim_response_v1"

#: The fixture's own contract, separate from the response's: the fixture carries documents,
#: a roster and responses, and its shape can change without the response format moving.
CLUB_NEWS_FIXTURE_CONTRACT_VERSION: Final = "club_news_fixture_v1"

#: The only claim vocabulary there is. A closed categorical list, deliberately: a generated
#: likelihood, percentage, chance or score is forbidden on a member-facing surface and is
#: an unmeasured claim besides, so there is no probability anywhere in this lane -- not even
#: internally. A closed vocabulary also cannot invent a nuance the source did not have.
ROTATION_DISPOSITIONS: Final[tuple[str, ...]] = (
    "not_addressed",
    "no_statement",
    "stated_expected_to_start",
    "stated_expected_absent",
    "stated_rotation_risk",
    "stated_returning_from_injury",
    "stated_minutes_limited",
    "ambiguous",
)

#: How precisely the source dated itself. A day-only dateline is recorded as ``day`` and is
#: never rounded up to an instant: rounding would manufacture a time-of-knowledge claim.
PUBLISHED_PRECISIONS: Final[tuple[str, ...]] = ("instant", "day", "unknown")

#: Who the words are attributed to, as a role. Never a person's name.
CLAIM_SPEAKERS: Final[tuple[str, ...]] = (
    "manager",
    "club_official",
    "club_statement",
    "unattributed",
)


class ClubNewsError(DataSourceError):
    """The club-news seam could not serve what was asked of it."""


@dataclass(frozen=True, slots=True)
class RawDocument:
    """One fetched document, and everything about the fetch that has to be replayable.

    The bytes are the artifact; the rest is what makes a claim traceable to them. The
    requested and final URLs are both kept because a redirect changes which page was
    actually read, and a citation that names the page we asked for rather than the one we
    got would be pointing at the wrong words.

    ``fetched_at_utc`` is when *we* looked. It is never used as the document's own
    dateline: what the source said about its own publication time is a separate field on
    the claim, and absent there means absent.
    """

    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    byte_length: int
    fetched_at_utc: str
    content: bytes

    def __post_init__(self) -> None:
        if not self.requested_url or not self.final_url:
            raise InvalidValueError("A fetched document must name both URLs.")
        if self.byte_length != len(self.content):
            raise InvalidValueError(
                f"{self.requested_url} declares {self.byte_length} bytes and carries "
                f"{len(self.content)}. The length is what a sidecar records, so it may "
                "not disagree with the bytes it describes."
            )
        normalize_utc_timestamp(self.fetched_at_utc, label="fetched_at_utc")


@dataclass(frozen=True, slots=True)
class RosterPlayer:
    """One squad-eligible player, as a claim about a name has to be resolved against.

    ``player_id`` is the platform's persistent ``code``, never the per-season element id:
    a claim recorded this week is read again next season.
    """

    player_id: int
    web_name: str
    team_name: str


@dataclass(frozen=True, slots=True)
class ClaimResponse:
    """What the model said, and the identity it is stamped with.

    ``text`` is verbatim and unparsed on purpose. It is written into the snapshot store as
    its own payload and hashed there, so the rows derived from it can be rebuilt from the
    stored bytes rather than from a second call to a model that may answer differently.
    """

    text: str
    model_identifier: str
    model_version: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise InvalidValueError("A claim response with no text is not a response.")
        if not self.model_identifier or not self.model_version:
            raise InvalidValueError(
                "A response must name the model and version that produced it; without "
                "them the claim cannot be replayed."
            )


class ClubNewsProvider(Protocol):
    """Where a club's words come from, and what reads them. Two methods, no more."""

    def fetch(self, url: str) -> RawDocument: ...

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse: ...


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ClubNewsError(f"{label} must be a JSON object, got {type(value).__name__}.")
    return value


def _require_list(document: Mapping[str, object], key: str, label: str) -> list[object]:
    value = document.get(key)
    if not isinstance(value, list) or not value:
        raise ClubNewsError(f"{label} must carry a non-empty {key!r} array.")
    return value


def _require_text(document: Mapping[str, object], key: str, label: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ClubNewsError(f"{label} field {key!r} must be non-empty text, got {value!r}.")
    return value


def _require_integer(document: Mapping[str, object], key: str, label: str) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ClubNewsError(f"{label} field {key!r} must be an integer, got {value!r}.")
    return value


class FixtureClubNewsProvider:
    """Serves the committed synthetic fixture, and only it.

    The fixture is the specification of the hard cases -- a day-only dateline, a document
    with no dateline at all, a player the model says nothing about, a player whose club was
    never read, a span carrying a literal per-cent sign, two colliding surnames, a response
    the parser must refuse. Those are the states the downstream refusals exist for, and a
    live page cannot be relied on to contain any of them.

    It carries no real club's bytes. Every document here was written by us, and
    ``data/sample/README.md`` states the rule the directory keeps.
    """

    def __init__(self, fixture_path: Path | str) -> None:
        self._path = Path(fixture_path)
        self._document = self._load()

    def _load(self) -> Mapping[str, object]:
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as error:
            raise ClubNewsError(
                f"Cannot read the club-news fixture at {self._path}: {error}"
            ) from error
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ClubNewsError(f"{self._path} is not valid JSON: {error}") from error
        document = _require_mapping(parsed, str(self._path))
        version = document.get("contract_version")
        if version != CLUB_NEWS_FIXTURE_CONTRACT_VERSION:
            raise ClubNewsError(
                f"{self._path} declares contract {version!r}, not "
                f"{CLUB_NEWS_FIXTURE_CONTRACT_VERSION!r}."
            )
        _require_list(document, "documents", str(self._path))
        _require_list(document, "roster", str(self._path))
        _require_mapping(document.get("response"), f"{self._path} 'response'")
        return document

    @property
    def urls(self) -> tuple[str, ...]:
        """Every URL the fixture can serve, in the order it declares them."""

        return tuple(
            _require_text(_require_mapping(entry, "A fixture document"), "requested_url", "It")
            for entry in _require_list(self._document, "documents", str(self._path))
        )

    def clubs_declared(self) -> tuple[str, ...]:
        """Every club the week set out to read, whether or not a document arrived.

        Exposed because the difference between this and :meth:`clubs_covered` is what makes
        "no source was read for this player's club" a recordable fact rather than a silence.
        The fixture has always declared both; only the accessors were missing.
        """

        return self._club_names("clubs_declared")

    def clubs_covered(self) -> tuple[str, ...]:
        """The clubs a document was actually read for.

        A club here whose document mentioned nobody is still covered: it published and said
        nothing about our players, which is a different statement from never having been
        read. Collapsing the two is exactly what the evidence column exists to prevent.
        """

        return self._club_names("clubs_covered")

    def _club_names(self, key: str) -> tuple[str, ...]:
        value = self._document.get(key)
        if not isinstance(value, list) or not value:
            raise ClubNewsError(f"{self._path} must carry a non-empty {key!r} array.")
        names: list[str] = []
        for entry in value:
            if not isinstance(entry, str) or not entry.strip():
                raise ClubNewsError(f"{self._path} lists {entry!r} in {key!r}; a club is a name.")
            names.append(entry.strip())
        return tuple(names)

    def roster(self) -> tuple[RosterPlayer, ...]:
        """The fixture's own roster, so the identity join can be tested against it alone."""

        players: list[RosterPlayer] = []
        for entry in _require_list(self._document, "roster", str(self._path)):
            record = _require_mapping(entry, "A fixture roster entry")
            players.append(
                RosterPlayer(
                    player_id=_require_integer(record, "player_id", "A fixture roster entry"),
                    web_name=_require_text(record, "web_name", "A fixture roster entry"),
                    team_name=_require_text(record, "team_name", "A fixture roster entry"),
                )
            )
        return tuple(players)

    def fetch(self, url: str) -> RawDocument:
        """Return the fixture's document for ``url``, or refuse.

        Refusing an unknown URL rather than returning an empty document is the point: a
        caller that has been handed nothing must not be able to mistake it for a club that
        published nothing this week. Those are different states all the way to the card.
        """

        for entry in _require_list(self._document, "documents", str(self._path)):
            record = _require_mapping(entry, "A fixture document")
            if _require_text(record, "requested_url", "A fixture document") != url:
                continue
            content = _require_text(record, "content", "A fixture document").encode("utf-8")
            return RawDocument(
                requested_url=url,
                final_url=_require_text(record, "final_url", "A fixture document"),
                http_status=_require_integer(record, "http_status", "A fixture document"),
                content_type=_require_text(record, "content_type", "A fixture document"),
                byte_length=len(content),
                fetched_at_utc=_require_text(record, "fetched_at_utc", "A fixture document"),
                content=content,
            )
        raise ClubNewsError(
            f"The club-news fixture at {self._path} carries no document for {url!r}. It "
            "serves what it declares and nothing else; a missing document is not an empty "
            "one."
        )

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        """Return the fixture's canned response, unchanged whatever it is handed.

        Deliberately indifferent to its arguments. A stub that varied its answer would be a
        second implementation of the thing it stands in for, and the tests downstream would
        be measuring that instead of their own behaviour. The arguments are still typed and
        still checked, so a caller that assembles them wrongly fails here rather than at
        the first real call.
        """

        if not documents:
            raise ClubNewsError("Nothing to code: no document was read.")
        if not roster:
            raise ClubNewsError("Nothing to code against: the roster is empty.")
        response = _require_mapping(self._document.get("response"), "The fixture response")
        return ClaimResponse(
            text=_require_text(response, "text", "The fixture response"),
            model_identifier=_require_text(response, "model_identifier", "The fixture response"),
            model_version=_require_text(response, "model_version", "The fixture response"),
        )

    def unparseable_responses(self) -> tuple[ClaimResponse, ...]:
        """Responses a parser must refuse rather than coerce.

        Kept beside the good one rather than built in a test, because "the shape the parser
        does not accept" is a property of the format this fixture documents, and a copy of
        it inside a test file would drift away from the format it is meant to violate.
        """

        declared = self._document.get("unparseable_responses")
        if not isinstance(declared, list):
            return ()
        responses: list[ClaimResponse] = []
        for entry in declared:
            record = _require_mapping(entry, "A fixture unparseable response")
            responses.append(
                ClaimResponse(
                    text=_require_text(record, "text", "A fixture unparseable response"),
                    model_identifier=_require_text(
                        record, "model_identifier", "A fixture unparseable response"
                    ),
                    model_version=_require_text(
                        record, "model_version", "A fixture unparseable response"
                    ),
                )
            )
        return tuple(responses)
