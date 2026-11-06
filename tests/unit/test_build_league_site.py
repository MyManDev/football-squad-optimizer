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


def test_a_refused_advice_record_names_the_escape_a_deadline_needs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The record refuses a week it already holds, and the refusal has to be actionable.

    The published files are already on disk when this fires: only the record refused. An
    operator reading it minutes before a deadline must be told what to do next, or they
    will improvise — and every improvisation here (deleting the record, pointing the build
    somewhere else) destroys the evidence the record exists to be.
    """

    import sys

    import scripts.build_league_site as build_league_site

    from squadopt.application.advice_record import AdviceRecordConflictError

    def refuse(root: Path, requested: str | None) -> str:
        raise AdviceRecordConflictError("advice/101/saf-puan/1.json: published_sha256 moved")

    monkeypatch.setattr(build_league_site, "resolve_live_snapshot_id", refuse)
    monkeypatch.setattr(sys, "argv", ["build_league_site", "--league", "352490"])

    assert build_league_site.main() == 1

    printed = capsys.readouterr().err
    assert "published_sha256 moved" in printed
    assert "--no-advice-record" in printed
    assert "scripts.run_week" in printed


def _by_hand_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *extra: str
) -> tuple[Any, list[dict[str, Any]]]:
    """``build_league_site.main`` up to the solve, with the capture and the build faked.

    Returns the module and the list each ``league_mapper`` call appends its keyword
    arguments to; the mapper hands back a build whose one member had two three-week
    searches, one answered by native HiGHS and one fallen back.
    """

    import sys
    from contextlib import contextmanager
    from types import SimpleNamespace

    import scripts.build_league_site as build_league_site

    from squadopt.planning.native_highs import (
        CP_SAT_BACKEND,
        NATIVE_BACKEND,
        NativeWindowOutcome,
    )

    prepared = SimpleNamespace(
        request=SimpleNamespace(snapshot_id="named-capture"),
        registrations=(101,),
        standings=(101,),
        season="2026-27",
        inputs=SimpleNamespace(deadline=SimpleNamespace(gameweek=8)),
        scored_gameweek=None,
        scored_members=0,
    )
    member = SimpleNamespace(
        entry_id=101,
        rendered=True,
        reason="",
        native_windows=(
            NativeWindowOutcome(3, NATIVE_BACKEND, "1.15.1", ""),
            NativeWindowOutcome(3, CP_SAT_BACKEND, "1.15.1", "The native solve did not prove"),
        ),
    )
    built = SimpleNamespace(
        report=SimpleNamespace(rendered_count=1, members=(member,), removed=(), files=()),
        top100_note="",
        purchase_prices_note="",
        legacy_tree=None,
    )
    mapped: list[dict[str, Any]] = []

    @contextmanager
    def mapper(request: Any, workers: int, **keywords: Any) -> Any:
        mapped.append(keywords)
        yield map

    monkeypatch.setattr(build_league_site, "resolve_live_snapshot_id", lambda *_: "named-capture")
    monkeypatch.setattr(build_league_site, "prepare_league_publication", lambda _: prepared)
    monkeypatch.setattr(build_league_site, "leagues_beside", lambda *_: ())
    monkeypatch.setattr(build_league_site, "league_mapper", mapper)
    monkeypatch.setattr(build_league_site, "publish_prepared_league", lambda *_, **__: built)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_league_site",
            "--league",
            "352490",
            "--snapshot-root",
            str(tmp_path),
            "--out",
            str(tmp_path / "out"),
            "--no-advice-record",
            *extra,
        ],
    )
    return build_league_site, mapped


def test_a_by_hand_build_refuses_a_native_child_without_the_pinned_highs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every window would otherwise fall back to CP-SAT in silence and publish plans the
    weekly run does not publish from the same capture."""

    build_league_site, mapped = _by_hand_build(monkeypatch, tmp_path)
    monkeypatch.setattr(build_league_site, "native_window_version", lambda: "1.14.0")

    assert build_league_site.main() == 1

    printed = capsys.readouterr().err
    assert "loads HiGHS 1.14.0" in printed
    assert "highspy==1.15.1" in printed
    assert "--cp-sat-windows" in printed
    assert mapped == [], "nothing may be solved after the refusal"

    def missing() -> str:
        raise RuntimeError("No module named 'highspy'")

    monkeypatch.setattr(build_league_site, "native_window_version", missing)
    assert build_league_site.main() == 1
    assert "cannot start in this environment: No module named 'highspy'" in (
        capsys.readouterr().err
    )
    assert mapped == []


def test_a_by_hand_build_prints_which_backend_answered_each_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    build_league_site, mapped = _by_hand_build(monkeypatch, tmp_path)
    monkeypatch.setattr(build_league_site, "native_window_version", lambda: "1.15.1")

    assert build_league_site.main() == 0

    assert mapped == [{"native_windows": True}]
    printed = capsys.readouterr().out
    assert "window solver: native HiGHS 1.15.1" in printed
    assert (
        "  windows       101  3 weeks: 2 searches, 1 native HiGHS 1.15.1, 1 CP-SAT fallback"
    ) in printed
    assert "fallback x1: The native solve did not prove" in printed


def test_a_cp_sat_only_build_binds_no_native_solver_and_starts_no_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The rehearsal's comparison build: the same capture with every window on CP-SAT."""

    build_league_site, mapped = _by_hand_build(monkeypatch, tmp_path, "--cp-sat-windows")

    def probe() -> str:
        raise AssertionError("a CP-SAT-only build must not start the native child")

    monkeypatch.setattr(build_league_site, "native_window_version", probe)

    assert build_league_site.main() == 0

    assert mapped == [{"native_windows": False}]
    assert "window solver: CP-SAT alone for every search" in capsys.readouterr().out
