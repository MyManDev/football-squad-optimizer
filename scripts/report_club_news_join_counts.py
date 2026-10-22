"""Count what one week's club news became, offline, and print the join-count record.

    python -m scripts.report_club_news_join_counts --club-news-log <run id>.club-news.log

The protocol is ``docs/research/club_news_join_counts_gw8_prereg.md``: it fixes every count
printed here, how each is computed, and the reading that decides #1006. This command only
reads what the weekly run already left on the publishing PC: the club-news capture and the
decision capture in the snapshot store, the rotation table and manifest the weekly run
exported from them, the source registry, and the acquisition receipt
``data/logs/weekly/<run id>.club-news.log``. It opens no network connection, calls no model
and writes nothing unless ``--output`` names a new file.

**The table is replayed, not trusted.** The no-match, unknown-team, club-source and conflict
counts and the unverifiable citations live only in the attributes of the table the exporter
builds in memory, never in its manifest (#1006 item 4); the ambiguous count is the one the
manifest carries, as ``claims_ambiguous``. So the rotation table is rebuilt here from the two
captures through the exporter's own code, from a clean checkout at the commit the manifest
names and with ``squadopt`` imported from that checkout's own ``src``, and the record is
printed only when the rebuilt bytes hash to the digest the published manifest declares and
the manifest rebuilt from the replay equals the published one. The digest binds the rows,
the manifest binds every attribute it carries, and the commit binds the attributes it does
not. Anything else refuses rather than count a table nobody published.

**Every raw claim ends in exactly one place.** The claims each stored response lists are
followed through the exporter's own reading: a response refused whole, a citation that could
not be verified (of the response's own club or of another), a claim that reached the
identity join and then matched one player, none or several, a source of another club, a
conflict, an identical repeat, or a placed row. The record is printed only when the places
before the join add up to the raw claims and the placed rows are the published table's. The
identical repeats are counted by nothing: they are what remains of the claims that reached
the join after the placed and unresolved ones, as the protocol defines them, so only a
negative remainder refuses, and a place of the join that went uncounted would read as
repeats rather than refuse.

**A club whose model call failed is named, from the receipt.** The capture stores only the
answers that were kept, so a call that was attempted and whose answer was then refused, or
never came, leaves no trace in it (#1006 item 10). The receipt names those clubs, and the
record is printed only when its outcomes cover exactly the clubs the capture read and holds
no answer for.
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.parse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias

import pandas as pd
from scripts._provenance import REPOSITORY_ROOT, _git_revision

import squadopt
from squadopt.application.manager_words import (
    NOT_CAPTAIN_DISPOSITIONS,
    WORDS_UNRESOLVED,
    WORDS_WITHHELD_FIGURE,
    ManagerWord,
    _decision_fixture_basis,
    load_manager_words,
)
from squadopt.application.rotation_export import (
    _inputs_from_capture,
    _manifest,
    _manifest_identity,
    _table_bytes,
)
from squadopt.data.atomic import document_bytes
from squadopt.data.claim_identity import normalise_claim_name
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import CLUB_NEWS_SOURCE, ClubNewsError, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, read_club_news_capture
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import locate_claims_reporting
from squadopt.data.sources.club_news_metadata import publication_metadata
from squadopt.data.timestamps import as_instant
from squadopt.features.rotation_evidence import (
    CONTRACT_VERSION,
    build_rotation_evidence_table,
    claim_targets_next_fixture,
)
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.platform.club_news_fetch import load_club_sources

#: The record's own shape. A field added, removed or recomputed is a new version. Version 2
#: is the protocol's amendment of 2026-10-22, made before any GW8 data existed: it adds
#: ``excluded_from_lost_unapplied`` and leaves ``next_match_before_target`` out of
#: ``lost_unapplied``. No record of version 1 was printed from GW8 data.
RECORD_VERSION: Final = "club_news_join_counts_v2"
PROTOCOL: Final = "docs/research/club_news_join_counts_gw8_prereg.md"
REPORTER: Final = "scripts/report_club_news_join_counts.py"

DEFAULT_SNAPSHOT_ROOT: Final = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_ROTATION_DIR: Final = REPOSITORY_ROOT / "artifacts" / "rotation"
DEFAULT_REGISTRY: Final = REPOSITORY_ROOT / "data" / "sources" / "club_news_sources.json"

#: The offline registry placeholder. It is never contacted, so it is no host of the week.
PLACEHOLDER_CLUB: Final = "Example FC"

#: The scope labels whose not-applied absence or doubt statement the record can show was
#: right: the statement names another competition or a match already played.
SCOPES_NOT_THE_DECISION: Final = frozenset({"other_competition", "past"})

#: A not-applied absence or doubt statement labelled ``upcoming_premier_league`` on a page
#: dated to the instant, whose "next match", by the decision capture's own calendar, is a
#: league match of its club that kicks off before the target-gameweek fixture: like ``past``,
#: its words name a match that is not the decision's (``next_match_before_target``).
NEXT_MATCH_BEFORE_TARGET: Final = "next_match_before_target"

#: Why a not-applied absence or doubt statement is left out of ``lost_unapplied``, each
#: counted by name in ``excluded_from_lost_unapplied``: the two scope labels, then the next
#: match that is not the decision's.
NOT_LOST_UNAPPLIED: Final = (*sorted(SCOPES_NOT_THE_DECISION), NEXT_MATCH_BEFORE_TARGET)

#: The decision capture's calendar, its roster by player (club, club code, short name) and
#: its capture instant, as the manager-word reader reads them (``_decision_fixture_basis``).
FixtureBasis: TypeAlias = tuple[pd.DataFrame, dict[int, tuple[str, int, str]], str]

#: The reasons the identity join and the club-source check record, named in the record even
#: when they are zero. Any other reason the table reports is carried and counted as well.
JOIN_REASONS: Final = (
    "no_match",
    "unknown_team",
    "ambiguous",
    "other_club_source",
    "unverified_club_source",
    "conflicting_player_claims",
)

#: Why an absence or doubt statement that became a row was given no role. Each statement is
#: counted under the first condition of the rule that fails, tested in this order. The
#: exporter verifies a next-match scope only from an instant publication time, so a page
#: without one never verifies scope either; testing publication first keeps
#: ``scope_unverified`` to statements whose page was dated to the instant.
#: ``NEXT_MATCH_BEFORE_TARGET`` is tested between the second cause and the third, and a
#: statement it names is no loss, so these four still add up to ``lost_unapplied``.
UNAPPLIED_CAUSES: Final = (
    "publication_unverified",
    "publication_day_precision",
    "scope_unverified",
    "publication_not_before_fetch",
)

VERDICT_NO_RAW_CLAIMS: Final = "no_raw_claims"
VERDICT_NONE_LOST: Final = "no_statement_lost"
VERDICT_LOST: Final = "statements_lost"
#: What the protocol reads from each verdict for #1006.
ISSUE_1006_READING: Final[Mapping[str, str]] = {
    VERDICT_NO_RAW_CLAIMS: "unanswered",
    VERDICT_NONE_LOST: "close",
    VERDICT_LOST: "route_items_3_7_4_10",
}

_CAPTURE_LINE: Final = re.compile(r"^Capture\s+(club-news-\S+)\s*$")
_RAW_CLAIMS_LINE: Final = re.compile(r"^Raw claims\s+(\d+);")
_BUDGET_LINE: Final = re.compile(r"^Call budget\s+(\d+); (\d+) attempted;")
_READ_REFUSAL: Final = "Read refusal: "
_CODING_REFUSAL: Final = "Coding refusal: "
#: The coding stage's four outcomes that are not an answer, as
#: ``squadopt.platform.club_news_coverage.format_coding_stage`` labels them. The acquisition
#: prints each once, as ``<label>: <n> [<club>, <club>]``, whenever it read a page, so the
#: receipt of every acquisition that wrote a capture carries all four.
CALL_FAILED: Final = "Call attempted and failed"
BUDGET_STOPPED: Final = "Stopped by the call budget, no call attempted"
REFUSED_BEFORE_CALL: Final = "Refused before a call was attempted"
NOTHING_SELECTED: Final = "No document selected for coding"
_OUTCOME_LABELS: Final = (CALL_FAILED, BUDGET_STOPPED, REFUSED_BEFORE_CALL, NOTHING_SELECTED)
_OUTCOME_LINE: Final = re.compile(r"^(?P<label>[^:]+): (?P<count>\d+) \[(?P<clubs>[^\]]*)\]$")


class JoinCountError(Exception):
    """The inputs do not add up to one week the record can describe."""


@dataclass(frozen=True, slots=True)
class LogFacts:
    """What the acquisition receipt says that no capture stores."""

    file_name: str
    capture_id: str
    raw_claims_printed: int
    model_call_budget: int
    model_calls_attempted: int
    read_refusal_lines: int
    coding_refusal_lines: int
    call_failed_clubs: tuple[str, ...]
    budget_stopped_clubs: tuple[str, ...]
    refused_before_call_clubs: tuple[str, ...]
    nothing_selected_clubs: tuple[str, ...]

    @property
    def not_coded_clubs(self) -> tuple[str, ...]:
        """Every club the four outcome lines name: read, and given no answer."""

        return (
            *self.call_failed_clubs,
            *self.budget_stopped_clubs,
            *self.refused_before_call_clubs,
            *self.nothing_selected_clubs,
        )


@dataclass(frozen=True, slots=True)
class Funnel:
    """The exporter's per-response reading, with every count it does not keep."""

    raw: int
    raw_per_coded_club: int
    responses_stored: int
    responses_distinct: int
    responses_reused: int
    refused_responses: int
    refused_clubs: tuple[str, ...]
    refused_without_claims_list: int
    in_refused_responses: int
    unverifiable_own_club: int
    unverifiable_other_club: int
    parsed: int


def read_log(path: Path) -> LogFacts:
    """Read the acquisition receipt the Friday launcher keeps beside the weekly log.

    PowerShell writes it with a byte order mark, so it is read as ``utf-8-sig``. Only the
    line shapes below are read, all printed by ``squadopt.platform.club_news_acquire``;
    every other line is left alone. An acquisition that wrote a capture prints the capture
    line, the raw claims line, the call budget line and the four outcome lines exactly once
    each, so a receipt missing one, or repeating one, is not the receipt of one capture.
    """

    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as error:
        raise JoinCountError(f"Cannot read the club-news log {path}: {error}") from error
    captures: list[str] = []
    raw: list[int] = []
    budget: list[tuple[int, int]] = []
    outcomes: dict[str, list[tuple[str, ...]]] = {label: [] for label in _OUTCOME_LABELS}
    read_refusals = coding_refusals = 0
    for line in (entry.rstrip() for entry in lines):
        if (found := _CAPTURE_LINE.match(line)) is not None:
            captures.append(found.group(1))
        elif (found := _RAW_CLAIMS_LINE.match(line)) is not None:
            raw.append(int(found.group(1)))
        elif (found := _BUDGET_LINE.match(line)) is not None:
            budget.append((int(found.group(1)), int(found.group(2))))
        elif line.startswith(_READ_REFUSAL):
            read_refusals += 1
        elif line.startswith(_CODING_REFUSAL):
            coding_refusals += 1
        elif (found := _OUTCOME_LINE.match(line)) is not None and found["label"] in outcomes:
            clubs = tuple(found["clubs"].split(", ")) if found["clubs"] else ()
            if len(clubs) != int(found["count"]):
                raise JoinCountError(
                    f"{path.name} counts {found['count']} clubs on its line "
                    f"{found['label']!r} and lists {len(clubs)}."
                )
            outcomes[found["label"]].append(clubs)
    if len(set(captures)) != 1:
        raise JoinCountError(
            f"{path.name} names {len(set(captures))} club-news captures; the receipt of one "
            "completed acquisition names exactly one."
        )
    printed = {
        "Raw claims": len(raw),
        "Call budget": len(budget),
        **{label: len(outcomes[label]) for label in _OUTCOME_LABELS},
    }
    missing = [label for label, times in printed.items() if times != 1]
    if missing:
        raise JoinCountError(
            f"{path.name} does not print each of {missing} exactly once; the receipt of one "
            "acquisition that wrote a capture does."
        )
    return LogFacts(
        file_name=path.name,
        capture_id=captures[0],
        raw_claims_printed=raw[0],
        model_call_budget=budget[0][0],
        model_calls_attempted=budget[0][1],
        read_refusal_lines=read_refusals,
        coding_refusal_lines=coding_refusals,
        call_failed_clubs=outcomes[CALL_FAILED][0],
        budget_stopped_clubs=outcomes[BUDGET_STOPPED][0],
        refused_before_call_clubs=outcomes[REFUSED_BEFORE_CALL][0],
        nothing_selected_clubs=outcomes[NOTHING_SELECTED][0],
    )


def find_rotation_table(rotation_dir: Path, news_capture_id: str) -> Path:
    """The one table the weekly run exported from this news capture, or refuse.

    The name is the exporter's own: the contract, the season and gameweek, the last twelve
    characters of the news capture and of the decision capture. More than one match means
    one news capture was exported against several decision captures, and choosing between
    them is the operator's call, made with ``--rotation-table``.
    """

    pattern = f"{CONTRACT_VERSION}_*_{news_capture_id[-12:]}_decision_*.csv"
    matches = sorted(rotation_dir.glob(pattern))
    if len(matches) != 1:
        raise JoinCountError(
            f"{len(matches)} rotation tables in {rotation_dir} match {pattern}"
            + (f": {[match.name for match in matches]}" if matches else "")
            + ". Name the published one with --rotation-table."
        )
    return matches[0]


def _raw_claims(text: str) -> int | None:
    """How many claims a stored response lists, or ``None`` when it lists none readably."""

    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict):
        return None
    claims = document.get("claims")
    return len(claims) if isinstance(claims, list) else None


def response_funnel(documents: Sequence[RawDocument], coded: Sequence[CodedClub]) -> Funnel:
    """Follow each stored response as ``rotation_export._inputs_from_capture`` reads it.

    Same grouping (one reading per distinct response text, located only against its own
    clubs' documents), same two calls and same refusal, so the counts are the exporter's.
    What this keeps that the exporter does not is the dropped claims about another club's
    players and the number of claims in a response refused whole.
    """

    texts = tuple(dict.fromkeys(entry.response.text for entry in coded))
    per_club = {entry.club: _raw_claims(entry.response.text) for entry in coded}
    raw = in_refused = refused = unlisted = own = other = parsed_total = 0
    refused_clubs: list[str] = []
    for text in texts:
        associated = [entry for entry in coded if entry.response.text == text]
        clubs = {entry.club for entry in associated}
        documents_of_response = tuple(doc for doc in documents if doc.club in clubs)
        listed = _raw_claims(text)
        raw += listed or 0
        try:
            located, dropped = locate_claims_reporting(
                associated[0].response, documents_of_response
            )
            parsed = parse_claim_response(located, documents_of_response)
        except ClubNewsError:
            refused += 1
            refused_clubs.extend(entry.club for entry in associated)
            in_refused += listed or 0
            unlisted += listed is None
            continue
        names = {normalise_claim_name(club) for club in clubs}
        mine = sum(normalise_claim_name(claim.team_name) in names for claim in dropped)
        own += mine
        other += len(dropped) - mine
        parsed_total += len(parsed)
        if listed != len(dropped) + len(parsed):
            raise JoinCountError(
                f"A response for {sorted(clubs)} lists {listed} claims, and its reading "
                f"accounts for {len(dropped) + len(parsed)}."
            )
    return Funnel(
        raw=raw,
        raw_per_coded_club=sum(count or 0 for count in per_club.values()),
        responses_stored=len(coded),
        responses_distinct=len(texts),
        responses_reused=sum(entry.reused_from_snapshot is not None for entry in coded),
        refused_responses=refused,
        refused_clubs=tuple(sorted(set(refused_clubs))),
        refused_without_claims_list=unlisted,
        in_refused_responses=in_refused,
        unverifiable_own_club=own,
        unverifiable_other_club=other,
        parsed=parsed_total,
    )


def reading(*, raw: int, unreadable_responses: int, failed_calls: int, lost: int) -> str:
    """The protocol's verdict, from four counts and nothing else.

    A stored response with no readable list of claims, and a call that was attempted and
    left no stored answer, both hide statements that cannot be counted, so either one is a
    loss before the other counts are read.
    """

    if unreadable_responses > 0 or failed_calls > 0:
        return VERDICT_LOST
    if raw == 0:
        return VERDICT_NO_RAW_CLAIMS
    if lost == 0:
        return VERDICT_NONE_LOST
    return VERDICT_LOST


def next_match_before_target(
    word: ManagerWord, basis: FixtureBasis | None, target_gameweek: int
) -> bool:
    """Whether the statement's "next match" is a club match before the decision's fixture.

    Only for a statement labelled ``upcoming_premier_league`` on a page whose publication the
    reader verifies to an instant at or before the decision capture. The decision capture's
    calendar is read as the reader reads it (``basis``), and both answers come from the
    rule's own binding, ``claim_targets_next_fixture``, which takes the club's first dated
    fixture after the publication instant: published at the capture instant, the statement
    would bind to the club's target-gameweek fixture, and published at its own instant it
    does not. So the club's first dated league fixture after that instant kicks off before
    the target fixture. An undated, blank or double target week, a target fixture that
    kicked off by the capture, or another club fixture kicking off after the capture and no
    later than the target binds nothing at the capture instant, and its statement stays a
    loss under its own cause, as does one published after the capture.
    """

    if (
        basis is None
        or word.fixture_scope != "upcoming_premier_league"
        or not word.publication_verified
        or word.published_precision != "instant"
        or word.published_at_utc is None
    ):
        return False
    calendar, players, captured = basis
    player = players.get(word.player_id)
    if player is None or player[0] != word.club:
        return False
    try:
        if as_instant(word.published_at_utc) > as_instant(captured):
            return False
    except (TypeError, ValueError):
        return False

    def binds(published_at_utc: str) -> bool:
        return claim_targets_next_fixture(
            calendar,
            team_code=player[1],
            target_gameweek=target_gameweek,
            captured_at_utc=captured,
            published_at_utc=published_at_utc,
            published_precision="instant",
        )

    return binds(captured) and not binds(word.published_at_utc)


def not_applied_reading(word: ManagerWord, basis: FixtureBasis | None, target_gameweek: int) -> str:
    """Where a not-applied absence or doubt statement is counted.

    Called only for an absence or doubt statement the reader gave no role and no
    double-gameweek reason. It returns one of ``NOT_LOST_UNAPPLIED``, which is no loss, or
    the first condition of the rule's role that the statement fails (``UNAPPLIED_CAUSES``).
    The two scope labels leave a statement out whatever else holds. The next match before
    the target is tested after the two publication causes, because it needs a publication
    instant, and before ``scope_unverified``, so a statement it leaves out never reaches the
    cause items 3 and 7 address. The last cause is what remains when the page is dated to
    the instant and the scope is verified, which the rule refuses only for a page with no
    fetch instant or one published after its fetch.
    """

    if word.fixture_scope in SCOPES_NOT_THE_DECISION:
        return word.fixture_scope
    if not word.publication_verified:
        return UNAPPLIED_CAUSES[0]
    if word.published_precision != "instant":
        return UNAPPLIED_CAUSES[1]
    if next_match_before_target(word, basis, target_gameweek):
        return NEXT_MATCH_BEFORE_TARGET
    if not word.scope_verified:
        return UNAPPLIED_CAUSES[2]
    return UNAPPLIED_CAUSES[3]


def require_this_checkouts_code() -> None:
    """Refuse unless ``squadopt`` is imported from the ``src`` of this checkout.

    The commit check reads the checkout ``scripts/`` sits in, and the replay runs whatever
    ``squadopt`` the interpreter imported. Run from a worktree without its own ``src`` first
    on the path, it would replay another checkout's code under a passing commit check.
    """

    package = Path(squadopt.__file__).resolve()
    if not package.is_relative_to(REPOSITORY_ROOT / "src"):
        raise JoinCountError(
            f"squadopt is imported from {package.parent}, not from {REPOSITORY_ROOT / 'src'}: "
            "put this checkout's src first on PYTHONPATH, as the protocol describes."
        )


def _origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _address(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, "")
    )


def _hosts(
    registry: Path, documents: Sequence[RawDocument], declared: Sequence[str]
) -> tuple[dict[str, object], dict[str, int]]:
    """Registered hosts asked, answered and refused, and registered pages asked and read."""

    sources = [s for s in load_club_sources(registry) if s.club != PLACEHOLDER_CLUB]
    unknown = sorted(set(declared) - {s.club for s in sources} - {PLACEHOLDER_CLUB})
    if unknown:
        raise JoinCountError(
            f"The capture declares {unknown}, which {registry.name} does not register; it is "
            "not the registry the acquisition read."
        )
    asked_sources = [s for s in sources if s.club in set(declared)]
    asked = sorted({_origin(s.url) for s in asked_sources})
    held = [doc for doc in documents if doc.club != PLACEHOLDER_CLUB]
    served = {_origin(doc.requested_url) for doc in held}
    if served - set(asked):
        raise JoinCountError(
            f"The capture holds documents from {sorted(served - set(asked))}, which no "
            "declared club registers."
        )
    answered = sorted(host for host in asked if host in served)
    read = {_address(doc.requested_url) for doc in held}
    return (
        {
            "registered": len({_origin(s.url) for s in sources}),
            "asked": len(asked),
            "answered": len(answered),
            "refused": len(asked) - len(answered),
            "asked_hosts": asked,
            "answered_hosts": answered,
            "refused_hosts": sorted(set(asked) - set(answered)),
        },
        {
            "asked": len(asked_sources),
            "read": sum(_address(s.url) in read for s in asked_sources),
        },
    )


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JoinCountError(f"Cannot read the manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise JoinCountError(f"{path.name} is not a JSON object.")
    return document


def _int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise JoinCountError(f"{label} must be an integer, got {value!r}.")
    return value


def _news_capture(root: Path, identifier: str) -> CapturedSnapshot:
    snapshot = read_snapshot(root, identifier)
    if snapshot.metadata.source != CLUB_NEWS_SOURCE:
        raise JoinCountError(f"{identifier} is not a club-news capture.")
    return snapshot


def build_record(
    *,
    table_path: Path,
    snapshot_root: Path,
    registry: Path,
    log: LogFacts,
    repository_commit: str,
    repository_dirty: bool,
) -> dict[str, object]:
    """Every count of the record, or a refusal naming the first one that does not hold."""

    manifest_path = table_path.with_suffix(".manifest.json")
    manifest = _read_manifest(manifest_path)
    if manifest.get("club_news_source_kind") != "capture":
        raise JoinCountError(
            f"{table_path.name} was exported from {manifest.get('club_news_source_kind')!r}, "
            "not from a club-news capture; the fixture is not club news."
        )
    export_commit = manifest.get("repository_commit")
    if repository_commit != export_commit or repository_dirty:
        # The digest binds the rows and the manifest binds what it carries; the counts that
        # live only in the replay's attributes are bound by running the export's own code.
        raise JoinCountError(
            f"This checkout is at {repository_commit}"
            + (" with local changes" if repository_dirty else "")
            + f", and {table_path.name} was exported at {export_commit}. Run this from a "
            "clean worktree at that commit, as the protocol describes."
        )
    news_id = str(manifest.get("club_news_snapshot_id"))
    if log.capture_id != news_id:
        raise JoinCountError(
            f"{log.file_name} names {log.capture_id}, and {table_path.name} was exported "
            f"from {news_id}; they are receipts of different weeks."
        )
    published = read_rotation_evidence_artifact(table_path, manifest_path)
    news = _news_capture(snapshot_root, news_id)
    decision = read_snapshot(snapshot_root, str(manifest["roster_snapshot_id"]))
    if as_instant(news.metadata.captured_at_utc) >= as_instant(decision.metadata.captured_at_utc):
        raise JoinCountError("The club-news capture does not precede the decision capture.")
    documents, coded, declared, covered, partial = read_club_news_capture(news)
    read_not_coded = sorted({doc.club for doc in documents} - {entry.club for entry in coded})
    if sorted(log.not_coded_clubs) != read_not_coded:
        raise JoinCountError(
            f"{log.file_name} names {sorted(log.not_coded_clubs)} as read and given no "
            f"answer, and the capture holds pages and no answer for {read_not_coded}."
        )

    # The exporter's own path, call for call (`rotation_export._export`).
    inputs = _inputs_from_capture(news)
    season = str(manifest["season"])
    target_gameweek = _int(manifest["target_gameweek"], "target_gameweek")
    deadline = str(manifest["deadline_timestamp_utc"])
    replay = build_rotation_evidence_table(
        season=season,
        target_gameweek=target_gameweek,
        deadline_timestamp_utc=deadline,
        decision_snapshot=decision,
        claims=inputs.claims,
        documents=inputs.documents,
        clubs_declared=inputs.clubs_declared,
        clubs_covered=inputs.clubs_covered,
        clubs_partially_covered=inputs.clubs_partially_covered,
        model=inputs.model,
        unverifiable_claims=inputs.unverifiable,
        unverifiable_response_clubs=inputs.unverifiable_response_clubs,
        club_news_snapshot_id=news_id,
    )
    replay_sha256 = hashlib.sha256(_table_bytes(replay)).hexdigest()
    if replay_sha256 != manifest.get("table_sha256"):
        raise JoinCountError(
            f"The replayed table hashes to {replay_sha256}, and {manifest_path.name} declares "
            f"{manifest.get('table_sha256')}, at the commit it was exported at: the captures "
            f"in {snapshot_root} are not the ones it was exported from."
        )
    # Every attribute the manifest carries, rebuilt from the replay through the exporter's
    # own writer and serialization. Only the wall-clock stamp is left out, as a replay of
    # the export leaves it out; the other identity fields are the manifest's own.
    rebuilt = json.loads(
        document_bytes(
            _manifest(
                replay,
                season=season,
                target_gameweek=target_gameweek,
                deadline_timestamp_utc=deadline,
                table_file=str(manifest.get("table_file")),
                table_sha256=replay_sha256,
                repository_commit=str(export_commit),
                generated_at_utc=str(manifest.get("generated_at_utc")),
                news_capture_id=news_id,
                news_captured_at_utc=inputs.captured_at_utc,
            )
        )
    )
    expected, held = _manifest_identity(rebuilt), _manifest_identity(manifest)
    differing = sorted(
        key for key in expected.keys() | held.keys() if expected.get(key) != held.get(key)
    )
    if differing:
        raise JoinCountError(
            f"The replayed table's attributes differ from {manifest_path.name} in {differing}."
        )

    funnel = response_funnel(documents, coded)
    if (
        funnel.refused_responses != len(inputs.refused_responses)
        or funnel.unverifiable_own_club != len(inputs.unverifiable)
        or funnel.parsed != len(inputs.claims)
    ):
        raise JoinCountError("The response reading disagrees with the exporter's own reading.")
    if log.raw_claims_printed != funnel.raw_per_coded_club:
        raise JoinCountError(
            f"{log.file_name} printed {log.raw_claims_printed} raw claims and the capture "
            f"lists {funnel.raw_per_coded_club}."
        )

    attrs = replay.attrs
    unresolved = {str(reason): int(count) for reason, count in attrs["claims_unresolved"]}
    placed = _int(attrs["claims_coded"], "claims_coded")
    repeats = funnel.parsed - placed - sum(unresolved.values())
    observed = int(published["rotation_claim_observed"].sum())
    if repeats < 0 or observed != placed or published.attrs["claims_coded"] != placed:
        raise JoinCountError("The placed claims do not add up to the published table's rows.")
    if funnel.raw != (
        funnel.in_refused_responses
        + funnel.unverifiable_own_club
        + funnel.unverifiable_other_club
        + funnel.parsed
    ):
        raise JoinCountError("The raw claims do not add up to their places.")

    words = load_manager_words(
        table_path, club_news_source=snapshot_root / news_id, snapshot_root=snapshot_root
    )
    exclusion = words.exclusion()
    acting = [word for word in words.words if word.disposition in NOT_CAPTAIN_DISPOSITIONS]
    # The decision capture's calendar as the reader read it for these statements.
    basis = _decision_fixture_basis(published, snapshot_root)
    not_applied = [
        (word, not_applied_reading(word, basis, words.gameweek))
        for word in acting
        if word.role is None and word.fixture_binding_reason is None
    ]
    unapplied = [word for word, place in not_applied if place in UNAPPLIED_CAUSES]
    causes = Counter(place for _word, place in not_applied)
    lost_before_table = (
        funnel.in_refused_responses
        + funnel.unverifiable_own_club
        + funnel.unverifiable_other_club
        + sum(unresolved.values())
    )
    lost = lost_before_table + len(unapplied)
    verdict = reading(
        raw=funnel.raw,
        unreadable_responses=funnel.refused_without_claims_list,
        failed_calls=len(log.call_failed_clubs),
        lost=lost,
    )
    host_counts, page_counts = _hosts(registry, documents, declared)
    statements = published["rotation_disposition"].dropna().astype(str).tolist()

    return {
        "record_version": RECORD_VERSION,
        "protocol": PROTOCOL,
        "reporter": REPORTER,
        "repository_commit": repository_commit,
        "repository_dirty": repository_dirty,
        "season": str(manifest["season"]),
        "target_gameweek": _int(manifest["target_gameweek"], "target_gameweek"),
        "deadline_timestamp_utc": str(manifest["deadline_timestamp_utc"]),
        "inputs": {
            "club_news_capture_id": news_id,
            "club_news_captured_at_utc": news.metadata.captured_at_utc,
            "decision_capture_id": decision.metadata.snapshot_id,
            "decision_captured_at_utc": decision.metadata.captured_at_utc,
            "rotation_table_file": table_path.name,
            "rotation_table_sha256": manifest["table_sha256"],
            "rotation_export_repository_commit": manifest.get("repository_commit"),
            "provider": manifest.get("provider"),
            "model_identifier": manifest.get("model_identifier"),
            "model_version": manifest.get("model_version"),
            "prompt_sha256": manifest.get("prompt_sha256"),
            "registry_file": registry.name,
            "registry_sha256": hashlib.sha256(registry.read_bytes()).hexdigest(),
            "club_news_log_file": log.file_name,
        },
        "checks": {
            "source_kind": "capture",
            "checkout_at_export_commit": True,
            "news_capture_precedes_decision_capture": True,
            "replay_table_sha256": replay_sha256,
            "replay_matches_published_table": True,
            "replay_matches_manifest": True,
            "claims_accounted": True,
            "log_capture_id_matches": True,
            "log_raw_claims_match": True,
            "log_outcomes_match_capture": True,
        },
        "hosts": host_counts,
        "registered_pages": page_counts,
        "clubs": {
            "declared": sorted(declared),
            "covered_in_capture": sorted(covered),
            "partially_covered_in_capture": sorted(partial),
            "covered_in_table": sorted(str(club) for club in published.attrs["clubs_covered"]),
            "read_not_coded": read_not_coded,
        },
        "documents": {
            "retained": len(documents),
            "by_club": dict(sorted(Counter(doc.club for doc in documents).items())),
            "with_verified_publication": sum(
                publication_metadata(doc.content, doc.content_type, doc.final_url).verified
                for doc in documents
            ),
        },
        "responses": {
            "stored": funnel.responses_stored,
            "distinct": funnel.responses_distinct,
            "reused_from_earlier_capture": funnel.responses_reused,
            "refused_whole": funnel.refused_responses,
            "refused_clubs": list(funnel.refused_clubs),
            "refused_without_claims_list": funnel.refused_without_claims_list,
        },
        "acquisition_log": {
            "model_call_budget": log.model_call_budget,
            "model_calls_attempted": log.model_calls_attempted,
            "raw_claims_printed": log.raw_claims_printed,
            "read_refusal_lines": log.read_refusal_lines,
            "coding_refusal_lines": log.coding_refusal_lines,
            "call_failed_clubs": sorted(log.call_failed_clubs),
            "budget_stopped_clubs": sorted(log.budget_stopped_clubs),
            "refused_before_call_clubs": sorted(log.refused_before_call_clubs),
            "nothing_selected_clubs": sorted(log.nothing_selected_clubs),
        },
        "claims": {
            "raw": funnel.raw,
            "raw_per_coded_club": funnel.raw_per_coded_club,
            "in_refused_responses": funnel.in_refused_responses,
            "unverifiable_citation_own_club": funnel.unverifiable_own_club,
            "unverifiable_citation_other_club": funnel.unverifiable_other_club,
            "reached_join": funnel.parsed,
            "joined_to_one_player": funnel.parsed
            - sum(
                unresolved.get(reason, 0) for reason in ("no_match", "unknown_team", "ambiguous")
            ),
            **{reason: unresolved.get(reason, 0) for reason in JOIN_REASONS},
            "unresolved_by_reason": dict(sorted(unresolved.items())),
            "identical_repeats": repeats,
            "placed": placed,
        },
        "table": {
            "rows": len(published),
            "roster_size": _int(manifest["roster_size"], "roster_size"),
            "players_with_statement": observed,
            "players_not_addressed": _int(
                manifest["players_not_addressed"], "players_not_addressed"
            ),
            "players_with_unverifiable_citation": len(attrs["players_with_unverifiable_citation"]),
            "players_with_conflicting_claims": len(attrs["players_with_conflicting_claims"]),
            "statements_by_disposition": dict(sorted(Counter(statements).items())),
        },
        "reader": {
            "source_check": words.source_check,
            "statements_read": len(words.words),
            "constraining_statements": len(words.constraining),
            "excluded_not_starting": 0 if exclusion is None else len(exclusion.not_starting),
            "excluded_not_captain": 0 if exclusion is None else len(exclusion.not_captain),
            "double_gameweek_reason": sum(
                word.fixture_binding_reason is not None for word in words.words
            ),
            "words_withheld": sum(
                word.words_status == WORDS_WITHHELD_FIGURE for word in words.words
            ),
            "words_unresolved": sum(word.words_status == WORDS_UNRESOLVED for word in words.words),
            "absence_or_doubt_statements": len(acting),
            "absence_or_doubt_not_applied_by_scope": dict(
                sorted(Counter(word.fixture_scope for word, _place in not_applied).items())
            ),
        },
        "loss": {
            "lost_before_table": lost_before_table,
            "lost_unapplied": len(unapplied),
            "lost_unapplied_by_cause": {cause: causes[cause] for cause in UNAPPLIED_CAUSES},
            "excluded_from_lost_unapplied": {
                reason: causes[reason] for reason in NOT_LOST_UNAPPLIED
            },
            "lost_unapplied_scope_unverified_by_scope": dict(
                sorted(
                    Counter(
                        word.fixture_scope
                        for word, place in not_applied
                        if place == "scope_unverified"
                    ).items()
                )
            ),
            "lost": lost,
            "responses_without_claims_list": funnel.refused_without_claims_list,
            "calls_attempted_and_failed": len(log.call_failed_clubs),
            "verdict": verdict,
            "issue_1006": ISSUE_1006_READING[verdict],
        },
    }


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--club-news-log",
        type=Path,
        required=True,
        help="the acquisition receipt data/logs/weekly/<run id>.club-news.log; it is the "
        "only record of which clubs' model calls failed, so it is always read",
    )
    parser.add_argument(
        "--rotation-table",
        type=Path,
        help="the published rotation table (.csv, its manifest beside it); found from the "
        "log's capture id when omitted",
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--rotation-dir", type=Path, default=DEFAULT_ROTATION_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path, help="also write the record here, once")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        require_this_checkouts_code()
        log = read_log(arguments.club_news_log)
        table = arguments.rotation_table or find_rotation_table(
            arguments.rotation_dir, log.capture_id
        )
        revision, dirty = _git_revision()
        record = build_record(
            table_path=table,
            snapshot_root=arguments.snapshot_root,
            registry=arguments.registry,
            log=log,
            repository_commit=revision,
            repository_dirty=dirty,
        )
        text = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if arguments.output is not None:
            with arguments.output.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    except (JoinCountError, DataError, OSError, ValueError, KeyError) as error:
        print(f"Refused: {error}")
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
