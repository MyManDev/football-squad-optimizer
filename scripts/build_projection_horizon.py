"""Project several gameweeks from the most recent capture, and record what it says.

    python -m scripts.build_projection_horizon
    python -m scripts.build_projection_horizon --from-gameweek 1 --gameweeks 4
    python -m scripts.build_projection_horizon --from-gameweek 2 --gameweeks 5 \
        --in-season-projection data/handoffs/2026-27-gw02.json

Reads a captured decision snapshot, projects every requested gameweek from that single
information state, and writes a summary the transfer planner's inputs can be checked
against.

The table itself stays local: it is derived from a third-party payload and from the
archive, and the repository is not a data store. What is committed is the summary.

This produces planning input, **not gate evidence.** The frozen evaluation objective is
single-gameweek realized squad points; nothing measures how far a multi-gameweek
projection drifts, and it will drift, because expected minutes for a later gameweek are
computed from what was known at the decision point.
"""

import argparse
import json
import sys
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.backtest.export_precision import write_export_table
from squadopt.data.errors import DataError
from squadopt.data.fixtures import aggregate_team_gameweek
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    fixture_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    build_projection_horizon,
    gameweek_fixture_fingerprints,
    infer_season,
    read_projection_handoff,
)

SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--snapshot-id", help="replay a named capture; omitted, the latest")
    parser.add_argument("--from-gameweek", type=int, default=1)
    parser.add_argument("--gameweeks", type=int, default=4, help="how many consecutive weeks")
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument(
        "--in-season-projection",
        type=Path,
        help="projection_handoff_v1 for a horizon beginning after gameweek 1",
    )
    parser.add_argument("--season", help="override; omitted, derived from the capture")
    parser.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "artifacts" / "horizon"
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "projection_horizon_run.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    try:
        identifiers = list_snapshot_ids(arguments.snapshot_root)
        if not identifiers:
            print(f"No snapshots under {arguments.snapshot_root}. Capture one first.")
            return 1
        snapshot_id = arguments.snapshot_id or identifiers[-1]
        snapshot = read_snapshot(arguments.snapshot_root, snapshot_id)
        season = arguments.season or infer_season(snapshot)

        first = int(arguments.from_gameweek)
        targets = tuple(range(first, first + int(arguments.gameweeks)))
        print(f"snapshot {snapshot_id}, season {season}, gameweeks {targets}")

        handoff = (
            read_projection_handoff(arguments.in_season_projection)
            if arguments.in_season_projection is not None
            else None
        )
        panel = None if handoff is not None else build_panel(arguments.archive_root)
        horizon = build_projection_horizon(
            snapshot,
            targets,
            panel=panel,
            season=season,
            in_season=handoff,
        )

        calendar = aggregate_team_gameweek(
            fixture_snapshot(
                snapshot.payloads[FIXTURES_PAYLOAD],
                snapshot.payloads[BOOTSTRAP_PAYLOAD],
                season=season,
                snapshot_id=snapshot_id,
                captured_at_utc=snapshot.metadata.captured_at_utc,
            )
        )
        fingerprints = gameweek_fixture_fingerprints(calendar, targets)
    except DataError as error:
        print(f"Could not build a projection horizon:\n  {error}")
        return 1

    table = horizon.table
    per_gameweek = [
        {
            "gameweek": int(gameweek),
            "players": int((table["gameweek"] == gameweek).sum()),
            "total_expected_points": float(
                table.loc[table["gameweek"] == gameweek, "expected_points"].sum()
            ),
            "blank_clubs": int(
                table.loc[table["gameweek"] == gameweek, "fixture_count"].eq(0).sum()
            ),
            "double_rows": int(
                table.loc[table["gameweek"] == gameweek, "fixture_count"].ge(2).sum()
            ),
            "fixture_fingerprint": fingerprints[int(gameweek)],
        }
        for gameweek in horizon.target_gameweeks
    ]

    document: dict[str, object] = {
        "artifact_type": "projection_horizon_run",
        "contract_version": horizon.contract_version,
        "season": horizon.season,
        "source_snapshot_id": horizon.source_snapshot_id,
        "captured_at_utc": snapshot.metadata.captured_at_utc,
        "model_name": horizon.model_name,
        "model_version": horizon.model_version,
        "feature_contract_version": horizon.feature_contract_version,
        "post_processing_contract_version": horizon.post_processing_contract_version,
        "horizon_fingerprint": horizon.horizon_fingerprint,
        "target_gameweeks": list(horizon.target_gameweeks),
        "rows": len(table),
        "per_gameweek": per_gameweek,
        "gate_evidence": False,
        "locked_holdout_accessed": False,
    }

    output_dir: Path = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / f"projection_horizon_{snapshot_id}.csv"
    write_export_table(table, table_path)
    write_json(output_dir / f"projection_horizon_{snapshot_id}.json", document)

    flat = len({entry["total_expected_points"] for entry in per_gameweek}) == 1
    lines = [
        "# Projection Horizon Run",
        "",
        f"- Contract: `{horizon.contract_version}`",
        f"- Snapshot: `{horizon.source_snapshot_id}` captured {snapshot.metadata.captured_at_utc}",
        f"- Model: `{horizon.model_name}@{horizon.model_version}`",
        f"- Post-processing: `{horizon.post_processing_contract_version}`",
        f"- Horizon fingerprint: `{horizon.horizon_fingerprint}`",
        "",
        "| Gameweek | Players | Total xP | Blank rows | Double rows | Fixture fingerprint |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for entry in per_gameweek:
        digest = str(entry["fixture_fingerprint"])[:12]
        lines.append(
            f"| {entry['gameweek']} | {entry['players']} "
            f"| {float(entry['total_expected_points']):.2f} | {entry['blank_clubs']} "
            f"| {entry['double_rows']} | `{digest}…` |"
        )
    lines += ["", "## What this run shows", ""]
    if flat:
        lines += [
            "Every gameweek projects the same total, and that is the correct answer rather "
            "than a defect. At capture time the published calendar is uniform: each club "
            "has exactly one fixture in every gameweek. Blank and double gameweeks are "
            "created later, by postponements and cup progression, so a capture taken "
            "before the season starts cannot show them.",
            "",
            "The consequence for planning is worth stating plainly: from an opening "
            "capture, the calendar contributes nothing to a horizon, and any advantage a "
            "transfer plan finds over a myopic one comes from price and transfer dynamics "
            "rather than from fixture variation.",
        ]
    else:
        lines += [
            "The calendar is uneven across this horizon, so the per-gameweek totals differ. "
            "Blank rows project exactly zero; double rows scale linearly with fixture count "
            "under `linear_fixture_count_scaling_v1`.",
        ]
    lines += [
        "",
        "## Limits",
        "",
        "This is planning input, not gate evidence. The frozen evaluation objective is "
        "single-gameweek realized squad points, and nothing here measures how far a "
        "multi-gameweek projection drifts.",
        "",
        "It will drift. Expected minutes for a later gameweek are computed from what was "
        "known at the decision point, so injuries, rotation and suspensions in between are "
        "unseen and the projection grows overconfident as the horizon lengthens — by an "
        "amount nobody has measured yet.",
        "",
        "The table is local and not committed; it derives from a third-party payload and "
        "the pinned archive.",
        "",
        "## Reproduction",
        "",
        "```powershell",
        ".venv\\Scripts\\python -m scripts.build_projection_horizon",
        "```",
    ]
    write_text(arguments.summary_output, "\n".join(lines) + "\n")

    print(json.dumps(document, indent=2, sort_keys=True))
    print(f"Wrote {table_path}")
    print(f"Wrote {arguments.summary_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
