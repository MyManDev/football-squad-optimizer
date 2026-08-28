"""Build deterministic one-, three-, and five-week transfer evidence in one run."""

import argparse
import sys
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT

from squadopt.application import HorizonBatchRequest, plan_horizon_batch
from squadopt.data.errors import DataError
from squadopt.planning import TransferPlanningError

SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "live"


def _horizons(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("horizons must be comma-separated integers") from error
    if not parsed:
        raise argparse.ArgumentTypeError("horizons cannot be empty")
    return parsed


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--ledger-root", type=Path, default=LEDGER_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument("--snapshot-id", help="replay a named capture; omitted, the latest")
    parser.add_argument("--season", help="override; omitted, derived from the capture")
    parser.add_argument("--from-gameweek", type=int)
    parser.add_argument("--horizons", type=_horizons, default=(1, 3, 5))
    parser.add_argument("--deterministic-time-per-gameweek", type=float, default=20.0)
    parser.add_argument("--solver-wall-ceiling-seconds", type=float, default=300.0)
    parser.add_argument("--in-season-projection", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    horizons = tuple(arguments.horizons)
    try:
        result = plan_horizon_batch(
            HorizonBatchRequest(
                snapshot_root=arguments.snapshot_root,
                ledger_root=arguments.ledger_root,
                artifact_root=arguments.artifact_root,
                in_season_projection=arguments.in_season_projection,
                snapshot_id=arguments.snapshot_id,
                season=arguments.season,
                from_gameweek=arguments.from_gameweek,
                horizons=horizons,
                shadow_horizons=frozenset(horizon for horizon in horizons if horizon > 1),
                deterministic_time_per_gameweek=arguments.deterministic_time_per_gameweek,
                solver_wall_ceiling_seconds=arguments.solver_wall_ceiling_seconds,
            )
        )
    except (DataError, TransferPlanningError, OSError, TypeError, ValueError) as error:
        print(f"Could not build the transfer horizon batch:\n  {error}")
        return 1

    print(f"{result.season} GW{result.first_gameweek}: {len(result.plans)} deterministic horizons")
    for plan in result.plans:
        horizon = plan.last_gameweek - plan.first_gameweek + 1
        role = "live control" if horizon == 1 else "research shadow"
        gap = plan.plan.diagnostics.get("relative_optimality_gap")
        gap_text = "n/a" if gap is None else f"{float(str(gap)):.6f}"
        print(f"  H{horizon}: {plan.solver_status.name}, {role}, relative gap {gap_text}")
    print(f"{'Wrote' if result.created else 'Reused'} {result.manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
