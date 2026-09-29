"""Paired full-pool temporal repair versus an unrestricted solver with equal configured caps."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.measure_shortlist_matrix import audit_plan

from squadopt.application.advice_variants import weighted_horizon
from squadopt.application.top100_weight import load_top100_counts, top100_manifest_path
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.data.snapshots import read_snapshot
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.recommendation import read_inputs
from squadopt.optimization import OptimizationConfig
from squadopt.planning import ChipAvailability, InitialSquadState, to_planning_horizon
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.refinement import optimize_refined_plan


def run(
    snapshot_root: Path,
    artifact_root: Path,
    snapshot_id: str,
    evidence: Path,
    states: Path,
    output: Path,
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
    profiles = json.loads(states.read_text(encoding="utf-8"))
    first = int(inputs.deadline.gameweek)
    cases = [(p, w, a, "plain") for p in (1000, 900) for w in (3, 5) for a in (0, 20, 50)]
    cases += [(p, 5, 20, m) for p in (1000, 900) for m in ("preferences", "freehit")]
    config = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "scripts/measure_shortlist_matrix.py",
        root / "src/squadopt/application/advice_variants.py",
        root / "src/squadopt/application/top100_weight.py",
        *sorted((root / "src/squadopt/planning").glob("*.py")),
    ]
    write(
        "protocol.json",
        {
            "analysis_at": datetime.now(UTC).isoformat(),
            "snapshot": snapshot_id,
            "forecast_fingerprint": forecast.fingerprint,
            "forecast_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "states_sha256": hashlib.sha256(states.read_bytes()).hexdigest(),
            "top100": counts.source_record(),
            "top100_manifest_sha256": hashlib.sha256(
                top100_manifest_path(evidence).read_bytes()
            ).hexdigest(),
            "sources": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
            "cases": cases,
            "pool": "full universe",
            "outcomes_read": False,
            "tuning": False,
            "repair": (
                "One forward sweep, free each adjacent pair; fix other squads to incumbent; "
                "full-horizon constraints; retain better complete incumbent"
            ),
            "caps": (
                "Baseline120wall/60det plus each repair30wall/15det. "
                "Control120+30*(w-1)wall/60+15*(w-1)det. Both initial solves add existing "
                "hold30wall/1det; repairs no hold. Wall ceilings may apply separately to tie "
                "phase; actual diagnostics recorded."
            ),
            "order": "control first on even cases, refinement first on odd cases",
            "screen": (
                "16 legal pairs, no incumbent regression, at least one gain>0.1 versus "
                "control, no loss>0.1 versus control"
            ),
            "scope": (
                "Constructed-squad, single-capture development engineering. Not independent "
                "future returns, forecast calibration, or automatic activation."
            ),
        },
    )
    records: list[dict[str, Any]] = []
    for index, (profile, window, weight, mode) in enumerate(cases):
        record: dict[str, Any] = dict(
            profile=profile, window=window, weight=weight, mode=mode, arms={}
        )
        print(f"START {profile}/{window}/{weight}/{mode}", flush=True)
        raw = profiles[str(profile)]
        state = InitialSquadState(tuple(raw["ids"]), raw["bank"], raw["ft"])
        projection = forecast.build_horizon(tuple(range(first, first + window)))
        base = to_planning_horizon(projection)
        weighted = to_planning_horizon(weighted_horizon(projection, counts.counts, weight))
        ordered = base.table.loc[
            base.table.gameweek.eq(first)
            & base.table.player_id.isin(state.squad_player_ids)
            & base.table.position.ne("GK")
        ].sort_values(["expected_points", "player_id"], ascending=[False, True])
        preferences = (
            DecisionPreferences(
                keep_players=(int(ordered.iloc[0].player_id),), no_hits=True, save_chips=True
            )
            if mode == "preferences"
            else DecisionPreferences()
        )
        chips = (
            ChipAvailability(available={"freehit": frozenset({first})}, forced={first: "freehit"})
            if mode == "freehit"
            else ChipAvailability()
        )
        if mode == "preferences":
            chips = ChipAvailability(
                available={c: frozenset(base.gameweeks) for c in ("3xc", "bboost")}
            )
        for arm in ("control", "refined") if index % 2 == 0 else ("refined", "control"):
            started = time.perf_counter()
            try:
                extra: dict[str, Any] = {}
                if arm == "control":
                    plan = optimize_transfer_plan(
                        weighted,
                        state,
                        replace(
                            config,
                            solver_time_limit_seconds=120 + 30 * (window - 1),
                            solver_deterministic_time_limit=60 + 15 * (window - 1),
                        ),
                        chips=chips,
                        preferences=preferences,
                        protect_hold=True,
                        linearization_level=2,
                    )
                else:
                    result = optimize_refined_plan(
                        weighted, state, config, chips=chips, preferences=preferences
                    )
                    plan = result.chosen
                    baseline = audit_plan(result.baseline, base, weighted, preferences, chips)
                    history = []
                    for step in result.steps:
                        info = dict(
                            pair=step.free_gameweeks,
                            accepted=step.accepted,
                            before=step.objective_before,
                            after=step.objective_after,
                            status=step.candidate.solver_status.name,
                            diagnostics=dict(step.candidate.diagnostics),
                        )
                        if step.candidate.has_solution:
                            info.update(
                                audit_plan(step.candidate, base, weighted, preferences, chips)
                            )
                        history.append(info)
                    extra = dict(
                        proof_status=result.proof_status,
                        baseline=baseline,
                        baseline_diagnostics=dict(result.baseline.diagnostics),
                        steps=history,
                    )
                    if (
                        plan.objective_value is None
                        or plan.objective_value < baseline["weighted_net_points"] - 1e-8
                    ):
                        raise ValueError("Incumbent regression.")
                record["arms"][arm] = dict(
                    **audit_plan(plan, base, weighted, preferences, chips),
                    status=plan.solver_status.name,
                    diagnostics=dict(plan.diagnostics),
                    **extra,
                )
            except Exception as error:
                record["arms"][arm] = dict(valid=False, error=str(error))
            record["arms"][arm]["wall_seconds"] = time.perf_counter() - started
            print(f"ARM {arm}: valid={record['arms'][arm]['valid']}", flush=True)
        records.append(record)
        write("results.json", records)
        print(f"DONE {len(records)}/{len(cases)}", flush=True)
    pairs = [r for r in records if all(a.get("valid") for a in r["arms"].values())]
    deltas = [
        r["arms"]["refined"]["weighted_net_points"] - r["arms"]["control"]["weighted_net_points"]
        for r in pairs
    ]
    write(
        "summary.json",
        dict(
            cases=len(records),
            valid_pairs=len(pairs),
            failures=len(records) - len(pairs),
            weighted_gains_over_0_1=sum(d > 0.1 for d in deltas),
            weighted_losses_over_0_1=sum(d < -0.1 for d in deltas),
            screen_passed=len(pairs) == len(cases)
            and any(d > 0.1 for d in deltas)
            and all(d >= -0.1 for d in deltas),
            promotion=False,
            independent_future_performance=False,
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "artifact-root", "evidence", "states", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    run(**vars(parser.parse_args()))
