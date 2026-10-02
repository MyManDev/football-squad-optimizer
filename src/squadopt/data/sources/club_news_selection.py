"""Conservative source selection before paid coding; no claim authorization.

Only explicit article categories/titles and verified publication times exclude a
page. Unknown content remains eligible and still faces the downstream quote gates.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from html.parser import HTMLParser

from squadopt.data.sources.club_news import RawDocument
from squadopt.data.sources.club_news_metadata import publication_metadata
from squadopt.data.timestamps import as_instant

SELECTION_POLICY_VERSION = "first_team_document_selection_v1"
MAX_DOCUMENT_AGE_DAYS = 7


class _Title(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.headings: list[str] = []
        self.current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "h1":
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self.current is not None:
            self.headings.append(" ".join("".join(self.current).split()))
            self.current = None


def article_priority(path: str, label: str) -> int:
    """Explicit irrelevant categories last, availability first, unknown otherwise."""
    decoded = path.casefold()
    category = (
        r"(?:women(?:s)?|ladies|u(?:18|19|21|23)s?|under[- ]?(?:18|19|21|23)s?|"
        r"tickets?|shop|hospitality)"
    )
    categories = rf"(?:academy|youth|{category})"
    if (
        re.search(rf"(?:^|/){categories}(?:/|$)", decoded)
        or re.search(rf"(?:^|/){category}[-_]", decoded)
        or re.match(rf"\s*{categories}(?:\s*:|\s*\||\s*[-\u2013\u2014])", label, re.IGNORECASE)
    ):
        return 2
    words = re.sub(r"[^a-z0-9]+", " ", f"{decoded} {label.casefold()}")
    if re.search(
        r"\b(?:injur(?:y|ies)|fitness|team news|first team|pre match|press conference|"
        r"match preview|medical update|fit for|squad update)\b",
        words,
    ):
        return 0
    return 1


@dataclass(frozen=True, slots=True)
class DocumentSelectionReason:
    club: str
    source_url: str
    selected: bool
    reason: str


@dataclass(frozen=True, slots=True)
class DocumentSelection:
    documents: tuple[RawDocument, ...]
    decisions: tuple[DocumentSelectionReason, ...]
    policy_version: str = SELECTION_POLICY_VERSION


def select_coding_documents(
    documents: Sequence[RawDocument], *, as_of: str | None = None
) -> DocumentSelection:
    cutoff = as_instant(as_of) if as_of is not None else None
    selected: list[RawDocument] = []
    decisions: list[DocumentSelectionReason] = []
    for document in documents:
        reader = _Title()
        if document.content_type.split(";", 1)[0] in ("text/html", "application/xhtml+xml"):
            reader.feed(document.content.decode("utf-8"))
        title = reader.headings[0] if len(reader.headings) == 1 else ""
        path = document.final_url.split("://", 1)[-1].partition("/")[2]
        reason = "eligible_unclassified"
        priority = article_priority(path, title)
        own_team_title = re.sub(
            rf"^{re.escape(document.club)}(?: FC| United)?\s+", "", title, flags=re.IGNORECASE
        )
        other_team = re.match(
            r"(?:women(?:'s)?|ladies|u(?:18|19|21|23)s?|under[- ]?(?:18|19|21|23)s?)\b",
            own_team_title,
            re.IGNORECASE,
        )
        if priority == 2 or other_team:
            reason = "explicit_other_team_or_commercial"
        elif re.match(
            r"(?:internationals?|international (?:round[- ]?up|report)|match report|highlights)"
            r"\s*[:|\u2013\u2014-]",
            title,
            re.IGNORECASE,
        ):
            reason = "explicit_other_competition_or_past_match"
        elif title.casefold() in {
            "news",
            "latest news",
            "all news",
            "first team news",
            "first-team news",
        }:
            reason = "explicit_discovery_index"
        elif priority == 0:
            reason = "availability_or_upcoming_match"
        eligible = not reason.startswith("explicit_")
        if eligible and cutoff is not None:
            metadata = publication_metadata(
                document.content, document.content_type, source_url=document.final_url
            )
            if metadata.verified and metadata.published_precision == "instant":
                published = as_instant(str(metadata.published_at_utc))
                if published > cutoff:
                    reason, eligible = "publication_after_observation", False
                elif published < cutoff - timedelta(days=MAX_DOCUMENT_AGE_DAYS):
                    reason, eligible = "publication_outside_current_window", False
        if eligible:
            selected.append(document)
        decisions.append(
            DocumentSelectionReason(document.club, document.requested_url, eligible, reason)
        )
    indexes = {
        doc.requested_url
        for doc in selected
        if any(
            other.club == doc.club
            and other.requested_url.startswith(doc.requested_url.rstrip("/") + "/")
            for other in selected
        )
    }
    return DocumentSelection(
        tuple(doc for doc in selected if doc.requested_url not in indexes),
        tuple(
            DocumentSelectionReason(
                d.club, d.source_url, False, "discovery_index_with_selected_articles"
            )
            if d.source_url in indexes
            else d
            for d in decisions
        ),
    )
