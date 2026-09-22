"""Measure hold, deterministic and observation-contingent plans on a named capture.

Requires completed measure_football_components.py evidence and frozen recommendations.
Outputs are forward sensitivity evidence, never realized policy gain or promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import traceback
from pathlib import Path

import pandas as pd

from squadopt.application.football_context import bind_football_context
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.football_history import archive_history
from squadopt.experiments.football_components import ComponentForecast, Components
from squadopt.live import read_inputs
from squadopt.live.football_horizon import build_football_horizon
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.horizon import to_planning_horizon
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse
from squadopt.prediction.football_contextual import ContextualFootballModel


def run(args):
    study, out = args.study, args.output
    out.mkdir(parents=True, exist_ok=False)
    tree = Path(__file__).resolve().parents[1]

    def write(name, value):
        (out / name).write_text(
            json.dumps(value, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8"
        )

    def read(path):
        table = pd.read_csv(path, low_memory=False)
        for col in ("kickoff", "feature_cutoff"):
            if col in table:
                table[col] = pd.to_datetime(table[col], utc=True)
        return table

    snap = read_snapshot(args.snapshots, args.snapshot_id)
    evidence = json.loads((study / "input-evidence.json").read_text())
    if (
        snap.metadata.snapshot_id != evidence["snapshot_id"]
        or snap.metadata.fingerprint != evidence["snapshot_fingerprint"]
    ):
        raise ValueError("Forward capture must match the measured source identity.")
    if hashlib.sha256(args.training.read_bytes()).hexdigest() != evidence["training_sha256"]:
        raise ValueError("Forward training must match the measured corpus.")
    inputs = read_inputs(snap, season="2026-27")
    if int(inputs.deadline.gameweek) != 6:
        raise ValueError("This prespecified study requires the GW6 decision capture.")
    cutoff = pd.Timestamp(inputs.captured_at_utc)
    raw = archive_history(args.archive)
    raw = pd.concat([raw, read(study / "current-history.csv")], ignore_index=True)
    train = read(args.training)
    train = train.loc[train.season.ne("2022-23")].copy()
    missing = [c for c in ("starts", "appeared", "long") if c not in train]
    if missing:
        train = train.merge(
            raw[["season", "fixture", "player_code", *missing]],
            on=["season", "fixture", "player_code"],
            validate="one_to_one",
        )
    train = pd.concat([train, read(study / "current-causal-training.csv")], ignore_index=True)
    assert (raw.kickoff + pd.Timedelta(hours=3) < cutoff).all()
    print("FORWARD FIT", flush=True)
    fitted = ContextualFootballModel(train, raw, cutoff=cutoff)
    recommendations = json.loads((study / "frozen-recommendations.json").read_text())
    params = next(
        r["parameters"] for r in recommendations if r["method"] == "botorch" and r["seed"] == 0
    )

    class ResearchModel(ContextualFootballModel):
        model_version = "football_component_research"

        def __init__(self, reference, history, switches, parameters):
            self.reference, self.history, self.switches, self.parameters = (
                reference,
                history,
                switches,
                parameters,
            )
            self.cutoff = reference.cutoff

        def predict(self, target, *, role_steps=0):
            if role_steps:
                raise ValueError("No role transition")
            return ComponentForecast(self.reference, self.history, target).predict(
                self.switches, attack_only=True, **self.parameters
            )

    boot = json.loads(snap.payloads["bootstrap-static.json"])
    clubs = {t["id"]: t["code"] for t in boot["teams"]}
    player_clubs = {p["code"]: clubs[p["team"]] for p in boot["elements"]}
    roster = inputs.players.copy()
    roster["club"] = roster.player_id.map(player_clubs)
    roster, _audit = bind_football_context(
        roster, inputs.availability, season="2026-27", gameweek=6, cutoff=cutoff, manager_words=None
    )
    fixtures = pd.DataFrame(json.loads(snap.payloads["fixtures.json"]))
    fixtures = fixtures.loc[fixtures.event.isin(range(6, 11))]
    calendar = pd.concat(
        [
            pd.DataFrame(
                {
                    "fixture": fixtures.id,
                    "club": fixtures["team_h" if home else "team_a"].map(clubs),
                    "opponent": fixtures["team_a" if home else "team_h"].map(clubs),
                    "home": float(home),
                    "GW": fixtures.event,
                    "kickoff": pd.to_datetime(fixtures.kickoff_time, utc=True),
                }
            )
            for home in (True, False)
        ],
        ignore_index=True,
    )
    opt = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    horizons = {}
    for label, switch, parameters in [
        ("control", Components(), {}),
        ("botorch", Components(True, True), params),
    ]:
        model = ResearchModel(fitted, raw, switch, parameters)
        horizon, components = build_football_horizon(
            model,
            raw,
            roster,
            calendar,
            gameweeks=(6, 7, 8, 9, 10),
            season="2026-27",
            source_snapshot_id=inputs.snapshot_id,
            captured_at=cutoff,
        )
        horizon.table.to_csv(out / (label + "-projections.csv"), index=False)
        components.to_csv(out / (label + "-components.csv"), index=False)
        horizons[label] = to_planning_horizon(horizon)
        print(label + " FORECAST READY", flush=True)
    first = horizons["control"].table.query("gameweek == 6").copy()
    first["price_tenths"] = first.buy_price_tenths
    initial_solve = optimize_squad(first, opt, linearization_level=2)
    assert initial_solve.solver_status is SolverStatus.OPTIMAL
    ids = tuple(int(x) for x in initial_solve.selected_squad.player_id)
    bank = 1000 - int(initial_solve.selected_squad.price_tenths.sum())
    initial = InitialSquadState(ids, bank, 1)
    star = int(
        first.loc[first.player_id.isin(ids)]
        .sort_values(["expected_points", "player_id"], ascending=[False, True])
        .iloc[0]
        .player_id
    )
    write(
        "source-hashes.json",
        {
            "script": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "frozen_recommendations": hashlib.sha256(
                (study / "frozen-recommendations.json").read_bytes()
            ).hexdigest(),
            "component_engine": hashlib.sha256(
                (tree / "src/squadopt/experiments/football_components.py").read_bytes()
            ).hexdigest(),
        },
    )
    write(
        "protocol.json",
        {
            "snapshot_id": inputs.snapshot_id,
            "capture": inputs.captured_at_utc,
            "initial_squad": "constructed from frozen control GW6, not owner holdings",
            "initial_player_ids": ids,
            "bank_tenths": bank,
            "free_transfers": 1,
            "chips": "none, equal for all arms",
            "observation": (
                "equal-probability +/-30% future expected points of highest projected held player; "
                "stress sensitivity, not calibrated"
            ),
            "observation_player_id": star,
            "windows": [3, 5],
            "parameters_frozen_before_outer": params,
            "solver_wall_seconds": 120,
            "solver_deterministic_limit": 60,
            "future_actual_outcomes": False,
            "promotion": False,
        },
    )
    records = []

    def report(plan):
        return {
            "status": plan.solver_status.value,
            "solver_diagnostics": dict(plan.diagnostics),
            "expected_net_points": None
            if plan.total_projected_score is None
            else plan.total_projected_score - plan.total_transfer_hit_points,
            "hit_points": plan.total_transfer_hit_points,
            "weeks": [
                {
                    "gameweek": w.gameweek,
                    "captain": int(w.captain.player_id),
                    "starting_xi": [int(x) for x in w.starting_xi.player_id],
                    "free_transfers_before": w.free_transfers_before,
                    "free_transfers_next": w.free_transfers_for_next_gameweek,
                    "transfers_in": [int(x) for x in w.transfers_in.player_id],
                    "transfers_out": [int(x) for x in w.transfers_out.player_id],
                    "hit_points": w.transfer_hit_points,
                    "chip": w.chip,
                }
                for w in plan.weeks
            ],
        }

    for label, full in horizons.items():
        for window in (3, 5):
            horizon = PlanningHorizon(full.table.loc[full.table.gameweek.lt(6 + window)].copy())
            for method in ("hold", "deterministic", "recourse"):
                print(f"{label} {window}wk {method} START", flush=True)
                start = time.perf_counter()
                entry = {
                    "model": label,
                    "window": window,
                    "method": method,
                    "horizon_fingerprint": horizon.horizon_fingerprint,
                }
                try:
                    if method == "hold":
                        held = PlanningHorizon(
                            horizon.table.loc[horizon.table.player_id.isin(ids)].copy()
                        )
                        plan = optimize_transfer_plan(held, initial, opt, linearization_level=2)
                        entry.update(report(plan))
                    elif method == "deterministic":
                        plan = optimize_transfer_plan(horizon, initial, opt, linearization_level=2)
                        entry.update(report(plan))
                    else:
                        nodes = []
                        for name, multiplier in [("low", 0.7), ("high", 1.3)]:
                            table = horizon.table.loc[horizon.table.gameweek.gt(6)].copy()
                            table.loc[table.player_id.eq(star), "expected_points"] *= multiplier
                            nodes.append(ObservationNode(name, 0.5, PlanningHorizon(table)))
                        result = optimize_observed_recourse(
                            horizon,
                            initial,
                            nodes,
                            opt,
                            candidate_count=1,
                            value_extra_free_transfer=True,
                        )
                        best = result.candidates[result.chosen_index]
                        entry.update(
                            status="OPTIMAL_RESTRICTED_MENU",
                            expected_net_points=best.expected_net_points,
                            candidates=len(result.candidates),
                            hold_feasible=result.hold_feasible,
                            first_captain=int(best.first_week.captain.player_id),
                            first_transfers_in=[
                                int(x) for x in best.first_week.transfers_in.player_id
                            ],
                            first_transfers_out=[
                                int(x) for x in best.first_week.transfers_out.player_id
                            ],
                            continuations=[
                                {
                                    "observation": v.observation_id,
                                    "extra_free_transfer_value": v.extra_free_transfer_value,
                                    **report(v.plan),
                                }
                                for v in best.continuations
                            ],
                        )
                except Exception as error:
                    entry.update(
                        status="FAILED", error=str(error), traceback=traceback.format_exc()
                    )
                entry["seconds"] = time.perf_counter() - start
                records.append(entry)
                write("results.json", records)
                print(
                    f"{label} {window}wk {method}: "
                    + str(entry.get("expected_net_points", entry.get("error"))),
                    flush=True,
                )
    write(
        "summary.json",
        {
            "cases": len(records),
            "failed": sum(x["status"] == "FAILED" for x in records),
            "unproved": sum(not x["status"].startswith("OPTIMAL") for x in records),
            "future_realized_gain_verified": False,
            "production_promotion": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "training", "snapshots", "study", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    run(parser.parse_args())
