"""Outcome-free input audit for the existing football prospective protocol.

Only inspect an explicitly supplied offline snapshot inventory and its artifacts.
This is readiness, not scoring, timestamp certification or model promotion.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.recommendation import project, read_inputs
from squadopt.platform.capture_context import load_capture_identity
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
        eligible = [item for item in captures if item.deadline.gameweek == week]
        row: dict[str, Any] = {
            "gameweek": week,
            "status": "missing",
            "reason": "no_own_target_capture",
        }
        if not eligible:
            row["inventory_targets"] = sorted({item.deadline.gameweek for item in captures})
            rows.append(row)
            continue
        latest = max(as_instant(item.captured_at_utc) for item in eligible)
        selected = [item for item in eligible if as_instant(item.captured_at_utc) == latest]
        if len(selected) != 1:
            row["reason"] = "ambiguous_latest_capture"
            rows.append(row)
            continue
        inputs = selected[0]
        row.update(
            snapshot_id=inputs.snapshot_id,
            own_target=inputs.deadline.gameweek,
            deadline_utc=inputs.deadline.deadline_utc,
            capture_selection_final=instant >= as_instant(inputs.deadline.deadline_utc),
        )
        path = football_artifact_path(artifact_root, inputs.snapshot_id)
        try:
            football = read_football_forecast(path, inputs)
            if football.projection.diagnostics["model_version"] != FOOTBALL_MODEL_VERSION:
                raise ValueError("The frozen protocol requires football v1.")
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified >= as_instant(inputs.deadline.deadline_utc) or modified > instant:
                raise ValueError("Football artifact write time is late or after this audit.")
        except (OSError, ValueError, DataError, KeyError, TypeError):
            row["reason"] = "football_missing_invalid_or_late"
            rows.append(row)
            continue
        try:
            identity = load_capture_identity(
                snapshot_root=snapshot_root,
                snapshot_id=inputs.snapshot_id,
                handoff_root=handoff_root,
                advice_contract_version="input_audit",
                repository_commit="input_audit",
                configuration_fingerprint="input_audit",
                season=season,
            )
            current = project(inputs, in_season=identity.handoff)
            if set(current.table.player_id) != set(football.projection.table.player_id):
                raise ValueError("Paired roster differs.")
        except (OSError, ValueError, DataError, KeyError, TypeError):
            row["reason"] = "current_missing_or_invalid"
            rows.append(row)
            continue
        row.update(
            status="inputs_ready",
            reason=None,
            football_fingerprint=football.fingerprint,
            football_model=FOOTBALL_MODEL_VERSION,
            artifact_write_utc=modified.isoformat(),
            current_fingerprint=identity.handoff.fingerprint,
            current_model=identity.handoff.model_version,
            paired_players=len(current.table),
        )
        rows.append(row)
    return {
        "contract_version": "football_prospective_input_audit_v1",
        "as_of": as_of,
        "season": season,
        "inventory": sorted(snapshot_ids),
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
            ),
            indent=2,
            allow_nan=False,
        )
    )
