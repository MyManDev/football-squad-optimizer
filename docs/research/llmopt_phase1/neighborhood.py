"""A declared small-pool diagnostic beside the full-pool expected-window replay.

The full-pool run's seed-completion gate can prevent either optional neighborhood from
running. Keep that negative coverage result; this separate diagnostic asks whether the
one-versus-two proposal actually runs when the very same 60-unit budget can complete
construction. Never replace a full-pool number with this restricted-pool result.
"""

import argparse
from dataclasses import replace
from pathlib import Path

from docs.research.llmopt_phase1.benchmark import (
    HERE,
    ROOT,
    expected_comparison,
    provenance,
    snapshots,
    write,
)
from scripts.measure_window_solver_highs import window_call

from squadopt.planning import PlanningHorizon


def candidate_ids(call, frozen):
    """Held fifteen, top four by forecast and cheapest two per position, ties by ID."""
    projection = frozen["projection"]
    first = call.horizon.table.loc[call.horizon.table.gameweek.eq(call.horizon.gameweeks[0])]
    first = first.loc[first.player_id.map(str).isin(projection["appearance_probability"])]
    ids = set(call.state.squad_player_ids)
    for position in ("GK", "DEF", "MID", "FWD"):
        players = first.loc[first.position.eq(position)].copy()
        players["forecast"] = players.player_id.map(lambda p: projection["expected_points"][str(p)])
        ids.update(
            players.sort_values(["forecast", "player_id"], ascending=[False, True])
            .head(4)
            .player_id
        )
        ids.update(players.sort_values(["buy_price_tenths", "player_id"]).head(2).player_id)
    return sorted(int(p) for p in ids)


def measure(output, limit):
    results = []
    for frozen, inputs in snapshots():
        for entry in sorted(inputs.members):
            if limit is not None and len(results) >= limit:
                break
            call = window_call(inputs, entry, 3)
            ids = candidate_ids(call, frozen)
            # Only the candidate universe changes, identically in the two arms.
            call = replace(
                call,
                horizon=PlanningHorizon(
                    call.horizon.table.loc[call.horizon.table.player_id.isin(ids)]
                ),
            )
            case = f"gw{inputs.gameweek}-{entry}"
            print(f"restricted {case} players={len(ids)}", flush=True)
            result = expected_comparison(call, frozen)
            write(ROOT / "artifacts/llmopt_phase1_neighborhood" / f"{case}.json", result)
            row = dict(
                case=case,
                candidate_ids=ids,
                selection_utility_gain_points=result["selection_utility_gain_points"],
                expected_net_gain_points=result["expected_net_gain_points"],
            )
            for arm in ("single", "up_to_two"):
                plan = result[arm]
                review = plan["expected_window"]
                row[arm] = {
                    k: plan[k]
                    for k in (
                        "seconds",
                        "proof",
                        "solver_status",
                        "best_bound",
                        "absolute_gap_points",
                        "expected_net_points",
                        "solver_calls",
                    )
                }
                row[arm].update(
                    chosen=review["chosen"],
                    actual_units=review["actual_total"],
                    optional=review["optional_swap"],
                    lineup_evaluations=review.get("lineup_evaluations"),
                )
            results.append(row)
            write(
                output,
                dict(
                    kind="llmopt_phase1_restricted_neighborhood",
                    **provenance(),
                    population="same 20 member-weeks, separate restricted universe",
                    protocol="held + top four forecast + cheapest two per position; ID ties",
                    configured_deterministic_units=60,
                    wall_safety_seconds=1800,
                    lineup_evaluation_cap=1153,
                    rows=results,
                ),
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--output", type=Path, default=HERE.parent / "llmopt_phase1_neighborhood.json"
    )
    args = parser.parse_args()
    measure(args.output, args.limit)
