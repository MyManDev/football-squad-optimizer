"""How the operator shells pick "the latest capture" out of a root four collectors share.

A snapshot identifier is ``{source}-{stamp}-{digest}``, so a lexical listing orders by
collector name before it orders by capture time: ``fpl-top100`` sorts after ``fpl-live``
however old it is. The weekly loop captures the Top-100 cohort and the elite picks into
the same root as the live capture, so "the last identifier" is reliably *not* a live one
and every shell that recommends, projects or replays from it has to say which source it
means.

The cohort capture in a test that pins a "last entry" selection has to be one that really
does sort last: ``fpl-top100`` and ``fpl-top200`` sort after ``fpl-live``, but
``fpl-elite-picks`` sorts before it and would let an unfiltered listing pass by accident.

Each capture here is written to ``tmp_path`` rather than read from ``data/snapshots/``,
which is gitignored: a test that needed a real capture would pass only on the machine
that took one.
"""

import sys
from pathlib import Path

import pytest
import scripts.build_projection_horizon as horizon_cli
import scripts.recommend_current_squad as recommend_cli

from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot

LIVE_AT = "2026-08-21T15:00:00Z"
COHORT_AT = "2026-01-01T12:00:00Z"


def _live(root: Path, captured_at: str = LIVE_AT) -> str:
    return write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=captured_at,
        payloads={"bootstrap-static.json": b"{}", "fixtures.json": b"[]"},
    ).snapshot_id


def _cohort(root: Path, *, source: str = "fpl-top100", captured_at: str = COHORT_AT) -> str:
    """A cohort capture: the Overall standings pages, none of the game-state payloads."""

    return write_snapshot(
        root,
        source=source,
        captured_at_utc=captured_at,
        payloads={"league-352490-standings-page-1.json": b"{}"},
    ).snapshot_id


# --- scripts.recommend_current_squad ------------------------------------------------


def test_the_recommender_takes_the_latest_live_capture_not_the_last_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prices and availability come from a live capture; a cohort holds neither."""

    live = _live(tmp_path)
    _cohort(tmp_path)
    monkeypatch.setattr(recommend_cli, "SNAPSHOT_ROOT", tmp_path)

    assert recommend_cli.resolve_snapshot_id(None) == live


def test_the_recommender_still_replays_any_capture_named_outright(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replay is the operator's own choice of capture, so it is checked against them all.

    Filtering the automatic pick must not narrow what may be named: the membership check
    and the "Held:" hint stay about everything on disk.
    """

    _live(tmp_path)
    cohort = _cohort(tmp_path)
    monkeypatch.setattr(recommend_cli, "SNAPSHOT_ROOT", tmp_path)

    assert recommend_cli.resolve_snapshot_id(cohort) == cohort
    with pytest.raises(DataError, match="No snapshot"):
        recommend_cli.resolve_snapshot_id("fpl-live-20260101T000000Z-000000000000")


def test_a_root_of_cohort_captures_alone_is_no_capture_to_recommend_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent a live capture the answer is "capture one", never another collector's."""

    _cohort(tmp_path)
    monkeypatch.setattr(recommend_cli, "SNAPSHOT_ROOT", tmp_path)

    with pytest.raises(DataError, match="No fpl-live snapshots"):
        recommend_cli.resolve_snapshot_id(None)


# --- scripts.build_projection_horizon -----------------------------------------------


def _horizon_argv(root: Path) -> list[str]:
    return ["build_projection_horizon", "--snapshot-root", str(root)]


def test_the_horizon_projects_from_the_latest_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A projection of the Overall standings pages is not a projection of anything."""

    live = _live(tmp_path)
    _cohort(tmp_path, source="fpl-top100")

    read: list[str] = []

    def _record(snapshot_root: Path, identifier: str) -> None:
        read.append(identifier)
        raise DataError("read no further; this test is about the selection")

    monkeypatch.setattr(horizon_cli, "read_snapshot", _record)
    monkeypatch.setattr(sys, "argv", _horizon_argv(tmp_path))

    assert horizon_cli.main() == 1
    assert read == [live], read


def test_the_horizon_replays_the_capture_it_is_given_even_from_a_cohort_only_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming a capture skips the selection, so it does not need a live one to exist."""

    cohort = _cohort(tmp_path)

    read: list[str] = []

    def _record(snapshot_root: Path, identifier: str) -> None:
        read.append(identifier)
        raise DataError("read no further; this test is about the selection")

    monkeypatch.setattr(horizon_cli, "read_snapshot", _record)
    monkeypatch.setattr(sys, "argv", [*_horizon_argv(tmp_path), "--snapshot-id", cohort])

    assert horizon_cli.main() == 1
    assert read == [cohort], read


def test_the_horizon_reports_a_root_holding_no_live_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _cohort(tmp_path)
    monkeypatch.setattr(sys, "argv", _horizon_argv(tmp_path))

    assert horizon_cli.main() == 1
