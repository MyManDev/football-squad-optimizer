"""The manager's word, as a constraint the member switches on.

This module applies model-coded club news as a declared constraint with a price,
not as a projection input. The separately authorized football participation and minute
consumers have their own gates. The evidence table states, per roster player, what
the club's own page said and how the model coded it, categorically. This module turns the
dispositions that name an absence or a doubt into a ``FirstWeekExclusion``, and carries the
manager's own words beside it, resolved from the captured bytes by digest and span, so the
member reads the source rather than a paraphrase of ours.

The rule is declared here, not measured anywhere:

- ``stated_expected_absent``: not in the eleven, and so not captain;
- verified ``stated_rotation_risk``: not captain; vague managed minutes constrain nothing;
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
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.application.strategies.catalog import FORBIDDEN_TEXT_PATTERN
from squadopt.data._long_paths import addressable
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import CLUB_NEWS_SOURCE, FixtureClubNewsProvider, RawDocument
from squadopt.data.sources.club_news_capture import read_captured_documents
from squadopt.data.sources.club_news_metadata import PUBLICATION_SOURCES, publication_metadata
from squadopt.data.sources.club_news_scope import FIXTURE_SCOPES, verified_fixture_scope
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    fixture_snapshot,
    short_name_roster,
    team_codes,
    team_names,
)
from squadopt.data.timestamps import as_instant
from squadopt.features.rotation_evidence import (
    claim_fixture_calendar,
    claim_has_only_multiple_fixture_failure,
    claim_targets_next_fixture,
)
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.planning import FirstWeekExclusion

# v3: a statement binds only when its quote is a whole sentence of the held source.
MANAGERS_WORD_RULE_VERSION: Final = "managers_word_rule_v3"
MANAGERS_WORD_FILE: Final = "hoca-sozu.json"
"""The file name of the switched-on plan beside a member's one-week baseline."""
NOT_STARTING_DISPOSITIONS: Final[frozenset[str]] = frozenset({"stated_expected_absent"})
NOT_CAPTAIN_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"stated_expected_absent", "stated_rotation_risk"}
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
    # Internal provenance retained only after the held source span resolves.
    source_sha256: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    fixture_scope: str = "unspecified"
    scope_verified: bool = False
    publication_verified: bool = False
    publication_source: str | None = None
    publication_source_sha256: str | None = None
    fixture_binding_reason: str | None = None

    def __post_init__(self) -> None:
        if self.fixture_binding_reason not in (None, "ambiguous_current_week_fixture"):
            raise ManagerWordsError("Unknown fixture binding reason.")
        if self.fixture_binding_reason is not None and (
            self.scope_verified or self.fixture_scope != "upcoming_premier_league"
        ):
            raise ManagerWordsError("Multiple-fixture evidence must remain unverified in scope.")
        if self.words is None and self.words_status == WORDS_SHOWN:
            object.__setattr__(self, "words_status", WORDS_UNRESOLVED)
        if self.words is not None and self.words_status != WORDS_SHOWN:
            raise ManagerWordsError("Words are either shown or withheld, never both.")
        provenance = (self.source_sha256, self.span_start, self.span_end)
        if any(value is not None for value in provenance) and (
            self.words_status == WORDS_UNRESOLVED
            or not isinstance(self.source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
            or isinstance(self.span_start, bool)
            or not isinstance(self.span_start, Integral)
            or isinstance(self.span_end, bool)
            or not isinstance(self.span_end, Integral)
            or not 0 <= self.span_start < self.span_end
        ):
            raise ManagerWordsError("Source provenance requires one resolved complete byte span.")
        if (
            self.fixture_scope not in FIXTURE_SCOPES
            or type(self.scope_verified) is not bool
            or type(self.publication_verified) is not bool
        ):
            raise ManagerWordsError("Claim attestation requires a known scope and boolean flags.")
        if (self.scope_verified or self.publication_verified) and any(
            value is None for value in provenance
        ):
            raise ManagerWordsError("Claim attestation requires a resolved complete source span.")
        if self.scope_verified and self.fixture_scope != "upcoming_premier_league":
            raise ManagerWordsError("Only explicit upcoming league scope can be verified.")
        if self.publication_verified and (
            self.publication_source not in PUBLICATION_SOURCES
            or not isinstance(self.publication_source_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.publication_source_sha256) is None
            or self.published_at_utc is None
            or self.published_precision not in ("instant", "day")
        ):
            raise ManagerWordsError(
                "Verified publication requires an explicit source date and digest."
            )

    @property
    def role(self) -> str | None:
        """What the rule makes of it: ``not_starting``, ``not_captain`` or ``None``."""

        if not (
            self.scope_verified
            and self.publication_verified
            and self.published_precision == "instant"
            and self.fetched_at_utc
        ):
            return None
        try:
            if as_instant(str(self.published_at_utc)) > as_instant(self.fetched_at_utc):
                return None
        except (DataError, ValueError, TypeError):
            return None
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
) -> tuple[RawDocument | None, str | None, bool]:
    """The document whose bytes hash to the citation, the cited span, and whether it stands alone.

    The claim parser hashed the bytes it indexed; whether those were the readable text
    or the raw content is settled by which one hashes to the digest, so both are tried
    and the span is cut from the one that matched. A digest no held document produces
    resolves to nothing rather than to different words presented as the source's own.

    The third value says whether the span is a whole sentence of the text it was cut from
    (:func:`_is_whole_sentence`). The scope rule reads the quote alone, so it cannot see
    what the source wrapped around it.
    """

    if digest is None:
        return None, None, False
    for document in documents:
        for candidate in (document.readable, document.content):
            if hashlib.sha256(candidate).hexdigest() != digest:
                continue
            try:
                first, last = int(str(start)), int(str(end))
            except (TypeError, ValueError):
                return document, None, False
            if not 0 <= first < last <= len(candidate):
                return document, None, False
            try:
                words = candidate[first:last].decode("utf-8").strip()
            except UnicodeDecodeError:
                return document, None, False
            return document, words or None, _is_whole_sentence(candidate, first, last)
    return None, None, False


#: What may stand between a sentence boundary and the quote: space, and a quotation mark
#: or bracket that opens (before) or closes (after) the sentence the quote is.
_SPACE: Final = " \t"
_MARKS: Final = "\"'\u201c\u201d\u2018\u2019()[]"
_SENTENCE_END: Final = ".!?"
_BOUNDARY: Final = _SENTENCE_END + "\n\r"
#: What may stand before the quoted statement: a boundary, or the colon that introduces
#: reported words ("Arteta said: ...", "Coach: ...").
_OPENING: Final = _BOUNDARY + ":"
#: What may close the quoted statement itself: a period, an exclamation mark or a line end.
_STATEMENT_END: Final = ".!\n\r"


def _is_whole_sentence(text: bytes, first: int, last: int) -> bool:
    """Whether ``text[first:last]`` is a complete sentence of ``text``, not part of one.

    A quote is located as any unique substring of the source, and the scope rule then
    reads the quote on its own. "Saka will miss the next Premier League match." is also a
    substring of "It is not true that Saka will miss the next Premier League match." and
    of "Arteta denied that Saka will miss the next Premier League match if he trains."
    Neither says what the quote says, and a quote that begins or ends inside a sentence
    cannot show that it does.

    So a statement can bind only where the source's own text bounds it: what comes before
    it is the start of the text, a line break, the end of a sentence, or the colon that
    introduces reported words, and what comes after it is the end of the text, a line
    break, or the end of a sentence. A question mark is not the end of a statement, and an
    ellipsis is not the end of anything. Anything else, including an attribution run into
    the words such as "Arteta said Saka will miss ...", leaves the words readable and
    without authority. That refuses some true statements. It never turns a sentence into
    its part.

    A line break counts as a boundary because the readable text puts a headline, a dateline
    and each paragraph on a line of its own, and most pages open their first sentence after
    one. It also stands for a ``<br>`` inside a sentence, which this rule cannot tell from
    a paragraph end; the same goes for a period that ends an abbreviation. Those two are
    the limit of a rule that reads punctuation and not grammar.
    """

    try:
        before = text[:first].decode("utf-8")
        quoted = text[first:last].decode("utf-8")
        after = text[last:].decode("utf-8")
    except UnicodeDecodeError:
        return False
    lead = before.rstrip(_SPACE).rstrip(_MARKS).rstrip(_SPACE)
    if lead and lead[-1] not in _OPENING:
        return False
    rest = after.lstrip(_SPACE).lstrip(_MARKS).lstrip(_SPACE)
    if rest.startswith((".", "\u2026")):
        # "... if he fails a late test": the sentence goes on, whatever the quote ends with.
        return False
    core = quoted.strip().rstrip(_MARKS)
    if core.endswith(("..", "\u2026")):
        return False
    if core.endswith((".", "!")):
        return True
    if core.endswith("?") or rest.startswith("?"):
        return False
    return not rest or rest[0] in _STATEMENT_END


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
    snapshot_root: Path | None = None,
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
    target_basis = _decision_fixture_basis(table, snapshot_root)
    words: list[ManagerWord] = []
    for row in table.to_dict(orient="records"):
        disposition = _text(row.get("rotation_disposition"))
        if disposition is None:
            continue
        document, cited, whole_sentence = _resolve(
            documents,
            _text(row.get("rotation_claim_source_sha256")),
            row.get("rotation_claim_span_start"),
            row.get("rotation_claim_span_end"),
        )
        resolved = cited is not None
        scope = _text(row.get("rotation_claim_fixture_scope")) or "unspecified"
        player = (
            target_basis[1].get(int(str(row["player_id"]))) if target_basis is not None else None
        )
        checked_scope = (
            verified_fixture_scope(
                cited.encode(), disposition, player_name=player[2] if player else None
            )
            if cited
            else ("unspecified", False)
        )
        scope_verified = (
            row.get("rotation_claim_scope_verified") is True
            and checked_scope == (scope, True)
            # The table's flag and the quote's own wording are not enough: the quote must
            # be a whole sentence of the source, or the source may say something else.
            and whole_sentence
        )
        if scope_verified:
            scope_verified = target_basis is not None and _targets_decision(
                row, document, target_basis
            )
        publication_source = _text(row.get("rotation_claim_publication_source"))
        publication_digest = _text(row.get("rotation_claim_publication_source_sha256"))
        metadata = (
            publication_metadata(document.content, document.content_type, document.final_url)
            if document is not None and resolved
            else None
        )
        publication_verified = (
            row.get("rotation_claim_publication_verified") is True
            and metadata is not None
            and metadata.verified
            and metadata.published_at_utc == _text(row.get("rotation_claim_published_at_utc"))
            and metadata.published_precision == _text(row.get("rotation_claim_published_precision"))
            and metadata.source == publication_source
            and metadata.source_sha256 == publication_digest
        )
        fixture_binding_reason = None
        if (
            not scope_verified
            and publication_verified
            and checked_scope == ("upcoming_premier_league", True)
            and whole_sentence
            and target_basis is not None
            and _targets_decision(row, document, target_basis, only_multiple=True)
        ):
            fixture_binding_reason = "ambiguous_current_week_fixture"
        status = WORDS_SHOWN if resolved else WORDS_UNRESOLVED
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
                source_sha256=_text(row.get("rotation_claim_source_sha256")) if resolved else None,
                span_start=int(str(row["rotation_claim_span_start"])) if resolved else None,
                span_end=int(str(row["rotation_claim_span_end"])) if resolved else None,
                fixture_scope=scope,
                scope_verified=scope_verified,
                publication_verified=publication_verified,
                publication_source=publication_source,
                publication_source_sha256=publication_digest,
                fixture_binding_reason=fixture_binding_reason,
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


def _club_news_snapshot(source: Path, snapshot_root: Path | None) -> CapturedSnapshot:
    root = Path(snapshot_root) if snapshot_root is not None else source.parent
    if source.resolve() != (root / source.name).resolve():
        raise ManagerWordsError("Configured club-news capture is outside its snapshot root.")
    snapshot = read_snapshot(root, source.name)
    if snapshot.metadata.source != CLUB_NEWS_SOURCE:
        raise ManagerWordsError("Configured capture is not a club-news capture.")
    return snapshot


def club_news_capture_id(source: Path, *, snapshot_root: Path | None = None) -> str | None:
    """Validate a configured capture's identity; a fixture file has no news capture ID."""
    source = Path(source)
    if source.is_file():
        return None
    if source.is_dir():
        return _club_news_snapshot(source, snapshot_root).metadata.snapshot_id
    raise ManagerWordsError("Configured club-news source is missing.")


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
        snapshot = _club_news_snapshot(path, snapshot_root)
        return (
            read_captured_documents(snapshot),
            SOURCE_CLUB_NEWS_CAPTURE,
            snapshot.metadata.snapshot_id,
        )
    raise ManagerWordsError(f"No club-news source at {path}: not a fixture file, not a capture.")


def load_manager_words(
    table_path: Path, *, club_news_source: Path, snapshot_root: Path | None = None
) -> ManagerWords:
    """The evidence table beside its manifest, joined to the documents it was coded from."""

    table = Path(table_path)
    manifest = table.with_suffix(".manifest.json")
    if not Path(addressable(manifest)).is_file():
        raise ManagerWordsError(f"No manifest beside {table.name}: expected {manifest.name}.")
    documents, kind, label = documents_from_source(club_news_source, snapshot_root=snapshot_root)
    return manager_words_from_artifact(
        table,
        manifest,
        documents=documents,
        source_kind=kind,
        source_label=label,
        snapshot_root=(snapshot_root or club_news_source.parent)
        if club_news_source.is_dir()
        else snapshot_root,
    )


def _decision_fixture_basis(
    table: pd.DataFrame,
    snapshot_root: Path | None,
) -> tuple[pd.DataFrame, dict[int, tuple[str, int, str]], str] | None:
    """Read only the exact immutable decision named by the checked manifest."""
    if snapshot_root is None or "rotation_claim_scope_verified" not in table:
        return None
    try:
        snapshot = read_snapshot(snapshot_root, str(table.attrs["roster_snapshot_id"]))
        captured = snapshot.metadata.captured_at_utc
        if set(table.captured_at_utc.astype(str)) != {captured}:
            return None
        bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
        calendar = fixture_snapshot(
            snapshot.payloads[FIXTURES_PAYLOAD],
            bootstrap,
            season=str(table.season.iloc[0]),
            snapshot_id=snapshot.metadata.snapshot_id,
            captured_at_utc=captured,
        )
        calendar = claim_fixture_calendar(calendar, snapshot.payloads[FIXTURES_PAYLOAD], bootstrap)
        codes, names = team_codes(bootstrap), team_names(bootstrap)
        by_name = {name: codes[identifier] for identifier, name in names.items()}
        players = {
            int(str(row.player_id)): (
                str(row.team_name),
                by_name[str(row.team_name)],
                str(row.web_name),
            )
            for row in short_name_roster(bootstrap).itertuples()
        }
        return calendar, players, captured
    except (DataError, KeyError, ValueError, OSError):
        return None


def _targets_decision(
    row: Mapping[Hashable, object],
    document: RawDocument | None,
    basis: tuple[pd.DataFrame, dict[int, tuple[str, int, str]], str],
    *,
    only_multiple: bool = False,
) -> bool:
    calendar, players, captured = basis
    player = players.get(int(str(row["player_id"])))
    if document is None or player is None or player[0] != document.club:
        return False
    if only_multiple:
        try:
            published = as_instant(str(row.get("rotation_claim_published_at_utc")))
            fetched = as_instant(document.fetched_at_utc)
            cutoff = as_instant(captured)
            if not published <= fetched <= cutoff or cutoff - published > pd.Timedelta(days=7):
                return False
        except (DataError, TypeError, ValueError):
            return False
    check = claim_has_only_multiple_fixture_failure if only_multiple else claim_targets_next_fixture
    return check(
        calendar,
        team_code=player[1],
        target_gameweek=int(str(row["target_gameweek"])),
        captured_at_utc=captured,
        published_at_utc=_text(row.get("rotation_claim_published_at_utc")),
        published_precision=_text(row.get("rotation_claim_published_precision")) or "unknown",
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
    "club_news_capture_id",
    "documents_from_source",
    "load_manager_words",
    "manager_words_from_artifact",
]
