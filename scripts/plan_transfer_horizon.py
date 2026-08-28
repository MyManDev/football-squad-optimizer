"""Plan 1, 3 or 5 gameweeks from a captured in-season information state.

Example:

    python -m scripts.plan_transfer_horizon --gameweeks 3 \
        --in-season-projection data/handoffs/2026-27-gw02.json

The output is a deterministic expected-points plan, not a probability forecast. Player
projections and availability are frozen at the first deadline; only the captured fixture
calendar varies across later weeks. No price transition is invented.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, write_json

from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.live import (
    build_projection_horizon,
    held_squad_from_ledger,
    infer_season,
    plan_transfer_horizon,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    ProjectionHorizon,
    TransferPlanningConfig,
    TransferPlanningError,
    TransferPlanResult,
)

SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"


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
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "live" / "transfer_horizon.json",
    )
    parser.add_argument("--print-json", action="store_true", help="print the full artifact")
    return parser.parse_args()


def _player_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {
            "player_id": int(row.player_id),
            "name": str(row.name),
            "team_id": str(row.team_id),
            "position": str(row.position),
            "price_tenths": int(row.price_tenths),
            "expected_points": float(row.expected_points),
        }
        for row in frame.itertuples(index=False)
    ]


def _document(
    horizon: ProjectionHorizon,
    plan: TransferPlanResult,
    transfer_config: TransferPlanningConfig,
) -> dict[str, object]:
    """Serialize the typed planner result without pandas or NumPy values."""

    # Kept local to the CLI: the public Python result remains TransferPlanResult, while
    # this JSON is an operational replay artifact.
    if not isinstance(horizon, ProjectionHorizon):
        raise TypeError("horizon must be a ProjectionHorizon.")
    if not isinstance(plan, TransferPlanResult):
        raise TypeError("plan must be a TransferPlanResult.")
    if not isinstance(transfer_config, TransferPlanningConfig):
        raise TypeError("transfer_config must be a TransferPlanningConfig.")
    return {
        "artifact_type": "live_transfer_horizon",
        "contract_version": "live_transfer_horizon_v1",
        "season": horizon.season,
        "source_snapshot_id": horizon.source_snapshot_id,
        "projection_horizon_contract_version": horizon.contract_version,
        "projection_horizon_fingerprint": horizon.horizon_fingerprint,
        "model_name": horizon.model_name,
        "model_version": horizon.model_version,
        "feature_contract_version": horizon.feature_contract_version,
        "post_processing_contract_version": horizon.post_processing_contract_version,
        "target_gameweeks": list(horizon.target_gameweeks),
        "transfer_planning_contract_version": plan.contract_version,
        "transfer_configuration_fingerprint": transfer_config.configuration_fingerprint,
        "transfer_policy": {
            "max_transfers_per_gameweek": transfer_config.max_transfers_per_gameweek,
            "transfer_hit_cost_points": transfer_config.transfer_hit_cost_points,
            "banked_transfer_value_points": transfer_config.banked_transfer_value_points,
        },
        "solver_status": plan.solver_status.name,
        "publication_status": (
            "proven" if plan.solver_status is SolverStatus.OPTIMAL else "shadow_unproven"
        ),
        "objective_value": plan.objective_value,
        "total_projected_score": plan.total_projected_score,
        "total_projected_bench_points": plan.total_projected_bench_points,
        "total_transfer_hit_points": plan.total_transfer_hit_points,
        "diagnostics": dict(plan.diagnostics),
        "weeks": [
            {
                "gameweek": week.gameweek,
                "squad": _player_rows(week.selected_squad),
                "starting_xi": _player_rows(week.starting_xi),
                "bench": _player_rows(week.bench),
                "captain_player_id": int(week.captain["player_id"]),
                "transfers_in": _player_rows(week.transfers_in),
                "transfers_out": _player_rows(week.transfers_out),
                "transfer_count": week.transfer_count,
                "paid_transfer_count": week.paid_transfer_count,
                "transfer_hit_points": week.transfer_hit_points,
                "bank_before_tenths": week.bank_before_tenths,
                "bank_after_tenths": week.bank_after_tenths,
                "free_transfers_before": week.free_transfers_before,
                "free_transfers_for_next_gameweek": week.free_transfers_for_next_gameweek,
                "projected_score": week.projected_score,
                "projected_bench_points": week.projected_bench_points,
            }
            for week in plan.weeks
        ],
        "stated_limits": [
            "Player projections and availability are frozen at the first decision snapshot.",
            "Only the captured fixture calendar varies across later gameweeks.",
            "Prices are held fixed; no price-transition model is applied.",
            "This artifact contains deterministic expected-point outputs only.",
        ],
    }


def main() -> int:
    arguments = _arguments()
    try:
        identifiers = list_snapshot_ids(arguments.snapshot_root)
        if not identifiers:
            raise DataError(f"No snapshots under {arguments.snapshot_root}.")
        snapshot_id = arguments.snapshot_id or identifiers[-1]
        snapshot = read_snapshot(arguments.snapshot_root, snapshot_id)
        season = arguments.season or infer_season(snapshot)
        handoff = read_projection_handoff(arguments.in_season_projection)
        first = arguments.from_gameweek or handoff.gameweek
        if first < 2:
            raise DataError("A held-squad transfer horizon starts at gameweek 2 or later.")
        targets = tuple(range(first, first + arguments.gameweeks))
        inputs = read_inputs(snapshot, season=season, gameweek=first)
        horizon = build_projection_horizon(
            snapshot,
            targets,
            season=season,
            in_season=handoff,
        )
        held = held_squad_from_ledger(
            arguments.ledger_root,
            season,
            before_gameweek=first,
            budget_tenths=1_000,
        )
        rules = read_season_rules(snapshot, season=season)
        deterministic_limit = (
            arguments.solver_deterministic_time_limit
            if arguments.solver_deterministic_time_limit is not None
            else 20.0 * arguments.gameweeks
        )
        optimization = OptimizationConfig(
            solver_time_limit_seconds=arguments.solver_wall_ceiling_seconds,
            solver_deterministic_time_limit=deterministic_limit,
        )
        plan, transfer_config = plan_transfer_horizon(
            inputs,
            horizon,
            held,
            rules,
            optimization=optimization,
        )
        if plan.solver_status is not SolverStatus.OPTIMAL and not arguments.allow_feasible_shadow:
            used = plan.diagnostics.get("deterministic_time_used")
            gap = plan.diagnostics.get("relative_optimality_gap")
            raise DataError(
                f"The {arguments.gameweeks}-week plan is {plan.solver_status.name}, not "
                f"proven optimal (deterministic time {used!r}, relative gap {gap!r}). "
                "It may only be written explicitly with --allow-feasible-shadow."
            )
        document = _document(horizon, plan, transfer_config)
        write_json(arguments.output, document)
    except (DataError, TransferPlanningError, OSError, TypeError, ValueError) as error:
        print(f"Could not plan the transfer horizon:\n  {error}")
        return 1

    if arguments.print_json:
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        objective = plan.objective_value
        if objective is None:
            raise TypeError("An optimal transfer plan must carry an objective value.")
        print(
            f"{season} GW{first}-GW{targets[-1]}: {plan.solver_status.name}, "
            f"objective {objective:.4f}"
        )
        for week in plan.weeks:
            incoming = ", ".join(str(name) for name in week.transfers_in["name"].tolist())
            outgoing = ", ".join(str(name) for name in week.transfers_out["name"].tolist())
            moves = f"{outgoing or 'none'} -> {incoming or 'none'}"
            print(
                f"  GW{week.gameweek}: {week.projected_score:.4f} xP, "
                f"{week.transfer_count} transfer(s), {week.transfer_hit_points:.0f} hit; "
                f"{moves}"
            )
    print(f"Wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
