"""Reading a club's page, and the four refusals that come before the bytes are used.

Every test here is offline. The opener is injected, so what the adapter would have sent and
how it judges what came back are both asserted without a request leaving the machine --
which is also the only way to test a 429 followed by a 200, or a host that disallows us.

The refusals carry the weight. A fetch that fails loudly costs a club's coverage for one
week, which this lane records honestly; a fetch that succeeds with the wrong bytes puts a
citation in front of a member. So the tests below are mostly about the second never
happening quietly.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from squadopt.platform.club_news_fetch import (
    CLUB_NEWS_SOURCES_CONTRACT_VERSION,
    MAXIMUM_DOCUMENT_BYTES,
    ClubNewsFetchError,
    ClubSource,
    fetch_club_document,
    fetch_registered_documents,
    load_club_sources,
    read_url,
    robots_allows,
)

REGISTRY = Path(__file__).resolve().parents[2] / "data" / "sources" / "club_news_sources.json"

PAGE = "https://club.example/team-news"
ROBOTS = "https://club.example/robots.txt"
SOURCE = ClubSource(club="Example FC", url=PAGE)
FIXED_NOW = datetime(2026, 9, 12, 14, 5, 0, tzinfo=UTC)


class _Reply:
    """One canned HTTP response, as much of one as the adapter reads."""

    def __init__(
        self,
        content: bytes = b"<p>Saka trained fully.</p>",
        *,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
        final_url: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self._content = content
        self.status = status
        self._final_url = final_url or PAGE
        headers = {"Content-Type": content_type}
        if last_modified is not None:
            headers["Last-Modified"] = last_modified
        self.headers = headers

    def geturl(self) -> str:
        return self._final_url

    def read(self, amount: int | None = None) -> bytes:
        return self._content if amount is None else self._content[:amount]

    def __enter__(self) -> "_Reply":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _Opener:
    """Serves prepared replies by URL and records every request."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self._replies = replies
        self.requested: list[str] = []
        self.agents: list[str] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Any:
        self.requested.append(request.full_url)
        self.agents.append(str(request.get_header("User-agent", "")))
        reply = self._replies.get(request.full_url)
        if reply is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        if isinstance(reply, list):
            head = reply.pop(0)
            if isinstance(head, Exception):
                raise head
            return head
        if isinstance(reply, Exception):
            raise reply
        return reply


def _allowing_robots(body: bytes = b"User-agent: *\nAllow: /\n") -> _Reply:
    return _Reply(content=body, content_type="text/plain")


def _opener(page: Any = None, *, robots: Any = None) -> _Opener:
    return _Opener(
        {
            ROBOTS: robots if robots is not None else _allowing_robots(),
            PAGE: page if page is not None else _Reply(),
        }
    )


def _slept() -> tuple[list[float], Any]:
    delays: list[float] = []
    return delays, delays.append


# --- what a good read produces ----------------------------------------------


def test_a_read_document_carries_its_club_and_both_urls() -> None:
    """The club comes from the registry entry, so nothing downstream has to remember it."""

    document = fetch_club_document(SOURCE, opener=_opener(), now=lambda: FIXED_NOW)

    assert document.club == "Example FC"
    assert document.requested_url == PAGE
    assert document.final_url == PAGE
    assert document.byte_length == len(document.content)


def test_a_redirect_is_recorded_as_the_page_that_was_read() -> None:
    """A citation names the page we read, not the one we asked for."""

    served = _Reply(final_url=f"{PAGE}/full")

    document = fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)

    assert document.requested_url == PAGE
    assert document.final_url == f"{PAGE}/full"


def test_the_fetch_instant_comes_from_the_clock_and_not_the_response() -> None:
    """Pinned so a capture is reproducible and the third clock stays separable."""

    document = fetch_club_document(SOURCE, opener=_opener(), now=lambda: FIXED_NOW)

    assert document.fetched_at_utc == "2026-09-12T14:05:00Z"


def test_a_publication_header_is_kept_as_an_instant() -> None:
    """The transport's own claim, normalised into the one form the pipeline compares."""

    served = _Reply(last_modified="Fri, 11 Sep 2026 14:00:00 GMT")

    document = fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)

    assert document.last_modified_utc == "2026-09-11T14:00:00Z"


def test_no_publication_header_stays_absent_and_is_never_the_fetch_instant() -> None:
    """R07's rule, as a test: absent is absent, not backfilled from when we looked."""

    document = fetch_club_document(SOURCE, opener=_opener(), now=lambda: FIXED_NOW)

    assert document.last_modified_utc is None


def test_an_unparseable_publication_header_is_treated_as_absent() -> None:
    """A guess at what a malformed header meant would be a manufactured claim."""

    served = _Reply(last_modified="last tuesday")

    document = fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)

    assert document.last_modified_utc is None


def test_the_request_sends_one_identity() -> None:
    """One program, one user-agent -- the same one the live capture already uses."""

    opener = _opener()

    fetch_club_document(SOURCE, opener=opener, now=lambda: FIXED_NOW)

    assert {agent for agent in opener.agents} == {
        "squadopt/1.0 (private research; contact via repository owner)"
    }


# --- the four refusals ------------------------------------------------------


def test_a_disallowed_path_refuses_and_says_the_club_is_not_covered() -> None:
    """A stated preference is not overridden, and the lane already has a state for it."""

    robots = _Reply(content=b"User-agent: *\nDisallow: /team-news\n", content_type="text/plain")

    with pytest.raises(ClubNewsFetchError, match="not covered"):
        fetch_club_document(SOURCE, opener=_opener(robots=robots), now=lambda: FIXED_NOW)


def test_a_robots_file_that_cannot_be_read_is_not_consent() -> None:
    """ "We could not ask" is not "they said yes", so the page is not fetched."""

    broken = urllib.error.HTTPError(ROBOTS, 500, "Server Error", {}, None)  # type: ignore[arg-type]

    with pytest.raises(ClubNewsFetchError, match="preference is unknown"):
        fetch_club_document(SOURCE, opener=_opener(robots=broken), now=lambda: FIXED_NOW)


def test_a_host_serving_no_robots_file_has_stated_no_preference() -> None:
    """A 404 is silence, and silence about robots is not a refusal."""

    missing = urllib.error.HTTPError(ROBOTS, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    assert robots_allows(SOURCE, opener=_opener(robots=missing), sleeper=lambda _: None)


def test_a_document_that_is_not_text_is_refused() -> None:
    """A byte span cannot be located in a PDF, so a quote from one is unresolvable."""

    served = _Reply(content=b"%PDF-1.7", content_type="application/pdf")

    with pytest.raises(ClubNewsFetchError, match="application/pdf"):
        fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)


def test_a_document_over_the_ceiling_is_refused_rather_than_truncated() -> None:
    """Truncation would hash to something no replay reproduces."""

    served = _Reply(content=b"x" * (MAXIMUM_DOCUMENT_BYTES + 1))

    with pytest.raises(ClubNewsFetchError, match="wrong URL rather than a long page"):
        fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)


def test_an_empty_document_is_not_a_club_that_published_nothing() -> None:
    """Those are different facts and this one is a read that did not work."""

    with pytest.raises(ClubNewsFetchError, match="served no bytes"):
        fetch_club_document(SOURCE, opener=_opener(_Reply(content=b"")), now=lambda: FIXED_NOW)


def test_a_plain_http_source_is_refused_on_construction() -> None:
    """A citation into bytes an intermediary could have rewritten is not a citation."""

    with pytest.raises(ClubNewsFetchError, match="https"):
        ClubSource(club="Example FC", url="http://club.example/team-news")


# --- the retry rule ---------------------------------------------------------


def test_a_rate_limit_is_retried_and_then_succeeds() -> None:
    """429 says "later", so it is waited out rather than reported as a failure."""

    delays, sleeper = _slept()
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: [urllib.error.HTTPError(PAGE, 429, "Too Many", {}, None), _Reply()],  # type: ignore[arg-type]
        }
    )

    document = fetch_club_document(SOURCE, opener=opener, now=lambda: FIXED_NOW, sleeper=sleeper)

    assert document.club == "Example FC"
    assert delays == [2.0]


def test_a_forbidden_page_is_not_retried() -> None:
    """403 says "never", and asking again four times is neither polite nor useful."""

    delays, sleeper = _slept()
    forbidden = urllib.error.HTTPError(PAGE, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    with pytest.raises(ClubNewsFetchError, match="403"):
        read_url(PAGE, opener=_opener(forbidden), sleeper=sleeper)

    assert delays == []


def test_a_persistent_server_error_reports_every_attempt() -> None:
    """The number of attempts is in the message, so "it failed" is not the whole record."""

    delays, sleeper = _slept()
    broken = urllib.error.HTTPError(PAGE, 503, "Unavailable", {}, None)  # type: ignore[arg-type]
    opener = _Opener({ROBOTS: _allowing_robots(), PAGE: [broken, broken, broken, broken]})

    with pytest.raises(ClubNewsFetchError, match="all 4 attempts"):
        read_url(PAGE, opener=opener, sleeper=sleeper)

    assert delays == [2.0, 4.0, 8.0]


# --- one club failing does not fail the week --------------------------------


def test_a_refused_club_is_returned_beside_the_read_ones() -> None:
    """Declared and covered are different columns because this happens."""

    other = ClubSource(club="Other FC", url="https://other.example/news")
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(),
            "https://other.example/robots.txt": _allowing_robots(),
        }
    )

    documents, refused = fetch_registered_documents(
        (SOURCE, other), opener=opener, now=lambda: FIXED_NOW
    )

    assert [document.club for document in documents] == ["Example FC"]
    assert [club for club, _reason in refused] == ["Other FC"]
    assert "404" in refused[0][1]


def test_reading_no_source_is_refused() -> None:
    """An empty registry is not a week in which every club published nothing."""

    with pytest.raises(ClubNewsFetchError, match="nothing to read"):
        fetch_registered_documents(())


# --- the registry -----------------------------------------------------------


def test_the_committed_registry_reads() -> None:
    """It ships with a placeholder so the shape is exercised without naming a real host."""

    sources = load_club_sources(REGISTRY)

    assert [source.club for source in sources] == ["Example FC"]
    assert all(source.url.startswith("https://club.example") for source in sources)


def test_the_committed_registry_names_no_real_host() -> None:
    """Until a terms reading exists, the registry permits nothing real."""

    document = json.loads(REGISTRY.read_text(encoding="utf-8"))

    hosts = {entry["url"].split("/")[2] for entry in document["sources"]}
    assert hosts == {"club.example"}


def test_every_registered_source_points_at_a_terms_reading(tmp_path: Path) -> None:
    """The load-bearing field. Without it the entry is a permission nobody gave."""

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION,
                "sources": [{"club": "Example FC", "url": PAGE}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError, match="no 'terms_record'"):
        load_club_sources(path)


def _registry(tmp_path: Path, *entries: dict[str, str]) -> Path:
    """A registry file carrying exactly ``entries``, each with its terms pointer."""

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION,
                "sources": [
                    {"terms_record": "docs/club_news_sources.md", **entry} for entry in entries
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_one_page_registered_twice_is_refused(tmp_path: Path) -> None:
    """The same address twice is read twice and coded twice, from one sentence."""

    path = _registry(
        tmp_path, {"club": "Example FC", "url": PAGE}, {"club": "Example FC", "url": PAGE}
    )

    with pytest.raises(ClubNewsFetchError, match="twice"):
        load_club_sources(path)


def test_a_club_may_register_more_than_one_page(tmp_path: Path) -> None:
    """A club that splits team news and its injury table is registered, not refused.

    Nothing below joins a claim to a club's page -- a claim cites a document by digest and
    byte span -- so two pages for one club leave no question with two answers. Both entries
    survive in the declared order, because the fetch order is what makes two runs over one
    registry produce the same capture.
    """

    path = _registry(
        tmp_path,
        {"club": "Example FC", "url": "https://club.example/team-news"},
        {"club": "Example FC", "url": "https://club.example/injuries"},
    )

    sources = load_club_sources(path)

    assert [source.club for source in sources] == ["Example FC", "Example FC"]
    assert [source.url for source in sources] == [
        "https://club.example/team-news",
        "https://club.example/injuries",
    ]


def test_two_spellings_of_one_host_are_one_address(tmp_path: Path) -> None:
    """Host names are case-insensitive, so this is the same page registered twice."""

    path = _registry(
        tmp_path,
        {"club": "Example FC", "url": "https://club.example/team-news"},
        {"club": "Example FC", "url": "https://Club.Example/team-news"},
    )

    with pytest.raises(ClubNewsFetchError, match="twice"):
        load_club_sources(path)


def test_two_paths_differing_only_in_case_are_two_addresses(tmp_path: Path) -> None:
    """Paths are case-sensitive, and folding them would refuse a truthful registry.

    Whether a host serves the same bytes at both is the host's business and not something
    this module may assume; refusing here would turn a guess into a rejected permission.
    """

    path = _registry(
        tmp_path,
        {"club": "Example FC", "url": "https://club.example/team-news"},
        {"club": "Example FC", "url": "https://club.example/Team-News"},
    )

    assert len(load_club_sources(path)) == 2


def test_an_empty_registry_is_refused(tmp_path: Path) -> None:
    """A registry that permits nothing is an absent registry, not a permissive one."""

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps({"contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION, "sources": []}),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError, match="non-empty"):
        load_club_sources(path)


def test_a_registry_under_another_contract_is_refused(tmp_path: Path) -> None:
    """A registry read under one shape is a different statement about permission."""

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps({"contract_version": "club_news_sources_v2", "sources": []}),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError, match="declares contract"):
        load_club_sources(path)


def test_the_terms_record_the_registry_points_at_exists() -> None:
    """A pointer to a file nobody wrote is the same as no pointer."""

    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    root = REGISTRY.resolve().parents[2]

    for entry in document["sources"]:
        assert (root / entry["terms_record"]).is_file(), entry["terms_record"]


def test_registered_sources_are_read_in_the_declared_order(tmp_path: Path) -> None:
    """So two runs over one registry produce the same request order and the same capture."""

    path = tmp_path / "sources.json"
    clubs: Sequence[str] = ("C FC", "A FC", "B FC")
    path.write_text(
        json.dumps(
            {
                "contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION,
                "sources": [
                    {
                        "club": club,
                        "url": f"https://club.example/{index}",
                        "terms_record": "docs/club_news_sources.md",
                    }
                    for index, club in enumerate(clubs)
                ],
            }
        ),
        encoding="utf-8",
    )

    assert [source.club for source in load_club_sources(path)] == list(clubs)
