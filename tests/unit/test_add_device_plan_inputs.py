"""The script writes into an older tree exactly what the builder writes into a new one."""

import hashlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
from scripts.add_device_plan_inputs import DevicePlanInputsError, add_device_plan_inputs, main
from tests.unit.test_league_views import _legal_squad, _member_picks, _Provider, _world_context

from squadopt.application.device_plan import DEVICE_PLAN_DOCUMENT
from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import build_league_views
from squadopt.contracts.league_tree import (
    PublishedLeague,
    read_league_directory,
    write_league_directory,
)
from squadopt.data.errors import DataError


@pytest.fixture(name="world")
def _world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The shared world whose bootstrap carries ``cost_change_start``, as a real one does,
    so the per-capture device-plan table can read each player's start price."""

    return world_module.build_world(tmp_path, start_prices=True)


def _build(world: dict[str, Any], out: Path) -> None:
    inputs, projection, rules = _world_context(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, _legal_squad(world))}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out / "league",
    )


def _strip(tree: Path) -> None:
    """A tree as a build from before the inputs would have left it."""

    (tree / "league" / DEVICE_PLAN_DOCUMENT).unlink()
    for path in (tree / "league" / "entries").glob("*.json"):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        del envelope["payload"]["device_plan"]
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8", newline="\n")


def test_the_script_writes_the_builder_s_bytes(world: dict[str, Any], tmp_path: Path) -> None:
    built = tmp_path / "built"
    _build(world, built)
    older = tmp_path / "older"
    shutil.copytree(built, older)
    _strip(older)
    assert not (older / "league" / DEVICE_PLAN_DOCUMENT).exists()

    out = io.StringIO()
    written = add_device_plan_inputs(
        snapshot_root=world["snapshot_root"],
        snapshot_id=world["gw2_id"],
        handoff_path=world_module._handoff(world),
        site_data_root=older,
        verify=True,
        out=out,
    )
    table = f"device/{world['gw2_id']}/{DEVICE_PLAN_DOCUMENT}"
    assert written == ["entries/101.json", DEVICE_PLAN_DOCUMENT, table]
    for relative in ("league/entries/101.json", f"league/{DEVICE_PLAN_DOCUMENT}"):
        assert (older / relative).read_bytes() == (built / relative).read_bytes(), relative
    assert "same as published" in out.getvalue()
    # The capture's own table beside the tree, under the tree's stamp (#981 step 1); the
    # legacy tree has no directory, so no line names it.
    envelope = json.loads((older / table).read_text(encoding="utf-8"))
    copy = json.loads((older / "league" / DEVICE_PLAN_DOCUMENT).read_text(encoding="utf-8"))
    assert envelope["generated_at_utc"] == copy["generated_at_utc"]
    assert envelope["payload"]["contract_version"] == "league_device_plan_v2"
    assert "league_id" not in envelope["payload"]
    assert [p["id"] for p in envelope["payload"]["players"]] == [
        p["id"] for p in copy["payload"]["players"]
    ]
    assert not (older / "leagues.json").exists()


def test_a_tree_naming_another_capture_is_refused_untouched(
    world: dict[str, Any], tmp_path: Path
) -> None:
    built = tmp_path / "built"
    _build(world, built)
    _strip(built)
    path = built / "league" / "entries" / "101.json"
    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["payload"]["source_snapshot_id"] = "fpl-live-another-capture"
    path.write_text(json.dumps(envelope, indent=2), encoding="utf-8", newline="\n")
    before = {p: p.read_bytes() for p in built.rglob("*.json")}

    with pytest.raises(DevicePlanInputsError, match="names capture"):
        add_device_plan_inputs(
            snapshot_root=world["snapshot_root"],
            snapshot_id=world["gw2_id"],
            handoff_path=world_module._handoff(world),
            site_data_root=built,
            out=io.StringIO(),
        )
    assert {p: p.read_bytes() for p in built.rglob("*.json")} == before
    assert not (built / "league" / DEVICE_PLAN_DOCUMENT).exists()


def test_the_command_refuses_with_a_sentence_and_exit_one(
    world: dict[str, Any], tmp_path: Path, capsys
) -> None:
    code = main(
        [
            "--snapshot-root",
            str(world["snapshot_root"]),
            "--snapshot-id",
            "fpl-live-nowhere",
            "--handoff",
            str(world_module._handoff(world)),
            "--site-data-root",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert capsys.readouterr().out.startswith("Refused: ")


def test_on_a_directory_site_the_league_s_line_names_the_table_and_the_stamp_is_kept(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = _world_context(world)
    site = tmp_path / "site"
    build_league_views(
        _Provider({101: _member_picks(world, 101, _legal_squad(world))}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=site / "leagues" / "352490",
    )
    (site / "leagues" / "352490" / DEVICE_PLAN_DOCUMENT).unlink()
    for path in (site / "leagues" / "352490" / "entries").glob("*.json"):
        envelope = json.loads(path.read_text(encoding="utf-8"))
        del envelope["payload"]["device_plan"]
        path.write_text(json.dumps(envelope, indent=2), encoding="utf-8", newline="\n")
    lines = [
        PublishedLeague(352490, "Test League", "2026-27", 2, "leagues/352490"),
        PublishedLeague(9, "League 9", "2026-27", 2, "leagues/9"),
    ]
    write_league_directory(site, lines, generated_at_utc="2026-09-01T12:00:00Z")

    written = add_device_plan_inputs(
        snapshot_root=world["snapshot_root"],
        snapshot_id=world["gw2_id"],
        handoff_path=world_module._handoff(world),
        site_data_root=site,
        out=io.StringIO(),
        league_id=352490,
    )
    table = f"device/{world['gw2_id']}/{DEVICE_PLAN_DOCUMENT}"
    assert written == ["entries/101.json", DEVICE_PLAN_DOCUMENT, table, "leagues.json"]
    assert (site / table).is_file()
    directory = json.loads((site / "leagues.json").read_text(encoding="utf-8"))
    # The directory keeps its own stamp; only this league's line gains the table.
    assert directory["generated_at_utc"] == "2026-09-01T12:00:00Z"
    digest = hashlib.sha256((site / table).read_bytes()).hexdigest()
    assert read_league_directory(site) == [
        PublishedLeague(9, "League 9", "2026-27", 2, "leagues/9"),
        PublishedLeague(352490, "Test League", "2026-27", 2, "leagues/352490", table, digest),
    ]


def test_a_table_of_another_payload_already_on_the_site_is_refused_untouched(
    world: dict[str, Any], tmp_path: Path
) -> None:
    built = tmp_path / "built"
    _build(world, built)
    _strip(built)
    table = built / "device" / world["gw2_id"] / DEVICE_PLAN_DOCUMENT
    table.parent.mkdir(parents=True)
    table.write_text(json.dumps({"payload": {"contract_version": "other"}}), encoding="utf-8")
    before = {p: p.read_bytes() for p in built.rglob("*.json")}
    with pytest.raises(DataError, match="already holds another device-plan table") as refused:
        add_device_plan_inputs(
            snapshot_root=world["snapshot_root"],
            snapshot_id=world["gw2_id"],
            handoff_path=world_module._handoff(world),
            site_data_root=built,
            out=io.StringIO(),
        )
    assert {p: p.read_bytes() for p in built.rglob("*.json")} == before
    # The script names its own way out, which works because it never reads the other
    # leagues' lines: remove the capture's directory and run it for every league again.
    assert str(refused.value).endswith(
        f"a table is written once per capture. Remove {table.parent} and run "
        "scripts/add_device_plan_inputs.py again for every league of the list (--league)."
    )
    assert "weekly run" not in str(refused.value)
