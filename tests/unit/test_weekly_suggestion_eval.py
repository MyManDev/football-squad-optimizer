"""Historical advice is selected and scored from evidence, never solved again."""

import copy
import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from statistics import NormalDist
from typing import Any, cast

import jsonschema
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
from squadopt.evaluation.live_series import (
    LiveSeriesPower,
    LiveSeriesReading,
    NotYetEstimable,
    read_live_series,
)
from squadopt.evaluation.models import EvaluationValidationError

SEASON = "2026-27"
DEADLINE = "2026-09-12T10:00:00Z"
CAPTURED = "2026-09-09T09:00:00Z"
PUBLISHED = "2026-09-09T10:00:00Z"
# Deadlines for the multi-week fixtures; gameweek 4 keeps the single-week fixture's clock.
DEADLINES = {3: "2026-09-05T10:00:00Z", 4: DEADLINE, 5: "2026-09-19T10:00:00Z"}
STARTERS = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
BENCH = [2, 12, 6, 7]
POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def recorded(
    *,
    captured: str = CAPTURED,
    published: str = PUBLISHED,
    name: str = "capture-a",
    gameweek: int = 4,
    entry_id: int = 101,
    digest: str = "a" * 64,
) -> dict[str, Any]:
    return {
        "contract_version": MEMBER_ADVICE_RECORD_CONTRACT_VERSION,
        "season": SEASON,
        "gameweek": gameweek,
        "entry_id": entry_id,
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
                "advice_sha256": digest,
            }
        ],
    }


def test_recorded_switches_do_not_become_additional_baselines() -> None:
    record = recorded()
    baseline = record["advice"][0]
    baseline["published_path"] = "advice/101/saf-puan/1.json"
    record["advice"] = [
        {**baseline, "published_path": f"advice/101/saf-puan/1/{switch}.json"}
        for switch in ("hoca-sozu", "top100-20", "top100-20-hoca-sozu", "chip-bboost")
    ]
    with pytest.raises(review.SuggestionEvaluationError, match="missing_advice"):
        review._advice(record)
    record["advice"].append(baseline)
    assert review._advice(record) is baseline
    record["advice"].append(copy.deepcopy(baseline))
    with pytest.raises(review.SuggestionEvaluationError, match="ambiguous_advice"):
        review._advice(record)


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


def shown_by_tree(root: Path, tree: dict[tuple[int, int], str]) -> dict[str, Any] | None:
    return review.select_record(
        root, season=SEASON, gameweek=4, entry_id=101, deadline_utc=DEADLINE, published=tree
    )


def test_a_record_from_a_run_that_never_published_is_not_what_the_member_was_told(
    tmp_path: Path,
) -> None:
    # The gameweek 6 shape: one run recorded capture-b and never published it, and the site
    # carried capture-a. Both are before the deadline and the unpublished one is later, so
    # the latest stamp alone would take it.
    records = tmp_path / "records"
    shown = recorded()
    unpublished = recorded(
        captured="2026-09-10T09:00:00Z",
        published="2026-09-10T10:00:00Z",
        name="capture-b",
        digest="b" * 64,
    )
    record_member_advice(records, shown)
    record_member_advice(records, unpublished)
    assert choose(records) == unpublished
    tree = {(101, 4): "capture-a"}
    assert shown_by_tree(records, tree) == shown
    week = review.evaluate_week(
        records,
        season=SEASON,
        gameweek=4,
        entry_id=101,
        deadline_utc=DEADLINE,
        captures=[snapshot(tmp_path / "snapshots")],
        published=tree,
    )
    assert week.status == "available"
    assert (week.advice_snapshot_id, week.advice_sha256) == ("capture-a", "a" * 64)
    # Had the site carried the later capture instead, that record would be the one.
    assert shown_by_tree(records, {(101, 4): "capture-b"}) == unpublished


@pytest.mark.parametrize(
    "tree",
    [{}, {(101, 4): "capture-elsewhere"}, {(202, 4): "capture-a"}, {(101, 3): "capture-a"}],
)
def test_a_week_whose_records_the_published_tree_does_not_name_is_refused_not_scored(
    tmp_path: Path, tree: dict[tuple[int, int], str]
) -> None:
    record_member_advice(tmp_path, recorded())
    with pytest.raises(review.SuggestionEvaluationError, match="not_published"):
        shown_by_tree(tmp_path, tree)
    result = review.evaluate_week(
        tmp_path,
        season=SEASON,
        gameweek=4,
        entry_id=101,
        deadline_utc=DEADLINE,
        captures=[],
        published=tree,
    )
    assert (result.status, result.reason) == ("unavailable", "not_published")
    assert result.advice_snapshot_id is None and result.suggested is None


def test_a_published_capture_whose_record_came_too_late_does_not_promote_another(
    tmp_path: Path,
) -> None:
    record_member_advice(tmp_path, recorded())
    record_member_advice(
        tmp_path, recorded(captured="2026-09-10T09:00:00Z", published=DEADLINE, name="capture-b")
    )
    with pytest.raises(review.SuggestionEvaluationError, match="not_published"):
        shown_by_tree(tmp_path, {(101, 4): "capture-b"})
    late_only = tmp_path / "late-only"
    record_member_advice(late_only, recorded(published=DEADLINE))
    assert shown_by_tree(late_only, {(101, 4): "capture-a"}) is None


def put(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_the_published_tree_names_each_member_week_and_the_page_outranks_the_history(
    tmp_path: Path,
) -> None:
    league = tmp_path / "league"
    put(
        league / "history/101.json",
        {
            "payload": {
                "entry_id": 101,
                "weeks": [
                    {"gameweek": 4, "advice_snapshot_id": "tuesday"},
                    {"gameweek": 3, "advice_snapshot_id": "gw3"},
                    {"gameweek": 2, "advice_snapshot_id": None},
                ],
            }
        },
    )
    # A later publish of the same week: the page names Friday's capture.
    put(league / "entries/101.json", {"payload": {"gameweek": 4, "source_snapshot_id": "friday"}})
    # A history filed under one member that names another is not evidence for either.
    put(
        league / "history/202.json",
        {"payload": {"entry_id": 303, "weeks": [{"gameweek": 3, "advice_snapshot_id": "x"}]}},
    )
    put(league / "entries/202.json", {"payload": {"gameweek": 4, "source_snapshot_id": None}})
    put(league / "entries/index.json", {"payload": {"gameweek": 4, "source_snapshot_id": "x"}})
    (league / "entries/303.json").write_text("{not json", encoding="utf-8")
    assert review.published_page_captures(league) == {(101, 4): "friday"}
    assert review.published_advice_captures(league) == {(101, 4): "friday", (101, 3): "gw3"}
    assert review.published_advice_captures(tmp_path / "no-tree") == {}


def test_the_history_shows_the_published_record_and_no_record_the_site_never_carried(
    tmp_path: Path,
) -> None:
    records, league = tmp_path / "records", tmp_path / "out"
    record_member_advice(records, recorded())
    record_member_advice(
        records,
        recorded(
            captured="2026-09-10T09:00:00Z",
            published="2026-09-10T10:00:00Z",
            name="capture-b",
            digest="b" * 64,
        ),
    )
    record_member_advice(records, recorded(entry_id=202, name="capture-c"))
    # The site carried capture-a for 101, and for 202 a capture this archive holds no record of.
    for entry_id, capture in ((101, "capture-a"), (202, "capture-d")):
        page = {"payload": {"gameweek": 4, "source_snapshot_id": capture}}
        put(league / "entries" / f"{entry_id}.json", page)
    written = review.publish_suggestion_histories(
        record_root=records,
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=snapshot(tmp_path / "snapshots"),
        season=SEASON,
        league_id=352490,
        entry_ids=[101, 202],
        out_dir=league,
        published=review.published_advice_captures(league),
    )
    weeks = {
        path.stem: json.loads(path.read_text(encoding="utf-8"))["payload"]["weeks"]
        for path in written
        if path.parent.name == "history"
    }
    told = weeks["101"][0]
    assert (told["status"], told["advice_snapshot_id"], told["advice_sha256"]) == (
        "available",
        "capture-a",
        "a" * 64,
    )
    never = weeks["202"][0]
    assert (never["status"], never["reason"], never["advice_snapshot_id"]) == (
        "unavailable",
        "not_published",
        None,
    )


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
        published={(101, 4): "capture-a"},
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
            published={},
        )


def test_later_other_strategy_does_not_displace_the_pure_points_record(tmp_path: Path) -> None:
    early = recorded()
    record_member_advice(tmp_path, early)
    other = recorded(name="capture-b", published="2026-09-10T10:00:00Z")
    other["advice"][0]["strategy"] = "risk"
    record_member_advice(tmp_path, other)
    assert choose(tmp_path) == early


def test_old_and_new_told_blocks_are_read_as_the_same_pure_points_advice(
    tmp_path: Path,
) -> None:
    """Which document ``told`` names never decides what the settled review reads.

    An older record named the rule's pick as told (``source`` ``suggested_strategy``) and
    carried no ``suggested_strategy`` key; a newer one names the page's pure-points plan
    (``source`` ``page_default``) and keeps the pick in that key. The rule's pick here is
    ``ortak-koru``, whose recorded plan pays a larger hit under another digest, so a reader
    that followed ``told`` would score a different week. Selection, the settled score and the
    history rows all read the pure-points document by its address, so both shapes read
    exactly as a record without the block does, and neither record is rewritten.
    """

    pick = {
        "strategy": "ortak-koru",
        "rule_id": "gap_and_weeks_strategy_rule_v1",
        "band": "ahead",
        "rival_entry_id": 202,
        "points_ahead_of_rival": 300,
        "scored_gameweek": 3,
        "gameweeks_remaining": 35,
        "band_edge_points": 125.4,
    }
    shapes: dict[str, dict[str, Any]] = {
        "none": {},
        "old": {
            "told": {
                "strategy": "ortak-koru",
                "window": 1,
                "rival_entry_id": 202,
                "published_path": "advice/101/ortak-koru/1.json",
                "source": "suggested_strategy",
            }
        },
        "new": {
            "told": {
                "strategy": "saf-puan",
                "window": 1,
                "rival_entry_id": None,
                "published_path": "advice/101/saf-puan/1.json",
                "source": "page_default",
            },
            "suggested_strategy": {**pick, "published_path": "advice/101/ortak-koru/1.json"},
        },
    }
    capture = snapshot(tmp_path / "snapshots")
    reviews: dict[str, review.WeekReview] = {}
    rows: dict[str, dict[str, Any]] = {}
    for shape, blocks in shapes.items():
        record = recorded()
        baseline = record["advice"][0]
        baseline.update(published_path="advice/101/saf-puan/1.json", expected_points_cost=0)
        record["advice"].append(
            {
                **baseline,
                "strategy": "ortak-koru",
                "rival_entry_id": 202,
                "published_path": "advice/101/ortak-koru/1.json",
                "transfer_hit_points": 8,
                "advice_sha256": "b" * 64,
            }
        )
        record.update(blocks)
        root = tmp_path / shape
        record_member_advice(root, record)
        chosen = choose(root)
        assert chosen == record  # read back as written: an older told is never rewritten
        assert review._advice(chosen) == baseline
        reviews[shape] = evaluate(root, [capture])
        rows[shape] = review._history_week(reviews[shape], chosen)
    assert reviews["old"] == reviews["new"] == reviews["none"]
    assert reviews["new"].advice_sha256 == "a" * 64
    assert reviews["new"].suggested == review.SuggestedScore(24, 4, 20, 2, 0, None)
    assert rows["old"] == rows["new"] == rows["none"]


def publish_for(
    root: Path,
    *,
    gameweek: int,
    entry_id: int,
    digest: str = "a" * 64,
    name: str = "capture-a",
    published_hour: str = "07",
) -> None:
    """Record one member's pre-deadline advice for one gameweek."""
    day = DEADLINES[gameweek][:10]
    record_member_advice(
        root,
        recorded(
            gameweek=gameweek,
            entry_id=entry_id,
            captured=f"{day}T06:00:00Z",
            published=f"{day}T{published_hour}:00:00Z",
            name=name,
            digest=digest,
        ),
    )


def shown_everywhere(
    entry_ids: Sequence[int], gameweeks: Sequence[int], name: str = "capture-a"
) -> dict[tuple[int, int], str]:
    """A published tree that carried capture ``name`` for every one of these member-weeks."""
    return {(entry_id, week): name for entry_id in entry_ids for week in gameweeks}


def capture_with(
    root: Path,
    *,
    events: dict[int, bool],
    actuals: dict[int, dict[int, int]] | None = None,
    captured: str = "2026-09-22T09:00:00Z",
) -> CapturedSnapshot:
    """A capture whose named gameweeks are settled or not, with the actual scores it knows."""
    bootstrap = {
        "events": [
            {
                "id": 1,
                "deadline_time": "2026-08-15T10:00:00Z",
                "finished": True,
                "data_checked": True,
            },
            *[
                {
                    "id": week,
                    "deadline_time": DEADLINES[week],
                    "finished": settled,
                    "data_checked": settled,
                }
                for week, settled in events.items()
            ],
        ],
        "elements": [{"id": i + 100, "code": i} for i in range(1, 16)],
    }
    payloads = {"bootstrap-static.json": json.dumps(bootstrap).encode()}
    for week, settled in events.items():
        if not settled:
            continue
        payloads[f"event-gw{week:02d}-live.json"] = json.dumps(
            {
                "elements": [
                    {"id": i + 100, "stats": {"total_points": 2, "minutes": 90, "starts": 1}}
                    for i in range(1, 16)
                ]
            }
        ).encode()
    for entry_id, weeks in (actuals or {}).items():
        payloads[f"entry-{entry_id}-history.json"] = json.dumps(
            {
                "current": [
                    {
                        "event": week,
                        "points": scored,
                        "total_points": scored,
                        "event_transfers_cost": 0,
                    }
                    for week, scored in weeks.items()
                ]
            }
        ).encode()
    metadata = write_snapshot(root, source="fpl-live", captured_at_utc=captured, payloads=payloads)
    return read_snapshot(root, metadata.snapshot_id)


def reviewed(
    tmp_path: Path, *, entry_ids: list[int], anchor: CapturedSnapshot
) -> dict[int, tuple[review.WeekReview, ...]]:
    return review.review_member_weeks(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=entry_ids,
    )


def test_settled_member_weeks_become_one_comparison_each(tmp_path: Path) -> None:
    for entry_id in (101, 202):
        for week in (3, 4):
            publish_for(tmp_path / "records", gameweek=week, entry_id=entry_id)
    anchor = capture_with(
        tmp_path / "snapshots",
        events={3: True, 4: True},
        actuals={101: {3: 18, 4: 25}, 202: {3: 20, 4: 22}},
    )
    reviews = reviewed(tmp_path, entry_ids=[101, 202], anchor=anchor)
    comparisons = review.settled_member_week_comparisons(reviews, season=SEASON)
    # The recorded advice nets 20 in every week here, so the difference is 20 minus the score.
    assert [(row.entry_id, row.gameweek, row.difference) for row in comparisons] == [
        (101, 4, -5.0),
        (101, 3, 2.0),
        (202, 4, -2.0),
        (202, 3, 0.0),
    ]
    assert {row.season for row in comparisons} == {SEASON}
    reading = read_live_series(comparisons)
    assert isinstance(reading, LiveSeriesPower)
    assert (reading.member_weeks, reading.weeks) == (4, 2)
    assert reading.between_week_degrees_of_freedom == 1


def test_a_week_without_a_settled_comparison_contributes_nothing(tmp_path: Path) -> None:
    for week in (3, 4, 5):
        publish_for(tmp_path / "records", gameweek=week, entry_id=101)
    # Gameweek 3 settles but its actual score is absent, 4 has not settled, and 5 has no
    # published deadline. None of the three is a difference of zero.
    anchor = capture_with(tmp_path / "snapshots", events={3: True, 4: False})
    reviews = reviewed(tmp_path, entry_ids=[101], anchor=anchor)
    assert [(week.gameweek, week.status, week.reason) for week in reviews[101]] == [
        (5, "unavailable", "missing_deadline"),
        (4, "unsettled", "not_settled"),
        (3, "available", None),
    ]
    assert reviews[101][2].actual_reason == "actual_score_missing"
    assert review.settled_member_week_comparisons(reviews, season=SEASON) == ()


def test_the_record_as_it_stands_today_refuses_rather_than_reporting_zero(
    tmp_path: Path,
) -> None:
    # Fifteen members, one published gameweek, nothing settled: the archive on 13 September.
    entry_ids = list(range(101, 116))
    for entry_id in entry_ids:
        publish_for(tmp_path / "records", gameweek=4, entry_id=entry_id)
    anchor = capture_with(tmp_path / "snapshots", events={4: False})
    reading = review.live_series_reading(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=entry_ids,
    )
    assert isinstance(reading, NotYetEstimable)
    assert (reading.reason, reading.member_weeks, reading.weeks) == (
        "no_settled_member_weeks",
        0,
        0,
    )
    assert not hasattr(reading, "within_week_correlation")
    reviews = reviewed(tmp_path, entry_ids=entry_ids, anchor=anchor)
    assert len(reviews) == 15
    assert {(week.status, week.reason) for weeks in reviews.values() for week in weeks} == {
        ("unsettled", "not_settled")
    }


def test_the_published_document_is_the_reviews_it_serializes(tmp_path: Path) -> None:
    for week in (3, 4):
        publish_for(tmp_path / "records", gameweek=week, entry_id=101)
    publish_for(tmp_path / "records", gameweek=4, entry_id=202)
    anchor = capture_with(
        tmp_path / "snapshots",
        events={3: True, 4: True},
        actuals={101: {3: 18, 4: 25}, 202: {4: 22}},
    )
    reviews = reviewed(tmp_path, entry_ids=[101, 202], anchor=anchor)
    written = review.publish_suggestion_histories(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=[101, 202],
        out_dir=tmp_path / "out",
        published=shown_everywhere((101, 202), (3, 4)),
    )
    assert [path.name for path in written] == ["101.json", "202.json", "series-horizon.json"]
    assert [week.gameweek for week in reviews[101]] == [4, 3]  # Newest week first.
    for entry_id, path in zip((101, 202), written[:2], strict=True):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["contract_version"] == review.CONTRACT_VERSION
        assert document["payload"]["entry_id"] == entry_id
        assert document["payload"]["weeks"] == json.loads(
            json.dumps([asdict(week) for week in reviews[entry_id]])
        )


def test_python_result_matches_the_browser_contract_fixture(tmp_path: Path) -> None:
    record_member_advice(tmp_path / "records", recorded())
    result = evaluate(tmp_path / "records", [snapshot(tmp_path / "snapshots")])
    fixture = Path(__file__).parents[2] / "web/src/fixtures/weeklySuggestionHistory.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    assert document["contract_version"] == review.CONTRACT_VERSION
    assert document["payload"]["weeks"] == json.loads(json.dumps([asdict(result)]))


HORIZON_SCHEMA = Path(__file__).parents[2] / "docs/contracts/member_week_horizon_v1.schema.json"
# The contract's required field list, written out so the producer's document is checked
# against it on every run. The schema file itself is the consumer lane's and lands with it,
# so ``check_contract`` below adds the committed schema's judgement when it is in the tree
# and these assertions carry the check until then.
HORIZON_FIELDS = (
    "contract_version",
    "season",
    "league_id",
    "scoring_basis",
    "population",
    "measurement_artifact",
    "within_week_correlation",
    "required_week_clusters",
    "member_week_keys",
)


def check_contract(document: dict[str, Any]) -> None:
    """Assert every constraint member_week_horizon_v1 places on a published document."""
    assert sorted(document) == sorted(HORIZON_FIELDS)
    assert document["contract_version"] == "member_week_horizon_v1"
    assert re.fullmatch(r"[0-9]{4}-[0-9]{2}", document["season"])
    assert isinstance(document["league_id"], int) and document["league_id"] >= 1
    assert document["scoring_basis"] == "official_autosub_captain_v2"
    assert document["population"] == "recorded_member_suggestions_vs_actual"
    assert re.fullmatch(r"docs/[a-z0-9_-]+\.json", document["measurement_artifact"])
    correlation = document["within_week_correlation"]
    assert isinstance(correlation, float) and -1.0 <= correlation <= 1.0
    required = document["required_week_clusters"]
    assert isinstance(required, int) and not isinstance(required, bool) and required >= 2
    keys = document["member_week_keys"]
    assert isinstance(keys, list) and len(keys) >= 2
    assert len(set(keys)) == len(keys)
    assert all(isinstance(key, str) and key for key in keys)
    if HORIZON_SCHEMA.is_file():  # Both halves are in one tree; let the committed schema rule.
        jsonschema.validate(document, json.loads(HORIZON_SCHEMA.read_text(encoding="utf-8")))


def reader_keys(histories: Sequence[Path]) -> list[str]:
    """Rebuild the reader's record keys from the published bytes, the way it spells them.

    ``web/src/features/league/history/liveSeries.ts`` keeps an available week that has a
    suggestion, an actual score and a difference, and names it entry, gameweek, advice digest,
    outcome capture. This walks the published documents rather than the reviews behind them,
    so the comparison covers what a browser would actually receive.
    """
    keys = []
    for path in histories:
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        for week in payload["weeks"]:
            if (
                week["status"] != "available"
                or week["suggested"] is None
                or week["actual"] is None
                or week["net_difference"] is None
            ):
                continue
            keys.append(
                f"{payload['entry_id']}:{week['gameweek']}:"
                f"{week['advice_sha256']}:{week['outcome_snapshot_id']}"
            )
    return sorted(keys)


def settled_two_weeks(tmp_path: Path) -> CapturedSnapshot:
    """Two members, two settled weeks each: the smallest record that carries a horizon."""
    for entry_id in (101, 202):
        for week in (3, 4):
            publish_for(tmp_path / "records", gameweek=week, entry_id=entry_id)
    return capture_with(
        tmp_path / "snapshots",
        events={3: True, 4: True},
        actuals={101: {3: 18, 4: 25}, 202: {3: 20, 4: 22}},
    )


def horizon_document(reading: object, **stated: object) -> dict[str, Any] | None:
    """Build a handoff for this league and season, stating the basis and population."""
    arguments: dict[str, Any] = {
        "season": SEASON,
        "league_id": 352490,
        "scoring_basis": review.RECORDED_ADVICE_SCORING_BASIS,
        "population": review.SETTLED_COMPARISON_POPULATION,
        **stated,
    }
    return review.series_horizon_document(cast(LiveSeriesReading, reading), **arguments)


def published(
    tmp_path: Path, anchor: CapturedSnapshot, shown: dict[tuple[int, int], str] | None = None
) -> tuple[Path, ...]:
    return review.publish_suggestion_histories(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=anchor,
        season=SEASON,
        league_id=352490,
        entry_ids=[101, 202],
        out_dir=tmp_path / "out",
        published=shown_everywhere((101, 202), (3, 4)) if shown is None else shown,
    )


def test_the_horizon_names_the_keys_the_page_builds_from_the_same_publication(
    tmp_path: Path,
) -> None:
    anchor = settled_two_weeks(tmp_path)
    written = published(tmp_path, anchor)
    horizon = tmp_path / "out" / review.SERIES_HORIZON_FILE
    assert written[-1] == horizon
    document = json.loads(horizon.read_text(encoding="utf-8"))
    check_contract(document)
    # The safety property: a horizon measured against one set of member-weeks is unusable
    # against any other, and the reader compares whole sorted lists for equality.
    assert sorted(document["member_week_keys"]) == reader_keys(written[:2])
    assert len(document["member_week_keys"]) == 4
    assert document["season"] == SEASON and document["league_id"] == 352490
    assert document["measurement_artifact"] == "docs/measurement_instrument.json"


def test_the_published_horizon_is_the_reading_of_the_reviews_it_was_published_with(
    tmp_path: Path,
) -> None:
    anchor = settled_two_weeks(tmp_path)
    written = published(tmp_path, anchor)
    reviews = reviewed(tmp_path, entry_ids=[101, 202], anchor=anchor)
    reading = read_live_series(review.settled_member_week_comparisons(reviews, season=SEASON))
    assert isinstance(reading, LiveSeriesPower)
    document = json.loads(written[-1].read_text(encoding="utf-8"))
    horizon = reading.weeks_to_detect(review.BACKTEST_PRECISION_FLOOR_POINTS)
    assert document["required_week_clusters"] == horizon.total_weeks
    assert list(reading.member_week_keys) == document["member_week_keys"]
    # Required although the page renders none of it: the correlation is the whole distance
    # between this target and the one an independence assumption would have produced, and a
    # producer that drops it leaves the page at "unknown" with nothing on screen to say why.
    assert document["within_week_correlation"] == reading.within_week_correlation
    assert document["within_week_correlation"] > 0.0
    # The target rests on this record's own dependence, not on an independence assumption.
    independent = math.ceil(
        (reading.member_week_standard_deviation / horizon.effect) ** 2
        * (NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.8)) ** 2
        / reading.average_members_per_week
    )
    assert document["required_week_clusters"] > independent


def test_an_unsupportable_record_publishes_no_horizon_and_clears_a_stale_one(
    tmp_path: Path,
) -> None:
    # Fifteen members, one published week, nothing settled: the archive as it stands.
    entry_ids = list(range(101, 116))
    for entry_id in entry_ids:
        publish_for(tmp_path / "records", gameweek=4, entry_id=entry_id)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    stale = out_dir / review.SERIES_HORIZON_FILE
    stale.write_text('{"contract_version": "member_week_horizon_v1"}\n', encoding="utf-8")
    written = review.publish_suggestion_histories(
        record_root=tmp_path / "records",
        snapshot_root=tmp_path / "snapshots",
        as_of_snapshot=capture_with(tmp_path / "snapshots", events={4: False}),
        season=SEASON,
        league_id=352490,
        entry_ids=entry_ids,
        out_dir=out_dir,
        published=shown_everywhere(entry_ids, (4,)),
    )
    # Publishing nothing is the true statement, and the page already renders "not yet" for an
    # absent document. A target measured on a record that no longer stands does not stay put.
    assert not stale.exists()
    assert [path.parent.name for path in written] == ["history"] * 15


def test_the_published_target_is_floored_at_the_instruments_own_two_week_minimum(
    tmp_path: Path,
) -> None:
    anchor = settled_two_weeks(tmp_path)
    reviews = reviewed(tmp_path, entry_ids=[101, 202], anchor=anchor)
    reading = read_live_series(review.settled_member_week_comparisons(reviews, season=SEASON))
    assert isinstance(reading, LiveSeriesPower)
    # An effect this large is already detectable, so the arithmetic asks for a single week.
    assert reading.weeks_to_detect(1000.0).total_weeks == 1
    document = horizon_document(reading, effect=1000.0)
    assert document is not None
    # A clustered reading does not exist below two weeks, so one is not a count anyone could
    # measure at, and the reader refuses anything under two.
    assert document["required_week_clusters"] == 2
    check_contract(document)


def test_a_later_advice_for_one_week_moves_that_key_and_no_other(tmp_path: Path) -> None:
    anchor = settled_two_weeks(tmp_path)
    before = json.loads(published(tmp_path, anchor)[-1].read_text(encoding="utf-8"))
    # The same member and the same week, published again before the deadline under a second
    # capture with a different advice digest. Entry and gameweek alone could not tell the two
    # apart, and the horizon would then describe bytes nobody is reading.
    publish_for(
        tmp_path / "records",
        gameweek=4,
        entry_id=101,
        digest="b" * 64,
        name="capture-b",
        published_hour="08",
    )
    shown = {**shown_everywhere((101, 202), (3, 4)), (101, 4): "capture-b"}
    after = json.loads(published(tmp_path, anchor, shown)[-1].read_text(encoding="utf-8"))
    moved = set(before["member_week_keys"]) ^ set(after["member_week_keys"])
    assert {tuple(key.split(":", 2)[:2]) for key in moved} == {("101", "4")}
    assert sorted(after["member_week_keys"]) == reader_keys(
        [tmp_path / "out" / "history" / f"{entry_id}.json" for entry_id in (101, 202)]
    )
    assert sorted(before["member_week_keys"]) != sorted(after["member_week_keys"])


def test_a_refusal_builds_no_document_at_all() -> None:
    reading = read_live_series(())
    assert isinstance(reading, NotYetEstimable)
    assert horizon_document(reading) is None


@pytest.mark.parametrize(
    "stated",
    [
        {"scoring_basis": "named_eleven_no_autosubs"},
        {"scoring_basis": "realized_squad_points_v1"},
        {"population": "all_league_members"},
        {"population": "recorded_member_suggestions_vs_paper_ledger"},
        {"measurement_artifact": "docs/Measurement_Instrument.json"},
        {"measurement_artifact": "measurement_instrument.json"},
    ],
)
def test_a_series_on_another_basis_or_population_is_refused_not_relabelled(
    tmp_path: Path,
    stated: dict[str, str],
) -> None:
    anchor = settled_two_weeks(tmp_path)
    reviews = reviewed(tmp_path, entry_ids=[101, 202], anchor=anchor)
    reading = read_live_series(review.settled_member_week_comparisons(reviews, season=SEASON))
    # The contract fixes the basis and the population, and a fixed value in a schema is a
    # promise about what produced the numbers. Stamping one over another series is the silent
    # mislabelling this refusal exists to prevent.
    with pytest.raises(review.SuggestionEvaluationError):
        horizon_document(reading, **stated)


def test_the_basis_and_population_are_read_from_where_they_were_produced() -> None:
    # Not the contract constants repeated at the call site: one names the scorer that ran and
    # the other the filter that chose the rows, and the document builder compares the two.
    assert review.RECORDED_ADVICE_SCORING_BASIS == review.CONTRACT_SCORING_BASIS
    assert review.SETTLED_COMPARISON_POPULATION == review.CONTRACT_POPULATION


def test_a_record_that_froze_no_starting_vice_never_reaches_this_series() -> None:
    # The named-eleven basis exists for a decision with no bench order and no vice-captain.
    # This scorer refuses such a record rather than scoring it and letting the publication
    # label the number official_autosub_captain_v2.
    record = recorded()
    advice = dict(record["advice"][0])
    advice["vice_captain"] = advice["bench"][0]
    with pytest.raises(review.SuggestionEvaluationError, match="vice-captain must start"):
        review.score_recorded_advice(record, advice, points())


def test_a_settled_week_without_its_provenance_is_refused_rather_than_named() -> None:
    settled = review.WeekReview(
        gameweek=4,
        status="available",
        reason=None,
        advice_sha256="a" * 64,
        outcome_snapshot_id="fpl-live-20260922T090000Z-abcdef123456",
        suggested=review.SuggestedScore(20.0, 0.0, 20.0, 0.0, 0.0, None),
        actual=review.ActualScore(18.0, 0.0, 18.0),
        net_difference=2.0,
    )
    assert len(review.settled_member_week_comparisons({101: (settled,)}, season=SEASON)) == 1
    # dataclasses.replace, not copy.replace: the latter arrived in 3.13 and the merge gate
    # also runs 3.11, where it does not exist.
    for broken in (
        dataclasses.replace(settled, outcome_snapshot_id=None),
        dataclasses.replace(settled, advice_sha256=None),
        dataclasses.replace(settled, advice_sha256="not-a-digest"),
    ):
        with pytest.raises(review.SuggestionEvaluationError):
            review.settled_member_week_comparisons({101: (broken,)}, season=SEASON)
