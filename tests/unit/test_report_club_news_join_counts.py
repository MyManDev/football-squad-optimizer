"""The join-count reporter, on synthetic captures written and exported by the real code.

Every week here is written through ``write_club_news_capture`` and exported through
``export_rotation_evidence``, the same two calls the Friday run makes, so the reporter is held
to tables the exporter actually wrote. Nothing reaches a network or calls a model: the
responses are stored text, and one test removes the socket layer while the command runs.
"""

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

from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD

REPOSITORY = Path(__file__).resolve().parents[2]
PROTOCOL = REPOSITORY / "docs" / "research" / "club_news_join_counts_gw8_prereg.md"
COMMIT = "0" * 40
PUBLISHED = "2026-09-12T13:00:00Z"
FETCHED = "2026-09-12T14:00:00Z"
NEWS_CAPTURED_AT = "2026-09-12T14:30:00Z"
MODEL = "synthetic-stub"

ARSENAL = "https://arsenal.example/news"
UNITED = "https://united.example/news"
EVERTON = "https://everton.example/news"

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


def _document(club: str, url: str, lines: tuple[str, ...]) -> RawDocument:
    content = ("Published: " + PUBLISHED + "\n" + "\n".join(lines) + "\n").encode("utf-8")
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
    club: str, url: str, claims: list[dict[str, Any]], *, text: str | None = None
) -> CodedClub:
    body = {
        "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        "documents": [
            {"url": url, "published_at_utc": PUBLISHED, "published_precision": "instant"}
        ],
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
) -> tuple[Path, str, Path]:
    """Write a decision capture and a news capture, and export them as the weekly run does."""

    root = tmp_path / "snapshots"
    decision = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
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


def _record(tmp_path: Path, root: Path, table: Path, log: Path | None = None) -> dict[str, Any]:
    return report.build_record(
        table_path=table,
        snapshot_root=root,
        registry=_registry(tmp_path),
        log=None if log is None else report.read_log(log),
        repository_commit=COMMIT,
        repository_dirty=False,
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
    record = _record(tmp_path, root, table)

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
        "lost": 7,
        "verdict": "statements_lost",
        "issue_1006": "route_items_3_7_4_10",
    }
    assert record["inputs"]["club_news_capture_id"] == news
    assert record["checks"]["replay_matches_published_table"] is True


def test_hosts_count_registered_hosts_and_leave_the_placeholder_out(tmp_path: Path) -> None:
    root, _news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table)

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
    record = _record(tmp_path, root, table)

    assert record["claims"]["raw"] == 0
    assert record["claims"]["placed"] == 0
    assert record["table"]["players_not_addressed"] == record["table"]["roster_size"]
    assert record["reader"]["source_check"] == "nothing_cited"
    assert record["reader"]["constraining_statements"] == 0
    assert record["loss"] == {
        "lost_before_table": 0,
        "lost_unapplied": 0,
        "lost": 0,
        "verdict": "no_raw_claims",
        "issue_1006": "unanswered",
    }


def test_claims_that_all_reach_their_outcome_read_as_none_lost(tmp_path: Path) -> None:
    lines = ARSENAL_LINES
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
                ],
            ),
        ),
        declared=("Arsenal",),
        covered=("Arsenal",),
    )
    record = _record(tmp_path, root, table)

    assert record["claims"]["joined_to_one_player"] == 2
    assert record["claims"]["placed"] == 2
    assert record["reader"]["constraining_statements"] == 1
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
    record = _record(tmp_path, root, table)

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
    record = _record(tmp_path, root, table)

    assert record["claims"]["raw"] == 3
    assert record["claims"]["reached_join"] == 3
    assert record["claims"]["identical_repeats"] == 1
    assert record["claims"]["conflicting_player_claims"] == 2
    assert record["claims"]["placed"] == 0
    assert record["table"]["players_with_conflicting_claims"] == 1
    assert record["loss"]["lost_before_table"] == 2


@pytest.mark.parametrize(
    ("raw", "unreadable", "lost", "verdict"),
    [
        (0, 0, 0, "no_raw_claims"),
        (0, 1, 0, "statements_lost"),
        (4, 0, 0, "no_statement_lost"),
        (4, 0, 1, "statements_lost"),
        (4, 1, 0, "statements_lost"),
    ],
)
def test_the_reading_is_fixed_by_three_counts(
    raw: int, unreadable: int, lost: int, verdict: str
) -> None:
    assert report.reading(raw=raw, unreadable_responses=unreadable, lost=lost) == verdict


def test_a_replay_that_differs_from_the_published_table_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _news, table = _mixed_week(tmp_path)
    monkeypatch.setattr(report, "_table_bytes", lambda frame: b"not the published bytes")

    with pytest.raises(report.JoinCountError, match="Run this from the commit"):
        _record(tmp_path, root, table)


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
        _record(tmp_path, root, Path(str(result["table_path"])))


def _log(tmp_path: Path, news: str, *, raw: int) -> Path:
    """The receipt as the Friday launcher leaves it: a byte order mark, the offline check
    first, then the acquisition's own lines."""

    path = tmp_path / "friday-2026-27-gw04.club-news.log"
    lines = [
        "Configuration valid: provider 'synthetic', model 'synthetic-stub'.",
        "Registry      4 pages, 4 clubs declared",
        "Read          1 documents",
        f"Raw claims    {raw}; source validation occurs during export",
        "Call budget   3; 2 attempted; no automatic provider retry",
        "Read refusal: Man Utd: https://united.example/news answered 503.",
        "Coding refusal: Everton: the call failed.",
        f"Raw claims: {raw}, as the model stated them. How many apply is not known here.",
        f"Capture       {news}",
    ]
    path.write_bytes(b"\xef\xbb\xbf" + "\r\n".join(lines).encode("utf-8") + b"\r\n")
    return path


def test_the_receipt_is_read_and_held_to_the_capture(tmp_path: Path) -> None:
    root, news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table, _log(tmp_path, news, raw=10))

    assert record["acquisition_log"] == {
        "model_call_budget": 3,
        "model_calls_attempted": 2,
        "raw_claims_printed": 10,
        "read_refusal_lines": 1,
        "coding_refusal_lines": 1,
    }
    assert record["checks"]["log_capture_id_matches"] is True
    assert record["checks"]["log_raw_claims_match"] is True
    assert record["inputs"]["club_news_log_file"] == "friday-2026-27-gw04.club-news.log"


def test_a_receipt_of_another_capture_or_count_refuses(tmp_path: Path) -> None:
    root, news, table = _mixed_week(tmp_path)

    with pytest.raises(report.JoinCountError, match="receipts of different weeks"):
        _record(
            tmp_path, root, table, _log(tmp_path, "club-news-20260912T143000Z-0123456789ab", raw=10)
        )
    (tmp_path / "friday-2026-27-gw04.club-news.log").unlink()
    with pytest.raises(report.JoinCountError, match="printed 9 raw claims"):
        _record(tmp_path, root, table, _log(tmp_path, news, raw=9))


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


def _keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return {str(key) for key in value} | {k for item in value.values() for k in _keys(item)}
    return set()


def test_the_protocol_defines_every_field_the_record_carries(tmp_path: Path) -> None:
    root, news, table = _mixed_week(tmp_path)
    record = _record(tmp_path, root, table, _log(tmp_path, news, raw=10))
    protocol = PROTOCOL.read_text(encoding="utf-8")
    # Data-valued maps carry club names, reasons and scope labels as keys, not fields.
    data_keys = set(record["documents"]["by_club"]) | set(record["claims"]["unresolved_by_reason"])
    data_keys |= set(record["table"]["statements_by_disposition"])
    data_keys |= set(record["reader"]["absence_or_doubt_not_applied_by_scope"])

    undefined = sorted(key for key in _keys(record) - data_keys if f"`{key}`" not in protocol)
    assert undefined == []
    for value in (report.RECORD_VERSION, *report.ISSUE_1006_READING.items()):
        for text in value if isinstance(value, tuple) else (value,):
            assert f"`{text}`" in protocol
