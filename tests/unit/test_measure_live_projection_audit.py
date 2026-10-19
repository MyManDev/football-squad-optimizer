"""Which handoff the live audit pools, on synthetic captures, handoffs and advice records.

The arithmetic is replaced by markers so that each test reads only the choice: every handoff
carries one distinct number, and the pool reports which numbers it stacked.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import measure_live_projection_audit as runner

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.data.sources import BOOTSTRAP_PAYLOAD
from squadopt.data.sources.fpl_live import live_payload
from squadopt.live.recommendation import InSeasonProjection, write_projection_handoff

SEASON = "2026-27"
WEEKS = range(4, 11)


def _deadline(week: int) -> str:
    return f"2026-09-{week + 8:02d}T12:00:00Z"


def _identifier(stamp: str) -> str:
    return "fpl-live-" + stamp.replace("-", "").replace(":", "") + "-" + "a" * 12


def _capture(stamp: str, settled_through: int = 0) -> CapturedSnapshot:
    events = [
        {
            "id": week,
            "deadline_time": _deadline(week),
            "finished": week <= settled_through,
            "data_checked": week <= settled_through,
        }
        for week in WEEKS
    ]
    payloads = {BOOTSTRAP_PAYLOAD: json.dumps({"events": events}).encode()}
    for week in range(WEEKS.start, settled_through + 1):
        payloads[live_payload(week)] = b"{}"
    identifier = _identifier(stamp)
    return CapturedSnapshot(
        SnapshotMetadata(identifier, "fpl-live", stamp, "snapshot_v1", {}, "b" * 64), payloads
    )


def _pre_deadline(week: int) -> CapturedSnapshot:
    return _capture(f"2026-09-{week + 8:02d}T09:00:00Z")


class Disk:
    """A data root holding the stores the runner reads, all synthetic."""

    def __init__(self, root: Path, settled_through: int) -> None:
        self.root = root
        self.captures = [_pre_deadline(week) for week in WEEKS]
        self.settled_through = settled_through
        self.outcome_shift = 0.0

    def settle(self) -> CapturedSnapshot:
        return _capture("2026-09-30T23:00:00Z", self.settled_through)

    def handoff(self, week: int, name: str, marker: float) -> str:
        capture = _pre_deadline(week).metadata.snapshot_id
        projection = InSeasonProjection(
            season=SEASON,
            gameweek=week,
            source_snapshot_id=capture,
            model_name="synthetic",
            model_version=name,
            feature_contract_version="synthetic",
            expected_points={1: marker},
        )
        directory = self.root / "handoffs" / "by-capture" / capture
        directory.mkdir(parents=True, exist_ok=True)
        write_projection_handoff(directory / f"{name}.json", projection)
        return projection.fingerprint

    def advice(
        self,
        week: int,
        fingerprint: str | None,
        *,
        published: str,
        entry: int = 101,
        capture: CapturedSnapshot | None = None,
    ) -> None:
        source = capture or _pre_deadline(week)
        identifier = source.metadata.snapshot_id
        directory = (
            self.root / "advice_records" / SEASON / f"gw{week:02d}" / f"entry-{entry}" / identifier
        )
        directory.mkdir(parents=True, exist_ok=True)
        document = {
            "contract_version": "member_advice_record_v2",
            "season": SEASON,
            "gameweek": week,
            "entry_id": entry,
            "capture": {
                "snapshot_id": identifier,
                "captured_at_utc": source.metadata.captured_at_utc,
            },
            "generated_at_utc": published,
            "provenance": {"projection_handoff_fingerprint": fingerprint},
        }
        (directory / "advice.json").write_text(json.dumps(document), encoding="utf-8")

    def ledger(self, week: int, fingerprint: str, mode: str) -> None:
        directory = self.root / "ledger" / SEASON / f"gw{week:02d}"
        directory.mkdir(parents=True, exist_ok=True)
        document = {"metadata": {"mode": mode, "projection_handoff_fingerprint": fingerprint}}
        (directory / "decision.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def disk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Disk]:
    store = Disk(tmp_path / "data", settled_through=10)

    def captures() -> dict[str, CapturedSnapshot]:
        every = [*store.captures, store.settle()]
        return {capture.metadata.snapshot_id: capture for capture in every}

    monkeypatch.setattr(runner, "list_snapshot_ids", lambda *a, **k: sorted(captures()))
    monkeypatch.setattr(runner, "read_snapshot", lambda root, i: captures()[i])
    monkeypatch.setattr(runner, "infer_season", lambda capture: SEASON)
    monkeypatch.setattr(runner, "player_snapshot", lambda bootstrap: pd.DataFrame())
    monkeypatch.setattr(runner, "_multipliers", lambda bootstrap: {})
    monkeypatch.setattr(runner, "game_forecast", lambda bootstrap: {})
    monkeypatch.setattr(runner, "_prior_minutes_per_week", lambda bootstrap: None)
    monkeypatch.setattr(
        runner,
        "live_event_outcomes",
        lambda *a, **k: pd.DataFrame({"shift": [store.outcome_shift]}),
    )

    def frame(players: Any, outcomes: pd.DataFrame, **kwargs: Any) -> pd.DataFrame:
        marker = kwargs["expected_points"][1] + float(outcomes["shift"].iloc[0])
        return pd.DataFrame({"marker": [marker]})

    def summary(table: pd.DataFrame) -> dict[str, object]:
        return {"forecasts": {}, "marker": float(table["marker"].iloc[0])}

    def stacked(frames: dict[int, pd.DataFrame]) -> dict[str, object]:
        if not frames:
            return {"gameweeks": []}
        markers = {str(week): float(table["marker"].iloc[0]) for week, table in frames.items()}
        return {
            "gameweeks": sorted(frames),
            "rests_on_gameweeks": len(frames),
            "forecasts": {},
            "markers": markers,
        }

    monkeypatch.setattr(runner, "audit_frame", frame)
    monkeypatch.setattr(runner, "summarise_gameweek", summary)
    monkeypatch.setattr(runner, "pool", stacked)
    yield store


def _measure(root: Path, **options: Any) -> dict[str, Any]:
    record: dict[str, Any] = runner.measure(root, **options)
    return record


def _labels(record: dict[str, Any], week: int) -> dict[str, str]:
    return {
        projection["model_version"]: projection["label"]
        for projection in record["gameweeks"][str(week)]["projections"]
    }


def _before(week: int, hour: int = 10) -> str:
    return f"2026-09-{week + 8:02d}T{hour:02d}:00:00Z"


def _gw4_like(disk: Disk) -> tuple[str, str]:
    """GW4: an elite handoff the advice read, and a control the ledger holds as a replay.

    The control is named so that it sorts last by file name, where the old rule took it.
    """

    elite = disk.handoff(4, "a-elite", 4.1)
    control = disk.handoff(4, "b-control", 4.2)
    disk.ledger(4, control, "replay")
    disk.advice(4, elite, published=_before(4))
    return elite, control


def test_the_pool_takes_the_handoff_the_published_advice_read(disk: Disk) -> None:
    elite, control = _gw4_like(disk)
    live = disk.handoff(5, "live", 5.1)
    disk.ledger(5, live, "live")
    disk.advice(5, live, published=_before(5))

    record = _measure(disk.root, through_gameweek=5)

    assert record["pooled_handoffs"] == {"4": elite, "5": live}
    assert record["pooled"]["markers"] == {"4": 4.1, "5": 5.1}
    assert _labels(record, 4) == {"a-elite": "pooled", "b-control": "replay"}
    held = [p for p in record["gameweeks"]["4"]["projections"] if p["in_ledger"]]
    assert [(p["handoff_fingerprint"], p["ledger_mode"]) for p in held] == [(control, "replay")]
    assert record["gameweeks"]["4"]["capture_source"] == "published_advice"
    assert record["pooled"]["primary_projection_rule"] == runner.POOLING_RULE


def test_the_last_publish_before_the_deadline_is_the_one_pooled(disk: Disk) -> None:
    early = disk.handoff(4, "a-early", 4.1)
    late = disk.handoff(4, "b-late", 4.2)
    disk.advice(4, early, published=_before(4, 9), entry=101)
    disk.advice(4, late, published=_before(4, 11), entry=102)

    record = _measure(disk.root, through_gameweek=4)

    assert record["pooled_handoffs"] == {"4": late}
    assert _labels(record, 4) == {"a-early": "beside", "b-late": "pooled"}


def test_a_handoff_only_advice_after_the_deadline_names_is_a_replay(disk: Disk) -> None:
    live = disk.handoff(5, "a-live", 5.1)
    rerun = disk.handoff(5, "b-rerun", 5.2)
    disk.advice(5, live, published=_before(5), entry=101)
    disk.advice(5, rerun, published="2026-09-13T13:00:00Z", entry=102)

    record = _measure(disk.root, through_gameweek=5)

    assert _labels(record, 5) == {"a-live": "pooled", "b-rerun": "replay"}
    assert record["pooled"]["markers"] == {"5": 5.1}


def test_advice_published_only_after_the_deadline_pools_nothing(disk: Disk) -> None:
    disk.handoff(5, "a-live", 5.1)
    rerun = disk.handoff(5, "b-rerun", 5.2)
    disk.advice(5, rerun, published="2026-09-13T13:00:00Z")

    record = _measure(disk.root, through_gameweek=5)

    assert record["pooled"] == {
        "gameweeks": [],
        "comparison_may_be_stated": False,
        "primary_projection_rule": runner.POOLING_RULE,
    }
    assert "only after it" in record["not_pooled"]["5"]
    assert _labels(record, 5) == {"a-live": "beside", "b-rerun": "replay"}


def test_a_week_whose_advice_names_no_pre_deadline_handoff_is_listed_and_not_pooled(
    disk: Disk,
) -> None:
    """GW6: no record names a handoff, so the last file by name does not stand in for one."""

    elite, _ = _gw4_like(disk)
    disk.handoff(6, "a-first", 6.1)
    disk.handoff(6, "b-last", 6.2)

    record = _measure(disk.root, through_gameweek=6)

    assert record["pooled_handoffs"] == {"4": elite}
    assert record["pooled"]["gameweeks"] == [4]
    assert "no retained advice record" in record["not_pooled"]["6"]
    assert _labels(record, 6) == {"a-first": "beside", "b-last": "beside"}
    assert record["gameweeks"]["6"]["capture_source"] == "last_before_deadline"


@pytest.mark.parametrize(
    "spoil, reason",
    [
        ("two_handoffs", "2 different captures or handoffs"),
        ("no_handoff", "names no projection handoff"),
        ("not_kept", "is not kept"),
        ("late_capture", "capture taken after the deadline"),
    ],
)
def test_a_published_handoff_that_cannot_be_proved_is_not_pooled(
    disk: Disk, spoil: str, reason: str
) -> None:
    first = disk.handoff(5, "a-first", 5.1)
    second = disk.handoff(5, "b-second", 5.2)
    if spoil == "two_handoffs":
        disk.advice(5, first, published=_before(5), entry=101)
        disk.advice(5, second, published=_before(5), entry=102)
    elif spoil == "no_handoff":
        disk.advice(5, None, published=_before(5))
    elif spoil == "not_kept":
        disk.advice(5, "f" * 64, published=_before(5))
    else:
        late = _capture("2026-09-13T12:30:00Z")
        disk.captures.append(late)
        disk.advice(5, first, published=_before(5), capture=late)

    record = _measure(disk.root, through_gameweek=5)

    assert record["pooled"]["gameweeks"] == []
    assert reason in record["not_pooled"]["5"]


def test_through_gameweek_reads_no_settled_week_after_it(disk: Disk) -> None:
    for week in (4, 5, 6):
        fingerprint = disk.handoff(week, "live", week + 0.1)
        disk.advice(week, fingerprint, published=_before(week))

    bounded = _measure(disk.root, through_gameweek=5)
    unbounded = _measure(disk.root)

    assert bounded["through_gameweek"] == 5
    assert set(bounded["gameweeks"]) | set(bounded["not_audited"]) == {"4", "5"}
    assert bounded["pooled"]["gameweeks"] == [4, 5]
    assert unbounded["pooled"]["gameweeks"] == [4, 5, 6]
    assert set(unbounded["not_audited"]) == {"7", "8", "9", "10"}


def _six_weeks(disk: Disk) -> None:
    for week in range(4, 10):
        fingerprint = disk.handoff(week, "live", week + 0.1)
        disk.advice(week, fingerprint, published=_before(week))


def test_a_dated_reading_is_taken_only_at_its_fixed_week(disk: Disk) -> None:
    _six_weeks(disk)

    assert _measure(disk.root, through_gameweek=8)["dated_pooled_readings"] == []
    assert _measure(disk.root)["dated_pooled_readings"] == []
    taken = _measure(disk.root, through_gameweek=9)["dated_pooled_readings"]

    assert [reading["through_gameweek"] for reading in taken] == [9]
    assert taken[0]["pooled"]["gameweeks"] == [4, 5, 6, 7, 8, 9]
    assert taken[0]["pooled"]["comparison_may_be_stated"] is True


def test_a_dated_reading_is_not_taken_before_its_week_settles(disk: Disk) -> None:
    _six_weeks(disk)
    disk.settled_through = 8

    assert _measure(disk.root, through_gameweek=9)["dated_pooled_readings"] == []


def test_a_dated_reading_stays_in_the_record_when_later_weeks_are_added(disk: Disk) -> None:
    _six_weeks(disk)
    first = _measure(disk.root, through_gameweek=9)
    dated = json.loads(json.dumps(first["dated_pooled_readings"]))
    dated[0]["taken_at_utc"] = "2026-11-03T09:00:00+00:00"
    first["dated_pooled_readings"] = dated
    fingerprint = disk.handoff(10, "live", 10.1)
    disk.advice(10, fingerprint, published=_before(10))

    later = _measure(disk.root, previous=first)
    again = _measure(disk.root, through_gameweek=9, previous=later)

    assert later["pooled"]["gameweeks"] == [4, 5, 6, 7, 8, 9, 10]
    assert later["dated_pooled_readings"] == dated
    assert again["dated_pooled_readings"] == dated


def test_a_dated_reading_that_would_change_is_refused(disk: Disk) -> None:
    _six_weeks(disk)
    first = _measure(disk.root, through_gameweek=9)
    disk.outcome_shift = 0.5

    with pytest.raises(SystemExit, match="never replaced"):
        _measure(disk.root, through_gameweek=9, previous=first)
    assert (
        _measure(disk.root, previous=first)["dated_pooled_readings"]
        == (first["dated_pooled_readings"])
    )


def test_dated_readings_of_another_season_are_refused(disk: Disk) -> None:
    _six_weeks(disk)
    first = _measure(disk.root, through_gameweek=9)
    first["season"] = "2025-26"

    with pytest.raises(SystemExit, match="another output"):
        _measure(disk.root, previous=first)


def test_the_runner_keeps_the_dated_reading_across_regenerations_on_disk(
    disk: Disk, tmp_path: Path
) -> None:
    _six_weeks(disk)
    output = tmp_path / "record.json"
    markdown = tmp_path / "record.md"

    def run(*extra: str) -> dict[str, Any]:
        common = ["--data-root", str(disk.root), "--json-output", str(output)]
        assert runner.main([*common, "--markdown-output", str(markdown), *extra]) == 0
        document: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
        return document

    taken = run("--through-gameweek", "9")["dated_pooled_readings"]
    regenerated = run()

    assert taken and regenerated["dated_pooled_readings"] == taken
    text = markdown.read_text(encoding="utf-8")
    assert "## Dated pooled reading through gameweek 9" in text
    assert "pooled: the handoff the published advice read" in text


def test_an_earlier_record_without_dated_readings_is_read_as_none(disk: Disk) -> None:
    _six_weeks(disk)
    committed: dict[str, object] = {"season": SEASON, "pooled": {"gameweeks": [4, 5]}}

    record = _measure(disk.root, through_gameweek=8, previous=committed)

    assert record["dated_pooled_readings"] == []
