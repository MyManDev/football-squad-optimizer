"""The manager's word, as a constraint the member switches on.

Model-sourced club news enters advice the one way this repository allows it to: as a
declared constraint with a price, never as a projection input (the 8 September decision,
``docs/rotation_evidence_contract.md``). The evidence table states, per roster player, what
the club's own page said and how the model coded it, categorically. This module turns the
dispositions that name an absence or a doubt into a ``FirstWeekExclusion``, and carries the
manager's own words beside it, resolved from the captured bytes by digest and span, so the
member reads the source rather than a paraphrase of ours.

The rule is declared here, not measured anywhere:

- ``stated_expected_absent``: not in the eleven, and so not captain;
- ``stated_rotation_risk`` and ``stated_minutes_limited``: not captain;
- everything else (expected to start, returning from injury, ambiguous, not addressed,
  no statement) constrains nothing.

The exclusion names every player the club's page spoke about, held or not: a player the
manager said will not travel must not be bought and started either. What the member is
shown is the subset that touches their own plan (the fifteen they hold, the fifteen their
pure-points control ends with, and the fifteen the switched-on plan ends with). What the
constraint costs is the difference between two of the member's own solves, published by
``advice.advise_with_managers_word``.
"""

import hashlib
import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.application.strategies.catalog import FORBIDDEN_TEXT_PATTERN
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import FixtureClubNewsProvider, RawDocument
from squadopt.data.sources.club_news_capture import read_captured_documents
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.planning import FirstWeekExclusion

MANAGERS_WORD_RULE_VERSION: Final = "managers_word_rule_v1"
MANAGERS_WORD_FILE: Final = "hoca-sozu.json"
"""The file name of the switched-on plan beside a member's one-week baseline."""
NOT_STARTING_DISPOSITIONS: Final[frozenset[str]] = frozenset({"stated_expected_absent"})
NOT_CAPTAIN_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"stated_expected_absent", "stated_rotation_risk", "stated_minutes_limited"}
)
SOURCE_SYNTHETIC_FIXTURE: Final = "synthetic_fixture"
#: What a quote may not carry onto a member page. The Python copy guard
#: (``FORBIDDEN_TEXT_PATTERN``) was written for the site's own words; a quote is a third
#: party's sentence and can say anything, so this is the wider list the web guard applies to
#: rendered pages (``web/src/testSupport/honesty.ts``, ``AS_A_CHANCE``) plus the spelled-out
#: forms a manager says aloud. No ownership exception: a quote is never an ownership share.
#: Over-withholding costs a member one quote, which stays one link away; under-withholding
#: publishes a claim the site has promised never to make.
QUOTE_WITHHELD_PATTERN: Final = re.compile(
    "|".join(
        (
            FORBIDDEN_TEXT_PATTERN.pattern,
            r"%",  # Quotes never receive the product-copy ownership exception.
            r"per\s?cent",
            r"percentage",
            r"probabilit",
            "olas\u0131l",
            r"chance",
            r"likelihood",
            r"odds",
            r"quantile",
            r"spread",
            r"\btail\b",
            r"ihtimal",
            "\u015fans",
            "y\u00fczde(?!n\\b)",
            r"kantil",
            "yay\u0131l\u0131m",
            r"\bkuyruk\b",
            r"\b50\s*[-/]\s*50\b",
            r"fifty[\s-]fifty",
        )
    ),
    re.IGNORECASE,
)

WORDS_SHOWN: Final = "shown"
WORDS_UNRESOLVED: Final = "unresolved"
WORDS_WITHHELD_FIGURE: Final = "withheld_figure"
"""A quote that carries wording the site never publishes (a per cent sign, a chance, odds):
the source's own words, but the rule about what a member page may show applies to every
sentence on it, whoever wrote the sentence. The page says the words were withheld and why,
and links the source."""
SOURCE_FIXTURE_FILE: Final = "fixture_file"
SOURCE_CLUB_NEWS_CAPTURE: Final = "club_news_capture"

SOURCE_CHECK_CITED_DOCUMENTS_HELD: Final = "cited_documents_held"
"""The digest guard compared the source with the table and it holds every cited document."""
SOURCE_CHECK_NOTHING_CITED: Final = "nothing_cited"
"""The table cites no document, which is what a week with no claims looks like, so the digest
guard had nothing to compare. It is not a pass: the source was not shown to be the one the
table was coded from, only not shown to be a different one. Logged when it happens."""

_LOG: Final = logging.getLogger(__name__)


class ManagerWordsError(DataError):
    """The evidence or its source could not be read as the manager's word."""


@dataclass(frozen=True, slots=True)
class ManagerWord:
    """One coded statement about one player, with the words it was coded from."""

    player_id: int
    disposition: str
    speaker: str | None
    published_at_utc: str | None
    published_precision: str | None
    club: str | None
    source_url: str | None
    fetched_at_utc: str | None
    words: str | None
    """The cited span, decoded; ``None`` when unresolved or withheld (``words_status``)."""
    words_status: str = WORDS_SHOWN

    def __post_init__(self) -> None:
        if self.words is None and self.words_status == WORDS_SHOWN:
            object.__setattr__(self, "words_status", WORDS_UNRESOLVED)
        if self.words is not None and self.words_status != WORDS_SHOWN:
            raise ManagerWordsError("Words are either shown or withheld, never both.")

    @property
    def role(self) -> str | None:
        """What the rule makes of it: ``not_starting``, ``not_captain`` or ``None``."""

        if self.disposition in NOT_STARTING_DISPOSITIONS:
            return "not_starting"
        if self.disposition in NOT_CAPTAIN_DISPOSITIONS:
            return "not_captain"
        return None


@dataclass(frozen=True, slots=True)
class ManagerWords:
    """One decision week's coded club news, ready to constrain a member's plan."""

    season: str
    gameweek: int
    source_kind: str
    source_label: str
    evidence_table: str
    clubs_covered: tuple[str, ...]
    words: tuple[ManagerWord, ...]
    source_check: str | None = None
    """What the digest guard found when this was read from an artifact
    (``SOURCE_CHECK_CITED_DOCUMENTS_HELD`` or ``SOURCE_CHECK_NOTHING_CITED``); ``None`` when
    it was built directly and no guard ran."""

    @property
    def constraining(self) -> tuple[ManagerWord, ...]:
        """Every statement the rule acts on, whoever holds the player."""

        return tuple(word for word in self.words if word.role is not None)

    def about(self, players: Iterable[int]) -> tuple[ManagerWord, ...]:
        """The constraining statements about the named players, for the member to read."""

        named = {int(player) for player in players}
        return tuple(word for word in self.constraining if word.player_id in named)

    def exclusion(self) -> FirstWeekExclusion | None:
        """The solver's half of the rule, or ``None`` when the page constrained nobody."""

        applied = self.constraining
        if not applied:
            return None
        return FirstWeekExclusion(
            not_starting=frozenset(w.player_id for w in applied if w.role == "not_starting"),
            not_captain=frozenset(w.player_id for w in applied if w.role == "not_captain"),
        )

    def as_source_record(self) -> dict[str, object]:
        return {
            "kind": "managers_word",
            "rule_version": MANAGERS_WORD_RULE_VERSION,
            "source_kind": self.source_kind,
            "source_label": self.source_label,
            "evidence_table": self.evidence_table,
            "clubs_covered": list(self.clubs_covered),
        }


def _text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or value is pd.NA:
        return None
    text = str(value).strip()
    return text or None


def _resolve(
    documents: Sequence[RawDocument], digest: str | None, start: object, end: object
) -> tuple[RawDocument | None, str | None]:
    """The document whose bytes hash to the citation, and the cited span decoded.

    The claim parser hashed the bytes it indexed; whether those were the readable text
    or the raw content is settled by which one hashes to the digest, so both are tried
    and the span is cut from the one that matched. A digest no held document produces
    resolves to nothing rather than to different words presented as the source's own.
    """

    if digest is None:
        return None, None
    for document in documents:
        for candidate in (document.readable, document.content):
            if hashlib.sha256(candidate).hexdigest() != digest:
                continue
            try:
                first, last = int(str(start)), int(str(end))
            except (TypeError, ValueError):
                return document, None
            if not 0 <= first < last <= len(candidate):
                return document, None
            return document, candidate[first:last].decode("utf-8", errors="replace").strip()
    return None, None


def _covered(table: pd.DataFrame, table_path: Path) -> tuple[str, ...]:
    """The clubs the manifest recorded as covered, never a set recomputed from documents.

    Covered means read **and** coded, and ``rotation_export`` narrows it once more when a
    club's claims lose their citations. The documents in hand only say what was *read*, so
    deriving coverage from them would publish a club whose page was fetched and whose coding
    failed as though the member were reading that club's news. The distinction cannot be
    recovered later either -- from the payloads alone, a club whose second page was refused is
    indistinguishable from one that only ever registered a single page -- which is exactly why
    the capture records the lists rather than leaving them to be recomputed.

    A frame without them did not come from ``read_rotation_evidence_artifact``, and guessing
    is the one thing this function exists to refuse.
    """

    covered = table.attrs.get("clubs_covered")
    if covered is None:
        raise ManagerWordsError(
            f"{Path(table_path).name} arrived without its manifest's coverage lists, so which "
            "clubs were covered is not known. Coverage is recorded when the week is captured "
            "and cannot be recomputed from the table."
        )
    return tuple(str(club) for club in covered)


def _require_the_coded_documents(
    table: pd.DataFrame, table_path: Path, documents: Sequence[RawDocument], source_label: str
) -> str:
    """Refuse documents that are not the ones this table's claims were coded from.

    The manifest lists the digest of every document a claim cites (``document_sha256s``,
    taken over the readable bytes the parser indexed). A source that holds none of them is a
    different week or a different source, and joining it would publish that source's label
    and link beside claims it never made.

    **A table with no claims cites nothing, and then there is nothing to compare.** Any source
    would pass a check over an empty list, so that case is not reported as a pass: it returns
    ``SOURCE_CHECK_NOTHING_CITED`` and logs a warning naming the table and the source. It is
    not refused either, because a quiet week with no claims is a real outcome (the first real
    run was one) and its source label is still what the member is told was read.
    """

    declared = table.attrs.get("document_sha256s")
    if declared is None:
        raise ManagerWordsError(
            f"{Path(table_path).name} arrived without its manifest's document digests, so "
            "which documents its claims cite is not known."
        )
    if not declared:
        _LOG.warning(
            "%s cites no document (claims coded: %s), so the club-news source %s could not be "
            "checked against it: the digest guard had nothing to compare. Recorded as %s.",
            Path(table_path).name,
            table.attrs.get("claims_coded", "not recorded"),
            source_label,
            SOURCE_CHECK_NOTHING_CITED,
        )
        return SOURCE_CHECK_NOTHING_CITED
    held: set[str] = set()
    for document in documents:
        held.add(hashlib.sha256(document.readable).hexdigest())
        held.add(hashlib.sha256(document.content).hexdigest())
    missing = sorted(str(digest) for digest in declared if str(digest) not in held)
    if missing:
        raise ManagerWordsError(
            f"The club-news source supplied does not hold {len(missing)} of the documents "
            f"{Path(table_path).name} cites (first: {missing[0][:12]}); it is not the "
            "source this table was coded from."
        )
    return SOURCE_CHECK_CITED_DOCUMENTS_HELD


def manager_words_from_artifact(
    table_path: Path,
    manifest_path: Path,
    *,
    documents: Sequence[RawDocument],
    source_kind: str,
    source_label: str,
) -> ManagerWords:
    """Read a verified evidence artifact into the statements the rule can act on."""

    table = read_rotation_evidence_artifact(Path(table_path), Path(manifest_path))
    seasons = {str(value) for value in table["season"].tolist()}
    gameweeks = {int(value) for value in table["target_gameweek"].tolist()}
    if len(seasons) != 1 or len(gameweeks) != 1:
        raise ManagerWordsError(
            f"{Path(table_path).name} spans seasons {sorted(seasons)} and gameweeks "
            f"{sorted(gameweeks)}; one artifact is one decision week."
        )
    clubs = _covered(table, table_path)
    source_check = _require_the_coded_documents(table, table_path, documents, source_label)
    words: list[ManagerWord] = []
    for row in table.to_dict(orient="records"):
        disposition = _text(row.get("rotation_disposition"))
        if disposition is None:
            continue
        document, cited = _resolve(
            documents,
            _text(row.get("rotation_claim_source_sha256")),
            row.get("rotation_claim_span_start"),
            row.get("rotation_claim_span_end"),
        )
        status = WORDS_SHOWN if cited is not None else WORDS_UNRESOLVED
        if cited is not None and QUOTE_WITHHELD_PATTERN.search(cited):
            cited, status = None, WORDS_WITHHELD_FIGURE
        words.append(
            ManagerWord(
                player_id=int(str(row["player_id"])),
                disposition=disposition,
                speaker=_text(row.get("rotation_claim_speaker")),
                published_at_utc=_text(row.get("rotation_claim_published_at_utc")),
                published_precision=_text(row.get("rotation_claim_published_precision")),
                club=None if document is None else document.club,
                source_url=None if document is None else document.final_url,
                fetched_at_utc=None if document is None else document.fetched_at_utc,
                words=cited,
                words_status=status,
            )
        )
    return ManagerWords(
        season=seasons.pop(),
        gameweek=gameweeks.pop(),
        source_kind=source_kind,
        source_label=source_label,
        evidence_table=Path(table_path).name,
        clubs_covered=clubs,
        words=tuple(sorted(words, key=lambda word: word.player_id)),
        source_check=source_check,
    )


def documents_from_source(
    source: Path, *, snapshot_root: Path | None = None
) -> tuple[tuple[RawDocument, ...], str, str]:
    """The captured documents behind an evidence table, with what kind of source they are.

    A file is the committed fixture, whose ``synthetic`` flag is what makes its words
    example data on every surface that shows them; a directory is a club-news capture
    under the snapshot root, read back exactly as it was fetched.
    """

    path = Path(source)
    if path.is_file():
        provider = FixtureClubNewsProvider(path)
        documents = tuple(provider.fetch(url) for url in provider.urls)
        synthetic = json.loads(path.read_text(encoding="utf-8")).get("synthetic") is True
        return documents, SOURCE_SYNTHETIC_FIXTURE if synthetic else SOURCE_FIXTURE_FILE, path.name
    if path.is_dir():
        root = Path(snapshot_root) if snapshot_root is not None else path.parent
        snapshot = read_snapshot(root, path.name)
        return read_captured_documents(snapshot), SOURCE_CLUB_NEWS_CAPTURE, path.name
    raise ManagerWordsError(f"No club-news source at {path}: not a fixture file, not a capture.")


def load_manager_words(
    table_path: Path, *, club_news_source: Path, snapshot_root: Path | None = None
) -> ManagerWords:
    """The evidence table beside its manifest, joined to the documents it was coded from."""

    table = Path(table_path)
    manifest = table.with_suffix(".manifest.json")
    if not manifest.is_file():
        raise ManagerWordsError(f"No manifest beside {table.name}: expected {manifest.name}.")
    documents, kind, label = documents_from_source(club_news_source, snapshot_root=snapshot_root)
    return manager_words_from_artifact(
        table, manifest, documents=documents, source_kind=kind, source_label=label
    )


__all__ = [
    "MANAGERS_WORD_FILE",
    "MANAGERS_WORD_RULE_VERSION",
    "NOT_CAPTAIN_DISPOSITIONS",
    "NOT_STARTING_DISPOSITIONS",
    "QUOTE_WITHHELD_PATTERN",
    "SOURCE_CHECK_CITED_DOCUMENTS_HELD",
    "SOURCE_CHECK_NOTHING_CITED",
    "SOURCE_CLUB_NEWS_CAPTURE",
    "SOURCE_FIXTURE_FILE",
    "SOURCE_SYNTHETIC_FIXTURE",
    "WORDS_SHOWN",
    "WORDS_UNRESOLVED",
    "WORDS_WITHHELD_FIGURE",
    "ManagerWord",
    "ManagerWords",
    "ManagerWordsError",
    "documents_from_source",
    "load_manager_words",
    "manager_words_from_artifact",
]
