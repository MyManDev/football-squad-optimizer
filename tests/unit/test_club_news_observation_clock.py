"""The one instant a week's club-news coding observes from.

It is taken after the last page was read. The document selection, the model's decision
context and the target-deadline check all use it, so an article published while the pages
were being read is judged against the moment its page was already in hand, and a deadline
that passed during the download stops the week instead of being coded against or replaced.

Offline throughout: the opener, the clock and the provider are injected, and every write is
under ``tmp_path``.
"""

import json
import urllib.error
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures.synthetic_rotation_capture import (
    DEADLINE,
    DECISION_SOURCE,
    TARGET_GAMEWEEK,
    bootstrap_payload,
)
from tests.unit.test_club_news_acquire import (
    ARSENAL,
    CONFIG,
    ROSTER,
    SOURCES,
    _Provider,
    _registry,
    _Reply,
)

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    ClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import (
    read_captured_documents,
    read_captured_responses,
)
from squadopt.data.sources.club_news_selection import select_coding_documents
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.data.timestamps import as_instant
from squadopt.platform.club_news_acquire import acquire_week, main
from squadopt.platform.club_news_provider import (
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    CodingProviderConfig,
    register_provider,
)

STARTED = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
ARTICLE = f"{ARSENAL}/saka-update"


def _text(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


class _Clock:
    """A clock that moves: every reading is ``step`` later than the one before."""

    def __init__(self, start: datetime = STARTED, step: timedelta = timedelta(minutes=1)) -> None:
        self._next = start
        self._step = step
        self.readings: list[datetime] = []

    def __call__(self) -> datetime:
        moment = self._next
        self._next = moment + self._step
        self.readings.append(moment)
        return moment


class _Timeline:
    """A clock that stands still until a page is requested, then moves by ``per_page``.

    The run's start is read before any page is asked for, so it is always ``start``. An
    observation taken before the fetch would be ``start`` as well, which is what lets a test
    tell the two apart.
    """

    def __init__(self, start: datetime, per_page: timedelta) -> None:
        self.now = start
        self._per_page = per_page
        self.pages: list[str] = []

    def __call__(self) -> datetime:
        return self.now

    def opener(self, published: str | None = None) -> Any:
        inner = _opener(published)

        def _open(request: Any, timeout: float) -> _Reply:
            if not request.full_url.endswith("/robots.txt"):
                self.pages.append(request.full_url)
                self.now = self.now + self._per_page
            return inner(request, timeout)  # type: ignore[no-any-return]

        return _open


def _article(published: str | None) -> bytes:
    meta = (
        ""
        if published is None
        else f'<meta property="article:published_time" content="{published}">'
    )
    return (
        f"<html><head>{meta}</head><body><h1>Team news: Saka</h1>"
        "<p>Saka trained fully.</p></body></html>"
    ).encode()


def _opener(published: str | None, requested: list[str] | None = None) -> Any:
    """The Arsenal index links one article; every other registered page is plain."""

    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if requested is not None:
            requested.append(url)
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        if url == ARSENAL:
            return _Reply(url, f"<a href='{ARTICLE}'>Saka update</a>".encode())
        if url == ARTICLE:
            return _Reply(url, _article(published))
        return _Reply(url)

    return _open


def _binder(
    seen: list[str], provider: ClubNewsProvider | None = None
) -> Callable[[str], tuple[ClubNewsProvider, CodingProviderConfig]]:
    def _bind(observed_at: str) -> tuple[ClubNewsProvider, CodingProviderConfig]:
        seen.append(observed_at)
        context = {
            "season": "2026-27",
            "gameweek": TARGET_GAMEWEEK,
            "deadline": DEADLINE,
            "as_of": observed_at,
        }
        config = CodingProviderConfig(
            provider=CONFIG.provider,
            model_identifier=CONFIG.model_identifier,
            api_key="k",
            target_context=context,
        )
        return provider or _Provider(), config

    return _bind


def _week(published: str | None, clock: _Clock, seen: list[str]) -> Any:
    return acquire_week(
        sources=SOURCES[:1],
        roster=ROSTER,
        opener=_opener(published),
        now=clock,
        sleeper=lambda _: None,
        bind_coding=_binder(seen),
    )


def _refuse(url: str) -> Any:
    raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)  # type: ignore[arg-type]


# --- the observation is taken after the fetch -------------------------------


def test_the_coding_observation_is_one_instant_after_every_page_was_read() -> None:
    clock = _Clock()
    seen: list[str] = []

    week = _week(None, clock, seen)

    assert seen == [week.coding_observed_at]
    observed = as_instant(str(week.coding_observed_at))
    assert week.documents
    assert all(as_instant(document.fetched_at_utc) < observed for document in week.documents)
    # The last reading of the clock, so nothing after it was looked at.
    assert observed == clock.readings[-1]


def test_an_article_published_while_the_pages_were_read_is_still_coded() -> None:
    """Published after the run started and before the observation, with its page in hand."""

    clock = _Clock()
    seen: list[str] = []
    published = _text(STARTED + timedelta(seconds=30))

    week = _week(published, clock, seen)

    assert week.document_selection is not None
    article = [d for d in week.document_selection.decisions if d.source_url == ARTICLE]
    assert [(d.selected, d.reason) for d in article] == [(True, "availability_or_upcoming_match")]
    assert [entry.club for entry in week.coded] == ["Arsenal"]
    # The instant the run started would have turned the same page away.
    earlier = select_coding_documents(week.documents, as_of=_text(STARTED))
    assert [d.reason for d in earlier.decisions if d.source_url == ARTICLE] == [
        "publication_after_observation"
    ]


@pytest.mark.parametrize(
    ("published", "reason"),
    [
        (_text(STARTED + timedelta(hours=2)), "publication_after_observation"),
        (_text(STARTED - timedelta(days=8)), "publication_outside_current_window"),
    ],
)
def test_a_future_or_stale_article_is_turned_away_for_its_own_reason(
    published: str, reason: str
) -> None:
    week = _week(published, _Clock(), [])

    assert week.document_selection is not None
    article = [d for d in week.document_selection.decisions if d.source_url == ARTICLE]
    assert [(d.selected, d.reason) for d in article] == [(False, reason)]
    assert ARTICLE not in {d.requested_url for d in week.document_selection.documents}


def test_what_is_coded_is_exactly_what_is_reported_as_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One selection, made once and handed on, rather than two that happen to agree."""

    from squadopt.platform import club_news_acquire, club_news_provider

    made: list[str | None] = []
    real = club_news_acquire.select_coding_documents

    def _counted(documents: Sequence[RawDocument], *, as_of: str | None = None) -> Any:
        made.append(as_of)
        return real(documents, as_of=as_of)

    def _never(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("The coding stage selected the documents a second time.")

    monkeypatch.setattr(club_news_acquire, "select_coding_documents", _counted)
    monkeypatch.setattr(club_news_provider, "select_coding_documents", _never)
    coded: list[list[str]] = []
    seen: list[str] = []

    class _Recording(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            coded.append([document.requested_url for document in documents])
            return super().code(documents, roster)

    week = acquire_week(
        sources=SOURCES,
        roster=ROSTER,
        opener=_opener(_text(STARTED + timedelta(seconds=30))),
        now=_Clock(),
        sleeper=lambda _: None,
        bind_coding=_binder(seen, _Recording()),
    )

    assert made == seen == [week.coding_observed_at]
    assert week.document_selection is not None
    reported = [document.requested_url for document in week.document_selection.documents]
    assert [url for call in coded for url in call] == reported


def test_a_page_stamped_later_than_the_observation_stops_the_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The order of the two instants is checked, not assumed."""

    from squadopt.platform import club_news_acquire

    read = acquire_week(
        sources=SOURCES[:1],
        roster=ROSTER,
        opener=_opener(None),
        now=lambda: STARTED + timedelta(hours=1),
        sleeper=lambda _: None,
        provider=_Provider(),
        config=CONFIG,
    ).documents
    assert read
    monkeypatch.setattr(club_news_acquire, "fetch_registered_documents", lambda *a, **k: (read, ()))
    seen: list[str] = []

    with pytest.raises(ClubNewsError, match="the clock went backwards"):
        acquire_week(
            sources=SOURCES[:1],
            roster=ROSTER,
            opener=_opener(None),
            now=lambda: STARTED + timedelta(minutes=30),
            sleeper=lambda _: None,
            bind_coding=_binder(seen),
        )
    assert seen == []


def test_nothing_is_observed_or_built_when_no_page_could_be_read() -> None:
    seen: list[str] = []

    def _open(request: Any, timeout: float) -> _Reply:
        if request.full_url.endswith("/robots.txt"):
            return _Reply(request.full_url, b"User-agent: *\nAllow: /\n")
        return _refuse(request.full_url)  # type: ignore[no-any-return]

    week = acquire_week(
        sources=SOURCES,
        roster=ROSTER,
        opener=_open,
        now=_Clock(),
        sleeper=lambda _: None,
        bind_coding=_binder(seen),
    )

    assert seen == []
    assert week.coding_observed_at is None
    assert week.documents == () and week.coded == ()
    assert week.clubs_declared == ("Arsenal", "Man Utd")
    assert {club for club, _reason in week.refused_pages} == {"Arsenal", "Man Utd"}


@pytest.mark.parametrize(
    "given",
    [
        (),
        ("provider",),
        ("config",),
        ("provider", "bind_coding"),
        ("config", "bind_coding"),
        ("provider", "config", "bind_coding"),
    ],
)
def test_the_coding_side_is_given_one_way_or_the_other(given: tuple[str, ...]) -> None:
    """A provider with its configuration, or a binder: any other combination is refused."""

    available: dict[str, Any] = {
        "provider": _Provider(),
        "config": CONFIG,
        "bind_coding": _binder([]),
    }
    requested: list[str] = []
    with pytest.raises(ClubNewsError, match="not both"):
        acquire_week(
            sources=SOURCES[:1],
            roster=ROSTER,
            opener=_opener(None, requested),
            now=_Clock(),
            sleeper=lambda _: None,
            **{name: available[name] for name in given},
        )
    # Refused before any page is asked for.
    assert requested == []


# --- the command ------------------------------------------------------------


def _roster_snapshot(root: Path, *, later_deadline: str | None = None) -> str:
    payload = bootstrap_payload()
    if later_deadline is not None:
        document = json.loads(payload)
        document["events"].append(
            {"id": TARGET_GAMEWEEK + 1, "deadline_time": later_deadline, "finished": False}
        )
        payload = json.dumps(document).encode()
    return write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc="2026-09-12T13:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: payload},
    ).snapshot_id


def _environment(name: str) -> dict[str, str]:
    return {
        PROVIDER_ENVIRONMENT_VARIABLE: name,
        MODEL_ENVIRONMENT_VARIABLE: "fake-model-1",
        KEY_ENVIRONMENT_VARIABLE: "not-a-real-key",
    }


def _command(tmp_path: Path, roster_id: str, *extra: str) -> list[str]:
    registry = _registry(tmp_path / "sources.json", SOURCES)
    return [
        "--roster-snapshot",
        roster_id,
        "--registry",
        str(registry),
        "--snapshot-root",
        str(tmp_path / "snapshots"),
        *extra,
    ]


def test_the_model_is_told_the_instant_the_selection_used(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The adapter is built once, after the fetch, with the observation as its ``as_of``."""

    events: list[str] = []
    built: list[CodingProviderConfig] = []

    def _factory(config: CodingProviderConfig) -> _Provider:
        events.append("provider built")
        built.append(config)
        return _Provider()

    name = "fake-observation-clock"
    register_provider(name, _factory)
    roster_id = _roster_snapshot(tmp_path / "snapshots")
    requested: list[str] = []
    clock = _Clock()

    def _open(request: Any, timeout: float) -> _Reply:
        events.append("page requested")
        return _opener(None, requested)(request, timeout)  # type: ignore[no-any-return]

    code = main(
        _command(tmp_path, roster_id),
        environ=_environment(name),
        opener=_open,
        now=clock,
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 0, printed
    assert len(built) == 1
    assert events.index("provider built") > max(
        position for position, event in enumerate(events) if event == "page requested"
    )
    context = built[0].target_context
    assert context is not None
    assert context["gameweek"] == TARGET_GAMEWEEK
    assert context["deadline"] == DEADLINE
    observed = str(context["as_of"])
    assert as_instant(observed) > STARTED
    assert f"Observed      {observed}" in printed
    capture_id = next(
        line.split()[-1] for line in printed.splitlines() if line.startswith("Capture")
    )
    documents = read_captured_documents(read_snapshot(tmp_path / "snapshots", capture_id))
    assert all(as_instant(d.fetched_at_utc) < as_instant(observed) for d in documents)


@pytest.mark.parametrize(
    ("later_deadline", "expected"),
    [
        (None, "no later deadline is published"),
        ("2026-09-19T17:30:00Z", f"gameweek {TARGET_GAMEWEEK + 1} was not substituted"),
    ],
)
def test_a_deadline_that_passes_during_the_download_stops_the_week(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    later_deadline: str | None,
    expected: str,
) -> None:
    """Nothing is coded against the closed week, and the next week is not taken instead."""

    built: list[CodingProviderConfig] = []

    def _factory(config: CodingProviderConfig) -> _Provider:
        built.append(config)
        return _Provider()

    name = f"fake-deadline-passes-{later_deadline is not None}"
    register_provider(name, _factory)
    roster_id = _roster_snapshot(tmp_path / "snapshots", later_deadline=later_deadline)
    before = sorted(path.name for path in (tmp_path / "snapshots").rglob("*") if path.is_dir())
    # Open at the start, half an hour before the deadline, and closed once the pages are
    # in: the clock moves twenty minutes with each page and not otherwise, so an observation
    # taken before the fetch would still see the week open.
    clock = _Timeline(datetime(2026, 9, 12, 17, 0, tzinfo=UTC), timedelta(minutes=20))

    code = main(
        _command(tmp_path, roster_id),
        environ=_environment(name),
        opener=clock.opener(),
        now=clock,
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 1
    assert len(clock.pages) >= 3
    assert printed.startswith("Refused:")
    assert f"gameweek {TARGET_GAMEWEEK} deadline {DEADLINE} passed" in printed
    assert expected in printed
    assert built == []
    after = sorted(path.name for path in (tmp_path / "snapshots").rglob("*") if path.is_dir())
    assert after == before


def test_an_observation_earlier_than_the_start_of_the_run_stops_the_week(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The clock steps back while the pages are read; the week is not coded."""

    built: list[CodingProviderConfig] = []
    name = "fake-backwards-clock"
    register_provider(name, lambda config: built.append(config) or _Provider())
    roster_id = _roster_snapshot(tmp_path / "snapshots")
    clock = _Timeline(STARTED, timedelta(seconds=-1))

    code = main(
        _command(tmp_path, roster_id),
        environ=_environment(name),
        opener=clock.opener(),
        now=clock,
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 1
    assert clock.pages
    assert "the clock went backwards" in printed
    assert built == []


def test_a_missing_client_library_refuses_before_any_page_is_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter is built after the fetch, so its library is checked before it."""

    from squadopt.platform import club_news_provider

    monkeypatch.setattr(club_news_provider.importlib.util, "find_spec", lambda _name: None)
    roster_id = _roster_snapshot(tmp_path / "snapshots")
    requested: list[str] = []

    code = main(
        _command(tmp_path, roster_id),
        environ={
            PROVIDER_ENVIRONMENT_VARIABLE: "gemini",
            KEY_ENVIRONMENT_VARIABLE: "not-a-real-key",
        },
        opener=_opener(None, requested),
        now=_Clock(),
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 1
    assert printed.startswith("Refused:")
    assert "llm extra" in printed
    assert requested == []


def test_the_command_says_nothing_was_observed_when_no_page_could_be_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built: list[CodingProviderConfig] = []
    name = "fake-nothing-read"
    register_provider(name, lambda config: built.append(config) or _Provider())
    roster_id = _roster_snapshot(tmp_path / "snapshots")

    def _open(request: Any, timeout: float) -> _Reply:
        if request.full_url.endswith("/robots.txt"):
            return _Reply(request.full_url, b"User-agent: *\nAllow: /\n")
        return _refuse(request.full_url)  # type: ignore[no-any-return]

    code = main(
        _command(tmp_path, roster_id),
        environ=_environment(name),
        opener=_open,
        now=_Clock(),
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 1
    assert "Observed" not in printed
    assert "Nothing was coded, so there is no week to capture." in printed
    assert built == []


def test_a_reused_answer_keeps_its_own_times_and_only_the_reading_is_new(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unchanged pages for the same target are not asked about twice.

    The second run observes from a later instant. That instant is not part of what makes a
    question the same question, so the first answer is reused as it was given; what is new
    in the second capture is when the pages were read.
    """

    calls: list[str] = []

    class _Counting(_Provider):
        def code(
            self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
        ) -> ClaimResponse:
            calls.append(documents[0].club)
            # Reuse requires the held answer to name the model the run asked for.
            return replace(super().code(documents, roster), model_identifier="fake-model-1")

    name = "fake-reuse-clock"
    register_provider(name, lambda config: _Counting())
    snapshots = tmp_path / "snapshots"
    roster_id = _roster_snapshot(snapshots)
    published = _text(STARTED - timedelta(hours=3))

    def _run(clock: _Clock, *extra: str) -> str:
        # Capture completion is its own clock; keep it on this synthetic week's timeline.
        monkeypatch.setattr(
            "squadopt.platform.club_news_acquire._utc_now",
            lambda: _text(clock.readings[-1] + timedelta(seconds=30)),
        )
        code = main(
            _command(tmp_path, roster_id, *extra),
            environ=_environment(name),
            opener=_opener(published),
            now=clock,
            sleeper=lambda _: None,
        )
        printed = capsys.readouterr().out
        assert code == 0, printed
        return printed

    first_printed = _run(_Clock(STARTED))
    first_id = next(
        line.split()[-1] for line in first_printed.splitlines() if line.startswith("Capture")
    )
    first = read_snapshot(snapshots, first_id)
    asked_first = list(calls)
    assert asked_first == ["Arsenal", "Man Utd"]

    # The second run starts after the first capture was written and before the deadline.
    later = as_instant(first.metadata.captured_at_utc) + timedelta(minutes=5)
    assert later < as_instant(DEADLINE)
    second_printed = _run(
        _Clock(later, timedelta(seconds=1)), "--previous-news-capture", str(snapshots / first_id)
    )
    second_id = next(
        line.split()[-1] for line in second_printed.splitlines() if line.startswith("Capture")
    )
    second = read_snapshot(snapshots, second_id)

    assert calls == asked_first
    assert "Reused        2 unchanged club responses" in second_printed
    old = {entry.club: entry for entry in read_captured_responses(first)}
    new = {entry.club: entry for entry in read_captured_responses(second)}
    assert new.keys() == old.keys()
    for club, entry in new.items():
        assert entry.response == old[club].response
        assert entry.request_fingerprint == old[club].request_fingerprint
        assert entry.reused_from_snapshot == first_id
    first_read = {d.requested_url: d for d in read_captured_documents(first)}
    for document in read_captured_documents(second):
        earlier = first_read[document.requested_url]
        assert document.content == earlier.content
        assert as_instant(document.fetched_at_utc) > as_instant(earlier.fetched_at_utc)
