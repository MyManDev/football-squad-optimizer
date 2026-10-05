"""Describe a completed news acquisition without treating silence as news coverage.

Names are joined exactly to the supplied snapshot teams. This report describes registered
and selected sources, documents received, and model responses. It does not inspect article
quality, validate claims, or establish that a club published no relevant news.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from squadopt.data.sources.club_news import RawDocument
from squadopt.data.sources.club_news_metadata import publication_metadata
from squadopt.data.sources.club_news_selection import DocumentSelection
from squadopt.platform.club_news_fetch import ClubSource
from squadopt.platform.club_news_provider import (
    REFUSAL_BEFORE_CALL,
    REFUSAL_BUDGET,
    REFUSAL_CALL_FAILED,
    REFUSAL_NOTHING_SELECTED,
)


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


@dataclass(frozen=True, slots=True)
class CodingStageReport:
    """What the coding stage did with the documents that were read, one outcome per place.

    Every list is in roster order and names league clubs only. Every club that was read
    has exactly one outcome: it is in ``answered_clubs`` or ``reused_clubs``, or in exactly
    one of the four refusal lists. The dated-article lists and the claims lists describe
    the coded clubs further and do not add outcomes: a coded club is in one of the two
    dated-article lists, and in ``empty_answer_clubs`` or ``unreadable_answer_clubs`` when
    its answer states no claim or no list of claims.

    A *dated article* is a selected document whose own held fields state a publication time
    verifiably. It is the only evidence this report has that a page is an article: a page
    reached by a link, or a registered page, can equally be a news index or navigation
    text, and is not called an article here because of its address.
    """

    selected_document_count: int
    dated_article_count: int
    documents_freshly_coded: int
    documents_reused: int
    dated_article_clubs: tuple[str, ...]
    no_dated_article_clubs: tuple[str, ...]
    answered_clubs: tuple[str, ...]
    empty_answer_clubs: tuple[str, ...]
    unreadable_answer_clubs: tuple[str, ...]
    reused_clubs: tuple[str, ...]
    call_failed_clubs: tuple[str, ...]
    budget_stopped_clubs: tuple[str, ...]
    refused_before_call_clubs: tuple[str, ...]
    nothing_selected_clubs: tuple[str, ...]
    raw_claim_count: int
    model_calls_attempted: int


_REFUSAL_KINDS = (
    REFUSAL_CALL_FAILED,
    REFUSAL_BUDGET,
    REFUSAL_BEFORE_CALL,
    REFUSAL_NOTHING_SELECTED,
)


def build_coding_stage_report(
    *,
    roster_clubs: Sequence[str],
    read_clubs: Sequence[str],
    selection: DocumentSelection,
    raw_claims: Mapping[str, int | None],
    reused_clubs: Sequence[str],
    refusal_kinds: Sequence[tuple[str, str]],
    model_calls_attempted: int,
) -> CodingStageReport:
    """Describe the coding stage from the one selection it used and its own outcomes.

    ``read_clubs`` are the clubs a document was read for; each has exactly one outcome
    here, and no outcome names a club that was not read. ``raw_claims`` names every coded
    club with the number of claims its answer states, or ``None`` for an answer that
    carries no list of claims. ``reused_clubs`` are the coded clubs whose answer came from
    an earlier capture. ``refusal_kinds`` is the coding stage's own list of which kind each
    refusal was. A club may not be both coded and refused, a reused club must be coded, a
    coded club must have a selected document, and a refusal for nothing selected is the
    refusal of a club with no selected document and of no other: an outcome that does
    not fit the selection is not an outcome this run can describe.
    """

    roster = _names(roster_clubs, "Snapshot teams")
    league = tuple(club for club in roster if club != "Example FC")
    league_set = set(league)

    def ordered(names: set[str]) -> tuple[str, ...]:
        return tuple(club for club in league if club in names)

    read = set(_names(read_clubs, "Read clubs"))
    coded = set(raw_claims)
    if any(
        count is not None and (type(count) is not int or count < 0) for count in raw_claims.values()
    ):
        raise ValueError("Claim counts must be nonnegative integers, or None for no claims list.")
    reused = set(_names(reused_clubs, "Reused clubs"))
    if reused - coded:
        raise ValueError("A reused response must belong to a coded club.")
    kind_of: dict[str, str] = {}
    for club, kind in refusal_kinds:
        if kind not in _REFUSAL_KINDS:
            raise ValueError(f"Unknown coding refusal kind {kind!r}.")
        if club in kind_of or club in coded:
            raise ValueError("A club has exactly one coding outcome.")
        kind_of[club] = kind
    if type(model_calls_attempted) is not int or model_calls_attempted < 0:
        raise ValueError("Model calls attempted must be a nonnegative integer.")
    outcomes = coded | set(kind_of)
    if outcomes - league_set:
        raise ValueError("Coding outcomes must belong to exact selected club names.")
    if read - league_set:
        raise ValueError("Read clubs must belong to exact selected club names.")
    if outcomes != read:
        raise ValueError(
            "Every read club has exactly one coding outcome, and no other club has one."
        )

    chosen = [document for document in selection.documents if document.club in league_set]
    with_selection = {document.club for document in selection.documents}
    if coded - with_selection:
        raise ValueError("A coded club must have a document selected for coding.")
    for club, kind in kind_of.items():
        if (kind == REFUSAL_NOTHING_SELECTED) != (club not in with_selection):
            raise ValueError(
                "A refusal for nothing selected is the refusal of a club with no selected document."
            )
    dated = [
        document
        for document in chosen
        if publication_metadata(
            document.content, document.content_type, source_url=document.final_url
        ).verified
    ]
    dated_clubs = {document.club for document in dated} & coded
    empty = {club for club, count in raw_claims.items() if count == 0}
    unreadable = {club for club, count in raw_claims.items() if count is None}

    def of_kind(kind: str) -> tuple[str, ...]:
        return ordered({club for club, found in kind_of.items() if found == kind})

    return CodingStageReport(
        selected_document_count=len(chosen),
        dated_article_count=len(dated),
        documents_freshly_coded=sum(d.club in coded - reused for d in chosen),
        documents_reused=sum(d.club in reused for d in chosen),
        dated_article_clubs=ordered(dated_clubs),
        no_dated_article_clubs=ordered(coded - dated_clubs),
        answered_clubs=ordered(coded - reused),
        empty_answer_clubs=ordered(empty),
        unreadable_answer_clubs=ordered(unreadable),
        reused_clubs=ordered(reused),
        call_failed_clubs=of_kind(REFUSAL_CALL_FAILED),
        budget_stopped_clubs=of_kind(REFUSAL_BUDGET),
        refused_before_call_clubs=of_kind(REFUSAL_BEFORE_CALL),
        nothing_selected_clubs=of_kind(REFUSAL_NOTHING_SELECTED),
        raw_claim_count=sum(
            count for club, count in raw_claims.items() if count and club in league_set
        ),
        model_calls_attempted=model_calls_attempted,
    )


def format_coding_stage(report: CodingStageReport) -> str:
    """Render the coding stage for an operator, one outcome to a line."""

    def line(label: str, clubs: Sequence[str]) -> str:
        return f"{label}: {len(clubs)} [{', '.join(clubs)}]"

    return "\n".join(
        [
            f"Selected for coding: {report.selected_document_count} documents, of which "
            f"{report.dated_article_count} dated articles.",
            f"Documents behind new answers: {report.documents_freshly_coded}; behind reused "
            f"answers: {report.documents_reused}.",
            line("Coded with a dated article", report.dated_article_clubs),
            line("Coded with no dated article", report.no_dated_article_clubs),
            line("Answered in this run", report.answered_clubs),
            line("Answer reused from an earlier capture", report.reused_clubs),
            line("Answer with no claims", report.empty_answer_clubs),
            line("Answer without a claims list", report.unreadable_answer_clubs),
            line("Call attempted and failed", report.call_failed_clubs),
            line("Stopped by the call budget, no call attempted", report.budget_stopped_clubs),
            line("Refused before a call was attempted", report.refused_before_call_clubs),
            line("No document selected for coding", report.nothing_selected_clubs),
            f"Model calls attempted: {report.model_calls_attempted}.",
            f"Raw claims: {report.raw_claim_count}, as the model stated them. How many apply "
            "is not known here; each is checked against its source at export.",
            "A dated article is a selected page whose own fields state a publication time "
            "verifiably. Any other page, registered or reached by a link, can be a news "
            "index or navigation text and is not called an article here.",
            "An answer with no claims is a successful empty answer. It is not a player "
            "update, not a failed call, and not a statement that the club published nothing.",
        ]
    )


__all__ = [
    "ClubNewsCoverageReport",
    "CodingStageReport",
    "build_club_news_coverage",
    "build_coding_stage_report",
    "format_club_news_coverage",
    "format_coding_stage",
]
