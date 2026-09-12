"""Historical advice is selected and scored from evidence, never solved again."""

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.application import weekly_suggestion_eval as review
from squadopt.application.advice_record import (
    MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
    RECORD_FILE,
    record_member_advice,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.evaluation.models import EvaluationValidationError

SEASON = "2026-27"
DEADLINE = "2026-09-12T10:00:00Z"
CAPTURED = "2026-09-09T09:00:00Z"
PUBLISHED = "2026-09-09T10:00:00Z"
STARTERS = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
BENCH = [2, 12, 6, 7]
POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def recorded(
    *, captured: str = CAPTURED, published: str = PUBLISHED, name: str = "capture-a"
) -> dict[str, Any]:
    return {
        "contract_version": MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
        "season": SEASON,
        "gameweek": 4,
        "entry_id": 101,
        "league_id": 352490,
        "player_id_space": "fpl_element_code",
        "generated_at_utc": published,
        "capture": {"snapshot_id": name, "captured_at_utc": captured},
        "players": {
            str(i): {"name": f"Player {i}", "position": position, "expected_points": 3.5}
            for i, position in enumerate(POSITIONS, start=1)
        },
        "advice": [
            {
                "strategy": "saf-puan",
                "window": 1,
                "rival_entry_id": None,
                "starting_xi": STARTERS,
                "bench": BENCH,
                "captain": 8,
                "vice_captain": 9,
                "scoring_complete": True,
                "chip": None,
                "transfer_hit_points": 4,
                "expected_own_points": 42.0,
                "advice_sha256": "a" * 64,
            }
        ],
    }


def points() -> pd.DataFrame:
    return pd.DataFrame({"player_id": range(1, 16), "total_points": 2.0, "minutes": 90})


def choose(root: Path) -> dict[str, Any] | None:
    return review.select_record(
        root, season=SEASON, gameweek=4, entry_id=101, deadline_utc=DEADLINE
    )


def snapshot(
    root: Path,
    *,
    finished: bool = True,
    checked: bool = True,
    captured: str = "2026-09-15T09:00:00Z",
    actual: bool = True,
    outcomes: bool = True,
    hits: int | None = 8,
) -> CapturedSnapshot:
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": "2026-08-15T10:00:00Z",
                "finished": True,
                "data_checked": True,
            },
            {"id": 4, "deadline_time": DEADLINE, "finished": finished, "data_checked": checked},
        ],
        "elements": [{"id": i + 100, "code": i} for i in range(1, 16)],
    }
    payloads = {"bootstrap-static.json": json.dumps(bootstrap).encode()}
    if outcomes:
        payloads["event-gw04-live.json"] = json.dumps(
            {
                "elements": [
                    {"id": i + 100, "stats": {"total_points": 2, "minutes": 90, "starts": 1}}
                    for i in range(1, 16)
                ]
            }
        ).encode()
    if actual:
        history = {"event": 4, "points": 30, "total_points": 150}
        if hits is not None:
            history["event_transfers_cost"] = hits
        payloads["entry-101-history.json"] = json.dumps({"current": [history]}).encode()
    metadata = write_snapshot(root, source="fpl-live", captured_at_utc=captured, payloads=payloads)
    return read_snapshot(root, metadata.snapshot_id)


def evaluate(root: Path, captures: list[CapturedSnapshot]) -> review.WeekReview:
    return review.evaluate_week(
        root, season=SEASON, gameweek=4, entry_id=101, deadline_utc=DEADLINE, captures=captures
    )


def test_selection_orders_publications_not_captures(tmp_path: Path) -> None:
    later_publication = recorded(published="2026-09-11T11:00:00Z")
    newer_capture = recorded(
        captured="2026-09-10T09:00:00Z", published="2026-09-10T10:00:00Z", name="capture-b"
    )
    record_member_advice(tmp_path, later_publication)
    record_member_advice(tmp_path, newer_capture)
    assert choose(tmp_path) == later_publication


@pytest.mark.parametrize("published", [DEADLINE, "2026-09-13T10:00:00Z"])
def test_post_deadline_publication_is_excluded_even_from_earlier_capture(
    tmp_path: Path,
    published: str,
) -> None:
    early = recorded()
    record_member_advice(tmp_path, early)
    record_member_advice(tmp_path, recorded(name="capture-b", published=published))
    assert choose(tmp_path) == early


@pytest.mark.parametrize(
    "changes",
    [
        {"league_id": 123},
        {"entry_id": True},
        {"player_id_space": "element"},
        {"contract_version": "future"},
        {"generated_at_utc": "2026-09-09T10:00:00"},
        {"generated_at_utc": "2026-09-08T10:00:00Z"},
    ],
)
def test_invalid_record_cannot_produce_a_score(tmp_path: Path, changes: dict[str, Any]) -> None:
    value = recorded()
    # Persist in the requested member's directory, then re-manifest the synthetic record.
    directory = record_member_advice(tmp_path, value)
    value.update(changes)
    from squadopt.live.ledger import write_manifest

    (directory / RECORD_FILE).write_text(json.dumps(value), encoding="utf-8")
    write_manifest(directory, contract_version=MEMBER_ADVICE_RECORD_CONTRACT_VERSION)
    assert evaluate(tmp_path, []).reason == "invalid_record"


def test_ambiguous_publication_refuses_to_pick_a_winner(tmp_path: Path) -> None:
    record_member_advice(tmp_path, recorded())
    record_member_advice(tmp_path, recorded(name="capture-b"))
    assert evaluate(tmp_path, []).reason == "ambiguous_record"


def test_corrupt_newer_record_does_not_fall_back_to_old_advice(tmp_path: Path) -> None:
    record_member_advice(tmp_path, recorded())
    newer = record_member_advice(tmp_path, recorded(name="capture-b"))
    (newer / RECORD_FILE).write_bytes(b"{}")
    assert evaluate(tmp_path, []).reason == "invalid_record"


def test_no_records_and_only_late_record_are_honest(tmp_path: Path) -> None:
    assert choose(tmp_path) is None
    record_member_advice(tmp_path, recorded(published=DEADLINE))
    result = evaluate(tmp_path, [])
    assert result.reason == "no_pre_deadline_record" and result.suggested is None


@pytest.mark.parametrize(
    ("chip", "hits", "gross"),
    [
        (None, 4, 24),
        ("bboost", 4, 32),
        ("3xc", 4, 26),
        ("wildcard", 0, 24),
        ("freehit", 0, 24),
    ],
)
def test_known_chips_and_transfer_charges_preserve_arithmetic(
    chip: str | None,
    hits: int,
    gross: int,
) -> None:
    record = recorded()
    advice = record["advice"][0]
    advice.update(chip=chip, transfer_hit_points=hits)
    before = copy.deepcopy(record)
    score, players = review.score_recorded_advice(record, advice, points())
    assert score.gross_points == gross
    assert score.net_points == gross - hits
    assert sum(player.counted_points for player in players) == gross
    assert all(player.forecast_error == -1.5 for player in players)
    assert record == before


def test_autosubs_respect_formation_and_captain_falls_back() -> None:
    record = recorded()
    outcomes = points()
    # One missing defender in a three-defender formation: skip the first bench midfielder.
    # Missing captain then admits that midfielder, and the vice receives the bonus.
    outcomes.loc[outcomes.player_id.isin([1, 3, 8]), ["minutes", "total_points"]] = 0
    outcomes.loc[outcomes.player_id == 6, "total_points"] = 7
    outcomes.loc[outcomes.player_id == 12, "total_points"] = 5
    score, players = review.score_recorded_advice(record, record["advice"][0], outcomes)
    by_id = {player.player_id: player for player in players}
    assert by_id[2].multiplier == by_id[6].multiplier == by_id[12].multiplier == 1
    assert by_id[9].multiplier == 2 and by_id[8].multiplier == 0
    assert score.gross_points == 32 and score.autosub_points == 14
    assert score.net_points == 28


def test_negative_captain_points_are_not_clamped() -> None:
    record = recorded()
    outcomes = points()
    outcomes.loc[outcomes.player_id == 8, "total_points"] = -2
    score, players = review.score_recorded_advice(record, record["advice"][0], outcomes)
    assert score.gross_points == 16 and score.captain_bonus_points == -2
    assert next(player for player in players if player.captain).counted_points == -4


@pytest.mark.parametrize(
    "changes",
    [
        {"scoring_complete": False},
        {"chip": "unknown"},
        {"transfer_hit_points": -4},
        {"transfer_hit_points": None},
        {"chip": "wildcard", "transfer_hit_points": 4},
        {"vice_captain": 2},
        {"starting_xi": [1] * 11},
    ],
)
def test_incomplete_or_invalid_advice_is_not_scored(changes: dict[str, Any]) -> None:
    record = recorded()
    record["advice"][0].update(changes)
    with pytest.raises((DataError, EvaluationValidationError)):
        review.score_recorded_advice(record, record["advice"][0], points())


@pytest.mark.parametrize(("finished", "checked"), [(False, False), (True, False)])
def test_unsettled_results_never_show_a_comparison(
    tmp_path: Path,
    finished: bool,
    checked: bool,
) -> None:
    record_member_advice(tmp_path / "records", recorded())
    capture = snapshot(tmp_path / "snapshots", finished=finished, checked=checked)
    result = evaluate(tmp_path / "records", [capture])
    assert result.status == "unsettled" and result.net_difference is None


def test_settled_score_uses_stable_codes_and_actual_gross_minus_hits(tmp_path: Path) -> None:
    record_member_advice(tmp_path / "records", recorded())
    capture = snapshot(tmp_path / "snapshots")
    result = evaluate(tmp_path / "records", [capture])
    assert result.status == "available" and result.reason is None
    assert result.suggested == review.SuggestedScore(24, 4, 20, 2, 0, None)
    assert result.actual == review.ActualScore(30, 8, 22)
    assert result.net_difference == -2
    assert result.advice_generated_at_utc == PUBLISHED
    assert result.outcome_snapshot_id == capture.metadata.snapshot_id
    assert [player.player_id for player in result.players] == STARTERS + BENCH


@pytest.mark.parametrize("options", [{"actual": False}, {"hits": None}])
def test_missing_actual_or_unknown_hit_does_not_become_zero(
    tmp_path: Path,
    options: dict[str, Any],
) -> None:
    record_member_advice(tmp_path / "records", recorded())
    result = evaluate(tmp_path / "records", [snapshot(tmp_path / "snapshots", **options)])
    assert result.status == "available" and result.suggested is not None
    assert result.actual is None and result.net_difference is None
    assert result.actual_reason == "actual_score_missing"


def test_missing_live_payload_is_not_an_unsettled_week(tmp_path: Path) -> None:
    record_member_advice(tmp_path / "records", recorded())
    result = evaluate(tmp_path / "records", [snapshot(tmp_path / "snapshots", outcomes=False)])
    assert result.status == "unavailable" and result.reason == "missing_outcomes"


def test_publication_is_bounded_by_capture_and_never_mutates_inputs(tmp_path: Path) -> None:
    records, snapshots = tmp_path / "records", tmp_path / "snapshots"
    record_member_advice(records, recorded())
    anchor = snapshot(snapshots, captured="2026-09-13T09:00:00Z", finished=False, checked=False)
    snapshot(snapshots)  # Future settled data must not enter this publication.

    def digests() -> dict[str, str]:
        return {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for root in (records, snapshots)
            for path in root.rglob("*")
            if path.is_file()
        }

    before = digests()
    written = review.publish_suggestion_histories(
        record_root=records,
        snapshot_root=snapshots,
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=[101, 202],
        out_dir=tmp_path / "out",
    )
    member = json.loads(written[0].read_text())
    assert member["payload"]["weeks"][0]["status"] == "unsettled"
    assert len(member["payload"]["weeks"]) == 1  # Do not fabricate weeks 1..3.
    assert json.loads(written[1].read_text())["payload"]["weeks"] == []
    assert before == digests()


def test_other_leagues_are_rejected(tmp_path: Path) -> None:
    capture = snapshot(tmp_path / "snapshots")
    with pytest.raises(review.SuggestionEvaluationError, match="Only league"):
        review.publish_suggestion_histories(
            record_root=tmp_path / "records",
            snapshot_root=tmp_path / "snapshots",
            as_of_snapshot=capture,
            season=SEASON,
            league_id=123,
            entry_ids=[101],
            out_dir=tmp_path / "out",
        )


def test_later_other_strategy_does_not_displace_the_pure_points_record(tmp_path: Path) -> None:
    early = recorded()
    record_member_advice(tmp_path, early)
    other = recorded(name="capture-b", published="2026-09-10T10:00:00Z")
    other["advice"][0]["strategy"] = "risk"
    record_member_advice(tmp_path, other)
    assert choose(tmp_path) == early


def test_python_result_matches_the_browser_contract_fixture(tmp_path: Path) -> None:
    record_member_advice(tmp_path / "records", recorded())
    result = evaluate(tmp_path / "records", [snapshot(tmp_path / "snapshots")])
    fixture = Path(__file__).parents[2] / "web/src/fixtures/weeklySuggestionHistory.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    assert document["contract_version"] == review.CONTRACT_VERSION
    assert document["payload"]["weeks"] == json.loads(json.dumps([asdict(result)]))


def test_as_of_replay_excludes_a_later_publication_before_the_deadline(tmp_path: Path) -> None:
    earlier = recorded()
    later = recorded(
        captured="2026-09-10T09:00:00Z", published="2026-09-11T11:00:00Z", name="capture-b"
    )
    record_member_advice(tmp_path, earlier)
    record_member_advice(tmp_path, later)
    assert choose(tmp_path) == later
    selected = review.select_record(
        tmp_path,
        season=SEASON,
        gameweek=4,
        entry_id=101,
        deadline_utc=DEADLINE,
        as_of_utc=earlier["generated_at_utc"],
    )
    assert selected == earlier
