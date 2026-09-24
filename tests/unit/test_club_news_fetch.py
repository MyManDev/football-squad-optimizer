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
    PER_ORIGIN_DELAY_SECONDS,
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


def test_a_redirect_within_the_same_origin_is_followed() -> None:
    """The same host answering a different path is the case the citation rule is for."""

    served = _Reply(final_url=f"{PAGE}/full")

    document = fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)

    assert document.requested_url == PAGE
    assert document.final_url == f"{PAGE}/full"


def test_a_redirect_to_another_origin_is_refused() -> None:
    """Consent does not travel across a redirect, and a real host proved it.

    `robots_allows` asks the origin the registry names. A redirect can be answered by a
    different host whose preference nobody asked and whose terms nobody read, so following
    it would let one host's consent stand in for another's. `www.nufc.co.uk/news` redirects
    to `www.newcastleunited.com/en/news`, and the first real run read one host under a
    reading signed for the other (#781).
    """

    served = _Reply(final_url="https://cdn.other.example/team-news")

    with pytest.raises(ClubNewsFetchError) as refusal:
        fetch_club_document(SOURCE, opener=_opener(served), now=lambda: FIXED_NOW)

    message = str(refusal.value)
    assert "https://cdn.other.example" in message
    assert "https://club.example" in message


def test_the_origin_refusal_follows_the_robots_switch() -> None:
    """A caller that has already decided not to ask is not told it failed to ask.

    ``check_robots=False`` is the replay path, where the preference was consulted when the
    capture was taken and the bytes are being re-read from disk. Refusing there would refuse
    a page whose consent was established, for a redirect that already happened.
    """

    served = _Reply(final_url="https://cdn.other.example/team-news")

    document = fetch_club_document(
        SOURCE, opener=_opener(served), now=lambda: FIXED_NOW, check_robots=False
    )

    assert document.final_url == "https://cdn.other.example/team-news"


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


# --- one host, asked once -----------------------------------------------------


def _three_pages_on_one_host() -> tuple[tuple[ClubSource, ...], _Opener]:
    """One club publishing on three paths, which the registry now permits."""

    sources = tuple(
        ClubSource(club="Example FC", url=f"https://club.example/{path}")
        for path in ("team-news", "injuries", "press-conference")
    )
    replies: dict[str, Any] = {ROBOTS: _allowing_robots()}
    for source in sources:
        replies[source.url] = _Reply(final_url=source.url)
    return sources, _Opener(replies)


def test_one_host_is_asked_for_its_robots_once_however_many_pages_it_serves() -> None:
    """Counted, not assumed. Three pages used to mean three identical questions.

    The verdicts are unchanged: one `robots.txt` decides every path of its host, so deciding
    them locally removes requests without moving a single answer.
    """

    sources, opener = _three_pages_on_one_host()

    documents, refused = fetch_registered_documents(
        sources, opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert refused == ()
    assert len(documents) == 3
    assert opener.requested.count(ROBOTS) == 1


def test_a_second_request_to_one_host_waits() -> None:
    """Politeness is owed to the machine answering, and it is measured through the clock."""

    sources, opener = _three_pages_on_one_host()
    delays, sleeper = _slept()

    fetch_registered_documents(sources, opener=opener, now=lambda: FIXED_NOW, sleeper=sleeper)

    # One robots request and three documents: the first contact is free, the other three wait.
    assert delays == [PER_ORIGIN_DELAY_SECONDS] * 3


def test_two_hosts_do_not_wait_for_each_other() -> None:
    """The debt is owed per host, so a slow neighbour does not slow an unrelated club."""

    other = ClubSource(club="Other FC", url="https://other.example/news")
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(),
            "https://other.example/robots.txt": _allowing_robots(),
            other.url: _Reply(final_url=other.url),
        }
    )
    delays, sleeper = _slept()

    documents, refused = fetch_registered_documents(
        (SOURCE, other), opener=opener, now=lambda: FIXED_NOW, sleeper=sleeper
    )

    assert refused == ()
    assert len(documents) == 2
    # Each host is contacted twice -- its robots and its one page -- so each waits once.
    assert delays == [PER_ORIGIN_DELAY_SECONDS, PER_ORIGIN_DELAY_SECONDS]


def test_a_host_whose_robots_cannot_be_read_is_asked_once_and_refuses_every_page() -> None:
    """Re-asking would not make the answer less unknown; it would only ask again."""

    sources, _opener = _three_pages_on_one_host()
    broken = urllib.error.HTTPError(ROBOTS, 500, "Server Error", {}, None)  # type: ignore[arg-type]
    replies: dict[str, Any] = {ROBOTS: broken}
    for source in sources:
        replies[source.url] = _Reply(final_url=source.url)
    opener = _Opener(replies)

    documents, refused = fetch_registered_documents(
        sources, opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert documents == ()
    assert len(refused) == 3
    assert all("preference is unknown" in reason for _club, reason in refused)
    assert opener.requested.count(ROBOTS) == 1


def test_each_refused_page_is_named_in_its_own_refusal() -> None:
    """A club is not told its page was refused under another club's address.

    Remembering the host's answer once is right; remembering the whole composed refusal was
    not. That message names the page it costs, so every later page of the host inherited the
    first page's URL -- and since one host can serve several clubs, a club could be handed a
    refusal pointing at a page that is not its own.
    """

    sources, _unused = _three_pages_on_one_host()
    broken = urllib.error.HTTPError(ROBOTS, 500, "Server Error", {}, None)  # type: ignore[arg-type]
    replies: dict[str, Any] = {ROBOTS: broken}
    for source in sources:
        replies[source.url] = _Reply(final_url=source.url)

    _documents, refused = fetch_registered_documents(
        sources, opener=_Opener(replies), now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert len(refused) == len(sources)
    for source, (_club, reason) in zip(sources, refused, strict=True):
        assert source.url in reason, reason
        others = [other.url for other in sources if other.url != source.url]
        assert not any(other in reason for other in others), reason


def test_a_host_serving_no_robots_is_asked_once_and_allows_every_page() -> None:
    """A 404 is silence, and silence is stated once for the whole host."""

    sources, _opener = _three_pages_on_one_host()
    replies: dict[str, Any] = {}
    for source in sources:
        replies[source.url] = _Reply(final_url=source.url)
    opener = _Opener(replies)

    documents, refused = fetch_registered_documents(
        sources, opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert refused == ()
    assert len(documents) == 3
    assert opener.requested.count(ROBOTS) == 1


# --- the registry -----------------------------------------------------------


def test_the_committed_registry_reads() -> None:
    """It loads, and it keeps the placeholder the offline fixture serves.

    The placeholder is not scaffolding left behind. It is the entry that exercises the
    reader when no real host is reachable, and nothing ever requests it.
    """

    sources = load_club_sources(REGISTRY)

    assert "Example FC" in {source.club for source in sources}
    assert any(source.url.startswith("https://club.example") for source in sources)


def _reading_rows() -> dict[str, tuple[str, str]]:
    """Host -> (read by, date), from the readings table in ``docs/club_news_sources.md``."""

    document = REGISTRY.parents[2] / "docs" / "club_news_sources.md"
    rows: dict[str, tuple[str, str]] = {}
    for line in document.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 6 or cells[0].startswith(("Host", "---")):
            continue
        rows[cells[0].strip("`")] = (cells[4], cells[5])
    return rows


def test_every_registered_host_has_a_signed_reading() -> None:
    """The rule the registry rests on, held against the document rather than described.

    This replaces a test that asserted no real host was registered, which was true until
    one was and then said nothing. What it was protecting is this: an entry whose host has
    no dated, signed reading is a permission nobody granted, and the placeholder is the
    one host exempt because no request is ever made for it.
    """

    document = json.loads(REGISTRY.read_text(encoding="utf-8"))
    rows = _reading_rows()

    unsigned = []
    for entry in document["sources"]:
        host = entry["url"].split("/")[2]
        if host == "club.example":
            continue
        reader, date = rows.get(host, ("", ""))
        if not reader or not date or reader == "\u2014" or date == "\u2014":
            unsigned.append(host)

    assert not unsigned, (
        "These hosts are registered and have no signed, dated reading in "
        f"docs/club_news_sources.md: {sorted(unsigned)}. A reading is a person's "
        "judgement and the registry is what it permits."
    )


def test_the_placeholder_is_the_only_unsigned_row() -> None:
    """A row without a name is a row nobody stands behind, and only one may exist."""

    unsigned = {
        host
        for host, (reader, date) in _reading_rows().items()
        if not reader.strip("\u2014 ") or not date.strip("\u2014 ")
    }

    assert unsigned == {"club.example"}


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
