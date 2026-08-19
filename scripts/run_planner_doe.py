"""Screen transfer-planner controls on real decision windows.

    python -m scripts.run_planner_doe --season 2024-25 --start-gameweeks 5,10,15,20,25,30

A one-factor-at-a-time screen around the planner's defaults: horizon length, transfer
hit cost, and horizon discounting are varied one control at a time, and every variant
is measured with the same rehearsal (planner versus the myopic weekly baseline, same
pools, same starting squads, realized points minus hits). The output says which
controls actually move real outcomes — and therefore which ones deserve a place in a
future search space — before any prediction-side horizon builder exists.
"""

import argparse
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments import (
    NAIVE_PROJECTION_RULE,
    ExperimentError,
    MultiGwRehearsal,
    MultiGwRehearsalConfig,
)
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
PLANNER_DOE_CONTRACT_VERSION = "planner_control_screen_v1"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--start-gameweeks", default="5,10,15,20,25,30")
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "planner_doe.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "planner_doe.md",
    )
    return parser.parse_args()


def _variants() -> tuple[tuple[str, int, TransferPlanningConfig], ...]:
    """One-factor-at-a-time around the defaults (horizon 3, hit 4.0, discount 1.0)."""

    return (
        ("baseline_h3", 3, TransferPlanningConfig()),
        ("horizon_2", 2, TransferPlanningConfig()),
        ("horizon_4", 4, TransferPlanningConfig()),
        ("hit_free", 3, TransferPlanningConfig(transfer_hit_cost_points=0.0)),
        ("hit_8", 3, TransferPlanningConfig(transfer_hit_cost_points=8.0)),
        ("discount_09", 3, TransferPlanningConfig(horizon_discount_factor=0.9)),
    )


def _fixture_counts(archive_root: Path, season: str) -> pd.DataFrame:
    fixtures = build_fixture_panel(archive_root, seasons=(season,))
    codes = load_team_codes(archive_root, season)
    name_by_code = {
        int(code): str(name)
        for name, code in zip(codes["name"].tolist(), codes["code"].tolist(), strict=True)
    }
    counts = (
        fixtures.groupby(["gameweek", "team_id"], sort=True)
        .size()
        .reset_index(name="fixture_count")
    )
    counts["team_id"] = counts["team_id"].map(lambda code: name_by_code[int(code)])
    return counts


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    season = str(arguments.season).strip()
    starts = tuple(int(value.strip()) for value in str(arguments.start_gameweeks).split(","))
    panel = build_panel(arguments.archive_root)
    counts = _fixture_counts(arguments.archive_root, season)

    variant_records: list[Mapping[str, object]] = []
    try:
        for label, horizon_length, transfer_config in _variants():
            config = MultiGwRehearsalConfig(
                season=season,
                horizon_length=horizon_length,
                form_window=arguments.form_window,
                candidate_pool_per_position=arguments.candidate_pool_per_position,
                cheap_pool_per_position=arguments.cheap_pool_per_position,
                transfer_config=transfer_config,
            )
            rehearsal = MultiGwRehearsal(panel, counts, config)
            advantages: list[float] = []
            planner_hits = 0.0
            planner_transfers = 0
            for start in starts:
                if start + horizon_length - 1 > max(rehearsal.available_gameweeks):
                    continue
                LOGGER.info("Variant %s: window %s", label, start)
                window = rehearsal.rehearse_window(start)
                advantages.append(window.planning_advantage_points)
                planner_hits += window.planned_transfer_hit_points
                transfers = window.diagnostics.get("planner_transfers", [])
                assert isinstance(transfers, list | tuple)
                planner_transfers += sum(int(value) for value in transfers)
            if not advantages:
                raise ExperimentError(
                    f"Variant {label} evaluated no windows; widen the start gameweeks."
                )
            variant_records.append(
                {
                    "variant": label,
                    "horizon_length": horizon_length,
                    "transfer_hit_cost_points": transfer_config.transfer_hit_cost_points,
                    "horizon_discount_factor": transfer_config.horizon_discount_factor,
                    "windows": len(advantages),
                    "mean_planning_advantage_points": sum(advantages) / len(advantages),
                    "min_advantage": min(advantages),
                    "max_advantage": max(advantages),
                    "total_planner_transfers": planner_transfers,
                    "total_planner_hit_points": planner_hits,
                }
            )
    except ExperimentError as error:
        print(f"Could not screen planner controls:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": PLANNER_DOE_CONTRACT_VERSION,
        "projection_rule": NAIVE_PROJECTION_RULE,
        "season": season,
        "start_gameweeks": list(starts),
        "design": "one_factor_at_a_time_around_defaults",
        "variants": variant_records,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }

    lines = [
        "# Planner control screen",
        "",
        f"- Contract: `{PLANNER_DOE_CONTRACT_VERSION}`; projection rule `{NAIVE_PROJECTION_RULE}`",
        f"- Season {season}; windows starting at {', '.join(map(str, starts))}",
        "- Design: one factor at a time around the defaults "
        "(horizon 3, hit 4.0, discount 1.0); every variant shares pools, starting "
        "squads, and the myopic baseline protocol",
        "",
        "| Variant | Horizon | Hit cost | Discount | Windows | Mean advantage "
        "| Min | Max | Transfers | Hit pts |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in variant_records:
        lines.append(
            f"| {record['variant']} | {record['horizon_length']} "
            f"| {record['transfer_hit_cost_points']:.0f} "
            f"| {record['horizon_discount_factor']:.2f} "
            f"| {record['windows']} "
            f"| {record['mean_planning_advantage_points']:+.2f} "
            f"| {record['min_advantage']:+.1f} | {record['max_advantage']:+.1f} "
            f"| {record['total_planner_transfers']} "
            f"| {record['total_planner_hit_points']:.0f} |"
        )
    lines += [
        "",
        "Read: a control whose variant row barely moves the mean advantage does not",
        "deserve a search dimension; a control that moves it belongs in the future",
        "horizon-policy search space. Measurement only; nothing was promoted.",
    ]
    markdown = "\n".join(lines) + "\n"

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
