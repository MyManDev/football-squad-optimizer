"""Structured run logging for the live path: one JSON object per event, per run."""

import json
import logging
from pathlib import Path

import pytest

from squadopt.live.runlog import JsonLineFormatter, configure_run_logging, new_run_id


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
