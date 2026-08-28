"""The league-site builder's two pure decisions: whose score, and from which week.

Both are tested over hand-built payload bytes rather than a capture on disk, because
``data/snapshots/`` is gitignored — a test that needed a real capture would pass on the
machine that produced one and fail everywhere else.
"""

import json
from typing import Any

import pytest
from scripts.build_league_site import last_scored_gameweek, member_points


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
