"""Describe a completed news acquisition without treating silence as news coverage.

Names are joined exactly to the supplied snapshot teams. This report describes registered
and selected sources, documents received, and model responses. It does not inspect article
quality, validate claims, or establish that a club published no relevant news.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from squadopt.data.sources.club_news import RawDocument
from squadopt.platform.club_news_fetch import ClubSource


@dataclass(frozen=True, slots=True)
class ClubNewsCoverageReport:
    """Roster-ordered club lists; failure lists describe missing acquisition outputs."""

    league_clubs: tuple[str, ...]
    registered_clubs: tuple[str, ...]
    selected_clubs: tuple[str, ...]
    read_clubs: tuple[str, ...]
    coded_clubs: tuple[str, ...]
    covered_clubs: tuple[str, ...]
    partially_covered_clubs: tuple[str, ...]
    unregistered_clubs: tuple[str, ...]
    unselected_clubs: tuple[str, ...]
    read_failed_clubs: tuple[str, ...]
    coding_failed_clubs: tuple[str, ...]
    unknown_registry_clubs: tuple[str, ...]
    ignored_placeholder_clubs: tuple[str, ...]
    registered_page_count: int
    selected_page_count: int
    read_document_count: int
    refused_pages: tuple[tuple[str, str], ...]
    refused_coding: tuple[tuple[str, str], ...]

    @property
    def counts(self) -> dict[str, int]:
        """Counts accompany the lists rather than replacing their exact identities."""

        return {
            "league": len(self.league_clubs),
            "registered": len(self.registered_clubs),
            "selected": len(self.selected_clubs),
            "read": len(self.read_clubs),
            "coded": len(self.coded_clubs),
            "covered": len(self.covered_clubs),
            "partially_covered": len(self.partially_covered_clubs),
            "unregistered": len(self.unregistered_clubs),
            "unselected": len(self.unselected_clubs),
            "read_failed": len(self.read_failed_clubs),
            "coding_failed": len(self.coding_failed_clubs),
            "unknown_registry": len(self.unknown_registry_clubs),
            "ignored_placeholder": len(self.ignored_placeholder_clubs),
            "registered_pages": self.registered_page_count,
            "selected_pages": self.selected_page_count,
            "read_documents": self.read_document_count,
        }


def _names(values: Sequence[str], label: str) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"{label} must contain nonempty exact club names.")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not repeat club names.")
    return tuple(values)


def build_club_news_coverage(
    *,
    roster_clubs: Sequence[str],
    registry_sources: Sequence[ClubSource],
    selected_sources: Sequence[ClubSource],
    documents: Sequence[RawDocument],
    coded_clubs: Sequence[str],
    covered_clubs: Sequence[str],
    partially_covered_clubs: Sequence[str],
    refused_pages: Sequence[tuple[str, str]],
    refused_coding: Sequence[tuple[str, str]],
) -> ClubNewsCoverageReport:
    """Compare a completed acquisition with the full captured league and registry.

    Unknown registry names are reported separately, never guessed into a team. Selecting
    one is refused. The offline ``Example FC`` placeholder never counts as a real club.
    Selection must contain actual registry entries, including their reading dates.
    Covered and partial lists are checked against the supplied documents and responses.
    An empty but successful model response is still coded; no claims are inferred here.
    """

    roster = _names(roster_clubs, "Snapshot teams")
    league = tuple(club for club in roster if club != "Example FC")
    league_set = set(league)
    registered_names = tuple(dict.fromkeys(source.club for source in registry_sources))
    registered_set = set(registered_names) & league_set
    selected_set = {source.club for source in selected_sources}
    if any(source not in registry_sources for source in selected_sources):
        raise ValueError("Selected sources must be exact entries from the supplied registry.")
    if len({source.address for source in selected_sources}) != len(selected_sources):
        raise ValueError("Selected sources must not repeat registered pages.")
    unknown_selected = selected_set - league_set - {"Example FC"}
    if unknown_selected:
        raise ValueError(
            f"Selected source clubs do not match exact snapshot team names: "
            f"{sorted(unknown_selected)!r}."
        )
    read_set = {document.club for document in documents}
    coded_set = set(_names(coded_clubs, "Coded clubs"))
    covered_set = set(_names(covered_clubs, "Covered clubs"))
    partial_set = set(_names(partially_covered_clubs, "Partly covered clubs"))
    refusal_names = {club for club, _ in (*refused_pages, *refused_coding)}
    acquired_names = read_set | coded_set | covered_set | partial_set | refusal_names
    if acquired_names - selected_set:
        raise ValueError("Acquisition results must belong to exact selected club names.")
    if coded_set - read_set:
        raise ValueError("A coded club must have a received document.")
    if covered_set != read_set & coded_set:
        raise ValueError("Covered clubs must equal clubs with documents and coded responses.")
    selected_urls: dict[str, set[str]] = {}
    read_urls: dict[str, set[str]] = {}
    for source in selected_sources:
        selected_urls.setdefault(source.club, set()).add(source.url)
    for document in documents:
        read_urls.setdefault(document.club, set()).add(document.requested_url)
    expected_partial = {club for club in covered_set if not selected_urls[club] <= read_urls[club]}
    if partial_set != expected_partial:
        raise ValueError("Partly covered clubs must reflect unread selected registered pages.")
    if {club for club, _ in refused_coding} - (read_set - coded_set):
        raise ValueError("Coding refusals require a read club without a coded response.")

    def ordered(names: set[str]) -> tuple[str, ...]:
        return tuple(club for club in league if club in names)

    return ClubNewsCoverageReport(
        league_clubs=league,
        registered_clubs=ordered(registered_set),
        selected_clubs=ordered(selected_set),
        read_clubs=ordered(read_set),
        coded_clubs=ordered(coded_set),
        covered_clubs=ordered(covered_set),
        partially_covered_clubs=ordered(partial_set),
        unregistered_clubs=ordered(league_set - registered_set),
        unselected_clubs=ordered(registered_set - selected_set),
        read_failed_clubs=ordered(selected_set - read_set),
        coding_failed_clubs=ordered(read_set - coded_set),
        unknown_registry_clubs=tuple(
            club for club in registered_names if club not in league_set and club != "Example FC"
        ),
        ignored_placeholder_clubs=tuple(club for club in registered_names if club == "Example FC"),
        registered_page_count=sum(source.club in league_set for source in registry_sources),
        selected_page_count=sum(source.club in league_set for source in selected_sources),
        read_document_count=sum(document.club in league_set for document in documents),
        refused_pages=tuple((club, reason) for club, reason in refused_pages if club in league_set),
        refused_coding=tuple(
            (club, reason) for club, reason in refused_coding if club in league_set
        ),
    )


def format_club_news_coverage(report: ClubNewsCoverageReport) -> str:
    """Render the operator report without implying article or claim completeness."""

    groups = (
        ("Snapshot clubs", report.league_clubs),
        ("Registered clubs", report.registered_clubs),
        ("Selected clubs", report.selected_clubs),
        ("Documents received", report.read_clubs),
        ("Responses coded", report.coded_clubs),
        ("Read and coded", report.covered_clubs),
        ("Partly read and coded", report.partially_covered_clubs),
        ("Not registered", report.unregistered_clubs),
        ("Registered, not selected", report.unselected_clubs),
        ("Selected, no documents", report.read_failed_clubs),
        ("Read, not coded", report.coding_failed_clubs),
        ("Unknown registry names", report.unknown_registry_clubs),
        ("Ignored placeholder", report.ignored_placeholder_clubs),
    )
    lines = [f"{label}: {len(clubs)} [{', '.join(clubs)}]" for label, clubs in groups]
    lines.append(
        f"Pages: {report.registered_page_count} registered, "
        f"{report.selected_page_count} selected; "
        f"{report.read_document_count} documents received (indexes or articles)."
    )
    for stage, refusals in (("Read", report.refused_pages), ("Coding", report.refused_coding)):
        lines.extend(f"{stage} refusal: {club}: {reason}" for club, reason in refusals)
    lines.append(
        "Read and coded describes acquisition only. It does not establish complete article "
        "text, validated claims, or that no relevant news was published."
    )
    return "\n".join(lines)


__all__ = ["ClubNewsCoverageReport", "build_club_news_coverage", "format_club_news_coverage"]
