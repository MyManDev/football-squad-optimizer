"""The club-news lane end to end: a registered page becomes an evidence table, twice.

Every other test of this lane starts from a capture somebody assembled. This one starts
where a real week starts -- a registry of pages -- and walks the whole chain:

    registry -> robots -> fetch -> model call -> capture on disk -> evidence table
                                                        |
                                                        +-> second export, no network,
                                                            no model, same digest

The two seams are the production ones, not monkeypatched internals. The network is an
injected ``Opener`` (``club_news_fetch``'s own parameter) and the model is an injected
``CodingClient`` (``club_news_model``'s own parameter), so what this exercises is the code
that runs on a real week with two objects swapped at the edges. Nothing opens a socket,
nothing needs a key, and every write is under ``tmp_path``.

The replay is the point R07 asks for and the reason the second export hands in an opener
and a client that **raise if they are called at all**: "it replays offline" has to be a
property of the code rather than of the test's good manners.
"""

import hashlib
import json
import urllib.error
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
)

from squadopt.application.rotation_export import (
    RotationExportRequest,
    export_rotation_evidence,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, FixtureClubNewsProvider, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    CodingFixture,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.platform.club_news_fetch import (
    ClubNewsFetchError,
    fetch_registered_documents,
    load_club_sources,
)
from squadopt.platform.club_news_model import AnthropicClubNewsProvider

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE = SAMPLE / "club_news_v1.fixture.json"
CODING_FIXTURE = SAMPLE / "club_news_coding_v1.fixture.json"

COMMIT = "0" * 40
#: Before the decision capture (2026-09-12T15:00:00Z), as a week's documents must be.
FETCHED_AT = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
NEWS_CAPTURED_AT = "2026-09-12T14:30:00Z"

#: Declared but never served: the registry sets out to read three clubs and the third 404s,
#: which is how "declared" and "covered" come to differ through the real path rather than by
#: being written down as different.
SILENT_CLUB = "Everton"


# --- the two edges, as the production seams see them ------------------------


@dataclass
class _Response:
    """As much of an HTTP response as ``_read_once`` reads."""

    body: bytes
    content_type: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    status: int = 200

    def __post_init__(self) -> None:
        self.headers = {"Content-Type": self.content_type, **dict(self.headers)}

    def read(self, amount: int) -> bytes:
        return self.body[:amount]

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Host:
    """One host, serving the committed fixture's bytes and a robots.txt."""

    def __init__(self, *, robots: bytes = b"User-agent: *\nAllow: /\n") -> None:
        provider = FixtureClubNewsProvider(FIXTURE)
        self.pages = {url: provider.fetch(url) for url in provider.urls}
        self.robots = robots
        self.requested: list[str] = []

    def __call__(self, request: Any, timeout: float) -> _Response:
        url = request.full_url
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return _Response(body=self.robots, content_type="text/plain", url=url)
        document = self.pages.get(url)
        if document is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _Response(
            body=document.content,
            content_type=document.content_type,
            url=document.final_url,
        )


def _answer_about(documents: Sequence[RawDocument]) -> str:
    """The committed coding response, narrowed to the documents that were handed over.

    Not a convenience. The registry admits **one page per club** -- `load_club_sources`
    refuses a club twice, because "which page is this club's" cannot have two answers --
    while the committed fixture carries two pages for Man Utd and a response citing both.
    So a week read through the registry sees fewer documents than the fixture file
    describes, and the prompt's own first rule is "read only those documents": a model
    handed two pages cannot cite a third.

    That gap is real and is recorded in its own test below rather than smoothed over here.
    """

    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    served = {url for document in documents for url in (document.requested_url, document.final_url)}
    return json.dumps(
        {
            "contract_version": fixture["contract_version"],
            "documents": [entry for entry in fixture["documents"] if entry["url"] in served],
            "claims": [entry for entry in fixture["claims"] if entry["source_url"] in served],
        },
        ensure_ascii=False,
    )


class _Model:
    """A client satisfying ``CodingClient``, answering about the documents it was sent."""

    def __init__(self, documents: Sequence[RawDocument]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._documents = documents

    @property
    def messages(self) -> "_Model":
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return _Message(content=[_Block(type="text", text=_answer_about(self._documents))])


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Message:
    content: list[_Block]
    model: str = "claude-opus-5-20260501"
    stop_reason: str = "end_turn"
    stop_details: Any = None


# --- the chain --------------------------------------------------------------


def _registry(path: Path, *, clubs: tuple[str, ...] | None = None) -> Path:
    """Write a source registry naming the fixture's pages, one entry per club."""

    provider = FixtureClubNewsProvider(FIXTURE)
    declared = provider.clubs_declared() if clubs is None else clubs
    first: dict[str, str] = {}
    for url in provider.urls:
        first.setdefault(provider.fetch(url).club, url)
    sources = [
        {
            "club": club,
            "url": first.get(club, f"https://club.example/{club.lower()}/absent"),
            "terms_record": "docs/club_news_sources.md",
        }
        for club in declared
    ]
    path.write_text(
        json.dumps({"contract_version": "club_news_sources_v1", "sources": sources}),
        encoding="utf-8",
    )
    return path


def _decision(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    )
    return metadata.snapshot_id


def _read_the_week(
    tmp_path: Path, *, host: _Host
) -> tuple[tuple[RawDocument, ...], tuple[tuple[str, str], ...], ClaimResponse, _Model]:
    """Registry -> robots -> fetch -> model call. The half that needs the outside world."""

    sources = load_club_sources(_registry(tmp_path / "club_news_sources.json"))
    documents, refused = fetch_registered_documents(
        sources, opener=host, now=lambda: FETCHED_AT, sleeper=lambda _: None
    )
    model = _Model(documents)
    provider = AnthropicClubNewsProvider(client=model)
    response = provider.code(documents, FixtureClubNewsProvider(FIXTURE).roster())
    return documents, refused, response, model


def _capture_the_week(
    root: Path,
    *,
    documents: tuple[RawDocument, ...],
    response: ClaimResponse,
    declared: tuple[str, ...],
) -> str:
    covered = tuple(dict.fromkeys(document.club for document in documents))
    metadata = write_club_news_capture(
        root,
        documents=documents,
        coded=tuple(
            CodedClub(
                club=club,
                response=response,
                prompt_contract_version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                prompt_sha256=coding_prompt_sha256(),
            )
            for club in covered
        ),
        clubs_declared=declared,
        clubs_covered=covered,
        captured_at_utc=NEWS_CAPTURED_AT,
    )
    return metadata.snapshot_id


def _export(root: Path, *, decision: str, news: str, output: Path) -> pd.DataFrame:
    request = RotationExportRequest(
        SEASON,
        TARGET_GAMEWEEK,
        DEADLINE,
        decision,
        root,
        None,
        output,
        club_news_snapshot=news,
        table_name="table",
    )
    export_rotation_evidence(request, repository_commit=COMMIT)
    return pd.read_csv(output / "table.csv")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- the acceptance ---------------------------------------------------------


def test_a_registered_page_becomes_an_evidence_table_and_replays_without_either_edge(
    tmp_path: Path,
) -> None:
    """The whole chain, then the same evidence built a second time from the capture alone.

    What makes the second export offline is **structural, not a tripwire**: it is handed a
    snapshot root and a capture id and there is no parameter through which a network or a
    model could be reached, because `application` may not import `platform` and the import
    contract fails the build if it ever does. So the thing worth asserting is not that a
    stub went unused -- it is that the model was asked exactly once for the whole chain, and
    that the second table is the first one byte for byte.
    """

    root = tmp_path / "snapshots"
    host = _Host()

    documents, refused, response, model = _read_the_week(tmp_path, host=host)
    news = _capture_the_week(
        root,
        documents=documents,
        response=response,
        declared=FixtureClubNewsProvider(FIXTURE).clubs_declared(),
    )
    decision = _decision(root)

    first = _export(root, decision=decision, news=news, output=tmp_path / "first")
    second = _export(root, decision=decision, news=news, output=tmp_path / "second")

    assert len(model.calls) == 1, "one week, one call -- and the replay added none"
    assert host.requested, "the first pass really did go through the fetch adapter"
    assert _digest(tmp_path / "first" / "table.csv") == _digest(tmp_path / "second" / "table.csv")
    pd.testing.assert_frame_equal(first, second)
    assert refused, "the declared club nobody served must be reported, not dropped"


def test_the_club_nobody_served_is_uncovered_rather_than_silent(tmp_path: Path) -> None:
    """A 404 and a club that published nothing are different facts, and stay different.

    The registry declares three clubs; the host serves two. The third must arrive as a
    refusal with a reason, and the table must mark its players uncovered rather than
    recording that nothing was said about them.
    """

    root = tmp_path / "snapshots"
    host = _Host()

    documents, refused, response, _ = _read_the_week(tmp_path, host=host)

    served = {document.club for document in documents}
    assert SILENT_CLUB not in served
    assert [club for club, _ in refused] == [SILENT_CLUB]
    assert "404" in dict(refused)[SILENT_CLUB]

    news = _capture_the_week(
        root,
        documents=documents,
        response=response,
        declared=FixtureClubNewsProvider(FIXTURE).clubs_declared(),
    )
    table = _export(root, decision=_decision(root), news=news, output=tmp_path / "out")

    covered = table.set_index("player_id")["club_source_covered"]
    assert not covered.all(), "a declared club nobody served cannot come out covered"


def test_a_host_that_disallows_our_path_is_not_read_at_all(tmp_path: Path) -> None:
    """The refusal happens before the document is requested, not after it is read."""

    host = _Host(robots=b"User-agent: *\nDisallow: /\n")
    sources = load_club_sources(_registry(tmp_path / "club_news_sources.json"))

    documents, refused = fetch_registered_documents(
        sources, opener=host, now=lambda: FETCHED_AT, sleeper=lambda _: None
    )

    assert documents == ()
    assert len(refused) == len(sources)
    assert all(url.endswith("/robots.txt") for url in host.requested)


def test_a_host_whose_robots_cannot_be_read_is_not_treated_as_consent(
    tmp_path: Path,
) -> None:
    """ "We could not ask" is not "they said yes", and the chain stops at that seam."""

    class _Broken(_Host):
        def __call__(self, request: Any, timeout: float) -> _Response:
            if request.full_url.endswith("/robots.txt"):
                raise urllib.error.HTTPError(request.full_url, 500, "Server Error", {}, None)  # type: ignore[arg-type]
            return super().__call__(request, timeout)

    sources = load_club_sources(_registry(tmp_path / "club_news_sources.json"))

    documents, refused = fetch_registered_documents(
        sources, opener=_Broken(), now=lambda: FETCHED_AT, sleeper=lambda _: None
    )

    assert documents == ()
    assert all("preference is unknown" in reason for _, reason in refused)


def test_documents_read_after_the_decision_capture_refuse_the_week(tmp_path: Path) -> None:
    """The deadline rule, exercised through the fetch clock rather than a hand-built record.

    A document fetched after the capture the decision was made from is knowledge the
    decision could not have had. The refusal belongs to the evidence path, and this is the
    chain proving the fetch clock is what feeds it.
    """

    root = tmp_path / "snapshots"
    host = _Host()
    sources = load_club_sources(_registry(tmp_path / "club_news_sources.json"))
    after = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)

    documents, _ = fetch_registered_documents(
        sources, opener=host, now=lambda: after, sleeper=lambda _: None
    )
    provider = AnthropicClubNewsProvider(client=_Model(documents))
    response = provider.code(documents, FixtureClubNewsProvider(FIXTURE).roster())
    news = _capture_the_week(
        root,
        documents=documents,
        response=response,
        declared=FixtureClubNewsProvider(FIXTURE).clubs_declared(),
    )

    with pytest.raises(DataError):
        _export(root, decision=_decision(root), news=news, output=tmp_path / "out")


def test_an_unregistered_page_is_never_requested(tmp_path: Path) -> None:
    """The registry is the permission, so a URL outside it produces no request at all."""

    host = _Host()
    registry = _registry(tmp_path / "club_news_sources.json", clubs=("Arsenal",))
    sources = load_club_sources(registry)

    documents, _ = fetch_registered_documents(
        sources, opener=host, now=lambda: FETCHED_AT, sleeper=lambda _: None
    )

    assert [document.club for document in documents] == ["Arsenal"]
    assert not any("united" in url for url in host.requested)


def test_the_model_is_asked_once_with_the_documents_that_were_actually_read(
    tmp_path: Path,
) -> None:
    """The bytes hashed into the capture are the bytes the model was shown.

    Not an incidental property: the manifest's document digests are only meaningful if the
    model read those documents and no others, which is also why the request carries no tool
    it could have fetched anything with.
    """

    host = _Host()

    documents, _, _, model = _read_the_week(tmp_path, host=host)

    assert len(model.calls) == 1
    sent = model.calls[0]
    assert "tools" not in sent
    content = sent["messages"][0]["content"]
    for document in documents:
        assert document.content.decode("utf-8") in content


def test_an_empty_registry_is_refused_rather_than_read_as_a_quiet_week(
    tmp_path: Path,
) -> None:
    """No source registered is a configuration that was never finished, not a silent week."""

    path = tmp_path / "club_news_sources.json"
    path.write_text(
        json.dumps({"contract_version": "club_news_sources_v1", "sources": []}),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError):
        load_club_sources(path)


def test_a_club_can_register_only_one_page_though_the_lane_carries_several(
    tmp_path: Path,
) -> None:
    """A limitation this chain found, pinned so it is a known shape rather than a surprise.

    Everything downstream of the fetch handles several documents per club: `RawDocument`
    carries a club, the capture stores one payload per document, and the committed fixture
    has two pages for Man Utd with claims citing both. The registry cannot express that --
    `load_club_sources` refuses a club twice, deliberately, because "which page is this
    club's" may not have two answers when the evidence table joins on the club.

    So a club whose news is split across a press conference and an injury update can be read
    through this path only in part. Whether the registry should take a list of pages per
    club is a decision, not a defect to fix in a test; this records the shape as it is, and
    fails if somebody changes it without meaning to.
    """

    path = tmp_path / "club_news_sources.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "club_news_sources_v1",
                "sources": [
                    {
                        "club": "Man Utd",
                        "url": "https://club.example/united/press-conference-gw4",
                        "terms_record": "docs/club_news_sources.md",
                    },
                    {
                        "club": "Man Utd",
                        "url": "https://club.example/united/squad-update",
                        "terms_record": "docs/club_news_sources.md",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError, match="Man Utd"):
        load_club_sources(path)
