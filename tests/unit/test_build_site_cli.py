"""CLI test for scripts.build_site: the shell over squadopt.application.build_site."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import scripts.build_site as cli
from tests.unit.test_season_ledger import _capture, _panel

from squadopt.application import UI_VIEW_CONTRACT_VERSION, site_publication
from squadopt.data.snapshots import write_snapshot
from squadopt.live import build_recommendation, project, read_inputs, record_decision

SEASON = "2026-27"


def test_the_shell_writes_the_tree_from_a_ledger_and_the_schema_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _capture(tmp_path / "snapshots")
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    record_decision(tmp_path / "ledger", recommendation, projection, report_text="report")

    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "schema.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "build_site",
            "--season",
            SEASON,
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--snapshot-root",
            str(tmp_path / "snapshots"),
            "--handoff-root",
            str(tmp_path / "handoffs"),
            "--log-root",
            str(tmp_path / "logs"),
            "--out",
            str(tmp_path / "site"),
            "--now",
            "2026-08-21T15:30:00Z",
        ],
    )
    assert cli.main() == 0
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text("utf-8"))
    assert index["contract_version"] == UI_VIEW_CONTRACT_VERSION
    assert index["payload"]["gameweeks"] == {SEASON: [1]}
    assert (tmp_path / "site" / "data" / SEASON / "status.json").is_file()

    monkeypatch.setattr(sys, "argv", ["build_site", "--schema-only"])
    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "only.json")
    assert cli.main() == 0


def _cohort_capture(root: Path, *, source: str, captured_at: str) -> None:
    """A capture from one of the cohort collectors, carrying none of the site's payloads."""

    write_snapshot(
        root,
        source=source,
        captured_at_utc=captured_at,
        payloads={"league-352490-standings-page-1.json": b"{}"},
    )


def _argv(tmp_path: Path) -> list[str]:
    # --no-status skips the season tick, keeping these tests about the selection this shell
    # makes. The tick makes its own, in `squadopt.application.season._read_state`; that one
    # names its source too now, and `tests/unit/test_season_tick.py` pins it.
    return [
        "build_site",
        "--no-status",
        "--season",
        SEASON,
        "--ledger-root",
        str(tmp_path / "ledger"),
        "--snapshot-root",
        str(tmp_path / "snapshots"),
        "--handoff-root",
        str(tmp_path / "handoffs"),
        "--log-root",
        str(tmp_path / "logs"),
        "--out",
        str(tmp_path / "site"),
        "--now",
        "2026-08-21T15:30:00Z",
    ]


def _ledger_from(snapshot: Any, tmp_path: Path) -> None:
    inputs = read_inputs(snapshot, season=SEASON)
    projection = project(inputs, _panel(players=(1001, 1004, 1012)))
    recommendation = build_recommendation(inputs, projection)
    record_decision(tmp_path / "ledger", recommendation, projection, report_text="report")


def test_the_shell_selects_the_live_capture_from_a_root_the_cohorts_share(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cohort capture must not win a selection on the strength of its name.

    A snapshot identifier is ``{source}-{stamp}-{digest}``, so a listing sorted lexically
    orders by source first and only then by time. `fpl-top200` sorts after `fpl-live`
    whatever the timestamps say, and four collectors default to this one root — so taking
    the last entry of an unfiltered listing published the league and the provisional score
    from a cohort capture that carries neither's payloads, however old it was.
    """

    root = tmp_path / "snapshots"
    live = _capture(root, captured_at="2026-08-21T15:00:00Z")
    _cohort_capture(root, source="fpl-top200", captured_at="2026-01-01T12:00:00Z")
    _ledger_from(live, tmp_path)

    read: list[str] = []
    real = site_publication.read_snapshot
    monkeypatch.setattr(
        site_publication,
        "read_snapshot",
        lambda snapshot_root, identifier: (
            read.append(identifier),
            real(snapshot_root, identifier),
        )[1],
    )
    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "schema.json")
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))

    assert cli.main() == 0
    assert read == [live.metadata.snapshot_id], read
    assert read[0].startswith("fpl-live-")


def test_the_shell_publishes_unavailable_rather_than_a_capture_of_another_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No live capture is not a reason to reach for a different one.

    The provisional score reads one capture and never backfills from another, so a root
    holding only cohort captures has to produce an unavailable view rather than a view
    built from payloads nobody asked for.
    """

    root = tmp_path / "snapshots"
    live = _capture(tmp_path / "elsewhere", captured_at="2026-08-21T15:00:00Z")
    _cohort_capture(root, source="fpl-top100", captured_at="2026-08-21T15:00:00Z")
    _ledger_from(live, tmp_path)

    read: list[str] = []
    monkeypatch.setattr(
        site_publication, "read_snapshot", lambda snapshot_root, identifier: read.append(identifier)
    )
    monkeypatch.setattr(cli, "write_ui_view_schema", lambda: tmp_path / "schema.json")
    monkeypatch.setattr(sys, "argv", _argv(tmp_path))

    assert cli.main() == 0
    assert read == [], read
    live_view = json.loads(
        (tmp_path / "site" / "data" / SEASON / "gw01" / "live.json").read_text("utf-8")
    )
    assert live_view["payload"]["status"] == "unavailable"
    assert live_view["payload"]["reason"] == "missing_capture"
