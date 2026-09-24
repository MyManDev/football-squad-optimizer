"""Network adapter for one club's own words, and the refusals that come before the request.

The layer boundary decides where this lives. ``platform`` owns network capture and
``application`` may not import it, so the concrete reader sits here beside
``fpl_capture`` and is handed to the evidence path as an operation rather than imported
by it. Nothing in ``data`` or ``application`` reaches a network because of this module.

**Four refusals happen before any bytes are used**, and each one exists because the
alternative is a silent wrong answer rather than a missing one:

- *The source is not in the registry.* A URL nobody recorded terms for is not read. The
  registry is the record of what we may read, so a URL absent from it is a URL nobody has
  answered that question about.
- *``robots.txt`` disallows the path.* The club is then reported as **not covered**, which
  is a state this lane already carries honestly all the way to the card: its players stay
  ``not_addressed``, and nothing pretends a page said nothing when it was never read.
- *The response is not a document.* A PDF or an image cannot have a byte span located in
  it by the coding step, so a quote taken from one could never be resolved.
- *The response is too large.* A ceiling, so a mistaken URL cannot pull a video into a
  capture that is meant to hold a team-news page.

**What it does not do.** It does not crawl: one registered path per club per call, no link
following, no discovery. It does not parse HTML -- the bytes are stored as they arrived and
the coding step reads them, because a citation is a span into the bytes we hashed and a
tidied copy would not be those bytes. And it never fills a publication time in from the
fetch instant; see :class:`RawDocument` for the three clocks.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final

from squadopt.data.sources.club_news import ClubNewsError, RawDocument
from squadopt.data.sources.club_news_readable import ReadableTextError, extract_readable_text

# One program, one identity. Imported rather than restated: a second user-agent string
# would make us two callers to anyone reading their logs, and the politeness policy this
# repository already committed to is the one that should apply to a club's server too.
from squadopt.platform.fpl_capture import (
    REQUEST_TIMEOUT_SECONDS,
    RETRY_ATTEMPTS,
    RETRY_INITIAL_SECONDS,
    RETRY_MAX_SECONDS,
    USER_AGENT,
)

#: Content types a coding step can take a byte span out of. Deliberately short: this is
#: the set whose bytes are text, not the set a browser can display.
READABLE_CONTENT_TYPES: Final[tuple[str, ...]] = (
    "text/html",
    "text/plain",
    "application/xhtml+xml",
    # A syndication feed. Registered like any other path and read like any other document:
    # this is not discovery and nothing follows an item's link. A club whose news page serves
    # an application shell and no readable text is not a club this lane can cover, and a feed
    # is often the same words with the shell taken off.
    "application/rss+xml",
    "application/atom+xml",
)

#: Ceiling for one document. A team-news page is tens of kilobytes; this is room for a
#: verbose one and a wall in front of a mistaken URL.
MAXIMUM_DOCUMENT_BYTES: Final = 2 * 1024 * 1024

#: Where ``robots.txt`` lives, by definition rather than by convention.
ROBOTS_PATH: Final = "/robots.txt"

#: Seconds to wait before contacting a host this run has already contacted. Declared, not
#: searched, and deliberately applied to the whole run rather than per club: politeness is
#: owed to the machine answering, and one host can serve several clubs' pages as easily as
#: one club can publish on several paths.
PER_ORIGIN_DELAY_SECONDS: Final = 1.0

#: The registry's own contract. Bumped when the entry shape moves, because a registry read
#: under one shape is not the same statement about permission as one read under another.
CLUB_NEWS_SOURCES_CONTRACT_VERSION: Final = "club_news_sources_v1"


class ClubNewsFetchError(ClubNewsError):
    """A club's page could not be read, or may not be.

    One type for both, because the caller's next move is the same either way: record the
    club as uncovered and carry on with the clubs that were read. The message says which
    it was, so a permission refusal is never mistaken for an outage.
    """


@dataclass(frozen=True, slots=True)
class ClubSource:
    """One club's registered page, and the club name a claim will be joined on.

    ``club`` is spelled as the capture spells it -- the bootstrap payload's ``teams[].name``,
    which is ``Man Utd`` rather than ``Manchester United``. The registry carries that
    spelling because the join is against the capture and not against a tidier name.
    """

    club: str
    url: str

    def __post_init__(self) -> None:
        if not self.club.strip():
            raise ClubNewsFetchError("A registered source must name its club.")
        parsed = urllib.parse.urlsplit(self.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ClubNewsFetchError(
                f"{self.url!r} is not an https URL with a host. A source is read over "
                "https or not at all: a citation into bytes an intermediary could have "
                "rewritten is not a citation."
            )

    @property
    def origin(self) -> str:
        """The scheme and host, which is what ``robots.txt`` belongs to."""

        parsed = urllib.parse.urlsplit(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def address(self) -> str:
        """The URL under the one normalisation the standards actually license.

        Used to tell two registry entries apart. Host names are case-insensitive, so
        ``Club.example`` and ``club.example`` are one address; paths are case-sensitive, so
        ``/team-news`` and ``/Team-News`` are two, and folding them would refuse a registry
        that is telling the truth. Nothing else is normalised -- no trailing slash, no query
        reordering -- because a guess about which of two spellings a host considers the same
        page is exactly the kind of guess this module does not make.
        """

        parsed = urllib.parse.urlsplit(self.url)
        return urllib.parse.urlunsplit(
            (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
        )


def load_club_sources(path: Path | str) -> tuple[ClubSource, ...]:
    """Read the registry of pages this project may fetch, or refuse it.

    Every entry must name a ``terms_record``. That is the load-bearing field: the registry
    is the record of what we *may* read, and an entry without a pointer to somebody's
    reading of that host's terms would be a permission nobody granted, dressed as
    configuration. The pointer is required to exist and is not followed here -- checking
    that a human wrote something is this function's job; judging what they wrote is not.

    **A club may register more than one page; an address may be registered once.** The
    earlier rule was the other way round, and its reason -- that two entries for one club
    would make "which page is this club's" a question with two answers -- asked the wrong
    question. Nothing downstream joins a claim to a club's page: a claim cites a *document*,
    by digest and byte span (:class:`~squadopt.data.sources.club_news_claims.ParsedClaim`),
    and that pointer has one answer however many pages the club publishes. The end-to-end
    test found the limit from the other side: a club that puts its team news and its injury
    table on separate pages could not be registered at all, though every layer below here
    already carries several documents and codes them in one call.

    The real duplicate is a repeated address. The same page registered twice is fetched
    twice, offered to the model twice, and yields the same claim twice from two identical
    digests -- a duplication the registry created, about a club that said something once.
    Hosts are compared case-insensitively because host names are; paths are not, because
    they are not.
    """

    location = Path(path)
    try:
        raw = location.read_text(encoding="utf-8")
    except OSError as error:
        raise ClubNewsFetchError(
            f"Cannot read the source registry at {location}: {error}"
        ) from error
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ClubNewsFetchError(f"{location} is not valid JSON: {error}") from error
    if not isinstance(document, dict):
        raise ClubNewsFetchError(f"{location} must be a JSON object.")
    version = document.get("contract_version")
    if version != CLUB_NEWS_SOURCES_CONTRACT_VERSION:
        raise ClubNewsFetchError(
            f"{location} declares contract {version!r}, not {CLUB_NEWS_SOURCES_CONTRACT_VERSION!r}."
        )
    entries = document.get("sources")
    if not isinstance(entries, list) or not entries:
        raise ClubNewsFetchError(
            f"{location} must carry a non-empty 'sources' array; a registry that permits "
            "nothing is not a registry, it is an absent one."
        )
    sources: list[ClubSource] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ClubNewsFetchError(f"{location} lists {entry!r}, which is not an object.")
        club = entry.get("club")
        url = entry.get("url")
        record = entry.get("terms_record")
        if not isinstance(club, str) or not isinstance(url, str):
            raise ClubNewsFetchError(
                f"{location} lists an entry whose 'club' and 'url' are not both text: {entry!r}."
            )
        if not isinstance(record, str) or not record.strip():
            raise ClubNewsFetchError(
                f"{location} registers {club!r} with no 'terms_record'. A source is "
                "registered only after somebody read that host's terms and wrote down what "
                "they said; without that pointer this entry is a permission nobody gave."
            )
        source = ClubSource(club=club, url=url)
        if source.address in seen:
            raise ClubNewsFetchError(
                f"{location} registers {url!r} twice. A club may have several pages, but one "
                "page registered twice is read twice and coded twice, which would put the "
                "same sentence in the evidence table as two claims."
            )
        seen.add(source.address)
        sources.append(source)
    return tuple(sources)


@dataclass(frozen=True, slots=True)
class _Read:
    """One completed HTTP read, before it is judged."""

    final_url: str
    status: int
    content_type: str
    last_modified: str | None
    content: bytes


Opener = Callable[[urllib.request.Request, float], Any]


def default_opener(request: urllib.request.Request, timeout: float) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _instant(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _transport_publication_claim(raw: str | None) -> str | None:
    """Read ``Last-Modified`` into the one instant format the pipeline compares.

    A header that cannot be parsed is treated as absent rather than repaired. It is the
    weakest of the three clocks to begin with, and a guess at what a malformed one meant
    would be a manufactured claim about when something was published.
    """

    if raw is None or not raw.strip():
        return None
    try:
        return _instant(parsedate_to_datetime(raw))
    except (TypeError, ValueError):
        return None


def _read_once(url: str, *, opener: Opener) -> _Read:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with opener(request, float(REQUEST_TIMEOUT_SECONDS)) as response:
        # One byte past the ceiling, so "too large" is detected rather than truncated into
        # a document that looks complete and hashes to something nobody can reproduce.
        content = bytes(response.read(MAXIMUM_DOCUMENT_BYTES + 1))
        headers: Mapping[str, str] = response.headers
        return _Read(
            final_url=str(response.geturl()),
            status=int(getattr(response, "status", 200) or 200),
            content_type=str(headers.get("Content-Type", "")),
            last_modified=_transport_publication_claim(headers.get("Last-Modified")),
            content=content,
        )


def read_url(
    url: str,
    *,
    opener: Opener = default_opener,
    attempts: int = RETRY_ATTEMPTS,
    sleeper: Callable[[float], None] = time.sleep,
) -> _Read:
    """Read one URL, translating network failures into the club-news error contract.

    The retry rule is ``fpl_capture.fetch``'s and for the same reason: 429 and 5xx say
    "later" and are retried with a bounded backoff, while every other 4xx says "never" and
    is raised at once. The loop is here rather than shared because that function returns
    bytes alone, and this adapter needs the final URL, the status, the content type and the
    publication header as well. A third caller that needs a response should be the one to
    extract the shared helper, rather than this becoming the second copy that outlives its
    excuse.
    """

    delay = RETRY_INITIAL_SECONDS
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _read_once(url, opener=opener)
        except urllib.error.HTTPError as error:
            retriable = error.code == 429 or 500 <= error.code < 600
            if not retriable or attempt == attempts:
                raise ClubNewsFetchError(
                    f"{url} returned HTTP {error.code} {error.reason}"
                    + (f" on all {attempts} attempts." if retriable else ".")
                ) from error
        except urllib.error.URLError as error:
            if attempt == attempts:
                raise ClubNewsFetchError(
                    f"{url} could not be reached on {attempts} attempts: {error.reason}"
                ) from error
        sleeper(delay)
        delay = min(delay * 2, RETRY_MAX_SECONDS)
    raise ClubNewsFetchError(f"{url} was not read and no failure was reported.")


class HostManners:
    """One run's memory of the hosts it has spoken to, so it speaks to each of them once.

    Two things are remembered, and both became necessary when a club gained the right to
    register more than one page.

    **The host's ``robots.txt``, parsed.** It used to be fetched once per document, so a club
    with three pages asked one host the same question three times. What is remembered is the
    parsed file rather than the answer, because the answer is about a *path*: one
    ``robots.txt`` decides every page of its host, and deciding them locally is exactly what
    removes the extra requests without changing a single verdict.

    A host whose ``robots.txt`` could not be read is remembered too, as the failure it was.
    Re-asking would not make the answer less unknown; it would only ask a struggling server
    the same question once per page.

    **Whether this run has already contacted the host**, so the second request waits. The
    wait is the full declared interval rather than a measured remainder: inside one run the
    requests are back to back, and a conservative constant needs no clock to be right.

    The memory lives for one call and is passed in, not stored on the module. A cache that
    outlived the run would answer this week's question with last week's file, and a host's
    stated preference is not a thing to remember across weeks.
    """

    def __init__(self, *, delay_seconds: float = PER_ORIGIN_DELAY_SECONDS) -> None:
        self._delay = float(delay_seconds)
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._refusals: dict[str, ClubNewsFetchError] = {}
        self._contacted: set[str] = set()

    def before_request(self, origin: str, sleeper: Callable[[float], None]) -> None:
        """Wait, if this run has already asked this host for something."""

        if origin in self._contacted:
            sleeper(self._delay)
        self._contacted.add(origin)

    def robots(
        self, origin: str, read: Callable[[], urllib.robotparser.RobotFileParser]
    ) -> urllib.robotparser.RobotFileParser:
        """The host's parsed ``robots.txt``, read at most once per run.

        A recorded refusal is re-raised rather than retried, so every page of a host whose
        preference could not be read refuses for the same stated reason.

        What is remembered is the **host-level** reason and nothing else. Caching the whole
        composed refusal was a defect: the message names the page that could not be fetched,
        so every later page of that host inherited the first page's URL and a club was told
        its own page was refused under another club's address.
        """

        refusal = self._refusals.get(origin)
        if refusal is not None:
            raise refusal
        cached = self._robots.get(origin)
        if cached is not None:
            return cached
        try:
            parser = read()
        except ClubNewsFetchError as error:
            self._refusals[origin] = error
            raise
        self._robots[origin] = parser
        return parser


def _origin_of(url: str) -> str:
    """The scheme and host of a URL, spelled as :attr:`ClubSource.origin` spells it."""

    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def robots_allows(
    source: ClubSource,
    *,
    opener: Opener = default_opener,
    sleeper: Callable[[float], None] = time.sleep,
    manners: HostManners | None = None,
) -> bool:
    """Ask the host's own machine-readable preference about this path.

    Read through the same reader as the document, deliberately.
    ``RobotFileParser.read`` would open its own connection with its own user-agent and no
    retry policy, which would make the question we ask about permission arrive differently
    from the request that acts on the answer.

    A host that serves no ``robots.txt`` has stated no preference, and a host whose
    ``robots.txt`` cannot be read is not treated as having granted anything: the first is
    allowed and the second refuses, because "we could not ask" is not "they said yes".
    """

    robots_url = f"{source.origin}{ROBOTS_PATH}"

    def _read() -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        if manners is not None:
            manners.before_request(source.origin, sleeper)
        try:
            read = read_url(robots_url, opener=opener, attempts=1, sleeper=sleeper)
        except ClubNewsFetchError as error:
            if "404" in str(error) or "410" in str(error):
                # Silence, and a host that states no preference states it for every path,
                # so an empty file is remembered exactly like a served one.
                parser.parse([])
                return parser
            # Host-level only. The page this refusal costs is added by the caller below, so a
            # remembered reason cannot carry the first page's URL to the second page's club.
            raise ClubNewsFetchError(f"{robots_url} could not be read: {error}") from error
        parser.parse(read.content.decode("utf-8", errors="replace").splitlines())
        return parser

    try:
        parser = _read() if manners is None else manners.robots(source.origin, _read)
    except ClubNewsFetchError as error:
        raise ClubNewsFetchError(
            f"This host's preference is unknown, so {source.url} is not fetched: {error}"
        ) from error
    return bool(parser.can_fetch(USER_AGENT, source.url))


def fetch_club_document(
    source: ClubSource,
    *,
    opener: Opener = default_opener,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = time.sleep,
    check_robots: bool = True,
    manners: HostManners | None = None,
) -> RawDocument:
    """Read one registered club page into a :class:`RawDocument`, or refuse.

    ``final_url`` is what the server actually served after any redirect, because a citation
    names the page that was read rather than the one that was asked for. The fetch instant
    is taken from the injected clock so a test can pin it; the publication claim comes from
    the response header or stays absent.
    """

    if check_robots and not robots_allows(source, opener=opener, sleeper=sleeper, manners=manners):
        raise ClubNewsFetchError(
            f"{source.origin}{ROBOTS_PATH} disallows {source.url} for this client, so "
            f"{source.club} is recorded as not covered rather than read anyway. A club "
            "nobody read is a state this lane carries; overriding a stated preference is "
            "not."
        )
    if manners is not None:
        manners.before_request(source.origin, sleeper)
    read = read_url(source.url, opener=opener, sleeper=sleeper)
    if check_robots and _origin_of(read.final_url) != source.origin:
        # `robots_allows` above asked the origin we *requested*. A redirect can be answered
        # by a different host, whose preference nobody asked and whose terms nobody read, so
        # following it would let one host's consent stand in for another's. That is not a
        # hypothetical: `www.nufc.co.uk/news` redirects to `www.newcastleunited.com/en/news`,
        # and the first real run read one host under a reading signed for the other (#781).
        #
        # The request has already gone; the final URL is not knowable before the response,
        # and a HEAD preflight would double every fetch and still not bind what the GET
        # returns. So what this refusal buys is narrower and still worth having: the bytes
        # are not used, the club is recorded as not covered rather than read, and once the
        # registry names the serving host with a reading of its own the redirect is gone.
        raise ClubNewsFetchError(
            f"{source.url} was answered by {_origin_of(read.final_url)}, which is not the "
            f"origin this run asked for permission at ({source.origin}). Its bytes are not "
            "read: a registered page is a host whose robots.txt this run consulted and whose "
            "terms somebody signed a reading for, and a redirect does not carry either of "
            "those across. Register the serving origin and sign its reading, then this page "
            "is fetched from the host that answers it."
        )
    if len(read.content) > MAXIMUM_DOCUMENT_BYTES:
        raise ClubNewsFetchError(
            f"{source.url} served more than {MAXIMUM_DOCUMENT_BYTES} bytes. A team-news "
            "page is tens of kilobytes, so this is a wrong URL rather than a long page, "
            "and a truncated document would hash to something no replay reproduces."
        )
    media_type = read.content_type.split(";", 1)[0].strip().lower()
    if media_type not in READABLE_CONTENT_TYPES:
        raise ClubNewsFetchError(
            f"{source.url} served {media_type!r}, which is not one of "
            f"{list(READABLE_CONTENT_TYPES)!r}. A byte span cannot be located in it, so a "
            "quote taken from it could never be resolved against the stored bytes."
        )
    if not read.content:
        raise ClubNewsFetchError(
            f"{source.url} served no bytes. An empty document is not a club that published "
            "nothing; it is a read that did not work."
        )
    try:
        readable = extract_readable_text(read.content, read.content_type)
    except ReadableTextError as error:
        # One unreadable page costs one club, not the week: the caller separates a club it
        # could not read from a club that said nothing, and that only works if this refusal
        # arrives in the same currency as every other per-source refusal here.
        raise ClubNewsFetchError(f"{source.url} has no readable text: {error}") from error
    return RawDocument(
        club=source.club,
        requested_url=source.url,
        final_url=read.final_url,
        http_status=read.status,
        content_type=read.content_type,
        byte_length=len(read.content),
        fetched_at_utc=_instant(now()),
        content=read.content,
        readable=readable,
        last_modified_utc=read.last_modified,
    )


def fetch_registered_documents(
    sources: Sequence[ClubSource],
    *,
    opener: Opener = default_opener,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleeper: Callable[[float], None] = time.sleep,
    check_robots: bool = True,
) -> tuple[tuple[RawDocument, ...], tuple[tuple[str, str], ...]]:
    """Read every registered source, returning what was read and why the rest was not.

    One club failing does not fail the week. That is the whole reason the evidence table
    separates "declared" from "covered": a club whose page 404s and a club that published
    nothing about anyone are different facts about different clubs, and returning the
    refusals beside the documents is what lets the caller record them apart instead of
    collapsing both into silence.

    Ordered as the registry declares them, so two runs over the same registry produce the
    same request order and the same capture.
    """

    if not sources:
        raise ClubNewsFetchError("No source was registered, so there is nothing to read.")
    documents: list[RawDocument] = []
    refused: list[tuple[str, str]] = []
    manners = HostManners()
    for source in sources:
        try:
            documents.append(
                fetch_club_document(
                    source,
                    opener=opener,
                    now=now,
                    sleeper=sleeper,
                    check_robots=check_robots,
                    manners=manners,
                )
            )
        except ClubNewsFetchError as error:
            refused.append((source.club, str(error)))
    return tuple(documents), tuple(refused)


__all__ = [
    "CLUB_NEWS_SOURCES_CONTRACT_VERSION",
    "MAXIMUM_DOCUMENT_BYTES",
    "PER_ORIGIN_DELAY_SECONDS",
    "READABLE_CONTENT_TYPES",
    "ROBOTS_PATH",
    "ClubNewsFetchError",
    "ClubSource",
    "HostManners",
    "default_opener",
    "fetch_club_document",
    "fetch_registered_documents",
    "load_club_sources",
    "read_url",
    "robots_allows",
]
