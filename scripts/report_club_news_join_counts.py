"""Count what one week's club news became, offline, and print the join-count record.

    python -m scripts.report_club_news_join_counts --club-news-log <run id>.club-news.log

The protocol is ``docs/research/club_news_join_counts_gw8_prereg.md``: it fixes every count
printed here, how each is computed, and the reading that decides #1006. This command only
reads what the weekly run already left on the publishing PC: the club-news capture and the
decision capture in the snapshot store, the rotation table and manifest the weekly run
exported from them, the source registry, and the acquisition receipt
``data/logs/weekly/<run id>.club-news.log``. It opens no network connection, calls no model
and writes nothing unless ``--output`` names a new file.

**The table is replayed, not trusted.** The no-match, ambiguous and unverifiable counts live
only in the attributes of the table the exporter builds in memory, never in its manifest
(#1006 item 4). So the rotation table is rebuilt here from the two captures through the
exporter's own code, and the record is printed only when the rebuilt bytes hash to the
digest the published manifest declares. A different digest means the code or the captures
are not the ones the weekly run used, and the command refuses rather than count a table
nobody published.

**Every raw claim ends in exactly one place.** The claims each stored response lists are
followed through the exporter's own reading: a response refused whole, a citation that could
not be verified (of the response's own club or of another), a claim that reached the
identity join and then matched one player, none or several, a source of another club, a
conflict, an identical repeat, or a placed row. The record is printed only when those places
add up to the raw claims, so a count that went missing refuses instead of reading as zero.
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
from typing import Final

from scripts._provenance import REPOSITORY_ROOT, _git_revision

from squadopt.application.manager_words import (
    NOT_CAPTAIN_DISPOSITIONS,
    WORDS_UNRESOLVED,
    WORDS_WITHHELD_FIGURE,
    load_manager_words,
)
from squadopt.application.rotation_export import _inputs_from_capture, _table_bytes
from squadopt.data.claim_identity import normalise_claim_name
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import CLUB_NEWS_SOURCE, ClubNewsError, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, read_club_news_capture
from squadopt.data.sources.club_news_claims import parse_claim_response
from squadopt.data.sources.club_news_coding import locate_claims_reporting
from squadopt.data.sources.club_news_metadata import publication_metadata
from squadopt.data.timestamps import as_instant
from squadopt.features.rotation_evidence import CONTRACT_VERSION, build_rotation_evidence_table
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.platform.club_news_fetch import load_club_sources

#: The record's own shape. A field added, removed or recomputed is a new version.
RECORD_VERSION: Final = "club_news_join_counts_v1"
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


class JoinCountError(Exception):
    """The inputs do not add up to one week the record can describe."""


@dataclass(frozen=True, slots=True)
class LogFacts:
    """What the acquisition receipt says that no capture stores."""

    file_name: str
    capture_id: str
    raw_claims_printed: int | None
    model_call_budget: int | None
    model_calls_attempted: int | None
    read_refusal_lines: int
    coding_refusal_lines: int


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

    PowerShell writes it with a byte order mark, so it is read as ``utf-8-sig``. Only four
    line shapes are read, all printed by ``squadopt.platform.club_news_acquire``; every
    other line is left alone.
    """

    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as error:
        raise JoinCountError(f"Cannot read the club-news log {path}: {error}") from error
    captures: list[str] = []
    raw: list[int] = []
    budget: list[tuple[int, int]] = []
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
    if len(set(captures)) != 1:
        raise JoinCountError(
            f"{path.name} names {len(set(captures))} club-news captures; the receipt of one "
            "completed acquisition names exactly one."
        )
    if len(raw) > 1 or len(budget) > 1:
        raise JoinCountError(f"{path.name} holds more than one acquisition's counts.")
    return LogFacts(
        file_name=path.name,
        capture_id=captures[0],
        raw_claims_printed=raw[0] if raw else None,
        model_call_budget=budget[0][0] if budget else None,
        model_calls_attempted=budget[0][1] if budget else None,
        read_refusal_lines=read_refusals,
        coding_refusal_lines=coding_refusals,
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


def reading(*, raw: int, unreadable_responses: int, lost: int) -> str:
    """The protocol's verdict, from three counts and nothing else."""

    if raw == 0 and unreadable_responses == 0:
        return VERDICT_NO_RAW_CLAIMS
    if lost == 0 and unreadable_responses == 0:
        return VERDICT_NONE_LOST
    return VERDICT_LOST


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


def _manifest(path: Path) -> dict[str, object]:
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
    log: LogFacts | None,
    repository_commit: str,
    repository_dirty: bool,
) -> dict[str, object]:
    """Every count of the record, or a refusal naming the first one that does not hold."""

    manifest_path = table_path.with_suffix(".manifest.json")
    manifest = _manifest(manifest_path)
    if manifest.get("club_news_source_kind") != "capture":
        raise JoinCountError(
            f"{table_path.name} was exported from {manifest.get('club_news_source_kind')!r}, "
            "not from a club-news capture; the fixture is not club news."
        )
    news_id = str(manifest.get("club_news_snapshot_id"))
    if log is not None and log.capture_id != news_id:
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

    # The exporter's own path, call for call (`rotation_export._export`).
    inputs = _inputs_from_capture(news)
    replay = build_rotation_evidence_table(
        season=str(manifest["season"]),
        target_gameweek=_int(manifest["target_gameweek"], "target_gameweek"),
        deadline_timestamp_utc=str(manifest["deadline_timestamp_utc"]),
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
            f"{manifest.get('table_sha256')}. Run this from the commit the manifest names, "
            f"{manifest.get('repository_commit')}."
        )

    funnel = response_funnel(documents, coded)
    if (
        funnel.refused_responses != len(inputs.refused_responses)
        or funnel.unverifiable_own_club != len(inputs.unverifiable)
        or funnel.parsed != len(inputs.claims)
    ):
        raise JoinCountError("The response reading disagrees with the exporter's own reading.")
    if log is not None and log.raw_claims_printed not in (None, funnel.raw_per_coded_club):
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
    unapplied = [
        word
        for word in acting
        if word.role is None
        and word.fixture_binding_reason is None
        and word.fixture_scope not in SCOPES_NOT_THE_DECISION
    ]
    lost_before_table = (
        funnel.in_refused_responses
        + funnel.unverifiable_own_club
        + funnel.unverifiable_other_club
        + sum(unresolved.values())
    )
    lost = lost_before_table + len(unapplied)
    verdict = reading(
        raw=funnel.raw, unreadable_responses=funnel.refused_without_claims_list, lost=lost
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
            "club_news_log_file": None if log is None else log.file_name,
        },
        "checks": {
            "source_kind": "capture",
            "news_capture_precedes_decision_capture": True,
            "replay_table_sha256": replay_sha256,
            "replay_matches_published_table": True,
            "claims_accounted": True,
            "log_capture_id_matches": None if log is None else True,
            "log_raw_claims_match": (
                None if log is None or log.raw_claims_printed is None else True
            ),
        },
        "hosts": host_counts,
        "registered_pages": page_counts,
        "clubs": {
            "declared": sorted(declared),
            "covered_in_capture": sorted(covered),
            "partially_covered_in_capture": sorted(partial),
            "covered_in_table": sorted(str(club) for club in published.attrs["clubs_covered"]),
            "read_not_coded": sorted(
                {doc.club for doc in documents} - {entry.club for entry in coded}
            ),
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
        "acquisition_log": None
        if log is None
        else {
            "model_call_budget": log.model_call_budget,
            "model_calls_attempted": log.model_calls_attempted,
            "raw_claims_printed": log.raw_claims_printed,
            "read_refusal_lines": log.read_refusal_lines,
            "coding_refusal_lines": log.coding_refusal_lines,
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
                sorted(
                    Counter(
                        word.fixture_scope
                        for word in acting
                        if word.role is None and word.fixture_binding_reason is None
                    ).items()
                )
            ),
        },
        "loss": {
            "lost_before_table": lost_before_table,
            "lost_unapplied": len(unapplied),
            "lost": lost,
            "verdict": verdict,
            "issue_1006": ISSUE_1006_READING[verdict],
        },
    }


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--club-news-log",
        type=Path,
        help="the acquisition receipt data/logs/weekly/<run id>.club-news.log",
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
    arguments = parser.parse_args(argv)
    if arguments.club_news_log is None and arguments.rotation_table is None:
        parser.error("name --club-news-log, --rotation-table, or both")
    return arguments


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        log = None if arguments.club_news_log is None else read_log(arguments.club_news_log)
        table = arguments.rotation_table
        if table is None and log is not None:
            table = find_rotation_table(arguments.rotation_dir, log.capture_id)
        if table is None:  # pragma: no cover - _parse_arguments requires one of the two
            raise JoinCountError("No rotation table was named.")
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
