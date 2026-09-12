import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.unit.test_advice_record import _world_context
from tests.unit.test_live_transfers import _world
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.scoreboard_baselines import baseline_score, human_baseline_rows
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_payload
from squadopt.live import LedgerEntry

world = _world


def test_baseline_captain_uses_lagged_captain_counts_not_settled_points() -> None:
    _, pool, outcomes = decision_inputs()
    pool["name"] = pool["player_id"].astype(str)
    pool["team_id"] = [player % 5 for player in range(1, 16)]
    pool["price_tenths"] = 50
    pool["ownership"] = [
        100 if player in (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15) else 1 for player in range(1, 16)
    ]
    counts = {player: float(100 if player == 9 else 0) for player in range(1, 16)}
    result = baseline_score(pool, outcomes, captain_counts=counts)
    assert result["net"] == pytest.approx(100)
    assert result["diagnostics"]["captain_shortfall"] == 1
    assert result["construction"].endswith("replay")


def test_standard_evidence_filename_is_read_and_late_evidence_is_excluded(
    world: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, projection, _ = _world_context(world)
    pre = read_snapshot(world["snapshot_root"], world["gw2_id"])
    bootstrap = json.loads(pre.payloads[BOOTSTRAP_PAYLOAD])
    for player in bootstrap["elements"]:
        player["selected_by_percent"] = "10.0"
    pre = replace(pre, payloads={**pre.payloads, BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode()})
    settled = replace(
        pre,
        metadata=replace(
            pre.metadata, snapshot_id="settled", captured_at_utc="2026-08-30T12:00:00Z"
        ),
        payloads={
            **pre.payloads,
            live_payload(2): json.dumps(
                {
                    "elements": [
                        {"id": row["id"], "stats": {"minutes": 90, "total_points": 2, "starts": 1}}
                        for row in bootstrap["elements"]
                    ]
                }
            ).encode(),
        },
    )
    projection.table.to_csv(tmp_path / "projections.csv", index=False)
    entry = LedgerEntry(
        "2026-27",
        2,
        {"snapshot_id": pre.metadata.snapshot_id, "deadline_utc": inputs.deadline.deadline_utc},
        {"source_snapshot_id": "settled"},
        tmp_path,
    )
    evidence = pd.DataFrame(
        {
            "player_id": projection.table["player_id"],
            "season": "2026-27",
            "target_gameweek": 2,
            "deadline_timestamp_utc": inputs.deadline.deadline_utc,
            "captured_at_utc": "2026-08-26T12:00:00Z",
            "source_snapshot_ids": "elite",
            "elite_start_count_lag1": 10,
            "elite_captain_count_lag1": 1,
            "elite_members_observed": 100,
            "elite_cohort_size": 100,
        }
    )
    (tmp_path / "player_evidence_v1_2026-27_gw02_top100.csv").touch()
    monkeypatch.setattr(
        "squadopt.application.scoreboard_baselines.read_player_evidence_artifact",
        lambda *args: evidence,
    )
    rows = human_baseline_rows((entry,), (pre, settled), evidence_root=tmp_path)[2]
    assert rows["elite_xi"]["net"] == 24
    assert rows["ownership_template"]["net"] == 24
    evidence["captured_at_utc"] = "2026-08-28T12:00:00Z"
    rows = human_baseline_rows((entry,), (pre, settled), evidence_root=tmp_path)[2]
    assert "elite_xi" not in rows
