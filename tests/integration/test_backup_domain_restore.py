"""A synthetic offline restore is usable by the actual immutable-record readers."""

import json
from pathlib import Path
from typing import Any

import pytest
from tests.unit import test_advice_record as advice_world
from tests.unit import test_live_transfers as live_world

from squadopt.application.advice_record import load_member_advice_record
from squadopt.application.entries import EntryRegistry
from squadopt.data.snapshots import read_snapshot
from squadopt.live import load_entry, read_projection_handoff
from squadopt.platform.backup_recovery import create_backup, restore_backup
from squadopt.platform.projection_retention import publish_retained_handoff

world = live_world._world


def test_restored_capture_ledger_registry_advice_and_publication_remain_readable(
    world: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_world._decide_gw1(monkeypatch, world)
    records, site, entries = tmp_path / "records", tmp_path / "site", tmp_path / "entries"
    advice_world._build(world, site, record_root=records)
    handoff = world["handoffs"] / "gw02.json"
    publish_retained_handoff(handoff, read_projection_handoff(handoff))
    entries.mkdir()
    (entries / "registry.json").write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [
                    {
                        "entry_id": 101,
                        "label": "Synthetic member",
                        "registered_at_utc": "2026-08-23T00:00:00Z",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    roots = {
        "snapshots": world["snapshot_root"],
        "ledger": world["ledger_root"],
        "handoffs": world["handoffs"],
        "advice_records": records,
        "entries": entries,
        "site": site,
    }
    directory, target = tmp_path / "backup", tmp_path / "restored"
    receipt = create_backup(roots, directory, writers_stopped=True)
    restore_backup(directory, target, manifest_sha256=receipt.manifest_sha256, writers_stopped=True)
    assert (
        read_snapshot(target / "snapshots", world["gw2_id"]).metadata
        == read_snapshot(world["snapshot_root"], world["gw2_id"]).metadata
    )
    assert (
        load_entry(target / "ledger", live_world.SEASON, 1).decision
        == load_entry(world["ledger_root"], live_world.SEASON, 1).decision
    )
    assert EntryRegistry.load(target / "entries" / "registry.json").ids() == (101,)
    assert read_projection_handoff(target / "handoffs" / "gw02.json").fingerprint == (
        read_projection_handoff(handoff).fingerprint
    )
    assert load_member_advice_record(
        target / "advice_records", live_world.SEASON, 2, 101, world["gw2_id"]
    ) == load_member_advice_record(records, live_world.SEASON, 2, 101, world["gw2_id"])
    assert advice_world._digests(target / "site") == advice_world._digests(site)
