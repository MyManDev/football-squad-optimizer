"""Structured run logging for the live path: one JSON object per event, per run."""

import json
import logging
from pathlib import Path

import pytest
from scripts.build_site import DEFAULT_LOG_ROOT as build_site_log_root
from scripts.build_site import REPOSITORY_ROOT as build_site_root

from squadopt.application.build import _recent_events
from squadopt.live.runlog import (
    LOG_ROOT_NAME,
    JsonLineFormatter,
    component_log_directory,
    configure_run_logging,
    new_run_id,
)
from squadopt.platform.cli import build_parser as cli_parser
from squadopt.platform.weekly_operations import WeeklyPaths


def test_a_run_writes_json_lines_with_its_run_id_and_fields(tmp_path: Path) -> None:
    log = configure_run_logging("season_tick", log_root=tmp_path, console=False)
    log.event("tick.start", now_utc="2026-08-21T15:30:00Z", dry_run=False)
    log.event("tick.plan", actions=[{"kind": "decide", "gameweek": 1}], path=tmp_path)
    logging.getLogger("squadopt.live.ledger").info(
        "ledger.decision.recorded", extra={"fields": {"season": "2026-27", "gameweek": 1}}
    )
    try:
        raise ValueError("boom")
    except ValueError:
        log.failure("tick.failed", performed=0)

    assert log.log_path is not None and log.log_path.parent.name == "season_tick"
    records = [json.loads(line) for line in log.log_path.read_text(encoding="utf-8").splitlines()]
    assert [r["message"] for r in records] == [
        "tick.start",
        "tick.plan",
        "ledger.decision.recorded",
        "tick.failed",
    ]
    assert {r["run_id"] for r in records} == {log.run_id}
    assert all(r["component"] == "season_tick" for r in records)
    assert records[0]["fields"] == {"now_utc": "2026-08-21T15:30:00Z", "dry_run": False}
    assert records[1]["fields"]["actions"] == [{"kind": "decide", "gameweek": 1}]
    assert records[1]["fields"]["path"] == tmp_path.as_posix()
    assert records[2]["logger"] == "squadopt.live.ledger"
    assert records[3]["level"] == "ERROR" and "ValueError: boom" in records[3]["exception"]


def test_configuring_twice_replaces_the_sinks_and_runs_are_distinguishable(
    tmp_path: Path,
) -> None:
    first = configure_run_logging("season_tick", log_root=tmp_path, console=False)
    first.event("one")
    second = configure_run_logging("season_tick", log_root=tmp_path, console=False)
    second.event("two")
    assert first.run_id != second.run_id
    assert first.log_path == second.log_path  # same day, same file, appended
    handlers = [
        h
        for h in logging.getLogger("squadopt").handlers
        if getattr(h, "_squadopt_run_handler", False)
    ]
    assert len(handlers) == 1  # the earlier file handler was replaced, not stacked
    records = [
        json.loads(line) for line in second.log_path.read_text(encoding="utf-8").splitlines()
    ]  # type: ignore[union-attr]
    assert [(r["message"], r["run_id"]) for r in records] == [
        ("one", first.run_id),
        ("two", second.run_id),
    ]


def test_no_log_root_keeps_logging_in_memory_and_bad_component_is_refused() -> None:
    log = configure_run_logging("gameweek_ops", log_root=None, console=False)
    assert log.log_path is None
    log.event("nothing.written")
    with pytest.raises(ValueError, match="component"):
        configure_run_logging(" ", log_root=None)
    assert new_run_id() != new_run_id()
    formatter = JsonLineFormatter("run", "c")
    record = logging.LogRecord("squadopt.x", logging.INFO, __file__, 1, "m", None, None)
    assert json.loads(formatter.format(record))["message"] == "m"


def test_a_log_root_is_qualified_with_its_component_exactly_once(tmp_path: Path) -> None:
    """The producer hands over an unqualified root; only the join helper adds the component.

    The status page read ``data/logs/season_tick/season_tick`` and reported no run log at
    all, because ``WeeklyPaths`` handed over a root that already named the component and
    the reader qualified it again. Writer and reader now share one join, so the round trip
    below fails the moment a caller pre-qualifies its root.
    """

    root = WeeklyPaths.under(tmp_path).log_root
    assert root == tmp_path / LOG_ROOT_NAME
    assert root.name != "season_tick", "a root a caller holds is above every component"

    log = configure_run_logging("season_tick", log_root=root, console=False)
    log.event("tick.week.done")
    assert log.log_path is not None
    assert log.log_path.parent == component_log_directory(root, "season_tick")

    # What the writer wrote is what the reader reads, from the same root.
    assert _recent_events(root, "season_tick", 10)[0].message == "tick.week.done"
    # Qualifying that same root a second time is the defect, and finds nothing.
    assert _recent_events(component_log_directory(root, "season_tick"), "season_tick", 10) == ()
    with pytest.raises(ValueError, match="component"):
        component_log_directory(root, " ")


def test_every_holder_of_a_log_root_agrees_on_the_same_unqualified_root(tmp_path: Path) -> None:
    """The weekly runner, the command line and the site builder must not drift apart."""

    arguments = cli_parser().parse_args(
        ["season", "tick", "--workspace-root", str(tmp_path), "--dry-run"]
    )
    assert Path(arguments.log_root) == LOG_ROOT_NAME
    assert WeeklyPaths.under(tmp_path).log_root == tmp_path / LOG_ROOT_NAME
    assert build_site_log_root == build_site_root / LOG_ROOT_NAME


def test_a_machine_with_no_run_log_reads_as_no_runs_rather_than_an_error(tmp_path: Path) -> None:
    """Absent is not zero: nothing recorded is an empty list, not a failure."""

    assert _recent_events(None, "season_tick", 10) == ()
    assert _recent_events(tmp_path / "never-run", "season_tick", 10) == ()
    (tmp_path / "empty" / "season_tick").mkdir(parents=True)
    assert _recent_events(tmp_path / "empty", "season_tick", 10) == ()
