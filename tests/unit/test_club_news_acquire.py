"""Acquiring one week's club news: what is read, what is coded, and what is recorded as read.

Offline throughout. The opener is injected, the provider is a fake registered the way a real
one would be, and every write is under ``tmp_path``. No key is read and no host is contacted.

What these tests are mostly about is the three coverage lists, because they are the part only
this moment can compute: ten minutes later, from the payloads alone, a club whose second page
was refused is indistinguishable from a club that only ever registered one.
"""

import json
import urllib.error
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures.synthetic_rotation_capture import DECISION_SOURCE, bootstrap_payload

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import read_captured_coverage
from squadopt.data.sources.club_news_coding import CODING_MODEL_IDENTIFIER
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.platform.club_news_acquire import acquire_week, main
from squadopt.platform.club_news_fetch import CLUB_NEWS_SOURCES_CONTRACT_VERSION, ClubSource
from squadopt.platform.club_news_provider import (
    DEFAULT_PROVIDER,
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    CodingProviderConfig,
    register_provider,
)

FETCHED_AT = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
READ_ON = date(2026, 9, 1)
CONFIG = CodingProviderConfig(
    provider=DEFAULT_PROVIDER, model_identifier=CODING_MODEL_IDENTIFIER, api_key="k"
)
ROSTER = (RosterPlayer(player_id=1, web_name="Saka", team_name="Arsenal"),)

UNITED_PRESS = "https://club.example/united/press"
UNITED_INJURIES = "https://club.example/united/injuries"
ARSENAL = "https://club.example/arsenal/team-news"

SOURCES = (
    ClubSource(club="Arsenal", url=ARSENAL, terms_read_on=READ_ON),
    ClubSource(club="Man Utd", url=UNITED_PRESS, terms_read_on=READ_ON),
    ClubSource(club="Man Utd", url=UNITED_INJURIES, terms_read_on=READ_ON),
)


class _Reply:
    def __init__(self, url: str, body: bytes = b"<p>Saka trained fully.</p>") -> None:
        self._body = body
        self._url = url
        self.status = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def geturl(self) -> str:
        return self._url

    def read(self, amount: int | None = None) -> bytes:
        return self._body if amount is None else self._body[:amount]

    def __enter__(self) -> "_Reply":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _opener(*, missing: frozenset[str] = frozenset()) -> Any:
    """Serves every registered page and an allowing robots, minus whatever is missing."""

    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        if url in missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _Reply(url)

    return _open


class _Provider:
    """Answers for every club, or refuses one by name."""

    def __init__(self, *, refuses: str | None = None) -> None:
        self._refuses = refuses

    def fetch(self, url: str) -> RawDocument:  # pragma: no cover - never called
        raise AssertionError(url)

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        club = documents[0].club
        if club == self._refuses:
            raise ClubNewsError(f"The response reached the ceiling, for {club}.")
        return ClaimResponse(
            text=json.dumps({"documents": [], "claims": []}),
            model_identifier=CODING_MODEL_IDENTIFIER,
            model_version="v1",
        )


def _acquire(**overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "sources": SOURCES,
        "provider": _Provider(),
        "config": CONFIG,
        "roster": ROSTER,
        "opener": _opener(),
        "now": lambda: FETCHED_AT,
        "sleeper": lambda _: None,
    }
    arguments.update(overrides)
    return acquire_week(**arguments)


# --- what a whole week looks like -------------------------------------------


def test_every_registered_page_is_read_and_every_club_is_coded() -> None:
    """The path the test helper used to walk, now with a registry it did not choose."""

    week = _acquire()

    assert len(week.documents) == 3
    assert [entry.club for entry in week.coded] == ["Arsenal", "Man Utd"]
    assert week.clubs_declared == ("Arsenal", "Man Utd")
    assert week.clubs_covered == ("Arsenal", "Man Utd")
    assert week.clubs_partially_covered == ()
    assert week.refused_pages == ()
    assert week.refused_coding == ()


# --- the three coverage lists -----------------------------------------------


def test_a_club_with_one_page_refused_is_covered_and_named_as_read_in_part() -> None:
    """The distinction #524 asked for, computed at the only moment that can compute it."""

    week = _acquire(opener=_opener(missing=frozenset({UNITED_INJURIES})))

    assert len(week.documents) == 2
    assert week.clubs_covered == ("Arsenal", "Man Utd")
    assert week.clubs_partially_covered == ("Man Utd",)
    assert [club for club, _reason in week.refused_pages] == ["Man Utd"]


def test_a_club_whose_every_page_is_refused_is_not_covered_at_all() -> None:
    """Unread, not partly read -- and not silently dropped from the declared list either."""

    week = _acquire(opener=_opener(missing=frozenset({UNITED_PRESS, UNITED_INJURIES})))

    assert week.clubs_declared == ("Arsenal", "Man Utd")
    assert week.clubs_covered == ("Arsenal",)
    assert week.clubs_partially_covered == ()


def test_a_club_read_but_not_coded_is_not_covered() -> None:
    """Nothing it said survives into evidence, so calling it covered would assert a read.

    The evidence table would refuse it anyway: provenance is per club, and a covered club
    with no response is one the manifest cannot describe.
    """

    week = _acquire(provider=_Provider(refuses="Man Utd"))

    assert len(week.documents) == 3
    assert week.clubs_covered == ("Arsenal",)
    assert week.clubs_partially_covered == ()
    assert [club for club, _reason in week.refused_coding] == ["Man Utd"]


def test_partly_covered_never_names_a_club_that_is_not_covered() -> None:
    """A narrowing of coverage, never a substitute for it."""

    week = _acquire(
        opener=_opener(missing=frozenset({UNITED_INJURIES})), provider=_Provider(refuses="Man Utd")
    )

    assert week.clubs_covered == ("Arsenal",)
    assert week.clubs_partially_covered == ()
    assert set(week.clubs_partially_covered) <= set(week.clubs_covered)


def test_articles_are_coded_with_their_club_and_a_missing_one_narrows_nothing() -> None:
    """A followed article is a document of the registered page's club, not a registered page.

    So it reaches the club's one call beside the index, and when one cannot be read the club
    stays fully covered: partial coverage is about the pages the registry declared, and the
    articles an index links to are a capped sample, never a list the week declared.
    """

    read = f"{ARSENAL}/saka-fit"
    lost = f"{ARSENAL}/removed"
    index = f"<a href='{read}'>Saka fit</a><a href='{lost}'>Removed</a>".encode()
    base = _opener(missing=frozenset({lost}))
    coded: list[list[str]] = []

    def _open(request: Any, timeout: float) -> _Reply:
        if request.full_url == ARSENAL:
            return _Reply(ARSENAL, index)
        return base(request, timeout)  # type: ignore[no-any-return]

    class _Recording(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            coded.append([document.requested_url for document in documents])
            return super().code(documents, roster)

    week = _acquire(sources=SOURCES[:1], opener=_open, provider=_Recording())

    assert [document.requested_url for document in week.documents] == [ARSENAL, read]
    assert coded == [[ARSENAL, read]]
    assert week.clubs_covered == ("Arsenal",)
    assert week.clubs_partially_covered == ()
    assert [club for club, _reason in week.refused_pages] == ["Arsenal"]
    assert week.refused_pages[0][1].startswith(f"An article linked from {ARSENAL}")


# --- the command ------------------------------------------------------------


def _registry(path: Path, sources: Sequence[ClubSource]) -> Path:
    path.write_text(
        json.dumps(
            {
                "contract_version": CLUB_NEWS_SOURCES_CONTRACT_VERSION,
                "sources": [
                    {
                        "club": source.club,
                        "url": source.url,
                        "terms_record": "docs/club_news_sources.md",
                        "terms_read_on": READ_ON.isoformat(),
                    }
                    for source in sources
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _roster_snapshot(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc="2026-09-12T15:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload()},
    )
    return metadata.snapshot_id


def test_the_command_refuses_without_a_key_and_never_reaches_a_fixture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """ "We could not ask" and "the fixture said" stay apart at the command as well."""

    registry = _registry(tmp_path / "sources.json", SOURCES)
    roster_id = _roster_snapshot(tmp_path / "snapshots")

    code = main(
        [
            "--roster-snapshot",
            roster_id,
            "--registry",
            str(registry),
            "--snapshot-root",
            str(tmp_path / "snapshots"),
        ],
        environ={},
        opener=_opener(),
        now=lambda: FETCHED_AT,
        sleeper=lambda _: None,
    )

    assert code == 1
    assert "Refused" in capsys.readouterr().out


def test_the_command_prints_the_capture_id_the_next_step_needs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The id is the point of the command: the weekly runner takes it next.

    The provider is selected by environment variable alone, with no code edit -- which is the
    same door a real provider will come through.
    """

    name = "fake-for-acquire"
    register_provider(name, lambda config: _Provider())
    registry = _registry(tmp_path / "sources.json", SOURCES)
    snapshots = tmp_path / "snapshots"
    roster_id = _roster_snapshot(snapshots)

    code = main(
        [
            "--roster-snapshot",
            roster_id,
            "--registry",
            str(registry),
            "--snapshot-root",
            str(snapshots),
        ],
        environ={
            PROVIDER_ENVIRONMENT_VARIABLE: name,
            MODEL_ENVIRONMENT_VARIABLE: "fake-model-1",
            KEY_ENVIRONMENT_VARIABLE: "not-a-real-key",
        },
        opener=_opener(),
        now=lambda: FETCHED_AT,
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 0
    capture_line = [line for line in printed.splitlines() if line.startswith("Capture")]
    assert capture_line, printed
    capture_id = capture_line[0].split()[-1]

    declared, covered, partial = read_captured_coverage(read_snapshot(snapshots, capture_id))
    assert declared == ("Arsenal", "Man Utd")
    assert covered == ("Arsenal", "Man Utd")
    assert partial == ()


def test_an_unlisted_model_refuses_the_command_before_any_page_is_fetched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The 9 October failure, caught at startup rather than one club at a time.

    The real free adapter is selected with a model the provider shut down, a key is present,
    and the opener counts every request. Nothing is fetched, no robots file is read, and the
    refusal names the model and never the key.
    """

    requested: list[str] = []

    def _counting(request: Any, timeout: float) -> _Reply:
        requested.append(request.full_url)
        return _opener()(request, timeout)  # type: ignore[no-any-return]

    key = "sentinel-key-for-acquire"
    registry = _registry(tmp_path / "sources.json", SOURCES)
    snapshots = tmp_path / "snapshots"
    roster_id = _roster_snapshot(snapshots)

    code = main(
        [
            "--roster-snapshot",
            roster_id,
            "--registry",
            str(registry),
            "--snapshot-root",
            str(snapshots),
        ],
        environ={
            PROVIDER_ENVIRONMENT_VARIABLE: "gemini",
            MODEL_ENVIRONMENT_VARIABLE: "gemini-2.0-flash",
            KEY_ENVIRONMENT_VARIABLE: key,
        },
        opener=_counting,
        now=lambda: FETCHED_AT,
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 1
    assert printed.startswith("Refused:")
    assert "'gemini-2.0-flash'" in printed
    assert key not in printed
    assert requested == []
