"""The script writes into an older tree exactly what the builder writes into a new one."""

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

world = world_module._world  # re-register the fixture in this module


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
    assert written == ["entries/101.json", DEVICE_PLAN_DOCUMENT]
    for relative in ("league/entries/101.json", f"league/{DEVICE_PLAN_DOCUMENT}"):
        assert (older / relative).read_bytes() == (built / relative).read_bytes(), relative
    assert "same as published" in out.getvalue()


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
