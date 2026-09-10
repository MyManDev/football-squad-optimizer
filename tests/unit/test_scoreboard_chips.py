import datetime
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from tests.unit.test_advice_record import _build
from tests.unit.test_live_transfers import _world

from squadopt.application.scoreboard_chips import recorded_chip_rows
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload

world = _world


def test_recorded_chip_alternative_is_scored_without_resolving(
    world: dict[str, Any], tmp_path: Path
) -> None:
    records = tmp_path / "records"
    _build(
        world,
        tmp_path / "site",
        record_root=records,
        now=datetime.datetime(2026, 8, 27, 12, tzinfo=datetime.UTC),
    )
    source = read_snapshot(world["snapshot_root"], world["gw2_id"])
    bootstrap = json.loads(source.payloads[BOOTSTRAP_PAYLOAD])
    for event in bootstrap["events"]:
        event["data_checked"] = False
    bootstrap["events"][1].update(finished=True, data_checked=True)
    live = {
        "elements": [
            {"id": row["id"], "stats": {"minutes": 90, "total_points": 2, "starts": 1}}
            for row in bootstrap["elements"]
        ]
    }
    source = replace(
        source,
        metadata=replace(
            source.metadata, snapshot_id="settled", captured_at_utc="2026-08-30T12:00:00Z"
        ),
        payloads={
            **source.payloads,
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode(),
            live_payload(2): json.dumps(live).encode(),
        },
    )
    rows = recorded_chip_rows(records, snapshot=source, snapshots=(source,), entry_ids=(101,))[2]
    boost = next(row for row in rows if row["chip"] == "bboost")
    assert boost["gameweek"] == 2
    assert boost["realized_chip_week_net"] == 28  # 15*2 + captain 2 - one paid transfer*4
    assert boost["outcome_snapshot_id"] == "settled"
    assert len(boost["advice_sha256"]) == 64
    future = next(row for row in rows if row["chip"] == "3xc")
    assert future["action"] == "hold"
    assert future["expected_points_gain"] is None
    assert future["realized_chip_week_net"] is None
    bootstrap["events"][1]["data_checked"] = False
    unchecked = replace(
        source, payloads={**source.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()}
    )
    pending = recorded_chip_rows(
        records, snapshot=unchecked, snapshots=(unchecked,), entry_ids=(101,)
    )[2]
    assert all(row["realized_chip_week_net"] is None for row in pending)
