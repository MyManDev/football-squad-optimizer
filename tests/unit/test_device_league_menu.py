"""A device league publishes usable inputs without entering any member solver."""

import json

import pytest
from scripts.check_league_tree import check_variants
from tests.unit.test_league_views import (
    _legal_squad,
    _member_picks,
    _Provider,
    _world_context,
    world,
)

from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.application.weekly_plan import WeekError, WeeklyRequest

__all__ = ["world"]


@pytest.mark.parametrize("count", [1, 77])
def test_device_members_need_no_solver_and_remove_old_advice(world, tmp_path, count):
    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    entries = list(range(101, 101 + count))
    provider = _Provider({entry: _member_picks(world, entry, squad) for entry in entries})
    entries.append(999)
    registrations = tuple(
        EntryRegistration(entry, str(entry), "2026-08-23T00:00:00Z") for entry in entries
    )
    out = tmp_path / "league"
    old = out / "advice/101/saf-puan/1.json"
    old.parent.mkdir(parents=True)
    old.write_text("{}")
    unrelated = out / "scoreboard.json"
    unrelated.write_text("retained")

    def never_solve(*args, **kwargs):
        pytest.fail("A device menu entered the member solver mapper")

    report = build_league_views(
        provider,
        registrations,
        inputs,
        projection,
        rules,
        league_id=755941,
        league_name="Second league",
        out_dir=out,
        device_only=True,
        mapper=never_solve,
        standings={
            entry: MemberStanding(
                entry_id=entry,
                team_name=str(entry),
                manager_name=str(entry),
                rank=rank,
                total_points=100 - rank,
            )
            for rank, entry in enumerate(entries, 1)
        },
        scored_gameweek=1,
        advice_record_root=tmp_path / "records",
    )
    assert report.rendered_count == count
    assert not old.exists()
    assert unrelated.read_text() == "retained"
    assert not (out / "entries/999.json").exists()
    assert not (tmp_path / "records").exists()

    def read(relative):
        path = out / relative
        return json.loads(path.read_bytes()) if path.exists() else None

    assert check_variants(read) == []
    for entry in entries[:-1]:
        index = read(f"advice/{entry}/index.json")["payload"]
        own = read(f"entries/{entry}.json")["payload"]
        assert index["menu"] == "device"
        assert index["chip_states"] == own["chips"]
        assert index["source_snapshot_id"] == own["source_snapshot_id"]
        assert index["computed"] == index["unavailable"] == []
        assert set(own["device_plan"]["held"]) == set(squad)
        assert [path.name for path in (out / "advice" / str(entry)).iterdir()] == ["index.json"]
    index = read("advice/101/index.json")["payload"]
    if count > 1:
        assert index["default_rival_entry_id"] == 102
        assert index["suggested_strategy"]["rival_entry_id"] == 102
    wrong = read("entries/101.json")
    wrong["payload"]["source_snapshot_id"] = "another-capture"
    (out / "entries/101.json").write_text(json.dumps(wrong))
    assert check_variants(read) == ["101: device menu has no matching squad inputs"]


def test_device_menus_only_name_leagues_in_the_run():
    for ids in [(755941,), (352490, 352490)]:
        with pytest.raises(WeekError, match="Device menus"):
            WeeklyRequest("2026-27", 8, (352490,), device_league_ids=ids).plan()


def test_weekly_device_stage_reports_timings_without_a_worker_pool(tmp_path, monkeypatch):
    from dataclasses import replace

    from tests.unit.test_weekly_operations import world as weekly_world

    import squadopt.platform.publication_workers as workers

    operation = weekly_world(tmp_path)
    operation.request = replace(operation.request, device_league_ids=(352490,), workers=8)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}

    def never_pool(*args, **kwargs):
        pytest.fail("The device league created a process pool")

    monkeypatch.setattr(workers, "ProcessPoolExecutor", never_pool)
    receipt = operation._league().value
    line = receipt["leagues"]["352490"]
    assert line["menu"] == "device"
    assert line["advice_recorded"] is False
    assert list(line["timings"]) == ["prepared", "projection", "members", "publication"]
    assert list(line["timings"].values()) == sorted(line["timings"].values())
