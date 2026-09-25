"""Reading a club's page, and the four refusals that come before the bytes are used.

Every test here is offline. The opener is injected, so what the adapter would have sent and
how it judges what came back are both asserted without a request leaving the machine --
which is also the only way to test a 429 followed by a 200, or a host that disallows us. The
few tests about how the real opener handles a redirect keep that promise another way: they
answer from a server on the loopback, or from a table put in place of urllib's https socket.

The refusals carry the weight. A fetch that fails loudly costs a club's coverage for one
week, which this lane records honestly; a fetch that succeeds with the wrong bytes puts a
citation in front of a member. So the tests below are mostly about the second never
happening quietly.
"""

import http.client
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from squadopt.platform.club_news_fetch import (
    CLUB_NEWS_SOURCES_CONTRACT_VERSION,
    MAXIMUM_ARTICLES_PER_HOST,
    MAXIMUM_DOCUMENT_BYTES,
    PER_ORIGIN_DELAY_SECONDS,
    TERMS_READING_VALID_DAYS,
    ClubNewsFetchError,
    ClubSource,
    SameOriginRedirects,
    article_links,
    default_opener,
    fetch_club_document,
    fetch_registered_documents,
    load_club_sources,
    read_url,
    robots_allows,
)

REGISTRY = Path(__file__).resolve().parents[2] / "data" / "sources" / "club_news_sources.json"

PAGE = "https://club.example/team-news"
ROBOTS = "https://club.example/robots.txt"
#: A reading eleven days before the pinned clock, so every test below is inside the interval
#: unless it says otherwise.
READ_ON = date(2026, 9, 1)
SOURCE = ClubSource(club="Example FC", url=PAGE, terms_read_on=READ_ON)
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


# --- a redirect is followed only within the origin that was asked --------------


@contextmanager
def _loopback_host(
    routes: dict[str, tuple[int, dict[str, str], bytes]],
) -> Iterator[tuple[str, list[str]]]:
    """A real HTTP server on the loopback, answering ``routes`` by path and recording each GET.

    The fake opener above cannot show what this section is about: it hands back a prepared
    ``final_url`` and never makes the request a redirect would make. Only a real transport
    shows whether a redirect's target was sent a request, so these tests use one.
    """

    requested: list[str] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requested.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a machine's proxy settings from carrying loopback requests anywhere else."""

    monkeypatch.setenv("no_proxy", "*")


@pytest.mark.usefixtures("_no_proxy")
def test_a_redirect_to_another_origin_is_never_requested_from_it() -> None:
    """The other host is sent nothing, rather than sent a request whose answer is discarded.

    The origin check in ``fetch_club_document`` reads the final URL, which exists only after
    the request to it has gone. An article link is printed by a club's page and nobody checked
    where it redirects, so the transport itself must stop at the redirect: the second server
    here stands for a host with no reading and no ``robots.txt`` asked, and it is never called.
    """

    registered_routes: dict[str, tuple[int, dict[str, str], bytes]] = {}
    elsewhere_routes = {"/elsewhere": (200, {"Content-Type": "text/html"}, b"<p>Other.</p>")}
    with (
        _loopback_host(elsewhere_routes) as (elsewhere, elsewhere_requested),
        _loopback_host(registered_routes) as (origin, requested),
    ):
        registered_routes["/news/article"] = (302, {"Location": f"{elsewhere}/elsewhere"}, b"")

        with pytest.raises(ClubNewsFetchError, match="HTTP 302") as refusal:
            read_url(f"{origin}/news/article", opener=default_opener, sleeper=lambda _: None)

    assert requested == ["/news/article"]
    assert elsewhere_requested == []
    assert "another origin" in str(refusal.value)


@pytest.mark.usefixtures("_no_proxy")
def test_a_redirect_within_the_origin_is_still_followed() -> None:
    """A page that moved on its own host is read where it moved to, as before."""

    routes = {
        "/news/old": (301, {"Location": "/news/new"}, b""),
        "/news/new": (200, {"Content-Type": "text/html"}, b"<p>Moved.</p>"),
    }
    with _loopback_host(routes) as (origin, requested):
        read = read_url(f"{origin}/news/old", opener=default_opener, sleeper=lambda _: None)

    assert requested == ["/news/old", "/news/new"]
    assert read.final_url == f"{origin}/news/new"
    assert read.content == b"<p>Moved.</p>"


def test_the_redirect_rule_compares_origins_before_anything_is_sent() -> None:
    """Driven directly: a new request is built only for the same scheme, host and port.

    The host is compared without case, as host names are; another port or plain http is
    another origin, as it is for the registry.
    """

    handler = SameOriginRedirects()
    request = urllib.request.Request(ARTICLE_ONE)
    headers = http.client.HTTPMessage()

    followed = handler.redirect_request(
        request, io.BytesIO(), 302, "Found", headers, "https://Club.Example/team-news/b"
    )

    assert followed is not None
    assert followed.full_url == "https://Club.Example/team-news/b"
    for elsewhere in (
        "https://other.example/team-news/b",
        "https://club.example:8443/team-news/b",
        "http://club.example/team-news/b",
    ):
        with pytest.raises(urllib.error.HTTPError, match="another origin"):
            handler.redirect_request(request, io.BytesIO(), 302, "Found", headers, elsewhere)


class _HttpsTable:
    """urllib's https socket replaced by a table, with every request it is handed recorded.

    Only the socket goes. ``default_opener`` still builds its own opener, the redirect handler
    still decides whether a 30x is followed, and a followed one still arrives here as a new
    request, so what is recorded is what a real run would have sent. That lets the whole
    reader, with its https-only sources, run through the real transport offline.
    """

    def __init__(self, routes: dict[str, tuple[int, dict[str, str], bytes]]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def answer(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        self.requested.append(request.full_url)
        status, headers, body = self.routes.get(request.full_url, (404, {}, b""))
        message = http.client.HTTPMessage()
        for name, value in headers.items():
            message[name] = value
        response = urllib.response.addinfourl(io.BytesIO(body), message, request.full_url, status)
        # What `http.client` sets and urllib's error processor reads as the reason phrase.
        response.msg = http.client.responses.get(status, "")  # type: ignore[attr-defined]
        return response


def _answer_https_from(monkeypatch: pytest.MonkeyPatch, routes: Any) -> _HttpsTable:
    table = _HttpsTable(routes)
    monkeypatch.setattr(
        urllib.request.HTTPSHandler,
        "https_open",
        lambda _handler, request: table.answer(request),
    )
    return table


_ALLOW_ALL = (200, {"Content-Type": "text/plain"}, b"User-agent: *\nAllow: /\n")


@pytest.mark.usefixtures("_no_proxy")
def test_an_article_that_redirects_off_the_host_sends_that_host_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path article links opened, read the way a real run reads it.

    A registered address is one somebody checked. An article link is printed by the club's
    page, and nobody checked where it redirects. Here one redirects to a host with no reading:
    that host receives no request, the article is named as not read, and the club's other
    article and its registered page are read as before.
    """

    moved = f"{PAGE}/moved"
    elsewhere = "https://other.example/team-news/moved"
    page = b"<a href='/team-news/moved'>Moved</a><a href='/team-news/saka-fit'>Saka</a>"
    table = _answer_https_from(
        monkeypatch,
        {
            ROBOTS: _ALLOW_ALL,
            PAGE: (200, {"Content-Type": "text/html"}, page),
            moved: (302, {"Location": elsewhere}, b""),
            "https://other.example/robots.txt": _ALLOW_ALL,
            elsewhere: (200, {"Content-Type": "text/html"}, b"<p>Elsewhere.</p>"),
            ARTICLE_ONE: (200, {"Content-Type": "text/html"}, ARTICLE_ONE_BODY),
        },
    )

    documents, refused = fetch_registered_documents(
        (SOURCE,), now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert table.requested == [ROBOTS, PAGE, moved, ARTICLE_ONE]
    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_ONE]
    assert len(refused) == 1
    club, reason = refused[0]
    assert club == "Example FC"
    assert f"An article linked from {PAGE}" in reason
    assert "HTTP 302" in reason
    assert "another origin" in reason


@pytest.mark.usefixtures("_no_proxy")
def test_a_robots_file_that_redirects_off_the_host_is_one_that_could_not_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another host's ``robots.txt`` does not answer for this one, so the host is refused.

    Following the redirect used to parse the other host's file as this host's preference.
    Now the other host is sent nothing, the preference is unknown, and the club is recorded
    as not covered, which is what an unreadable ``robots.txt`` has always cost.
    """

    table = _answer_https_from(
        monkeypatch,
        {
            ROBOTS: (301, {"Location": "https://other.example/robots.txt"}, b""),
            "https://other.example/robots.txt": _ALLOW_ALL,
            PAGE: (200, {"Content-Type": "text/html"}, b"<p>News.</p>"),
        },
    )

    documents, refused = fetch_registered_documents(
        (SOURCE,), now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert table.requested == [ROBOTS]
    assert documents == ()
    assert len(refused) == 1
    club, reason = refused[0]
    assert club == "Example FC"
    assert "could not be read" in reason
    assert "HTTP 301" in reason


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
        ClubSource(club="Example FC", url="http://club.example/team-news", terms_read_on=READ_ON)


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

    other = ClubSource(club="Other FC", url="https://other.example/news", terms_read_on=READ_ON)
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
        ClubSource(club="Example FC", url=f"https://club.example/{path}", terms_read_on=READ_ON)
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

    other = ClubSource(club="Other FC", url="https://other.example/news", terms_read_on=READ_ON)
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


def _registry(tmp_path: Path, *entries: dict[str, str | None]) -> Path:
    """A registry file carrying exactly ``entries``, each with its terms pointer."""

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION,
                "sources": [
                    {
                        "terms_record": "docs/club_news_sources.md",
                        "terms_read_on": READ_ON.isoformat(),
                        **entry,
                    }
                    for entry in entries
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
        json.dumps({"contract_version": "club_news_sources_v1", "sources": []}),
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
                        "terms_read_on": READ_ON.isoformat(),
                    }
                    for index, club in enumerate(clubs)
                ],
            }
        ),
        encoding="utf-8",
    )

    assert [source.club for source in load_club_sources(path)] == list(clubs)


# --- a registered page, followed to its articles ------------------------------

ARTICLE_ONE = "https://club.example/team-news/saka-fit"
ARTICLE_TWO = "https://club.example/team-news/press-conference"
DEEPER = "https://club.example/team-news/deeper"
PRIVATE = "https://club.example/team-news/private/injury-list"
OFF_HOST = "https://other.example/team-news/rumour"
#: Where three links printed with a dot segment would land. The first is what a browser makes
#: of ``/team-news/a/../b``; the other two are addresses a server may normalise out from under
#: the path ``robots.txt`` judged. All three sit under the index's own path as the prefix rule
#: reads it, so only the dot rule keeps them out.
DOT_RESOLVED = "https://club.example/team-news/b"
DOT_ENCODED = "https://club.example/team-news/%2e%2e/tickets"
DOT_ABSOLUTE = "https://club.example/team-news/./x"

#: An index written the way a club writes one: navigation, a list of headlines, and links
#: that must not be followed sitting between the ones that must.
INDEX = (
    "<html><head><title>News</title></head><body>"
    "<nav><a href='/tickets'>Tickets</a> <a href='/team-news'>News</a></nav>"
    "<ul>"
    "<li><a href='/team-news/saka-fit'>Saka fit for Saturday</a></li>"
    "<li><a href='https://club.example/team-news/press-conference#video'>Press</a></li>"
    "<li><a href='/team-news/saka-fit#comments'>Comments</a></li>"
    "<li><a href='https://other.example/team-news/rumour'>Elsewhere</a></li>"
    "<li><a href='//other.example/team-news/rumour'>Elsewhere, relative</a></li>"
    "<li><a href='https://club.example.other.example/team-news/x'>Look-alike</a></li>"
    "<li><a href='https://club.example:8443/team-news/x'>Another port</a></li>"
    "<li><a href='http://club.example/team-news/insecure'>Plain http</a></li>"
    "<li><a href='/team-news/private/injury-list'>Private</a></li>"
    "<li><a href='/team-news/../tickets'>Climbing out</a></li>"
    "<li><a href='/team-news/a/../b'>Climbing back in</a></li>"
    "<li><a href='/team-news/%2e%2e/tickets'>Climbing out, encoded</a></li>"
    "<li><a href='//club.example/team-news/./x'>A dot, protocol-relative</a></li>"
    "<li><a href='/team-news/café'>Not ASCII</a></li>"
    "<li><a href='mailto:press@club.example'>Mail</a></li>"
    "</ul></body></html>"
).encode()

ARTICLE_ONE_BODY = (
    b"<article><h1>Saka fit</h1><p>Saka trained fully on Thursday.</p>"
    b"<a href='/team-news/deeper'>Read more</a></article>"
)
ARTICLE_TWO_BODY = b"<article><h1>Press conference</h1><p>Rice is rested for the cup.</p></article>"


def _robots_keeping_private() -> _Reply:
    return _allowing_robots(b"User-agent: *\nDisallow: /team-news/private\n")


def _news_host(**overrides: Any) -> _Opener:
    """The index above, its two articles, and every link that must stay unrequested served too.

    Serving the off-host and deeper pages is deliberate: a test that only proved they were
    not served could pass while the reader asked for them anyway.
    """

    replies: dict[str, Any] = {
        ROBOTS: _robots_keeping_private(),
        PAGE: _Reply(INDEX),
        ARTICLE_ONE: _Reply(ARTICLE_ONE_BODY, final_url=ARTICLE_ONE),
        ARTICLE_TWO: _Reply(ARTICLE_TWO_BODY, final_url=ARTICLE_TWO),
        DEEPER: _Reply(b"<p>Deeper.</p>", final_url=DEEPER),
        PRIVATE: _Reply(b"<p>Private.</p>", final_url=PRIVATE),
        OFF_HOST: _Reply(b"<p>Rumour.</p>", final_url=OFF_HOST),
        "https://other.example/robots.txt": _allowing_robots(),
        DOT_RESOLVED: _Reply(b"<p>Resolved.</p>", final_url=DOT_RESOLVED),
        DOT_ENCODED: _Reply(b"<p>Encoded.</p>", final_url=DOT_ENCODED),
        DOT_ABSOLUTE: _Reply(b"<p>Absolute.</p>", final_url=DOT_ABSOLUTE),
    }
    replies.update(overrides)
    return _Opener(replies)


def _read_news_host(opener: _Opener) -> tuple[Any, Any]:
    return fetch_registered_documents(
        (SOURCE,), opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )


def test_a_registered_page_is_followed_to_its_articles_on_the_same_host() -> None:
    """I67: an index carries headlines, and the words a claim quotes are on the article.

    Each article is its own document, in the order the index lists it, carrying the index's
    club and its own readable text, so a claim cites the article and not the headline.
    """

    documents, _refused = _read_news_host(_news_host())

    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_ONE, ARTICLE_TWO]
    assert {document.club for document in documents} == {"Example FC"}
    one, two = documents[1], documents[2]
    assert b"Saka trained fully on Thursday." in one.readable
    assert b"Rice is rested" not in one.readable
    assert b"Rice is rested for the cup." in two.readable
    assert one.content == ARTICLE_ONE_BODY


def test_no_link_off_the_registered_origin_is_ever_requested() -> None:
    """Another host, a look-alike host, another port or plain http: none is registered."""

    opener = _news_host()

    _read_news_host(opener)

    assert sorted(set(opener.requested)) == sorted({ROBOTS, PAGE, ARTICLE_ONE, ARTICLE_TWO})
    assert not any("other.example" in url or url.startswith("http:") for url in opener.requested)


def test_an_articles_own_links_are_not_followed() -> None:
    """One step from a registered page and no further; this is not a crawler."""

    opener = _news_host()

    _read_news_host(opener)

    assert DEEPER not in opener.requested


def test_an_article_robots_disallows_is_not_requested_and_is_named() -> None:
    """The host's stated preference decides each article path, as it decides the index."""

    opener = _news_host()

    documents, refused = _read_news_host(opener)

    assert PRIVATE not in opener.requested
    assert PRIVATE not in [document.requested_url for document in documents]
    assert len(refused) == 1
    club, reason = refused[0]
    assert club == "Example FC"
    assert f"An article linked from {PAGE}" in reason
    assert "disallows" in reason
    assert PRIVATE in reason


def test_robots_is_asked_once_for_the_index_and_its_articles() -> None:
    """The articles are paths of a host this run has already asked."""

    opener = _news_host()

    _read_news_host(opener)

    assert opener.requested.count(ROBOTS) == 1


def test_every_article_request_waits_like_any_second_request() -> None:
    """Robots, the index and two articles: the first contact is free, the other three wait."""

    delays, sleeper = _slept()

    fetch_registered_documents(
        (SOURCE,), opener=_news_host(), now=lambda: FIXED_NOW, sleeper=sleeper
    )

    assert delays == [PER_ORIGIN_DELAY_SECONDS] * 3


def test_the_link_rule_keeps_same_origin_links_under_the_page_in_page_order() -> None:
    """The rule itself, before robots: the private path is a link and robots judges it later."""

    opener = _Opener({ROBOTS: _allowing_robots(), PAGE: _Reply(INDEX)})
    index = fetch_club_document(SOURCE, opener=opener, now=lambda: FIXED_NOW)

    assert article_links(SOURCE, index) == (ARTICLE_ONE, ARTICLE_TWO, PRIVATE)


def test_a_failed_article_costs_the_article_and_not_the_club() -> None:
    """The registered page was read, so the club is read; the article is named as missing."""

    missing = urllib.error.HTTPError(ARTICLE_TWO, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    documents, refused = _read_news_host(_news_host(**{ARTICLE_TWO: missing}))

    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_ONE]
    reasons = [reason for _club, reason in refused]
    assert any(ARTICLE_TWO in reason and "404" in reason for reason in reasons), reasons
    assert all(reason.startswith("An article linked from") for reason in reasons)


def test_an_article_answered_by_a_page_already_read_is_not_stored_twice() -> None:
    """A removed article that redirects to the index would give one URL two sets of bytes."""

    back_to_index = _Reply(INDEX, final_url=PAGE)

    documents, refused = _read_news_host(_news_host(**{ARTICLE_ONE: back_to_index}))

    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_TWO]
    assert any("not stored a second time" in reason for _club, reason in refused)


def test_a_registered_page_linked_from_another_is_read_once_as_itself() -> None:
    """A link to a registered page is left for that page's own entry, so it is read once."""

    injuries = "https://club.example/team-news/injuries"
    index = b"<a href='/team-news/injuries'>Injuries</a><a href='/team-news/saka-fit'>Saka</a>"
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(index),
            injuries: _Reply(b"<p>Nobody is injured.</p>", final_url=injuries),
            ARTICLE_ONE: _Reply(ARTICLE_ONE_BODY, final_url=ARTICLE_ONE),
        }
    )
    registered = (SOURCE, ClubSource(club="Example FC", url=injuries, terms_read_on=READ_ON))

    documents, refused = fetch_registered_documents(
        registered, opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert refused == ()
    assert opener.requested.count(injuries) == 1
    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_ONE, injuries]


def test_articles_are_capped_per_host_across_every_registered_page_it_serves() -> None:
    """One server, one budget: two indexes on one host share the cap, in registry order."""

    injuries = "https://club.example/injuries"
    replies: dict[str, Any] = {ROBOTS: _allowing_robots()}
    linked: dict[str, list[str]] = {PAGE: [], injuries: []}
    for page, path in ((PAGE, "/team-news"), (injuries, "/injuries")):
        for number in range(MAXIMUM_ARTICLES_PER_HOST):
            url = f"https://club.example{path}/item-{number}"
            linked[page].append(url)
            replies[url] = _Reply(f"<p>Item {number}.</p>".encode(), final_url=url)
        body = "".join(f"<a href='{url}'>{url}</a>" for url in linked[page])
        replies[page] = _Reply(body.encode(), final_url=page)
    registered = (SOURCE, ClubSource(club="Example FC", url=injuries, terms_read_on=READ_ON))
    opener = _Opener(replies)

    documents, refused = fetch_registered_documents(
        registered, opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    read = [document.requested_url for document in documents]
    articles = [url for url in read if url not in (PAGE, injuries)]
    assert refused == ()
    assert read.count(injuries) == 1
    assert articles == linked[PAGE][:MAXIMUM_ARTICLES_PER_HOST]
    assert not any(url in opener.requested for url in linked[injuries])


def test_a_feed_is_read_but_its_item_links_are_not_followed() -> None:
    """A feed already carries its items' words, so following them would read them twice."""

    feed = (
        b"<rss><channel><item><title>Saka fit</title>"
        b"<link>https://club.example/team-news/saka-fit</link>"
        b"<description>Saka trained fully.</description></item></channel></rss>"
    )
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(feed, content_type="application/rss+xml"),
            ARTICLE_ONE: _Reply(ARTICLE_ONE_BODY, final_url=ARTICLE_ONE),
        }
    )

    documents, _refused = fetch_registered_documents(
        (SOURCE,), opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert [document.requested_url for document in documents] == [PAGE]
    assert ARTICLE_ONE not in opener.requested


def test_a_page_registered_at_the_root_of_its_host_follows_nothing() -> None:
    """With no path to be under, every link on the site would count, so none does."""

    root = ClubSource(club="Example FC", url="https://club.example/", terms_read_on=READ_ON)
    opener = _Opener({ROBOTS: _allowing_robots(), root.url: _Reply(INDEX, final_url=root.url)})
    index = fetch_club_document(root, opener=opener, now=lambda: FIXED_NOW)

    assert article_links(root, index) == ()


def test_a_link_printed_with_a_dot_segment_is_skipped_and_not_resolved() -> None:
    """Literal or encoded, relative or absolute: the page did not print a clean address.

    ``/team-news/a/../b`` is the case that shows the rule is about what was printed. A browser
    resolves it to ``/team-news/b``, which is under the index and would pass every other rule,
    so only a check on the printed path keeps the reader from requesting an address the page
    never wrote down.
    """

    opener = _news_host()

    documents, _refused = _read_news_host(opener)

    for skipped in (DOT_RESOLVED, DOT_ENCODED, DOT_ABSOLUTE):
        assert skipped not in opener.requested, skipped
        assert skipped not in [document.requested_url for document in documents], skipped


def test_a_link_resolved_against_a_served_address_with_a_dot_segment_is_skipped() -> None:
    """The printed link is clean here; the address it resolves against is not.

    A query-only link keeps the served page's path as it arrived, encoded dot included, so
    the resolved path is checked as well as the printed one.
    """

    served_at = f"{PAGE}/%2e/list"
    page = b"<a href='?page=2'>Next</a><a href='/team-news/saka-fit'>Saka</a>"
    opener = _Opener({ROBOTS: _allowing_robots(), PAGE: _Reply(page, final_url=served_at)})
    index = fetch_club_document(SOURCE, opener=opener, now=lambda: FIXED_NOW)

    assert article_links(SOURCE, index) == (ARTICLE_ONE,)


def test_links_are_judged_against_the_registered_path_and_not_the_served_one() -> None:
    """A same-origin redirect to a shallower path does not widen what is followed.

    ``/team-news`` answered at ``/en`` would otherwise make everything under ``/en`` an
    article, tickets and shop included, which is not what "``/news`` leads to ``/news/...``"
    in the permission record says. A page served somewhere else is registered where it is
    served, as Newcastle was.
    """

    served_at = "https://club.example/en"
    tickets = "https://club.example/en/tickets/buy"
    shop = "https://club.example/en/shop/x"
    page = (
        b"<a href='/en/tickets/buy'>Tickets</a>"
        b"<a href='/team-news/saka-fit'>Saka</a>"
        b"<a href='/en/shop/x'>Shop</a>"
    )
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(page, final_url=served_at),
            ARTICLE_ONE: _Reply(ARTICLE_ONE_BODY, final_url=ARTICLE_ONE),
            tickets: _Reply(b"<p>Tickets.</p>", final_url=tickets),
            shop: _Reply(b"<p>Shop.</p>", final_url=shop),
        }
    )

    documents, refused = _read_news_host(opener)

    assert refused == ()
    assert [document.requested_url for document in documents] == [PAGE, ARTICLE_ONE]
    assert tickets not in opener.requested
    assert shop not in opener.requested


# --- a reading ages -----------------------------------------------------------


def _dated(read_on: date | None) -> ClubSource:
    return ClubSource(club="Example FC", url=PAGE, terms_read_on=read_on)


def test_a_host_whose_reading_has_aged_is_not_contacted_at_all() -> None:
    """F26: not the page and not its robots.txt. A stale reading is refused before a request."""

    opener = _opener()
    stale = FIXED_NOW.date() - timedelta(days=TERMS_READING_VALID_DAYS + 1)

    with pytest.raises(ClubNewsFetchError, match="days old") as refusal:
        fetch_club_document(_dated(stale), opener=opener, now=lambda: FIXED_NOW)

    assert opener.requested == []
    assert stale.isoformat() in str(refusal.value)
    assert "docs/club_news_sources.md" in str(refusal.value)


def test_a_reading_is_relied_on_through_its_last_day() -> None:
    """The boundary, pinned: exactly the interval old is still inside it."""

    last_day = FIXED_NOW.date() - timedelta(days=TERMS_READING_VALID_DAYS)

    document = fetch_club_document(_dated(last_day), opener=_opener(), now=lambda: FIXED_NOW)

    assert document.club == "Example FC"


def test_an_undated_host_is_not_contacted_at_all() -> None:
    """Nobody read it, which is the placeholder's case, and unread is not fine."""

    opener = _opener()

    with pytest.raises(ClubNewsFetchError, match="Nobody has dated"):
        fetch_club_document(_dated(None), opener=opener, now=lambda: FIXED_NOW)

    assert opener.requested == []


def test_a_reading_dated_after_the_fetch_is_refused() -> None:
    """A typo in the year would otherwise stretch a permission by a year."""

    opener = _opener()
    future = FIXED_NOW.date() + timedelta(days=2)

    with pytest.raises(ClubNewsFetchError, match="after this fetch"):
        fetch_club_document(_dated(future), opener=opener, now=lambda: FIXED_NOW)

    assert opener.requested == []


def test_a_reading_signed_a_day_ahead_of_utc_is_read() -> None:
    """A reader east of UTC can sign on a date UTC has not reached yet."""

    tomorrow = FIXED_NOW.date() + timedelta(days=1)

    document = fetch_club_document(_dated(tomorrow), opener=_opener(), now=lambda: FIXED_NOW)

    assert document.club == "Example FC"


def test_a_stale_host_costs_its_club_and_not_the_week() -> None:
    """The refusal arrives in the per-club currency, beside the clubs that were read."""

    stale = _dated(FIXED_NOW.date() - timedelta(days=TERMS_READING_VALID_DAYS + 30))
    other = ClubSource(club="Other FC", url="https://other.example/news", terms_read_on=READ_ON)
    opener = _Opener(
        {
            ROBOTS: _allowing_robots(),
            PAGE: _Reply(),
            "https://other.example/robots.txt": _allowing_robots(),
            other.url: _Reply(final_url=other.url),
        }
    )

    documents, refused = fetch_registered_documents(
        (stale, other), opener=opener, now=lambda: FIXED_NOW, sleeper=lambda _: None
    )

    assert [document.club for document in documents] == ["Other FC"]
    assert [club for club, _reason in refused] == ["Example FC"]
    assert not any(url.startswith("https://club.example") for url in opener.requested)


def test_an_entry_with_no_reading_date_is_refused(tmp_path: Path) -> None:
    """The key is required even where the answer is null: silence is not a date."""

    path = tmp_path / "sources.json"
    entry = {"club": "Example FC", "url": PAGE, "terms_record": "docs/club_news_sources.md"}
    path.write_text(
        json.dumps({"contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION, "sources": [entry]}),
        encoding="utf-8",
    )

    with pytest.raises(ClubNewsFetchError, match="no 'terms_read_on'"):
        load_club_sources(path)


def test_a_reading_date_the_rule_cannot_read_is_refused(tmp_path: Path) -> None:
    """A date written the local way is a reading the age rule cannot judge."""

    path = _registry(tmp_path, {"club": "Example FC", "url": PAGE, "terms_read_on": "22/09/2026"})

    with pytest.raises(ClubNewsFetchError, match="not a YYYY-MM-DD"):
        load_club_sources(path)


def test_a_null_reading_date_loads_and_is_carried_as_absent(tmp_path: Path) -> None:
    """The placeholder's honest value reads; it is the fetch that refuses it."""

    path = _registry(tmp_path, {"club": "Example FC", "url": PAGE, "terms_read_on": None})

    (source,) = load_club_sources(path)

    assert source.terms_read_on is None


def test_one_host_dated_twice_is_refused(tmp_path: Path) -> None:
    """A reading is of a host, so two of its pages cannot disagree about when it was read."""

    path = _registry(
        tmp_path,
        {"club": "Example FC", "url": PAGE, "terms_read_on": "2026-09-01"},
        {
            "club": "Example FC",
            "url": "https://Club.Example/injuries",
            "terms_read_on": "2026-09-02",
        },
    )

    with pytest.raises(ClubNewsFetchError, match="every page of one host"):
        load_club_sources(path)


def test_the_committed_registry_dates_match_the_signed_rows() -> None:
    """The registry's date is copied from the table, and the two may not drift apart.

    A row re-signed without the registry moving would keep refusing a host somebody just
    read, and a registry date moved without the row would be a permission nobody signed.
    """

    rows = _reading_rows()

    for source in load_club_sources(REGISTRY):
        host = urllib.parse.urlsplit(source.url).netloc
        _reader, signed = rows[host]
        if source.terms_read_on is None:
            assert signed == "—", host
        else:
            assert signed == source.terms_read_on.isoformat(), host


def test_the_documented_interval_and_expiry_dates_are_the_codes() -> None:
    """Prose that states a number is checked against the number it states."""

    document = (REGISTRY.parents[2] / "docs" / "club_news_sources.md").read_text(encoding="utf-8")

    assert f"{TERMS_READING_VALID_DAYS} days" in document
    for source in load_club_sources(REGISTRY):
        if source.terms_read_on is not None:
            last_day = source.terms_read_on + timedelta(days=TERMS_READING_VALID_DAYS)
            assert f"through {last_day.isoformat()}" in document, source.url
