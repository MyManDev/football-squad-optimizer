"""The league-site builder's two pure decisions: whose score, and from which week.

Both are tested over hand-built payload bytes rather than a capture on disk, because
``data/snapshots/`` is gitignored — a test that needed a real capture would pass on the
machine that produced one and fail everywhere else.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.build_league_site import (
    last_scored_gameweek,
    member_points,
    resolve_live_snapshot_id,
)

from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot


def _history(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps({"chips": [], "current": rows}).encode("utf-8")


def _events(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": rows}).encode("utf-8")


def test_each_member_is_scored_from_their_own_history() -> None:
    payloads = {
        "entry-11-history.json": _history(
            [
                {"event": 1, "points": 73, "total_points": 73},
                {"event": 2, "points": 51, "total_points": 124},
            ]
        ),
        "entry-22-history.json": _history([{"event": 1, "points": 46, "total_points": 46}]),
    }

    scores = member_points(payloads, [11, 22], gameweek=1)

    assert {entry: week.points for entry, week in scores.items()} == {11: 73, 22: 46}
    assert scores[11].total_points == 73


def test_a_member_the_capture_does_not_cover_is_omitted_rather_than_zeroed() -> None:
    """Omission becomes a null on the page; a zero would claim they scored nothing."""

    payloads = {"entry-11-history.json": _history([{"event": 1, "points": 73, "total_points": 73}])}

    scores = member_points(payloads, [11, 22], gameweek=1)

    assert 22 not in scores
    assert set(scores) == {11}


def test_a_member_who_has_not_played_the_asked_week_is_omitted() -> None:
    payloads = {"entry-11-history.json": _history([{"event": 1, "points": 73, "total_points": 73}])}

    assert member_points(payloads, [11], gameweek=2) == {}


@pytest.mark.parametrize(
    ("events", "before", "expected"),
    [
        ([{"id": 1, "finished": True, "data_checked": True}], 2, 1),
        # Finished but unchecked: bonus has not landed, so the week is not publishable.
        ([{"id": 1, "finished": True, "data_checked": False}], 2, None),
        # Building for the week that just scored: its own points are not "last week's".
        ([{"id": 1, "finished": True, "data_checked": True}], 1, None),
        (
            [
                {"id": 1, "finished": True, "data_checked": True},
                {"id": 2, "finished": True, "data_checked": True},
                {"id": 3, "finished": False, "data_checked": False},
            ],
            3,
            2,
        ),
    ],
)
def test_the_published_week_is_the_last_final_one_before_the_build(
    events: list[dict[str, Any]], before: int, expected: int | None
) -> None:
    assert last_scored_gameweek(_events(events), before=before) == expected


def test_the_pool_mapper_runs_render_member_only() -> None:
    """A pool worker rebuilds the batch's context itself, so the mapper must refuse any
    function but ``render_member`` rather than silently running its own."""

    import functools
    from concurrent.futures import ThreadPoolExecutor

    from scripts.build_league_site import pool_mapper

    from squadopt.application.league_views import render_member

    with ThreadPoolExecutor(max_workers=1) as executor:
        mapper = pool_mapper(executor)
        with pytest.raises(ValueError, match="render_member only"):
            mapper(len, [])  # type: ignore[arg-type]
        bound = functools.partial(
            render_member, provider=None, inputs=None, projection=None, rules=None
        )
        assert list(mapper(bound, [])) == []  # type: ignore[arg-type]


def test_the_league_tree_is_built_from_the_latest_live_capture(tmp_path: Path) -> None:
    """A cohort capture must not win the selection on the strength of its name.

    Top-100 and elite-picks captures share the snapshot root and their identifiers sort
    after every ``fpl-live`` one, so "the last directory" is not "the latest capture".
    Only a live capture carries the entry histories and standings the tree is built from.
    """

    live = write_snapshot(
        tmp_path,
        source="fpl-live",
        captured_at_utc="2026-08-21T15:00:00Z",
        payloads={"bootstrap-static.json": b"{}"},
    ).snapshot_id
    cohort = write_snapshot(
        tmp_path,
        source="fpl-top100",
        captured_at_utc="2026-01-01T12:00:00Z",
        payloads={"league-352490-standings-page-1.json": b"{}"},
    ).snapshot_id

    assert resolve_live_snapshot_id(tmp_path, None) == live
    # Naming a capture is the operator's own choice and is checked against them all.
    assert resolve_live_snapshot_id(tmp_path, cohort) == cohort


def test_a_root_holding_no_live_capture_names_what_is_missing(tmp_path: Path) -> None:
    write_snapshot(
        tmp_path,
        source="fpl-elite-picks",
        captured_at_utc="2026-08-21T15:00:00Z",
        payloads={"league-352490-standings-page-1.json": b"{}"},
    )

    with pytest.raises(DataError, match="No fpl-live"):
        resolve_live_snapshot_id(tmp_path, None)
