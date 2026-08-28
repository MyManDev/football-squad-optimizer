"""Plan 1, 3 or 5 gameweeks from a captured in-season information state.

Example:

    python -m scripts.plan_transfer_horizon --gameweeks 3 \
        --in-season-projection data/handoffs/2026-27-gw02.json

This is the command-line adapter over ``squadopt.application.plan_horizon``. The
result is deterministic expected-points evidence, not a probability forecast.
"""

import argparse
import json
import sys
from pathlib import Path

from scripts._experiment_cli import REPOSITORY_ROOT

from squadopt.application import HorizonPlanRequest, plan_horizon
from squadopt.data.errors import DataError
from squadopt.planning import TransferPlanningError

SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "live"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=SNAPSHOT_ROOT)
    parser.add_argument("--ledger-root", type=Path, default=LEDGER_ROOT)
    parser.add_argument("--snapshot-id", help="replay a named capture; omitted, the latest")
    parser.add_argument("--season", help="override; omitted, derived from the capture")
    parser.add_argument("--from-gameweek", type=int)
    parser.add_argument("--gameweeks", type=int, choices=(1, 3, 5), default=3)
    parser.add_argument(
        "--solver-deterministic-time-limit",
        type=float,
        help="CP-SAT deterministic units; default is 20 per projected gameweek",
    )
    parser.add_argument("--solver-wall-ceiling-seconds", type=float, default=300.0)
    parser.add_argument(
        "--allow-feasible-shadow",
        action="store_true",
        help="write a deterministic FEASIBLE plan with its gap, marked non-publishable",
    )
    parser.add_argument("--in-season-projection", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, default=ARTIFACT_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        help="write here; omitted, derive an immutable fingerprinted artifact path",
    )
    parser.add_argument("--print-json", action="store_true", help="print the full artifact")
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    try:
        result = plan_horizon(
            HorizonPlanRequest(
                snapshot_root=arguments.snapshot_root,
                ledger_root=arguments.ledger_root,
                artifact_root=arguments.artifact_root,
                snapshot_id=arguments.snapshot_id,
                season=arguments.season,
                from_gameweek=arguments.from_gameweek,
                gameweeks=arguments.gameweeks,
                solver_deterministic_time_limit=arguments.solver_deterministic_time_limit,
                solver_wall_ceiling_seconds=arguments.solver_wall_ceiling_seconds,
                allow_feasible_shadow=arguments.allow_feasible_shadow,
                in_season_projection=arguments.in_season_projection,
                output_path=arguments.output,
            )
        )
    except (DataError, TransferPlanningError, OSError, TypeError, ValueError) as error:
        print(f"Could not plan the transfer horizon:\n  {error}")
        return 1

    document = dict(result.document)
    if arguments.print_json:
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        objective = document.get("objective_value")
        if objective is None:
            raise TypeError("A recorded transfer plan must carry an objective value.")
        print(
            f"{result.season} GW{result.first_gameweek}-GW{result.last_gameweek}: "
            f"{result.solver_status.name}, objective {float(str(objective)):.4f}"
        )
        for week in result.plan.weeks:
            incoming = ", ".join(str(name) for name in week.transfers_in["name"].tolist())
            outgoing = ", ".join(str(name) for name in week.transfers_out["name"].tolist())
            moves = f"{outgoing or 'none'} -> {incoming or 'none'}"
            print(
                f"  GW{week.gameweek}: {week.projected_score:.4f} xP, "
                f"{week.transfer_count} transfer(s), "
                f"{week.transfer_hit_points:.0f} hit; {moves}"
            )
    print(f"{'Wrote' if result.created else 'Reused'} {result.artifact_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
