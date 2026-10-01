"""Offline accounting of registered, selected, read and coded club news."""

from datetime import date
from typing import Any

import pytest

from squadopt.data.sources.club_news import RawDocument
from squadopt.platform.club_news_coverage import (
    ClubNewsCoverageReport,
    build_club_news_coverage,
    format_club_news_coverage,
)
from squadopt.platform.club_news_fetch import ClubSource

READ_ON = date(2026, 10, 1)


def source(club: str, path: str = "news") -> ClubSource:
    return ClubSource(club, f"https://club.example/{club.replace(' ', '-')}/{path}", READ_ON)


def document(entry: ClubSource, *, url: str | None = None) -> RawDocument:
    # Navigation is deliberately sufficient to construct a received document. The coverage
    # report must not promote that fact into a claim about article completeness or news.
    content = b"<nav>News Tickets Shop</nav>"
    address = url or entry.url
    return RawDocument(
        club=entry.club,
        requested_url=address,
        final_url=address,
        http_status=200,
        content_type="text/html",
        byte_length=len(content),
        fetched_at_utc="2026-10-01T12:00:00Z",
        content=content,
        readable=b"News Tickets Shop\n",
    )


ARSENAL = source("Arsenal")
UNITED = source("Man Utd")
UNITED_SECOND = source("Man Utd", "press")
LIVERPOOL = source("Liverpool")
EVERTON = source("Everton")
PLACEHOLDER = source("Example FC")
UNKNOWN = source("Manchester United")
REGISTRY = (ARSENAL, UNITED, UNITED_SECOND, LIVERPOOL, EVERTON, PLACEHOLDER, UNKNOWN)


def report(**overrides: Any) -> ClubNewsCoverageReport:
    arguments: dict[str, Any] = {
        "roster_clubs": ("Everton", "Arsenal", "Man Utd", "Liverpool", "Chelsea"),
        "registry_sources": REGISTRY,
        "selected_sources": (ARSENAL, UNITED, UNITED_SECOND, LIVERPOOL),
        "documents": (document(UNITED), document(LIVERPOOL)),
        "coded_clubs": ("Man Utd",),
        "covered_clubs": ("Man Utd",),
        "partially_covered_clubs": ("Man Utd",),
        "refused_pages": (("Arsenal", "robots refused"), ("Man Utd", "press page failed")),
        "refused_coding": (("Liverpool", "response refused"),),
    }
    arguments.update(overrides)
    return build_club_news_coverage(**arguments)


def test_reports_league_denominator_and_distinct_acquisition_outcomes() -> None:
    result = report()
    assert result.league_clubs == ("Everton", "Arsenal", "Man Utd", "Liverpool", "Chelsea")
    assert result.registered_clubs == ("Everton", "Arsenal", "Man Utd", "Liverpool")
    assert result.selected_clubs == ("Arsenal", "Man Utd", "Liverpool")
    assert result.read_clubs == ("Man Utd", "Liverpool")
    assert result.coded_clubs == result.covered_clubs == ("Man Utd",)
    assert result.partially_covered_clubs == ("Man Utd",)
    assert result.unregistered_clubs == ("Chelsea",)
    assert result.unselected_clubs == ("Everton",)
    assert result.read_failed_clubs == ("Arsenal",)
    assert result.coding_failed_clubs == ("Liverpool",)
    assert result.unknown_registry_clubs == ("Manchester United",)
    assert result.ignored_placeholder_clubs == ("Example FC",)
    assert result.counts == {
        "league": 5,
        "registered": 4,
        "selected": 3,
        "read": 2,
        "coded": 1,
        "covered": 1,
        "partially_covered": 1,
        "unregistered": 1,
        "unselected": 1,
        "read_failed": 1,
        "coding_failed": 1,
        "unknown_registry": 1,
        "ignored_placeholder": 1,
        "registered_pages": 5,
        "selected_pages": 4,
        "read_documents": 2,
    }


def test_empty_successful_response_and_index_text_do_not_assert_news_completeness() -> None:
    text = format_club_news_coverage(report())
    assert "Read and coded: 1 [Man Utd]" in text
    assert "Read, not coded: 1 [Liverpool]" in text
    assert "Coding refusal: Liverpool: response refused" in text
    assert "indexes or articles" in text
    assert "does not establish complete article text, validated claims" in text
    assert "or that no relevant news was published" in text


def test_failed_linked_article_does_not_mean_unread_registered_page() -> None:
    result = report(
        selected_sources=(UNITED,),
        documents=(document(UNITED), document(UNITED, url=UNITED.url + "/story")),
        partially_covered_clubs=(),
        refused_pages=(("Man Utd", "a different linked article failed"),),
        refused_coding=(),
    )
    assert result.covered_clubs == ("Man Utd",)
    assert result.partially_covered_clubs == ()
    assert result.read_document_count == 2
    assert result.refused_pages == (("Man Utd", "a different linked article failed"),)


def test_offline_placeholder_never_counts_as_a_real_league_club() -> None:
    result = report(
        roster_clubs=("Example FC", "Arsenal"),
        registry_sources=(PLACEHOLDER,),
        selected_sources=(PLACEHOLDER,),
        documents=(document(PLACEHOLDER),),
        coded_clubs=("Example FC",),
        covered_clubs=("Example FC",),
        partially_covered_clubs=(),
        refused_pages=(),
        refused_coding=(),
    )
    assert result.league_clubs == result.unregistered_clubs == ("Arsenal",)
    assert result.registered_clubs == result.selected_clubs == result.covered_clubs == ()
    assert result.read_document_count == result.registered_page_count == 0
    assert result.ignored_placeholder_clubs == ("Example FC",)


def test_empty_registry_keeps_all_snapshot_clubs_unregistered() -> None:
    result = report(
        registry_sources=(),
        selected_sources=(),
        documents=(),
        coded_clubs=(),
        covered_clubs=(),
        partially_covered_clubs=(),
        refused_pages=(),
        refused_coding=(),
    )
    assert result.unregistered_clubs == result.league_clubs
    assert result.unselected_clubs == result.read_failed_clubs == result.coding_failed_clubs == ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"selected_sources": (UNKNOWN,)}, "exact snapshot team names"),
        ({"selected_sources": (source("Man Utd", "unregistered"),)}, "exact entries"),
        ({"selected_sources": (UNITED, UNITED)}, "repeat registered pages"),
        ({"roster_clubs": ("Man Utd", "Man Utd")}, "repeat club names"),
        ({"roster_clubs": (" ",)}, "nonempty exact club names"),
        ({"documents": (document(EVERTON),)}, "exact selected club names"),
        ({"coded_clubs": ("Arsenal",)}, "received document"),
        ({"covered_clubs": ()}, "documents and coded responses"),
        ({"partially_covered_clubs": ()}, "unread selected registered pages"),
        ({"refused_coding": (("Man Utd", "failed"),)}, "without a coded response"),
    ],
)
def test_refuses_guessed_names_or_inconsistent_acquisition_results(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        report(**overrides)
