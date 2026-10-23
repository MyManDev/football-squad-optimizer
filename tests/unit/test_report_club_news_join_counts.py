"""The join-count reporter, on synthetic captures written and exported by the real code.

Every week here is written through ``write_club_news_capture`` and exported through
``export_rotation_evidence``, the same two calls the Friday run makes, so the reporter is held
to tables the exporter actually wrote. Nothing reaches a network or calls a model: the
responses are stored text, and one test removes the socket layer while the command runs.
"""

import dataclasses
import json
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from scripts import report_club_news_join_counts as report
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
)

import squadopt
from squadopt.application.manager_words import _decision_fixture_basis, load_manager_words
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.platform.club_news_coverage import CodingStageReport, format_coding_stage

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "research" / "club_news_join_counts_gw8_prereg.md"
COMMIT = "0" * 40
PUBLISHED = "2026-09-12T13:00:00Z"
FETCHED = "2026-09-12T14:00:00Z"
NEWS_CAPTURED_AT = "2026-09-12T14:30:00Z"
MODEL = "synthetic-stub"

ARSENAL = "https://arsenal.example/news"
#: Two more pages on Arsenal's host: one that states no publication time, and one that states
#: only the day, as listing pages and some articles do.
ARSENAL_UNDATED = "https://arsenal.example/news/listing"
ARSENAL_DAY = "https://arsenal.example/news/day"
UNITED = "https://united.example/news"
EVERTON = "https://everton.example/news"
#: A capture id no week here wrote, for a receipt of another week.
OTHER_CAPTURE = "club-news-20260912T143000Z-0123456789ab"

#: One page of club text, one statement to a line, so every quote is a whole sentence.
ARSENAL_LINES = (
    "Saka will miss the next Premier League match.",
    "Rice might miss the next Premier League match.",
    "Timber will start the next Premier League match.",
    "Mount will miss the next Premier League match.",
    "Fernandes will miss the next Premier League match.",
    "Nobody will miss the next Premier League match.",
    "Odegaard will miss the cup tie.",
    "Jesus will miss the next Premier League match.",
)


def _document(
    club: str, url: str, lines: tuple[str, ...], published: str | None = PUBLISHED
) -> RawDocument:
    dateline = "" if published is None else "Published: " + published + "\n"
    content = (dateline + "\n".join(lines) + "\n").encode("utf-8")
    return RawDocument(
        club=club,
        requested_url=url,
        final_url=url,
        http_status=200,
        content_type="text/plain",
        byte_length=len(content),
        fetched_at_utc=FETCHED,
        content=content,
        readable=content,
    )


def _claim(
    player: str,
    team: str,
    disposition: str,
    quote: str,
    url: str,
    scope: str = "upcoming_premier_league",
) -> dict[str, Any]:
    return {
        "player_name": player,
        "team_name": team,
        "disposition": disposition,
        "speaker": "manager",
        "source_url": url,
        "quote": quote,
        "paraphrase": "A synthetic paraphrase.",
        "fixture_scope": scope,
    }


def _coded(
    club: str,
    url: str,
    claims: list[dict[str, Any]],
    *,
    text: str | None = None,
    pages: list[dict[str, Any]] | None = None,
) -> CodedClub:
    body = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "documents": pages
        or [{"url": url, "published_at_utc": PUBLISHED, "published_precision": "instant"}],
        "claims": claims,
    }
    response = ClaimResponse(
        text=json.dumps(body) if text is None else text,
        model_identifier=MODEL,
        model_version="fixture-2",
    )
    return CodedClub(
        club,
        response,
        ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        coding_prompt_sha256(MODEL),
        provider="synthetic",
    )


def _registry(tmp_path: Path) -> Path:
    def row(club: str, url: str, read_on: str | None) -> dict[str, object]:
        return {
            "club": club,
            "url": url,
            "terms_record": "docs/club_news_sources.md",
            "terms_read_on": read_on,
        }

    path = tmp_path / "club_news_sources.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "club_news_sources_v2",
                "sources": [
                    row("Arsenal", ARSENAL, "2026-09-01"),
                    row("Man Utd", UNITED, "2026-09-01"),
                    row("Everton", EVERTON, "2026-09-01"),
                    row("Example FC", "https://club.example/team-news", None),
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _week(
    tmp_path: Path,
    *,
    documents: tuple[RawDocument, ...],
    coded: tuple[CodedClub, ...],
    declared: tuple[str, ...],
    covered: tuple[str, ...],
    table_name: str | None = "table",
    calendar: bytes | None = None,
) -> tuple[Path, str, Path]:
    """Write a decision capture and a news capture, and export them as the weekly run does.

    ``calendar`` replaces the decision capture's fixtures payload (``_calendar``)."""

    root = tmp_path / "snapshots"
    decision = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: bootstrap_payload(),
            FIXTURES_PAYLOAD: fixtures_payload() if calendar is None else calendar,
        },
    ).snapshot_id
    news = write_club_news_capture(
        root,
        documents=documents,
        coded=coded,
        clubs_declared=declared,
        clubs_covered=covered,
        captured_at_utc=NEWS_CAPTURED_AT,
    ).snapshot_id
    result = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            None,
            tmp_path / "rotation",
            club_news_snapshot=news,
            table_name=table_name,
        ),
        repository_commit=COMMIT,
    )
    return root, news, Path(str(result["table_path"]))


def _log(
    tmp_path: Path,
    news: str,
    *,
    raw: int,
    call_failed: tuple[str, ...] = (),
    budget_stopped: tuple[str, ...] = (),
    attempted: int = 1,
    coding_stage: bool = True,
) -> Path:
    """The receipt as the Friday launcher leaves it: a byte order mark, the offline check
    first, then the acquisition's own lines, its coding stage printed by its own formatter."""

    stage = format_coding_stage(
        CodingStageReport(
            selected_document_count=1,
            dated_article_count=1,
            documents_freshly_coded=1,
            documents_reused=0,
            dated_article_clubs=("Arsenal",),
            no_dated_article_clubs=(),
            answered_clubs=("Arsenal",),
            empty_answer_clubs=(),
            unreadable_answer_clubs=(),
            reused_clubs=(),
            call_failed_clubs=call_failed,
            budget_stopped_clubs=budget_stopped,
            refused_before_call_clubs=(),
            nothing_selected_clubs=(),
            raw_claim_count=raw,
            model_calls_attempted=attempted,
        )
    )
    path = tmp_path / "friday-2026-27-gw04.club-news.log"
    lines = [
        "Configuration valid: provider 'synthetic', model 'synthetic-stub'.",
        "Registry      4 pages, 4 clubs declared",
        "Read          1 documents",
        f"Raw claims    {raw}; source validation occurs during export",
        f"Call budget   3; {attempted} attempted; no automatic provider retry",
        "Read refusal: Man Utd: https://united.example/news answered 503.",
        *(f"Coding refusal: {club}: the call failed." for club in call_failed),
        *(f"Coding refusal: {club}: Call budget exhausted." for club in budget_stopped),
        *(stage.splitlines() if coding_stage else ()),
        f"Capture       {news}",
    ]
    path.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8") + b"\r\n")
    return path


def _record(
    tmp_path: Path,
    root: Path,
    table: Path,
    *,
    raw: int,
    log: Path | None = None,
    call_failed: tuple[str, ...] = (),
    budget_stopped: tuple[str, ...] = (),
    commit: str = COMMIT,
    dirty: bool = False,
) -> dict[str, Any]:
    """The record of one exported week, read with a receipt of that week unless given one."""

    if log is None:
        manifest = json.loads(table.with_suffix(".manifest.json").read_text(encoding="utf-8"))
        news = str(manifest.get("club_news_snapshot_id", OTHER_CAPTURE))
        log = _log(tmp_path, news, raw=raw, call_failed=call_failed, budget_stopped=budget_stopped)
    return report.build_record(
        table_path=table,
        snapshot_root=root,
        registry=_registry(tmp_path),
        log=report.read_log(log),
        repository_commit=commit,
        repository_dirty=dirty,
    )


def _mixed_week(tmp_path: Path, **overrides: Any) -> tuple[Path, str, Path]:
    """One Arsenal page and answer that puts a claim in every place a claim can end."""

    lines = ARSENAL_LINES
    claims = [
        # Placed and applied: the player is not started.
        _claim("Saka", "Arsenal", "stated_expected_absent", lines[0], ARSENAL),
        # Placed and not applied, hedged: the label it gets is shared with other cases.
        _claim("Rice", "Arsenal", "stated_rotation_risk", lines[1], ARSENAL, "ambiguous"),
        # Placed; a start constrains nothing by rule.
        _claim("Timber", "Arsenal", "stated_expected_to_start", lines[2], ARSENAL),
        # Joined to one player of another club, cited from Arsenal's page.
        _claim("Mount", "Man Utd", "stated_expected_absent", lines[3], ARSENAL),
        # Two players share the surname at that club.
        _claim("Fernandes", "Man Utd", "stated_expected_absent", lines[4], ARSENAL),
        # Nobody of that name.
        _claim("Nobody", "Arsenal", "stated_expected_absent", lines[5], ARSENAL),
        # Placed and not applied because it names a cup tie.
        _claim(
            "Odegaard", "Arsenal", "stated_expected_absent", lines[6], ARSENAL, "other_competition"
        ),
        # A club the roster does not carry.
        _claim("Jesus", "Chelsea", "stated_expected_absent", lines[7], ARSENAL),
        # Quotes that are not in the page: one about Arsenal, one about another club.
        _claim("Havertz", "Arsenal", "stated_expected_absent", "Havertz is out.", ARSENAL),
        _claim("Zirkzee", "Man Utd", "stated_expected_absent", "Zirkzee is out.", ARSENAL),
    ]
    return _week(
        tmp_path,
        documents=(_document("Arsenal", ARSENAL, lines),),
        coded=(_coded("Arsenal", ARSENAL, claims),),
        declared=("Arsenal", "Man Utd"),
        covered=("Arsenal",),
        **overrides,
    )


def test_every_raw_claim_lands_in_exactly_one_counted_place(tmp_path: Path) -> None:
    root, news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table, raw=10)

    assert record["claims"] == {
        "raw": 10,
        "raw_per_coded_club": 10,
        "in_refused_responses": 0,
        "unverifiable_citation_own_club": 1,
        "unverifiable_citation_other_club": 1,
        "reached_join": 8,
        "joined_to_one_player": 5,
        "no_match": 1,
        "unknown_team": 1,
        "ambiguous": 1,
        "other_club_source": 1,
        "unverified_club_source": 0,
        "conflicting_player_claims": 0,
        "unresolved_by_reason": {
            "ambiguous": 1,
            "no_match": 1,
            "other_club_source": 1,
            "unknown_team": 1,
        },
        "identical_repeats": 0,
        "placed": 4,
    }
    assert record["table"]["players_with_statement"] == 4
    assert record["table"]["statements_by_disposition"] == {
        "stated_expected_absent": 2,
        "stated_expected_to_start": 1,
        "stated_rotation_risk": 1,
    }
    assert record["reader"]["constraining_statements"] == 1
    assert record["reader"]["excluded_not_starting"] == 1
    # A player kept out of the eleven is kept out of the captaincy too.
    assert record["reader"]["excluded_not_captain"] == 1
    assert record["reader"]["source_check"] == "cited_documents_held"
    assert record["reader"]["absence_or_doubt_statements"] == 3
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {
        "ambiguous": 1,
        "other_competition": 1,
    }
    # Six never reached a row; the hedged one reached a row and was not applied. The cup
    # tie is not a loss: its label shows it names another competition.
    assert record["loss"] == {
        "lost_before_table": 6,
        "lost_unapplied": 1,
        "lost_unapplied_by_cause": {
            "publication_unverified": 0,
            "publication_day_precision": 0,
            "scope_unverified": 1,
            "publication_not_before_fetch": 0,
        },
        "excluded_from_lost_unapplied": {
            "other_competition": 1,
            "past": 0,
            "next_match_before_target": 0,
        },
        "lost_unapplied_scope_unverified_by_scope": {"ambiguous": 1},
        "lost": 7,
        "responses_without_claims_list": 0,
        "calls_attempted_and_failed": 0,
        "verdict": "statements_lost",
        "issue_1006": "route_items_3_7_4_10",
    }
    assert record["inputs"]["club_news_capture_id"] == news
    assert record["checks"]["replay_matches_published_table"] is True
    assert record["checks"]["replay_matches_manifest"] is True
    assert record["checks"]["checkout_at_export_commit"] is True


def test_hosts_count_registered_hosts_and_leave_the_placeholder_out(tmp_path: Path) -> None:
    root, _news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table, raw=10)

    assert record["hosts"] == {
        "registered": 3,
        "asked": 2,
        "answered": 1,
        "refused": 1,
        "asked_hosts": ["https://arsenal.example", "https://united.example"],
        "answered_hosts": ["https://arsenal.example"],
        "refused_hosts": ["https://united.example"],
    }
    assert record["registered_pages"] == {"asked": 2, "read": 1}
    assert record["documents"] == {
        "retained": 1,
        "by_club": {"Arsenal": 1},
        "with_verified_publication": 1,
    }
    assert record["clubs"]["declared"] == ["Arsenal", "Man Utd"]
    assert record["clubs"]["covered_in_table"] == ["Arsenal"]


def test_an_answer_with_no_claims_reads_as_unanswered(tmp_path: Path) -> None:
    """The 21 October shape: one answered call, zero raw claims, nothing to lose."""

    root, _news, table = _week(
        tmp_path,
        documents=(_document("Arsenal", ARSENAL, ARSENAL_LINES),),
        coded=(_coded("Arsenal", ARSENAL, []),),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    record = _record(tmp_path, root, table, raw=0)

    assert record["claims"]["raw"] == 0
    assert record["claims"]["placed"] == 0
    assert record["table"]["players_not_addressed"] == record["table"]["roster_size"]
    assert record["reader"]["source_check"] == "nothing_cited"
    assert record["reader"]["constraining_statements"] == 0
    assert record["loss"]["lost"] == 0
    assert record["loss"]["calls_attempted_and_failed"] == 0
    assert record["loss"]["verdict"] == "no_raw_claims"
    assert record["loss"]["issue_1006"] == "unanswered"


def test_claims_that_all_reach_their_outcome_read_as_none_lost(tmp_path: Path) -> None:
    """An absence named for a cup tie or for a match already played is no loss: each scope
    label is left out of ``lost_unapplied`` and counted by name."""

    lines = (*ARSENAL_LINES, "Martinelli missed the last Premier League match.")
    root, _news, table = _week(
        tmp_path,
        documents=(_document("Arsenal", ARSENAL, lines),),
        coded=(
            _coded(
                "Arsenal",
                ARSENAL,
                [
                    _claim("Saka", "Arsenal", "stated_expected_absent", lines[0], ARSENAL),
                    _claim("Timber", "Arsenal", "stated_expected_to_start", lines[2], ARSENAL),
                    _claim(
                        "Odegaard",
                        "Arsenal",
                        "stated_expected_absent",
                        lines[6],
                        ARSENAL,
                        "other_competition",
                    ),
                    _claim(
                        "Martinelli", "Arsenal", "stated_expected_absent", lines[8], ARSENAL, "past"
                    ),
                ],
            ),
        ),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    record = _record(tmp_path, root, table, raw=4)

    assert record["claims"]["joined_to_one_player"] == 4
    assert record["claims"]["placed"] == 4
    assert record["reader"]["constraining_statements"] == 1
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {
        "other_competition": 1,
        "past": 1,
    }
    assert record["loss"]["lost_unapplied"] == 0
    assert record["loss"]["excluded_from_lost_unapplied"] == {
        "other_competition": 1,
        "past": 1,
        "next_match_before_target": 0,
    }
    assert record["loss"]["lost"] == 0
    assert record["loss"]["verdict"] == "no_statement_lost"
    assert record["loss"]["issue_1006"] == "close"


def test_a_response_refused_whole_loses_every_claim_it_lists(tmp_path: Path) -> None:
    lines = ARSENAL_LINES
    twice = [
        _claim("Saka", "Arsenal", "stated_expected_absent", lines[0], ARSENAL),
        _claim("Saka", "Arsenal", "stated_rotation_risk", lines[0], ARSENAL),
    ]
    everton_line = ("Branthwaite will start the next Premier League match.",)
    root, _news, table = _week(
        tmp_path,
        documents=(
            _document("Arsenal", ARSENAL, lines),
            _document("Man Utd", UNITED, ("Dalot trained today.",)),
            _document("Everton", EVERTON, everton_line),
        ),
        coded=(
            _coded("Arsenal", ARSENAL, twice),
            _coded("Man Utd", UNITED, [], text="not a JSON answer"),
            _coded(
                "Everton",
                EVERTON,
                [
                    _claim(
                        "Branthwaite",
                        "Everton",
                        "stated_expected_to_start",
                        everton_line[0],
                        EVERTON,
                    )
                ],
            ),
        ),
        declared=("Arsenal", "Man Utd", "Everton"),
        covered=("Arsenal", "Man Utd", "Everton"),
    )
    record = _record(tmp_path, root, table, raw=3)

    assert record["responses"] == {
        "stored": 3,
        "distinct": 3,
        "reused_from_earlier_capture": 0,
        "refused_whole": 2,
        "refused_clubs": ["Arsenal", "Man Utd"],
        "refused_without_claims_list": 1,
    }
    assert record["claims"]["raw"] == 3
    assert record["claims"]["in_refused_responses"] == 2
    assert record["claims"]["placed"] == 1
    assert record["clubs"]["covered_in_table"] == ["Everton"]
    assert record["loss"]["lost_before_table"] == 2
    assert record["loss"]["verdict"] == "statements_lost"


def test_identical_repeats_and_conflicts_are_told_apart(tmp_path: Path) -> None:
    """Three answers for one club: a statement, its exact repeat, and a contradiction."""

    lines = ARSENAL_LINES
    absent = [_claim("Saka", "Arsenal", "stated_expected_absent", lines[0], ARSENAL)]
    risk = [_claim("Saka", "Arsenal", "stated_rotation_risk", lines[0], ARSENAL)]
    first = _coded("Arsenal", ARSENAL, absent)
    root, _news, table = _week(
        tmp_path,
        documents=(_document("Arsenal", ARSENAL, lines),),
        coded=(
            first,
            _coded("Arsenal", ARSENAL, absent, text=first.response.text + " "),
            _coded("Arsenal", ARSENAL, risk),
        ),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    # The acquisition counts one answer per club, as the capture of a real week holds; this
    # synthetic week holds three for one club, so its receipt counts the last.
    record = _record(tmp_path, root, table, raw=1)

    assert record["claims"]["raw"] == 3
    assert record["claims"]["raw_per_coded_club"] == 1
    assert record["claims"]["reached_join"] == 3
    assert record["claims"]["identical_repeats"] == 1
    assert record["claims"]["conflicting_player_claims"] == 2
    assert record["claims"]["placed"] == 0
    assert record["table"]["players_with_conflicting_claims"] == 1
    assert record["loss"]["lost_before_table"] == 2


@pytest.mark.parametrize(
    ("raw", "unreadable", "failed", "lost", "verdict"),
    [
        (0, 0, 0, 0, "no_raw_claims"),
        (0, 1, 0, 0, "statements_lost"),
        (0, 0, 1, 0, "statements_lost"),
        (4, 0, 0, 0, "no_statement_lost"),
        (4, 0, 0, 1, "statements_lost"),
        (4, 1, 0, 0, "statements_lost"),
        (4, 0, 1, 0, "statements_lost"),
    ],
)
def test_the_reading_is_fixed_by_four_counts(
    raw: int, unreadable: int, failed: int, lost: int, verdict: str
) -> None:
    assert (
        report.reading(raw=raw, unreadable_responses=unreadable, failed_calls=failed, lost=lost)
        == verdict
    )


def _failed_call_week(tmp_path: Path, claims: list[dict[str, Any]]) -> tuple[Path, str, Path]:
    """Arsenal answers; Everton's page is read and its call leaves no stored answer."""

    return _week(
        tmp_path,
        documents=(
            _document("Arsenal", ARSENAL, ARSENAL_LINES),
            _document("Everton", EVERTON, ("Branthwaite trained today.",)),
        ),
        coded=(_coded("Arsenal", ARSENAL, claims),),
        declared=("Arsenal", "Everton"),
        covered=("Arsenal",),
    )


@pytest.mark.parametrize("answered_claims", [0, 1])
def test_a_call_that_was_attempted_and_failed_rules_out_any_other_verdict(
    tmp_path: Path, answered_claims: int
) -> None:
    """The answer that was refused, or never came, is in no capture: its statements are
    uncounted, so neither a clean week nor an empty one can be read from the rest."""

    saka = _claim("Saka", "Arsenal", "stated_expected_absent", ARSENAL_LINES[0], ARSENAL)
    root, _news, table = _failed_call_week(tmp_path, [saka][:answered_claims])
    record = _record(tmp_path, root, table, raw=answered_claims, call_failed=("Everton",))

    assert record["clubs"]["read_not_coded"] == ["Everton"]
    assert record["acquisition_log"]["call_failed_clubs"] == ["Everton"]
    assert record["checks"]["log_outcomes_match_capture"] is True
    assert record["claims"]["raw"] == answered_claims
    assert record["claims"]["placed"] == answered_claims
    assert record["loss"]["lost"] == 0
    assert record["loss"]["calls_attempted_and_failed"] == 1
    assert record["loss"]["verdict"] == "statements_lost"
    assert record["loss"]["issue_1006"] == "route_items_3_7_4_10"


def test_a_club_stopped_before_any_call_loses_no_statement(tmp_path: Path) -> None:
    """No call was made for it, so no statement existed to lose."""

    saka = _claim("Saka", "Arsenal", "stated_expected_absent", ARSENAL_LINES[0], ARSENAL)
    root, _news, table = _failed_call_week(tmp_path, [saka])
    record = _record(tmp_path, root, table, raw=1, budget_stopped=("Everton",))

    assert record["acquisition_log"]["budget_stopped_clubs"] == ["Everton"]
    assert record["loss"]["calls_attempted_and_failed"] == 0
    assert record["loss"]["verdict"] == "no_statement_lost"
    assert record["loss"]["issue_1006"] == "close"


def test_a_receipt_that_does_not_account_for_every_unanswered_club_refuses(
    tmp_path: Path,
) -> None:
    saka = _claim("Saka", "Arsenal", "stated_expected_absent", ARSENAL_LINES[0], ARSENAL)
    root, _news, table = _failed_call_week(tmp_path, [saka])

    with pytest.raises(report.JoinCountError, match=r"holds pages and no answer for \['Everton'\]"):
        _record(tmp_path, root, table, raw=1)


def test_a_receipt_without_its_coding_stage_refuses(tmp_path: Path) -> None:
    root, news, table = _mixed_week(tmp_path)
    log = _log(tmp_path, news, raw=10, coding_stage=False)

    with pytest.raises(report.JoinCountError, match="Call attempted and failed"):
        report.read_log(log)
    with pytest.raises(report.JoinCountError, match="exactly once"):
        _record(tmp_path, root, table, raw=10, log=log)


def test_statements_not_applied_are_counted_by_the_first_condition_they_fail(
    tmp_path: Path,
) -> None:
    undated = ("Martinelli will miss the next Premier League match.",)
    day = ("White will miss the next Premier League match.",)
    lines = ARSENAL_LINES
    pages = [
        {"url": ARSENAL, "published_at_utc": PUBLISHED, "published_precision": "instant"},
        {"url": ARSENAL_UNDATED, "published_at_utc": None, "published_precision": "unknown"},
        {"url": ARSENAL_DAY, "published_at_utc": "2026-09-12", "published_precision": "day"},
    ]
    claims = [
        # Applied: the page is dated to the instant and the scope is read.
        _claim("Saka", "Arsenal", "stated_expected_absent", lines[0], ARSENAL),
        # A hedge on a page dated to the instant: the scope is not verified.
        _claim("Rice", "Arsenal", "stated_rotation_risk", lines[1], ARSENAL, "ambiguous"),
        # A page that states no publication time.
        _claim("Martinelli", "Arsenal", "stated_expected_absent", undated[0], ARSENAL_UNDATED),
        # A page that states only the day.
        _claim("White", "Arsenal", "stated_expected_absent", day[0], ARSENAL_DAY),
    ]
    root, _news, table = _week(
        tmp_path,
        documents=(
            _document("Arsenal", ARSENAL, lines),
            _document("Arsenal", ARSENAL_UNDATED, undated, published=None),
            _document("Arsenal", ARSENAL_DAY, day, published="2026-09-12"),
        ),
        coded=(_coded("Arsenal", ARSENAL, claims, pages=pages),),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    record = _record(tmp_path, root, table, raw=4)

    assert record["claims"]["placed"] == 4
    assert record["documents"]["with_verified_publication"] == 2
    assert record["reader"]["constraining_statements"] == 1
    assert record["loss"]["lost_unapplied"] == 3
    assert record["loss"]["lost_unapplied_by_cause"] == {
        "publication_unverified": 1,
        "publication_day_precision": 1,
        "scope_unverified": 1,
        "publication_not_before_fetch": 0,
    }
    assert record["loss"]["lost_unapplied_scope_unverified_by_scope"] == {"ambiguous": 1}
    assert record["loss"]["verdict"] == "statements_lost"


@pytest.mark.parametrize(
    ("url", "published", "precision"),
    [
        pytest.param(ARSENAL_UNDATED, None, "unknown", id="page_states_no_publication"),
        pytest.param(ARSENAL_DAY, "2026-09-12", "day", id="page_dated_to_the_day"),
    ],
)
def test_a_cup_tie_or_a_past_match_is_no_loss_whatever_the_page_states(
    tmp_path: Path, url: str, published: str | None, precision: str
) -> None:
    """The two scope labels leave a statement out before its page's publication is read, so
    neither is lost under a publication cause on a page the rule cannot date to the instant."""

    lines = ("Martinelli missed the last Premier League match.", "Odegaard will miss the cup tie.")
    page = {"url": url, "published_at_utc": published, "published_precision": precision}
    claims = [
        _claim("Martinelli", "Arsenal", "stated_expected_absent", lines[0], url, "past"),
        _claim("Odegaard", "Arsenal", "stated_expected_absent", lines[1], url, "other_competition"),
    ]
    root, _news, table = _week(
        tmp_path,
        documents=(_document("Arsenal", url, lines, published=published),),
        coded=(_coded("Arsenal", url, claims, pages=[page]),),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    record = _record(tmp_path, root, table, raw=2)

    assert record["claims"]["placed"] == 2
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {
        "other_competition": 1,
        "past": 1,
    }
    assert record["loss"]["lost_unapplied"] == 0
    assert record["loss"]["lost_unapplied_by_cause"] == dict.fromkeys(report.UNAPPLIED_CAUSES, 0)
    assert record["loss"]["excluded_from_lost_unapplied"] == {
        "other_competition": 1,
        "past": 1,
        "next_match_before_target": 0,
    }
    assert record["loss"]["lost"] == 0
    assert record["loss"]["verdict"] == "no_statement_lost"
    _assert_accounted(record)


#: Man Utd play their previous league match on 2026-09-09 at 19:00 and their target fixture
#: on 2026-09-12 at 19:00, after the decision capture. A page published on the morning of the
#: 9th names, as "the next Premier League match", the match of that evening.
BEFORE_UNITED_MIDWEEK = "2026-09-09T10:00:00Z"
#: After that match and before the fetch, so the next match is the target fixture.
AFTER_UNITED_MIDWEEK = "2026-09-12T13:00:00Z"
DALOT = "Dalot will miss the next Premier League match."


def _team(name: str) -> int:
    teams = json.loads(bootstrap_payload())["teams"]
    return next(int(team["id"]) for team in teams if team["name"] == name)


def _calendar(
    *, changed: dict[int, dict[str, Any]] | None = None, added: tuple[dict[str, Any], ...] = ()
) -> bytes:
    """The synthetic decision calendar with fixtures changed (by id) or added."""

    records = [
        {**record, **(changed or {}).get(record["id"], {})}
        for record in json.loads(fixtures_payload())
    ]
    template = {"team_h_difficulty": 3, "team_a_difficulty": 3, "provisional_start_time": False}
    return json.dumps([*records, *({**template, **record} for record in added)]).encode("utf-8")


def _league_fixture(
    fixture_id: int, gameweek: int | None, home: str, away: str, kickoff: str | None
) -> dict[str, Any]:
    return {
        "id": fixture_id,
        "event": gameweek,
        "team_h": _team(home),
        "team_a": _team(away),
        "kickoff_time": kickoff,
        "finished": False,
    }


def _united_capture(
    tmp_path: Path,
    *,
    published: str | None = BEFORE_UNITED_MIDWEEK,
    stated: str | None = None,
    precision: str = "instant",
    line: str = DALOT,
    player: str = "Dalot",
    scope: str = "upcoming_premier_league",
    calendar: bytes | None = None,
) -> tuple[Path, str, Path]:
    """One Man Utd page and answer: Dalot's absence, quoted as ``DALOT`` from ``line``.

    The page states ``published``; the answer states ``stated`` for it, ``published`` unless
    given. A ``player`` other than the roster's short name is quoted as the whole ``line``."""

    quote = DALOT if DALOT in line and player == "Dalot" else line
    page = {
        "url": UNITED,
        "published_at_utc": published if stated is None else stated,
        "published_precision": precision,
    }
    return _week(
        tmp_path,
        documents=(_document("Man Utd", UNITED, (line,), published=published),),
        coded=(
            _coded(
                "Man Utd",
                UNITED,
                [_claim(player, "Man Utd", "stated_expected_absent", quote, UNITED, scope)],
                pages=[page],
            ),
        ),
        declared=("Man Utd",),
        covered=("Man Utd",),
        calendar=calendar,
    )


def _united_week(tmp_path: Path, **week: Any) -> dict[str, Any]:
    """The record of the week ``_united_capture`` writes with ``week``."""

    root, _news, table = _united_capture(tmp_path, **week)
    return _record(tmp_path, root, table, raw=1)


def _assert_accounted(record: dict[str, Any]) -> None:
    """The identities still hold with the exclusion: every claim in one place, the four
    causes adding up to ``lost_unapplied``, and every not-applied absence or doubt either a
    loss or left out by name."""

    loss = record["loss"]
    assert record["checks"]["claims_accounted"] is True
    assert sum(loss["lost_unapplied_by_cause"].values()) == loss["lost_unapplied"]
    assert loss["lost"] == loss["lost_before_table"] + loss["lost_unapplied"]
    assert sum(record["reader"]["absence_or_doubt_not_applied_by_scope"].values()) == (
        loss["lost_unapplied"] + sum(loss["excluded_from_lost_unapplied"].values())
    )


def test_a_next_match_statement_made_before_an_intervening_club_match_is_no_loss(
    tmp_path: Path,
) -> None:
    """Its words name the club match of that evening, not the decision's fixture: left out
    of ``lost_unapplied`` and counted as ``next_match_before_target``, so an otherwise clean
    week still reads as none lost and routes nothing, as the same page published after that
    match does."""

    before, after = tmp_path / "before", tmp_path / "after"
    before.mkdir()
    after.mkdir()
    record = _united_week(before)
    applied = _united_week(after, published=AFTER_UNITED_MIDWEEK)

    assert applied["reader"]["constraining_statements"] == 1
    assert applied["loss"]["excluded_from_lost_unapplied"]["next_match_before_target"] == 0
    assert applied["loss"]["verdict"] == "no_statement_lost"
    _assert_accounted(applied)

    assert record["claims"]["placed"] == 1
    assert record["reader"]["constraining_statements"] == 0
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {
        "upcoming_premier_league": 1
    }
    assert record["loss"]["lost_unapplied"] == 0
    assert record["loss"]["lost_unapplied_by_cause"] == dict.fromkeys(report.UNAPPLIED_CAUSES, 0)
    assert record["loss"]["excluded_from_lost_unapplied"] == {
        "other_competition": 0,
        "past": 0,
        "next_match_before_target": 1,
    }
    assert record["loss"]["lost"] == 0
    assert record["loss"]["verdict"] == "no_statement_lost"
    assert record["loss"]["issue_1006"] == "close"
    _assert_accounted(record)


#: A rearranged Man Utd league match in no gameweek, kicking off at 16:00 on the decision day:
#: after the decision capture (15:00) and before the target fixture (19:00).
AFTER_THE_CAPTURE = "2026-09-12T16:00:00Z"
_REARRANGED = _calendar(added=(_league_fixture(502, None, "Man Utd", "Fulham", AFTER_THE_CAPTURE),))
#: Dalot named in full: the exporter verifies the label with the coded name, and the reader,
#: which reads the roster's short name, does not verify the scope.
DALOT_IN_FULL = "Diogo Dalot will miss the next Premier League match."


@pytest.mark.parametrize(
    "week",
    [
        pytest.param(
            {"calendar": _REARRANGED},
            id="club_matches_before_and_after_the_capture",
        ),
        pytest.param(
            {"published": AFTER_UNITED_MIDWEEK, "calendar": _REARRANGED},
            id="club_match_after_the_capture_only",
        ),
        pytest.param(
            # Published at the capture instant itself, which is at or before the capture.
            {"published": CAPTURED_AT, "calendar": _REARRANGED},
            id="published_at_the_capture",
        ),
        pytest.param(
            {"line": DALOT_IN_FULL, "player": "Diogo Dalot"},
            id="player_named_in_full",
        ),
    ],
)
def test_the_earlier_club_match_may_fall_on_either_side_of_the_capture(
    tmp_path: Path, week: dict[str, Any]
) -> None:
    """The condition is the decision's: the club's first dated league fixture after the
    publication instant kicks off before the target fixture, wherever it falls against the
    capture. A full-name statement keeps its label, so it is left out like any other."""

    record = _united_week(tmp_path, **week)

    assert record["claims"]["placed"] == 1
    assert record["reader"]["constraining_statements"] == 0
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {
        "upcoming_premier_league": 1
    }
    assert record["loss"]["lost_unapplied"] == 0
    assert record["loss"]["lost_unapplied_by_cause"] == dict.fromkeys(report.UNAPPLIED_CAUSES, 0)
    assert record["loss"]["excluded_from_lost_unapplied"]["next_match_before_target"] == 1
    assert record["loss"]["verdict"] == "no_statement_lost"
    assert record["loss"]["issue_1006"] == "close"
    _assert_accounted(record)


#: A second target-week kickoff, three days after the first, for a double gameweek.
_LATER = "2026-09-15T19:00:00Z"


@pytest.mark.parametrize(
    ("week", "cause", "scope"),
    [
        pytest.param(
            {"published": "2026-09-09", "precision": "day"},
            "publication_day_precision",
            None,
            id="publication_verified_to_the_day",
        ),
        pytest.param(
            {"published": None, "precision": "unknown"},
            "publication_unverified",
            None,
            id="publication_unstated",
        ),
        pytest.param(
            # The page states an instant before the club's previous match, and the table
            # carries it, but the answer stated another, so the reader does not verify it.
            {"stated": "2026-09-09T10:05:00Z"},
            "publication_unverified",
            None,
            id="publication_does_not_recheck",
        ),
        pytest.param(
            {"line": "Dalot will miss Saturday's Premier League match.", "scope": "unspecified"},
            "scope_unverified",
            "unspecified",
            id="label_not_upcoming_premier_league",
        ),
        pytest.param(
            # The quote keeps its label from its own words and is not a whole sentence of
            # the page, so its scope is not verified although the calendar binds it.
            {"published": AFTER_UNITED_MIDWEEK, "line": "It is not true that " + DALOT},
            "scope_unverified",
            "upcoming_premier_league",
            id="no_intervening_match",
        ),
        pytest.param(
            {"published": AFTER_UNITED_MIDWEEK, "line": DALOT_IN_FULL, "player": "Diogo Dalot"},
            "scope_unverified",
            "upcoming_premier_league",
            id="player_named_in_full_with_no_intervening_match",
        ),
        pytest.param(
            {"calendar": _calendar(added=(_league_fixture(501, None, "Man Utd", "Fulham", None),))},
            "scope_unverified",
            "upcoming_premier_league",
            id="undated_calendar",
        ),
        pytest.param(
            {
                "published": AFTER_UNITED_MIDWEEK,
                "calendar": _calendar(
                    added=(
                        _league_fixture(501, None, "Man Utd", "Fulham", None),
                        _league_fixture(502, None, "Man Utd", "Fulham", AFTER_THE_CAPTURE),
                    )
                ),
            },
            "scope_unverified",
            "upcoming_premier_league",
            id="undated_beside_a_club_match_after_the_capture",
        ),
        pytest.param(
            {"calendar": _calendar(changed={401: {"team_a": _team("Fulham")}})},
            "scope_unverified",
            "upcoming_premier_league",
            id="blank_target_week",
        ),
        pytest.param(
            {
                "calendar": _calendar(
                    added=(_league_fixture(403, TARGET_GAMEWEEK, "Man Utd", "Fulham", _LATER),)
                )
            },
            "scope_unverified",
            "upcoming_premier_league",
            id="double_target_week",
        ),
        pytest.param(
            {"calendar": _calendar(changed={401: {"kickoff_time": "2026-09-12T14:45:00Z"}})},
            "scope_unverified",
            "upcoming_premier_league",
            id="target_kicked_off_by_the_capture",
        ),
        pytest.param(
            # A kickoff at the capture instant itself has kicked off by the capture.
            {"calendar": _calendar(changed={401: {"kickoff_time": CAPTURED_AT}})},
            "scope_unverified",
            "upcoming_premier_league",
            id="target_kicks_off_at_the_capture",
        ),
        pytest.param(
            {"published": "2026-09-12T16:00:00Z"},
            "scope_unverified",
            "upcoming_premier_league",
            id="published_after_the_capture",
        ),
    ],
)
def test_a_statement_outside_that_condition_stays_a_loss_under_its_own_cause(
    tmp_path: Path, week: dict[str, Any], cause: str, scope: str | None
) -> None:
    record = _united_week(tmp_path, **week)

    assert record["reader"]["constraining_statements"] == 0
    assert record["loss"]["lost_unapplied"] == 1
    assert record["loss"]["lost_unapplied_by_cause"] == {
        **dict.fromkeys(report.UNAPPLIED_CAUSES, 0),
        cause: 1,
    }
    assert record["loss"]["excluded_from_lost_unapplied"]["next_match_before_target"] == 0
    assert record["loss"]["lost_unapplied_scope_unverified_by_scope"] == (
        {} if scope is None else {scope: 1}
    )
    assert record["loss"]["verdict"] == "statements_lost"
    _assert_accounted(record)


@pytest.mark.parametrize(
    ("club", "on_roster", "qualifies"),
    [
        pytest.param("Man Utd", True, True, id="the_roster_club"),
        pytest.param("Arsenal", True, False, id="a_club_other_than_the_roster_club"),
        pytest.param("Man Utd", False, False, id="a_player_not_on_the_roster"),
    ],
)
def test_the_next_match_exclusion_asks_the_calendar_of_the_statements_own_club(
    tmp_path: Path, club: str, on_roster: bool, qualifies: bool
) -> None:
    """The calendar asked is the roster club's, so a statement whose club is not its player's
    roster club, or whose player the roster does not carry, is not left out. The reader
    resolves a citation by digest alone, so of two clubs' byte-identical pages it can take the
    other club's; the reader then refuses the scope, and the statement stays a
    ``scope_unverified`` loss."""

    root, news, table = _united_capture(tmp_path)
    published = read_rotation_evidence_artifact(table, table.with_suffix(".manifest.json"))
    basis = _decision_fixture_basis(published, root)
    words = load_manager_words(table, club_news_source=root / news, snapshot_root=root)
    assert basis is not None
    (word,) = words.words
    player_id = word.player_id if on_roster else max(basis[1]) + 1
    statement = dataclasses.replace(word, club=club, player_id=player_id)

    assert report.next_match_before_target(statement, basis, words.gameweek) is qualifies


def test_a_double_gameweek_statement_is_the_rules_declaration_not_a_loss(
    tmp_path: Path,
) -> None:
    """Arsenal play twice in the target week, so the rule declares the role undecidable and
    gives the statement ``ambiguous_current_week_fixture`` instead: not counted as lost."""

    calendar = _calendar(
        added=(_league_fixture(403, TARGET_GAMEWEEK, "Arsenal", "Fulham", _LATER),)
    )
    saka = _claim("Saka", "Arsenal", "stated_expected_absent", ARSENAL_LINES[0], ARSENAL)
    root, _news, table = _week(
        tmp_path,
        documents=(_document("Arsenal", ARSENAL, ARSENAL_LINES),),
        coded=(_coded("Arsenal", ARSENAL, [saka]),),
        declared=("Arsenal",),
        covered=("Arsenal",),
        calendar=calendar,
    )
    record = _record(tmp_path, root, table, raw=1)

    assert record["claims"]["placed"] == 1
    assert record["reader"]["constraining_statements"] == 0
    assert record["reader"]["double_gameweek_reason"] == 1
    assert record["reader"]["absence_or_doubt_not_applied_by_scope"] == {}
    assert record["loss"]["lost_unapplied"] == 0
    assert record["loss"]["lost"] == 0
    assert record["loss"]["verdict"] == "no_statement_lost"
    _assert_accounted(record)


def test_a_replay_that_differs_from_the_published_table_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _news, table = _mixed_week(tmp_path)
    monkeypatch.setattr(report, "_table_bytes", lambda frame: b"not the published bytes")

    with pytest.raises(report.JoinCountError, match="not the ones it was exported from"):
        _record(tmp_path, root, table, raw=10)


def test_a_replay_whose_counts_differ_from_the_manifest_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Code that changes a count and no row passes the digest; the manifest catches it."""

    root, _news, table = _mixed_week(tmp_path)
    build = report.build_rotation_evidence_table

    def recounted(**arguments: Any) -> Any:
        replay = build(**arguments)
        replay.attrs["claims_ambiguous"] += 1
        return replay

    monkeypatch.setattr(report, "build_rotation_evidence_table", recounted)

    with pytest.raises(report.JoinCountError, match=r"differ from .* in \['claims_ambiguous'\]"):
        _record(tmp_path, root, table, raw=10)


@pytest.mark.parametrize(
    ("commit", "dirty"), [("1" * 40, False), (COMMIT, True)], ids=["other_commit", "dirty"]
)
def test_a_checkout_that_is_not_the_export_commit_refuses(
    tmp_path: Path, commit: str, dirty: bool
) -> None:
    root, _news, table = _mixed_week(tmp_path)

    with pytest.raises(report.JoinCountError, match="clean worktree at that commit"):
        _record(tmp_path, root, table, raw=10, commit=commit, dirty=dirty)


def test_a_fixture_week_is_not_club_news(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    decision = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    ).snapshot_id
    result = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            REPOSITORY / "data" / "sample" / "club_news_v1.fixture.json",
            tmp_path / "rotation",
            table_name="fixture",
        ),
        repository_commit=COMMIT,
    )

    with pytest.raises(report.JoinCountError, match="not from a club-news capture"):
        _record(tmp_path, root, Path(str(result["table_path"])), raw=0)


def test_the_receipt_is_read_and_held_to_the_capture(tmp_path: Path) -> None:
    saka = _claim("Saka", "Arsenal", "stated_expected_absent", ARSENAL_LINES[0], ARSENAL)
    root, news, table = _failed_call_week(tmp_path, [saka])
    log = _log(tmp_path, news, raw=1, call_failed=("Everton",), attempted=2)
    record = _record(tmp_path, root, table, raw=1, log=log)

    assert record["acquisition_log"] == {
        "model_call_budget": 3,
        "model_calls_attempted": 2,
        "raw_claims_printed": 1,
        "read_refusal_lines": 1,
        "coding_refusal_lines": 1,
        "call_failed_clubs": ["Everton"],
        "budget_stopped_clubs": [],
        "refused_before_call_clubs": [],
        "nothing_selected_clubs": [],
    }
    assert record["checks"]["log_capture_id_matches"] is True
    assert record["checks"]["log_raw_claims_match"] is True
    assert record["inputs"]["club_news_log_file"] == "friday-2026-27-gw04.club-news.log"


def test_a_receipt_of_another_capture_or_count_refuses(tmp_path: Path) -> None:
    root, _news, table = _mixed_week(tmp_path)

    with pytest.raises(report.JoinCountError, match="receipts of different weeks"):
        _record(tmp_path, root, table, raw=10, log=_log(tmp_path, OTHER_CAPTURE, raw=10))
    with pytest.raises(report.JoinCountError, match="printed 9 raw claims"):
        _record(tmp_path, root, table, raw=9)


def test_a_receipt_whose_outcome_line_miscounts_its_clubs_refuses(tmp_path: Path) -> None:
    log = _log(tmp_path, OTHER_CAPTURE, raw=0, call_failed=("Everton",))
    printed = log.read_bytes()
    damaged = printed.replace(
        b"Call attempted and failed: 1 [Everton]", b"Call attempted and failed: 2 [Everton]"
    )
    assert damaged != printed
    log.write_bytes(damaged)

    with pytest.raises(
        report.JoinCountError,
        match=r"counts 2 clubs on its line 'Call attempted and failed' and lists 1\.",
    ):
        report.read_log(log)


def test_the_command_finds_the_table_from_the_receipt_offline_and_writes_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, news, table = _mixed_week(tmp_path, table_name=None)
    assert re.fullmatch(rf"rotation_evidence_v4_.*_{news[-12:]}_decision_.*\.csv", table.name)
    log = _log(tmp_path, news, raw=10)
    output = tmp_path / "join-counts.json"
    monkeypatch.setattr(report, "_git_revision", lambda: (COMMIT, False))

    def no_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the reporter opened a network connection")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    arguments = [
        "--club-news-log",
        str(log),
        "--snapshot-root",
        str(root),
        "--rotation-dir",
        str(tmp_path / "rotation"),
        "--registry",
        str(_registry(tmp_path)),
        "--output",
        str(output),
    ]

    assert report.main(arguments) == 0
    printed = capsys.readouterr().out
    assert output.read_text(encoding="utf-8") == printed
    record = json.loads(printed)
    assert record["inputs"]["rotation_table_file"] == table.name
    assert record["repository_commit"] == COMMIT
    assert record["loss"]["verdict"] == "statements_lost"

    assert report.main(arguments) == 1
    assert capsys.readouterr().out.startswith("Refused:")


@pytest.mark.parametrize(
    "checkout",
    [
        pytest.param("another", id="another_checkout"),
        # The package's own src as the checkout: squadopt is inside it and not in its src, as
        # an install in the checkout's own virtual environment or build folder would be.
        pytest.param("package_src", id="inside_the_checkout_but_not_in_its_src"),
    ],
)
def test_the_command_refuses_squadopt_imported_from_another_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    checkout: str,
) -> None:
    """The commit check reads this checkout; the replay would run the imported code. The
    guard runs before anything is read, so a receipt that does not exist is not what
    refuses."""

    root, _news, _table = _mixed_week(tmp_path, table_name=None)
    output = tmp_path / "join-counts.json"
    repository = (
        tmp_path / "another-checkout"
        if checkout == "another"
        else Path(squadopt.__file__).resolve().parents[1]
    )
    monkeypatch.setattr(report, "_git_revision", lambda: (COMMIT, False))
    monkeypatch.setattr(report, "REPOSITORY_ROOT", repository)
    arguments = [
        "--club-news-log",
        str(tmp_path / "no-such-receipt.club-news.log"),
        "--snapshot-root",
        str(root),
        "--rotation-dir",
        str(tmp_path / "rotation"),
        "--registry",
        str(_registry(tmp_path)),
        "--output",
        str(output),
    ]

    assert report.main(arguments) == 1
    printed = capsys.readouterr().out
    assert printed.startswith("Refused: squadopt is imported from ")
    assert f", not from {repository / 'src'}: " in printed
    assert printed.count("\n") == 1
    assert not output.exists()


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {k for item in value.values() for k in _keys(item)}
    return set()


def test_the_protocol_defines_every_field_the_record_carries(tmp_path: Path) -> None:
    root, _news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table, raw=10)
    protocol = PROTOCOL.read_text(encoding="utf-8")
    # Data-valued maps carry club names, reasons and scope labels as keys, not fields.
    data_keys = set(record["documents"]["by_club"]) | set(record["claims"]["unresolved_by_reason"])
    data_keys |= set(record["table"]["statements_by_disposition"])
    data_keys |= set(record["reader"]["absence_or_doubt_not_applied_by_scope"])
    data_keys |= set(record["loss"]["lost_unapplied_scope_unverified_by_scope"])

    undefined = sorted(key for key in _keys(record) - data_keys if f"`{key}`" not in protocol)
    assert undefined == []
    for value in (
        report.RECORD_VERSION,
        *report.ISSUE_1006_READING.items(),
        *report.UNAPPLIED_CAUSES,
        *report.NOT_LOST_UNAPPLIED,
    ):
        for text in value if isinstance(value, tuple) else (value,):
            assert f"`{text}`" in protocol

    # The loss section's sentence lists the record's loss fields in the record's order, each
    # count is defined where the protocol defines it ("`name`:", "`name` counts" or
    # "`name` =") and each verdict has its row; a mention alone is not a definition.
    listed = re.search(r"The record's `loss` section carries (.+?), which are:", protocol, re.S)
    assert listed is not None
    assert re.findall(r"`([^`]+)`", listed[1]) == list(record["loss"])
    counts = [key for key in record["loss"] if key not in ("verdict", "issue_1006")]
    for key in counts:
        assert re.search(rf"`{key}`(?::| counts | = )", protocol), key
    for verdict, reading in report.ISSUE_1006_READING.items():
        assert re.search(rf"^\| `{verdict}` \| [^|\n]+ \| `{reading}` \|", protocol, re.M), verdict
    version = re.search(r"^The record's version is `([^`]+)`", protocol, re.M)
    assert version is not None
    assert version[1] == report.RECORD_VERSION
