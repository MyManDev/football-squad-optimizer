"""Paired, outcome-free shortlist stress test; never activates a production default."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from squadopt.application.advice_variants import weighted_horizon
from squadopt.application.top100_weight import load_top100_counts, top100_manifest_path
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.data.snapshots import read_snapshot
from squadopt.experiments.planning_shortlist import shortlist_horizon
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.recommendation import read_inputs
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanResult,
    optimize_transfer_plan,
    to_planning_horizon,
)

REGRESSION_LIMIT = 0.1
SPEED_RATIO_LIMIT = 0.8


@dataclass(frozen=True)
class Case:
    profile: int
    window: int
    weight: int
    mode: str = "plain"


def cases() -> list[Case]:
    result = [Case(p, w, a) for p in (1000, 950, 900) for w in (3, 5) for a in (0, 20, 50)]
    result += [
        Case(p, 5, 20, m)
        for p in (1000, 950, 900)
        for m in ("3xc", "bboost", "wildcard", "freehit", "constraints", "save")
    ]
    return result + [Case(1000, 3, a) for a in (5, 10, 30, 40)]


def restrictions(
    case: Case, horizon: PlanningHorizon, initial: InitialSquadState
) -> tuple[DecisionPreferences, ChipAvailability]:
    first = horizon.table.loc[horizon.table.gameweek.eq(horizon.gameweeks[0])]
    ordered = first.sort_values(["expected_points", "player_id"], ascending=[False, True])
    held = set(initial.squad_player_ids)
    preferences = DecisionPreferences()
    chips = ChipAvailability()
    if case.mode == "constraints":
        outside = set(first.player_id) - set(shortlist_horizon(horizon, initial).table.player_id)
        if not outside:
            raise ValueError("Constraint case requires a player outside the ordinary shortlist.")
        keep = int(ordered.loc[ordered.player_id.isin(held)].iloc[-1].player_id)
        avoid = int(ordered.loc[~ordered.player_id.isin(held)].iloc[0].player_id)
        preferences = DecisionPreferences(
            keep_players=(keep,),
            avoid_players=tuple(sorted({avoid, int(min(outside))})),
            no_hits=True,
        )
    elif case.mode == "save":
        preferences = DecisionPreferences(save_chips=True)
        chips = ChipAvailability(
            available={c: frozenset(horizon.gameweeks) for c in ("3xc", "bboost")}
        )
    elif case.mode != "plain":
        first_week = horizon.gameweeks[0]
        chips = ChipAvailability(
            available={case.mode: frozenset({first_week})}, forced={first_week: case.mode}
        )
    return preferences, chips


def score_plan(plan: TransferPlanResult, horizon: PlanningHorizon) -> float:
    """Re-score returned decisions on a supplied full table, including BB and TC."""
    total = 0.0
    for week in plan.weeks:
        points = (
            horizon.table.loc[horizon.table.gameweek.eq(week.gameweek)]
            .set_index("player_id")
            .expected_points
        )
        total += float(points.loc[week.starting_xi.player_id].sum())
        total += float(points.loc[week.captain.player_id]) * (2 if week.chip == "3xc" else 1)
        if week.chip == "bboost":
            total += float(points.loc[week.bench.player_id].sum())
        total -= week.transfer_hit_points
    return total


def audit_plan(
    plan: TransferPlanResult,
    base: PlanningHorizon,
    weighted: PlanningHorizon,
    preferences: DecisionPreferences,
    chips: ChipAvailability,
) -> dict[str, Any]:
    if not plan.has_solution:
        raise ValueError("Solver returned no feasible plan.")
    if tuple(w.gameweek for w in plan.weeks) != base.gameweeks:
        raise ValueError("Returned plan does not cover the full requested horizon.")
    for week in plan.weeks:
        ids = set(week.selected_squad.player_id)
        if not set(preferences.keep_players) <= ids or set(preferences.avoid_players) & ids:
            raise ValueError("Player preference was violated.")
        if (preferences.no_hits and week.transfer_hit_points) or (
            preferences.save_chips and week.chip
        ):
            raise ValueError("Hit/chip preference was violated.")
        if week.gameweek in chips.forced and week.chip != chips.forced[week.gameweek]:
            raise ValueError("Forced chip was not played.")
    objective = score_plan(plan, weighted)
    if plan.objective_value is None or not math.isclose(
        objective, plan.objective_value, abs_tol=1e-7
    ):
        raise ValueError("Unrounded objective does not match independent full-table rescore.")
    return {
        "weighted_net_points": objective,
        "base_net_points": score_plan(plan, base),
        "hit_points": plan.total_transfer_hit_points,
        "valid": True,
        "weeks": [
            {
                "week": w.gameweek,
                "chip": w.chip,
                "squad": sorted(int(p) for p in w.selected_squad.player_id),
                "starters": sorted(int(p) for p in w.starting_xi.player_id),
                "captain": int(w.captain.player_id),
                "in": sorted(int(p) for p in w.transfers_in.player_id),
                "out": sorted(int(p) for p in w.transfers_out.player_id),
                "bank": w.bank_after_tenths,
                "free_next": w.free_transfers_for_next_gameweek,
            }
            for w in plan.weeks
        ],
    }


def summarize(records: list[dict[str, Any]], expected_cases: int) -> dict[str, Any]:
    pairs = []
    failed = 0
    for row in records:
        full, short = (row["arms"].get(name, {}) for name in ("full", "shortlist"))
        if not all(arm.get("valid") is True for arm in (full, short)):
            failed += 1
            continue
        pairs.append(
            {
                "case": row["case"],
                "weighted_delta": short["weighted_net_points"] - full["weighted_net_points"],
                "base_delta": short["base_net_points"] - full["base_net_points"],
                "wall_ratio": short["wall_seconds"] / full["wall_seconds"],
                "full_status": full["status"],
                "shortlist_status": short["status"],
            }
        )
    regressions = sum(p["weighted_delta"] < -REGRESSION_LIMIT for p in pairs)
    median = statistics.median(p["wall_ratio"] for p in pairs) if pairs else None
    return {
        "expected_cases": expected_cases,
        "recorded_cases": len(records),
        "valid_pairs": len(pairs),
        "failed_pairs": failed,
        "weighted_regressions_over_0_1": regressions,
        "median_wall_ratio": median,
        "screen_passed": len(pairs) == expected_cases
        and not failed
        and not regressions
        and median is not None
        and median <= SPEED_RATIO_LIMIT,
        "production_activation": False,
        "independent_future_performance": False,
        "pairs": pairs,
    }


def run(
    snapshot_root: Path, artifact_root: Path, snapshot_id: str, evidence: Path, output: Path
) -> None:
    output.mkdir(parents=True, exist_ok=False)

    def write(name: str, value: Any) -> None:
        (output / name).write_text(
            json.dumps(value, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8"
        )

    inputs = read_inputs(read_snapshot(snapshot_root, snapshot_id), season="2026-27", gameweek=None)
    artifact = football_artifact_path(artifact_root, snapshot_id)
    forecast = read_football_forecast(artifact, inputs)
    counts = load_top100_counts(evidence, inputs=inputs, projection=forecast.projection)
    first_week = int(inputs.deadline.gameweek)
    forecast.build_horizon(tuple(range(first_week, first_week + 5)))
    config = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "src/squadopt/experiments/planning_shortlist.py",
        root / "src/squadopt/application/advice_variants.py",
        root / "src/squadopt/application/top100_weight.py",
        *sorted((root / "src/squadopt/planning").glob("*.py")),
    ]
    protocol = {
        "snapshot": snapshot_id,
        "captured_at": inputs.captured_at_utc,
        "forecast_fingerprint": forecast.fingerprint,
        "forecast_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "top100": counts.source_record(),
        "top100_manifest_sha256": hashlib.sha256(
            top100_manifest_path(evidence).read_bytes()
        ).hexdigest(),
        "sources": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources
        },
        "cases": [vars(c) for c in cases()],
        "squads": (
            "Constructed at budgets 1000/950/900; total funds 1000/1000/900; "
            "FT 1/2/0. Not owner holdings."
        ),
        "limits": {
            "wall_seconds": 120,
            "deterministic": 60,
            "hold_extra_wall": 30,
            "hold_extra_deterministic": 1,
        },
        "shortlist": (
            "Unchanged weekly top8 plus cheapest5 after weighting; "
            "retain holdings and all named keep/avoid IDs."
        ),
        "execution": "Sequential, alternating arm order by case index; no tuning or recourse.",
        "screen": {
            "max_weighted_regression": REGRESSION_LIMIT,
            "max_median_wall_ratio": SPEED_RATIO_LIMIT,
            "all_valid_required": True,
        },
        "scope": (
            "Single-capture development engineering evidence; forced chips test conditional "
            "decisions, not optimal chip timing. Same lagged counts repeated across the horizon."
        ),
        "activation": False,
        "outcomes_read": False,
    }
    write("protocol.json", protocol)
    profiles = {}
    first = forecast.horizon.table.loc[forecast.horizon.table.gameweek.eq(first_week)].copy()
    for budget, funds, ft in ((1000, 1000, 1), (950, 1000, 2), (900, 900, 0)):
        solved = optimize_squad(first, replace(config, budget_tenths=budget), linearization_level=2)
        if solved.solver_status is not SolverStatus.OPTIMAL:
            raise ValueError("Squad construction must be proved before paired comparisons.")
        profiles[budget] = InitialSquadState(
            tuple(int(p) for p in solved.selected_squad.player_id),
            funds - int(solved.selected_squad.price_tenths.sum()),
            ft,
        )
    write(
        "initial-states.json",
        {
            str(k): {"ids": v.squad_player_ids, "bank": v.bank_tenths, "ft": v.free_transfers}
            for k, v in profiles.items()
        },
    )
    records = []
    for index, case in enumerate(cases()):
        initial = profiles[case.profile]
        projection = forecast.build_horizon(tuple(range(first_week, first_week + case.window)))
        base = to_planning_horizon(projection)
        weighted = to_planning_horizon(weighted_horizon(projection, counts.counts, case.weight))
        preferences, chips = restrictions(case, weighted, initial)
        selected = shortlist_horizon(
            weighted,
            initial,
            required_players=(*preferences.keep_players, *preferences.avoid_players),
        )
        entry: dict[str, Any] = {
            "case": vars(case),
            "base_fingerprint": base.horizon_fingerprint,
            "weighted_fingerprint": weighted.horizon_fingerprint,
            "shortlist_fingerprint": selected.horizon_fingerprint,
            "preferences": preferences.payload(),
            "arms": {},
        }
        records.append(entry)
        for method in ("full", "shortlist") if index % 2 == 0 else ("shortlist", "full"):
            print(f"{index + 1}/40 {case} {method} START", flush=True)
            chosen = weighted if method == "full" else selected
            start = time.perf_counter()
            arm: dict[str, Any] = {
                "pool_size": chosen.table.player_id.nunique(),
                "proof_scope": method,
                "valid": False,
            }
            try:
                plan = optimize_transfer_plan(
                    chosen,
                    initial,
                    config,
                    chips=chips,
                    preferences=preferences,
                    linearization_level=2,
                    protect_hold=True,
                )
                arm.update(status=plan.solver_status.name, diagnostics=dict(plan.diagnostics))
                arm.update(audit_plan(plan, base, weighted, preferences, chips))
            except Exception as error:
                arm.update(status="FAILED", error_type=type(error).__name__, error=str(error))
            arm["wall_seconds"] = time.perf_counter() - start
            entry["arms"][method] = arm
            write("results.json", records)
            print(
                f"{index + 1}/40 {method}: {arm['status']} {arm.get('weighted_net_points')}",
                flush=True,
            )
    write("summary.json", summarize(records, len(cases())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "artifact-root", "evidence", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    arguments = parser.parse_args()
    run(
        arguments.snapshot_root,
        arguments.artifact_root,
        arguments.snapshot_id,
        arguments.evidence,
        arguments.output,
    )
