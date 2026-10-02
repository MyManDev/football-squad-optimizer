"""What an acquisition reports about its coding stage, with each outcome in its own place.

Several things can happen to a club in one run and they are different facts: a page could not
be read, nothing of the club was selected, its input was refused before a call, the call
budget ran out, the call failed, the model answered with no claims, the answer had no list of
claims at all, the answer was reused. The report keeps them apart, counts attempted calls and
reused answers separately from claims, and calls a page an article only on its own evidence.

Offline throughout: the opener, the clock and the provider are injected.
"""

import json
import urllib.error
import urllib.parse
from collections.abc import Sequence
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_club_news_acquire import (
    ARSENAL,
    CONFIG,
    ROSTER,
    SOURCES,
    _Provider,
    _Reply,
)
from tests.unit.test_club_news_observation_clock import (
    ARTICLE,
    STARTED,
    _article,
    _Clock,
    _command,
    _environment,
    _roster_snapshot,
    _text,
)

from squadopt.contracts import injuries
from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import (
    CODING_MODEL_IDENTIFIER,
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
)
from squadopt.platform import club_news_acquire
from squadopt.platform.club_news_acquire import acquire_week, main
from squadopt.platform.club_news_coverage import (
    build_coding_stage_report,
    format_coding_stage,
)
from squadopt.platform.club_news_fetch import ClubSource
from squadopt.platform.club_news_provider import (
    REFUSAL_BEFORE_CALL,
    REFUSAL_BUDGET,
    REFUSAL_CALL_FAILED,
    REFUSAL_NOTHING_SELECTED,
    WeekCoding,
    code_week,
    code_week_by_club,
    register_provider,
)

LIVERPOOL = "https://club.example/liverpool/news"
EVERTON = "https://club.example/everton/news"
CHELSEA = "https://club.example/chelsea/news"
READ_ON = SOURCES[0].terms_read_on
WIDE = (
    *SOURCES,
    ClubSource(club="Liverpool", url=LIVERPOOL, terms_read_on=READ_ON),
    ClubSource(club="Everton", url=EVERTON, terms_read_on=READ_ON),
    ClubSource(club="Chelsea", url=CHELSEA, terms_read_on=READ_ON),
)
LEAGUE = ("Arsenal", "Man Utd", "Liverpool", "Everton", "Chelsea", "Spurs")
TARGET = {
    "season": "2026-27",
    "gameweek": 4,
    "deadline": "2026-09-12T17:30:00Z",
    "as_of": _text(STARTED + timedelta(minutes=30)),
}
TARGETED = replace(CONFIG, target_context=TARGET)


def _answer(claims: int | None) -> ClaimResponse:
    body: dict[str, Any] = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "documents": [],
    }
    if claims is not None:
        body["claims"] = [{"placeholder": index} for index in range(claims)]
    return ClaimResponse(
        text=json.dumps(body), model_identifier=CODING_MODEL_IDENTIFIER, model_version="v1"
    )


class _Outcomes(_Provider):
    """Arsenal states two claims, Man Utd answers with none, Liverpool's call fails."""

    def __init__(self, *, united_claims: int | None = 0) -> None:
        super().__init__()
        self.asked: list[str] = []
        self._united = united_claims

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        club = documents[0].club
        self.asked.append(club)
        if club == "Liverpool":
            raise ClubNewsError("The provider refused the request, for Liverpool.")
        return _answer(2 if club == "Arsenal" else self._united)


def _opener(*, article_days_old: int = 1) -> Any:
    """Five hosts, each a different story.

    Arsenal's page links one dated article. Man Utd's two pages and Liverpool's are plain.
    Everton's only page cannot be read. Chelsea's only page is a ticket-office page, which
    the selection turns away.
    """

    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        if url == EVERTON:
            raise urllib.error.HTTPError(url, 503, "Unavailable", {}, None)  # type: ignore[arg-type]
        if url == CHELSEA:
            return _Reply(url, b"<h1>Tickets: on sale now</h1><p>Buy early.</p>")
        if url == ARSENAL:
            return _Reply(url, f"<a href='{ARTICLE}'>Saka update</a>".encode())
        if url == ARTICLE:
            return _Reply(url, _article(_text(STARTED - timedelta(days=article_days_old))))
        return _Reply(url)

    return _open


def _week(provider: _Provider | None = None, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "sources": WIDE,
        "provider": provider or _Outcomes(),
        "config": TARGETED,
        "roster": ROSTER,
        "opener": _opener(),
        "now": _Clock(),
        "sleeper": lambda _: None,
    }
    arguments.update(overrides)
    return acquire_week(**arguments)


def _report(week: Any) -> Any:
    assert week.document_selection is not None
    return build_coding_stage_report(
        roster_clubs=LEAGUE,
        read_clubs=tuple(dict.fromkeys(d.club for d in week.documents)),
        selection=week.document_selection,
        raw_claims={entry.club: club_news_acquire._raw_claim_count(entry) for entry in week.coded},
        reused_clubs=week.reused_clubs,
        refusal_kinds=week.coding_refusal_kinds,
        model_calls_attempted=week.model_calls_attempted,
    )


# --- one outcome per place ----------------------------------------------------


def test_every_read_club_has_exactly_one_coding_outcome() -> None:
    week = _week(max_calls=3)
    report = _report(week)

    # Everton could not be read at all, so the coding stage never saw it.
    assert [club for club, _reason in week.refused_pages] == ["Everton"]
    # Chelsea was read and nothing of it was selected. No call.
    assert report.nothing_selected_clubs == ("Chelsea",)
    # Liverpool was asked and the call failed. A call was spent on it.
    assert report.call_failed_clubs == ("Liverpool",)
    # Man Utd was asked and answered with nothing: coded, and named as an empty answer.
    assert report.empty_answer_clubs == ("Man Utd",)
    # Arsenal was asked and answered with claims.
    assert report.answered_clubs == ("Arsenal", "Man Utd")
    assert report.raw_claim_count == 2
    assert report.budget_stopped_clubs == report.refused_before_call_clubs == ()
    assert report.unreadable_answer_clubs == report.reused_clubs == ()
    # Two answered and one failed: three calls were attempted.
    assert report.model_calls_attempted == 3

    outcomes = [
        *report.answered_clubs,
        *report.reused_clubs,
        *report.call_failed_clubs,
        *report.budget_stopped_clubs,
        *report.refused_before_call_clubs,
        *report.nothing_selected_clubs,
    ]
    assert sorted(outcomes) == sorted({document.club for document in week.documents})
    assert len(outcomes) == len(set(outcomes))


def test_a_club_stopped_by_the_budget_attempted_no_call() -> None:
    provider = _Outcomes()
    week = _week(provider, max_calls=1)
    report = _report(week)

    assert provider.asked == ["Arsenal"]
    assert week.model_calls_attempted == report.model_calls_attempted == 1
    assert report.budget_stopped_clubs == ("Man Utd", "Liverpool")
    assert report.call_failed_clubs == ()


def test_an_input_refused_before_its_call_is_not_a_failed_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refused while the question was being built: no call was begun, and none is counted."""

    from squadopt.platform import club_news_provider

    real = club_news_provider.coding_input_fingerprint

    def _fingerprint(config: Any, documents: Sequence[RawDocument], roster: Any) -> str:
        if documents[0].club == "Man Utd":
            raise ClubNewsError("The club's documents exceed the input budget.")
        return real(config, documents, roster)

    monkeypatch.setattr(club_news_provider, "coding_input_fingerprint", _fingerprint)
    provider = _Outcomes()
    week = _week(provider)
    report = _report(week)

    assert provider.asked == ["Arsenal", "Liverpool"]
    assert report.refused_before_call_clubs == ("Man Utd",)
    assert report.call_failed_clubs == ("Liverpool",)
    assert report.model_calls_attempted == 2


def test_an_answer_without_a_claims_list_is_not_an_empty_answer() -> None:
    report = _report(_week(_Outcomes(united_claims=None)))

    assert report.unreadable_answer_clubs == ("Man Utd",)
    assert report.empty_answer_clubs == ()
    assert report.raw_claim_count == 2
    assert "Answer without a claims list: 1 [Man Utd]" in format_coding_stage(report)


def test_a_reused_answer_attempts_no_call_and_is_listed_as_reused() -> None:
    first = _week()
    held = tuple(replace(entry, reused_from_snapshot="club-news-earlier") for entry in first.coded)
    provider = _Outcomes()

    week = _week(provider, previous=held)
    report = _report(week)

    # Only Liverpool, which had no held answer, is asked again.
    assert provider.asked == ["Liverpool"]
    assert report.reused_clubs == ("Arsenal", "Man Utd")
    assert report.answered_clubs == ()
    assert report.model_calls_attempted == 1
    assert report.documents_reused == 3 and report.documents_freshly_coded == 0
    printed = format_coding_stage(report)
    assert "Answer reused from an earlier capture: 2 [Arsenal, Man Utd]" in printed
    assert "Documents behind new answers: 0; behind reused answers: 3." in printed


# --- a page is an article on its own evidence ---------------------------------


def test_only_a_page_that_states_its_own_publication_time_is_a_dated_article() -> None:
    report = _report(_week())

    assert report.dated_article_count == 1
    assert report.dated_article_clubs == ("Arsenal",)
    assert report.no_dated_article_clubs == ("Man Utd",)
    # Arsenal's index gives way to its article; Man Utd's two pages and Liverpool's one remain.
    assert report.selected_document_count == 4
    assert report.documents_freshly_coded == 3

    printed = format_coding_stage(report)
    assert "Selected for coding: 4 documents, of which 1 dated articles." in printed
    assert "Coded with a dated article: 1 [Arsenal]" in printed
    assert "Coded with no dated article: 1 [Man Utd]" in printed
    assert "Answer with no claims: 1 [Man Utd]" in printed
    assert "Call attempted and failed: 1 [Liverpool]" in printed
    assert "No document selected for coding: 1 [Chelsea]" in printed
    assert "Model calls attempted: 3." in printed
    assert "Raw claims: 2, as the model stated them." in printed


def test_a_linked_page_that_states_no_publication_time_is_not_called_an_article() -> None:
    """Reached by a link and selected, yet nothing on it says it is an article."""

    section = f"{ARSENAL}/first-team"

    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        if url == ARSENAL:
            return _Reply(url, f"<a href='{section}'>First team</a>".encode())
        if url == section:
            return _Reply(url, b"<h1>First team news</h1><p>Latest stories.</p>")
        return _Reply(url)

    week = _week(_Provider(), sources=SOURCES[:1], opener=_open)
    report = _report(week)

    assert week.document_selection is not None
    assert [d.requested_url for d in week.document_selection.documents] == [section]
    assert report.dated_article_count == 0
    assert report.dated_article_clubs == ()
    assert report.no_dated_article_clubs == ("Arsenal",)


def test_when_the_article_is_turned_away_the_club_is_coded_without_one() -> None:
    """A stale article is not selected; the page that linked it is what gets coded."""

    week = _week(_Provider(), sources=SOURCES[:1], opener=_opener(article_days_old=30))
    report = _report(week)

    assert week.document_selection is not None
    turned_away = [d for d in week.document_selection.decisions if d.source_url == ARTICLE]
    assert [(d.selected, d.reason) for d in turned_away] == [
        (False, "publication_outside_current_window")
    ]
    assert [d.requested_url for d in week.document_selection.documents] == [ARSENAL]
    assert report.dated_article_clubs == ()
    assert report.no_dated_article_clubs == ("Arsenal",)
    # Turned away by the selection: not a page that failed to read, and not a refused club.
    assert week.refused_pages == () and week.refused_coding == ()


# --- inputs that do not describe one run are refused --------------------------


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"raw_claims": {"Arsenal": 2, "Man Utd": -1}}, "nonnegative integers"),
        ({"raw_claims": {"Arsenal": 2, "Man Utd": True}}, "nonnegative integers"),
        # Chelsea was read and nothing of it was selected: an answer for it is not this run's.
        (
            {
                "raw_claims": {"Arsenal": 2, "Man Utd": 0, "Chelsea": 1},
                "refusal_kinds": (("Liverpool", REFUSAL_CALL_FAILED),),
            },
            "document selected",
        ),
        ({"reused_clubs": ("Liverpool",)}, "must belong to a coded club"),
        ({"refusal_kinds": (("Liverpool", "something_else"),)}, "Unknown coding refusal kind"),
        ({"refusal_kinds": (("Arsenal", REFUSAL_CALL_FAILED),)}, "exactly one coding outcome"),
        (
            {
                "refusal_kinds": (
                    ("Liverpool", REFUSAL_CALL_FAILED),
                    ("Liverpool", REFUSAL_BUDGET),
                )
            },
            "exactly one coding outcome",
        ),
        ({"model_calls_attempted": -1}, "nonnegative integer"),
        ({"model_calls_attempted": True}, "nonnegative integer"),
        # A club that was read vanishes from no list: it has an outcome or the report is refused.
        ({"raw_claims": {"Arsenal": 2}}, "Every read club has exactly one coding outcome"),
        # An outcome for a club nobody read is not this run's.
        (
            {
                "refusal_kinds": (
                    ("Chelsea", REFUSAL_NOTHING_SELECTED),
                    ("Liverpool", REFUSAL_BUDGET),
                    ("Spurs", REFUSAL_BUDGET),
                )
            },
            "Every read club has exactly one coding outcome",
        ),
        # A name outside the league is not a club this report can place.
        (
            {"raw_claims": {"Arsenal": 2, "Man Utd": 0, "Example FC": 1}},
            "exact selected club names",
        ),
        (
            {"read_clubs": ("Arsenal", "Man Utd", "Chelsea", "Liverpool", "Nowhere")},
            "exact selected club names",
        ),
        # The kind of a refusal fits the selection: nothing selected is for a club with none.
        (
            {"refusal_kinds": (("Chelsea", REFUSAL_BUDGET), ("Liverpool", REFUSAL_BUDGET))},
            "nothing selected is the refusal of a club with no selected document",
        ),
        (
            {
                "refusal_kinds": (
                    ("Chelsea", REFUSAL_NOTHING_SELECTED),
                    ("Liverpool", REFUSAL_NOTHING_SELECTED),
                )
            },
            "nothing selected is the refusal of a club with no selected document",
        ),
    ],
)
def test_coding_inputs_that_do_not_describe_one_run_are_refused(
    overrides: dict[str, Any], message: str
) -> None:
    week = _week()
    arguments: dict[str, Any] = {
        "roster_clubs": LEAGUE,
        "read_clubs": tuple(dict.fromkeys(d.club for d in week.documents)),
        "selection": week.document_selection,
        "raw_claims": {"Arsenal": 2, "Man Utd": 0},
        "reused_clubs": (),
        "refusal_kinds": week.coding_refusal_kinds,
        "model_calls_attempted": 3,
    }
    arguments.update(overrides)
    with pytest.raises(ValueError, match=message):
        build_coding_stage_report(**arguments)


def test_a_week_coding_whose_kinds_do_not_follow_its_refusals_is_refused() -> None:
    week = _week(max_calls=1)
    coding = code_week(_Outcomes(), TARGETED, week.documents, ROSTER, max_calls=1)
    with pytest.raises(ValueError, match="Each refusal has its kind"):
        WeekCoding(coding.coded, coding.refused, coding.calls_attempted, coding.refusal_kinds[1:])
    with pytest.raises(ValueError, match="Each refusal has its kind"):
        WeekCoding(coding.coded, coding.refused, coding.calls_attempted, ())


def test_the_four_refusal_kinds_are_the_ones_the_coding_stage_names() -> None:
    week = _week(max_calls=1)
    kinds = dict(week.coding_refusal_kinds)

    assert [club for club, _kind in week.coding_refusal_kinds] == [
        club for club, _reason in week.refused_coding
    ]
    assert kinds == {
        "Chelsea": REFUSAL_NOTHING_SELECTED,
        "Man Utd": REFUSAL_BUDGET,
        "Liverpool": REFUSAL_BUDGET,
    }
    assert REFUSAL_BEFORE_CALL not in kinds.values()


def test_the_two_tuple_form_still_returns_what_was_coded_and_refused() -> None:
    week = _week()
    assert week.document_selection is not None
    coded, refused = code_week_by_club(_Outcomes(), TARGETED, week.documents, ROSTER)
    coding = code_week(_Outcomes(), TARGETED, week.documents, ROSTER)

    assert coding.calls_attempted == 3
    assert tuple(entry.club for entry in coded) == ("Arsenal", "Man Utd")
    assert refused == coding.refused
    assert [club for club, _reason in refused] == ["Chelsea", "Liverpool"]


# --- the command prints it ---------------------------------------------------


def _plain_opener(requested: list[str] | None = None) -> Any:
    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if requested is not None:
            requested.append(url)
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        if url == ARSENAL:
            return _Reply(url, f"<a href='{ARTICLE}'>Saka update</a>".encode())
        if url == ARTICLE:
            return _Reply(url, _article(_text(STARTED - timedelta(hours=2))))
        return _Reply(url)

    return _open


def test_the_command_prints_attempted_calls_dated_articles_and_empty_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    name = "fake-acquisition-report"
    register_provider(name, lambda config: _Provider())
    roster_id = _roster_snapshot(tmp_path / "snapshots")

    code = main(
        _command(tmp_path, roster_id, "--dry-run"),
        environ=_environment(name),
        opener=_plain_opener(),
        now=_Clock(),
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "Call budget   3; 2 attempted; no automatic provider retry" in printed
    assert "Selected for coding: 3 documents, of which 1 dated articles." in printed
    assert "Documents behind new answers: 3; behind reused answers: 0." in printed
    assert "Coded with a dated article: 1 [Arsenal]" in printed
    assert "Coded with no dated article: 1 [Man Utd]" in printed
    assert "Answer with no claims: 2 [Arsenal, Man Utd]" in printed
    assert "Model calls attempted: 2." in printed
    assert "Dry run: nothing written." in printed


def test_the_club_flow_asks_only_registered_hosts_with_the_central_source_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The league's central injury page stays off, and nothing in this flow needs it."""

    assert injuries.OFFICIAL_INJURY_SOURCE_ENABLED is False
    with pytest.raises(ValueError, match="disabled"):
        injuries.require_official_injury_source()

    name = "fake-central-off"
    register_provider(name, lambda config: _Provider())
    roster_id = _roster_snapshot(tmp_path / "snapshots")
    requested: list[str] = []

    code = main(
        _command(tmp_path, roster_id, "--dry-run"),
        environ=_environment(name),
        opener=_plain_opener(requested),
        now=_Clock(),
        sleeper=lambda _: None,
    )

    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "Coded         2 clubs" in printed
    registered = {urllib.parse.urlsplit(source.url).netloc for source in SOURCES}
    assert requested
    assert {urllib.parse.urlsplit(url).netloc for url in requested} == registered
