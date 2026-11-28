"""Read-only mathematical references for the public device horizon replay.

This calls the unchanged server planner and native process port with the member
window policy and the application's existing search budgets. It does not claim to
replay the original capture request: the original rules/handoff fingerprints are
unknown, and the verified rule metadata retains its actual source capture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from time import perf_counter
from typing import Any
from unittest.mock import patch

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.application.advice import (
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
)
from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.live.rules import SeasonRules, read_season_rules
from squadopt.live.transfers import member_window_policy
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import optimizer as server_model
from squadopt.planning.models import InitialSquadState, PlanningHorizon
from squadopt.planning.native_highs import native_window_executor, native_window_outcomes
from squadopt.platform.native_windows import execute_native_window


def reference_horizon(
    document: dict[str, Any], entry: dict[str, Any], window: int
) -> PlanningHorizon:
    """Use the replay's raw per-week points and the member's original sale lots."""
    if document["season"] != "2026-27" or window not in (3, 5):
        raise ValueError("An explicitly named live 2026-27 H3/H5 problem is required")
    players = {player["id"]: player for player in document["players"]}
    return PlanningHorizon(
        pd.DataFrame(
            {
                "gameweek": week["gameweek"],
                "player_id": row["id"],
                "name": players[row["id"]]["name"],
                "team_id": players[row["id"]]["team"],
                "position": players[row["id"]]["position"],
                "expected_points": row["expected_points"],
                "buy_price_tenths": row["buy_tenths"],
                "sell_price_tenths": entry["sell_tenths"].get(str(row["id"]), row["buy_tenths"]),
            }
            for week in document["horizon"]["weeks"][:window]
            for row in week["players"]
        )
    )


def solve_reference(
    document: dict[str, Any], entry: dict[str, Any], rules: SeasonRules, window: int
) -> dict[str, Any]:
    """Record primary proof, rank completion and move uniqueness independently."""
    horizon = reference_horizon(document, entry, window)
    policy = replace(
        member_window_policy(rules, gameweek=document["gameweek"], transfer_cap=1, weeks=window),
        acquisition_sell_on_fee=rules.transfers.sell_on_fee,
    )
    settings = OptimizationConfig(
        solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
        solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * window,
    )
    state = InitialSquadState(entry["held"], entry["bank_tenths"], entry["free_transfers"])
    built: list[Any] = []
    native: list[dict[str, Any]] = []
    original_build = server_model._build_model

    def capture_model(*args: Any, **kwargs: Any) -> Any:
        result = original_build(*args, **kwargs)
        built.append(result)
        return result

    def execute(packet: Any, seconds: float) -> Any:
        started = perf_counter()
        response = execute_native_window(packet, seconds)
        native.append(
            {
                "elapsed_seconds": perf_counter() - started,
                "wall_limit_seconds": seconds,
                **{
                    key: response.get(key)
                    for key in ("version", "threads", "optimal", "status", "objective", "bound")
                },
            }
        )
        return response

    started = perf_counter()
    with (
        patch.object(server_model, "_build_model", side_effect=capture_model),
        native_window_executor(execute),
        native_window_outcomes() as outcomes,
    ):
        result = server_model.optimize_transfer_plan(
            horizon,
            state,
            settings,
            policy,
            linearization_level=WINDOW_LINEARIZATION_LEVEL,
            protect_hold=True,
        )
    elapsed = perf_counter() - started
    diagnostics = dict(result.diagnostics)
    model_objective = diagnostics.get("scaled_model_objective_value")
    if model_objective is not None and not isinstance(model_objective, int | float):
        raise ValueError("The server returned a nonnumeric model objective")
    primary = (
        round(
            float(model_objective)
            * policy.objective_weight_scale
            * settings.expected_points_scale
        )
        if model_objective is not None
        else None
    )
    unique_moves = None
    uniqueness_status = None
    if result.solver_status is SolverStatus.OPTIMAL and primary is not None:
        artifacts = built[-1]
        alternative = artifacts.model.clone()
        alternative.clear_hints()
        alternative.add(artifacts.primary_objective == primary)
        differences: list[Any] = []
        for index, week in enumerate(result.weeks):
            players = artifacts.players_by_week[index].player_id.tolist()
            for family, chosen in (
                (artifacts.transfer_in_vars[index], set(week.transfers_in.player_id)),
                (artifacts.transfer_out_vars[index], set(week.transfers_out.player_id)),
            ):
                differences.extend(
                    1 - variable if player in chosen else variable
                    for player, variable in zip(players, family, strict=True)
                )
        alternative.add(sum(differences) >= 1)
        # Remove the rank objective. This asks whether ANY primary-optimal plan
        # changes a transfer, not whether the chosen rank optimum is unique.
        alternative.maximize(artifacts.primary_objective)
        certificate = cp_model.CpSolver()
        certificate.parameters.num_search_workers = 1
        certificate.parameters.max_time_in_seconds = 30
        certificate.parameters.max_deterministic_time = 10
        status = certificate.solve(alternative)
        uniqueness_status = certificate.status_name(status)
        if status == cp_model.INFEASIBLE:
            unique_moves = True
        elif status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            unique_moves = False
    return {
        "status": result.solver_status.name,
        "elapsed_seconds": elapsed,
        "horizon_fingerprint": horizon.horizon_fingerprint,
        "objective": result.objective_value,
        "objective_scaled": primary,
        "unique_moves": unique_moves,
        "uniqueness_status": uniqueness_status,
        "tiebreak_completed": diagnostics.get("tiebreak_completed"),
        "diagnostics": diagnostics,
        "native_attempts": native,
        "native_outcomes": [asdict(outcome) for outcome in outcomes],
        "weeks": [
            {
                "gameweek": week.gameweek,
                "squad": week.selected_squad.player_id.tolist(),
                "starting_xi": week.starting_xi.player_id.tolist(),
                "captain": int(week.captain.player_id),
                "transfers_in": week.transfers_in.player_id.tolist(),
                "transfers_out": week.transfers_out.player_id.tolist(),
                "bank_after_tenths": week.bank_after_tenths,
                "free_transfers_before": week.free_transfers_before,
                "free_transfers_after": week.free_transfers_for_next_gameweek,
                "transfer_hit_points": week.transfer_hit_points,
            }
            for week in result.weeks
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rule-bootstrap", type=Path, required=True)
    args = parser.parse_args()
    # Import the opt-in Windows controller only for its already verified public
    # input recipe. Normal reference tests remain platform independent.
    from tests.unit.device_horizon_benchmark import live_problem

    problem, provenance = live_problem(args.rule_bootstrap)
    raw = args.rule_bootstrap.read_bytes()
    meta = json.loads((args.rule_bootstrap.parent.parent / "metadata.json").read_bytes())
    snapshot = CapturedSnapshot(SnapshotMetadata(**meta), {"bootstrap-static.json": raw})
    rules = read_season_rules(snapshot, season="2026-27")
    print(
        json.dumps(
            {
                "event": "metadata",
                "purpose": "numeric-server-reference",
                "provenance": provenance,
                "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            },
            allow_nan=False,
        ),
        flush=True,
    )
    for member in problem["members"]:
        for window in (3, 5):
            print(
                json.dumps({"event": "start", "member": member["member"], "window": window}),
                flush=True,
            )
            reference = solve_reference(problem["document"], member["entry"], rules, window)
            print(
                json.dumps(
                    {
                        "event": "reference",
                        "member": member["member"],
                        "window": window,
                        **reference,
                    },
                    allow_nan=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
