"""Outcome-free input audit for the existing football prospective protocol.

Only inspect an explicitly supplied offline snapshot inventory and its artifacts.
This is readiness, not scoring, timestamp certification or model promotion. The
scored capture, the shadow artifact with its receipt and the pairing of the current
arm are read through ``scripts/football_prospective_inputs.py``, without the backend.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.football_prospective_inputs import (
    BRANCH_MISSING,
    pair_current,
    pairing_fields,
    scored_capture,
    shadow_artifact,
)

from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.recommendation import project, read_inputs
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION


def audit(
    snapshot_root: Path,
    handoff_root: Path,
    artifact_root: Path,
    *,
    snapshot_ids: list[str],
    season: str,
    gameweeks: list[int],
    as_of: str,
    advice_record_root: Path | None = None,
) -> dict[str, Any]:
    as_of = normalize_utc_timestamp(as_of, label="audit instant")
    instant = as_instant(as_of)
    if not snapshot_ids or len(set(snapshot_ids)) != len(snapshot_ids):
        raise ValueError("Supply a nonempty, unique offline snapshot inventory.")
    if not gameweeks or any(type(w) is not int or not 1 <= w <= 38 for w in gameweeks):
        raise ValueError("Gameweeks must be integers in 1..38.")
    captures = []
    for identifier in snapshot_ids:
        snapshot = read_snapshot(snapshot_root, identifier)
        if snapshot.metadata.source != "fpl-live":
            raise ValueError("Only fpl-live captures belong to this protocol.")
        inputs = read_inputs(snapshot, season=season, gameweek=None)
        if as_instant(inputs.captured_at_utc) > instant:
            raise ValueError("Inventory includes a capture later than the audit instant.")
        captures.append(inputs)
    rows = []
    for week in sorted(set(gameweeks)):
        row: dict[str, Any] = {
            "gameweek": week,
            "status": "missing",
            "reason": "no_own_target_capture",
        }
        selection = scored_capture(captures, week)
        if selection.inputs is None:
            row["reason"] = selection.reason
            if selection.reason == "no_own_target_capture":
                row["inventory_targets"] = sorted({item.deadline.gameweek for item in captures})
            rows.append(row)
            continue
        inputs = selection.inputs
        row.update(
            snapshot_id=inputs.snapshot_id,
            own_target=inputs.deadline.gameweek,
            deadline_utc=inputs.deadline.deadline_utc,
            capture_selection_final=instant >= as_instant(inputs.deadline.deadline_utc),
        )
        football = shadow_artifact(artifact_root, inputs, as_of=instant)
        row.update(
            receipt_matches=football.receipt_matches,
            receipt_status=football.receipt_status,
            football_served=football.football_served,
        )
        if football.status != "usable" or football.forecast is None:
            row["reason"] = "football_missing_invalid_or_late"
            rows.append(row)
            continue
        pairing = pair_current(handoff_root, inputs, advice_record_root=advice_record_root)
        row.update(pairing_fields(pairing))
        if pairing.branch == BRANCH_MISSING or pairing.handoff is None:
            row["reason"] = pairing.reason
            rows.append(row)
            continue
        try:
            current = project(inputs, in_season=pairing.handoff)
            if set(current.table.player_id) != set(football.forecast.projection.table.player_id):
                raise ValueError("Paired roster differs.")
        except (ValueError, DataError, KeyError, TypeError):
            row["reason"] = "current_missing_or_invalid"
            rows.append(row)
            continue
        row.update(
            status="replay" if pairing.replay else "inputs_ready",
            reason="current_handoff_written_at_or_after_deadline" if pairing.replay else None,
            football_fingerprint=football.forecast.fingerprint,
            football_model=FOOTBALL_MODEL_VERSION,
            artifact_write_utc=football.write_utc,
            paired_players=len(current.table),
        )
        rows.append(row)
    return {
        "contract_version": "football_prospective_input_audit_v1",
        "as_of": as_of,
        "season": season,
        "inventory": sorted(snapshot_ids),
        "advice_records_read": advice_record_root is not None,
        "weeks": rows,
        "outcomes_read": False,
        "promotion": False,
        "limitations": [
            "Inventory completeness is an operator responsibility.",
            "Local file write time is not independent timestamp proof.",
            "Ready inputs do not prove solver optimality or predictive superiority.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "handoff-root", "artifact-root"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--advice-record-root",
        type=Path,
        default=None,
        help=(
            "the member advice records (data/advice_records on the operator machine); "
            "without it no record is read and the current arm pairs by the backend rule"
        ),
    )
    parser.add_argument("--snapshot-id", action="append", required=True)
    parser.add_argument("--gameweek", type=int, action="append", required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--as-of", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit(
                args.snapshot_root,
                args.handoff_root,
                args.artifact_root,
                snapshot_ids=args.snapshot_id,
                season=args.season,
                gameweeks=args.gameweek,
                as_of=args.as_of,
                advice_record_root=args.advice_record_root,
            ),
            indent=2,
            allow_nan=False,
        )
    )
