"""Compare a fixed forecast-only shortlist with the full protected planning pool."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from squadopt.experiments.planning_shortlist import shortlist_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse


def run(study: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        (output / name).write_text(json.dumps(value, indent=2, default=str, allow_nan=False) + "\n")

    original = json.loads((study / "protocol.json").read_text())
    old = json.loads((study / "results.json").read_text())
    frame = pd.read_csv(study / "control-projections.csv", float_precision="round_trip")
    table = frame[
        [
            "gameweek",
            "player_id",
            "name",
            "team_id",
            "position",
            "expected_points",
            "appearance_probability",
        ]
    ].copy()
    table["buy_price_tenths"] = frame.price_tenths
    table["sell_price_tenths"] = frame.price_tenths
    ids = tuple(original["initial_player_ids"])
    initial = InitialSquadState(ids, original["bank_tenths"], original["free_transfers"])
    star = original["observation_player_id"]
    opt = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    root = Path(__file__).resolve().parents[1]
    sources = [Path(__file__), *sorted((root / "src/squadopt/planning").glob("*.py"))]
    write(
        "source-hashes.json",
        {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
    )
    write(
        "input-hashes.json",
        {
            name: hashlib.sha256((study / name).read_bytes()).hexdigest()
            for name in ("protocol.json", "results.json", "control-projections.csv")
        },
    )
    write(
        "protocol.json",
        {
            "source_capture": original["snapshot_id"],
            "windows": [3, 5],
            "methods": ["full", "shortlist", "recourse"],
            "forecast": "Frozen control table, identical to the previous study.",
            "holdings": "Same constructed squad and bank/FT, not owner holdings.",
            "observation": original["observation"],
            "chips": "none",
            "wall_seconds_per_solve": 120,
            "deterministic_limit_per_solve": 60,
            "protection_extra_budget": "Hold probe: up to 30 wall seconds / 1 deterministic unit.",
            "recourse": "One action plus hold; proved subproblems; extra FT diagnostic.",
            "method_total_costs_equal": False,
            "shortlist": "Weekly top8 + cheapest5 by position + holdings; fixed before results",
            "tuning": False,
            "promotion": False,
            "realized_policy_returns": False,
            "calibrated_observation_probabilities": False,
        },
    )

    def report(plan):
        return {
            "status": plan.solver_status.name,
            "expected_net_points": None
            if plan.total_projected_score is None
            else plan.total_projected_score - plan.total_transfer_hit_points,
            "hit_points": plan.total_transfer_hit_points,
            "diagnostics": dict(plan.diagnostics),
            "weeks": [
                {
                    "gameweek": w.gameweek,
                    "chip": w.chip,
                    "captain": int(w.captain.player_id),
                    "transfers_in": [int(x) for x in w.transfers_in.player_id],
                    "transfers_out": [int(x) for x in w.transfers_out.player_id],
                    "hit_points": w.transfer_hit_points,
                }
                for w in plan.weeks
            ],
        }

    records = []
    for window in (3, 5):
        horizon = PlanningHorizon(table.loc[table.gameweek.lt(6 + window)].copy())
        reference = next(
            x
            for x in old
            if x["model"] == "control" and x["window"] == window and x["method"] == "deterministic"
        )
        if horizon.horizon_fingerprint != reference["horizon_fingerprint"]:
            raise ValueError("Frozen horizon fingerprint no longer matches the recorded input.")
        for method in ("full", "shortlist", "recourse"):
            start = time.perf_counter()
            entry = {
                "window": window,
                "method": method,
                "horizon_fingerprint": horizon.horizon_fingerprint,
            }
            print(f"{window}wk {method} START", flush=True)
            try:
                chosen = horizon if method == "full" else shortlist_horizon(horizon, initial)
                entry["pool_size"] = chosen.table.player_id.nunique()
                entry["proof_scope"] = "full_roster" if method == "full" else "restricted_shortlist"
                if method != "recourse":
                    plan = optimize_transfer_plan(
                        chosen,
                        initial,
                        opt,
                        linearization_level=2,
                        protect_hold=True,
                    )
                    entry.update(report(plan))
                else:
                    nodes = []
                    for name, multiplier in (("low", 0.7), ("high", 1.3)):
                        future = chosen.table.loc[chosen.table.gameweek.gt(6)].copy()
                        future.loc[future.player_id.eq(star), "expected_points"] *= multiplier
                        nodes.append(ObservationNode(name, 0.5, PlanningHorizon(future)))
                    solved = optimize_observed_recourse(
                        chosen,
                        initial,
                        nodes,
                        opt,
                        candidate_count=1,
                        value_extra_free_transfer=True,
                    )
                    best = solved.candidates[solved.chosen_index]
                    entry.update(
                        status="OPTIMAL_RESTRICTED_MENU",
                        expected_net_points=best.expected_net_points,
                        first_transfers_in=[int(x) for x in best.first_week.transfers_in.player_id],
                        candidates=len(solved.candidates),
                        hold_feasible=solved.hold_feasible,
                        continuations=[
                            {
                                "observation": c.observation_id,
                                "extra_free_transfer_value": c.extra_free_transfer_value,
                                **report(c.plan),
                            }
                            for c in best.continuations
                        ],
                    )
            except Exception as error:
                entry.update(status="FAILED", error=str(error))
            entry["wall_seconds"] = time.perf_counter() - start
            records.append(entry)
            write("results.json", records)
            print(
                f"{window}wk {method}: {entry['status']}, {entry.get('expected_net_points')}",
                flush=True,
            )
    write(
        "summary.json",
        {
            "cases": len(records),
            "failed": sum(r["status"] == "FAILED" for r in records),
            "unproved": sum(not r["status"].startswith("OPTIMAL") for r in records),
            "promotion": False,
            "realized_policy_returns": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("study", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.study, args.output)
