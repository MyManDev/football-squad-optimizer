"""Full-universe, shared-continuation ablation on immutable captured projections."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.measure_shortlist_matrix import audit_plan

from squadopt.application.advice_variants import weighted_horizon
from squadopt.application.planner_review import ObservationContext, review_observed_plans
from squadopt.application.top100_weight import load_top100_counts, top100_manifest_path
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.data.snapshots import read_snapshot
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.recommendation import read_inputs
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    to_planning_horizon,
)
from squadopt.planning.recourse import ObservationNode
from squadopt.planning.recourse_chips import net_week_points


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
    cases = [(p, w, a, False) for p in (1000, 900) for w in (3, 5) for a in (0, 20, 50)]
    cases += [(p, 5, 20, True) for p in (1000, 900)]
    config = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "scripts/measure_shortlist_matrix.py",
        root / "src/squadopt/application/planner_review.py",
        root / "src/squadopt/application/advice_variants.py",
        root / "src/squadopt/application/top100_weight.py",
        *sorted((root / "src/squadopt/planning").glob("*.py")),
    ]
    analysis_at = datetime.now(UTC)
    write(
        "protocol.json",
        {
            "snapshot": snapshot_id,
            "analysis_issued_at": analysis_at.isoformat(),
            "historical_decision_replay": False,
            "authored_after_capture": True,
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
            "candidate_count": 1,
            "pool": "full universe",
            "observation": (
                "0.5/0.5 +/-30% future points for highest current projected held non-GK, ties by ID"
            ),
            "preferences": (
                "Optional keep that held player, no hits and save chips; no available chips"
            ),
            "solver": {
                "wall_seconds": 120,
                "deterministic": 60,
                "hold_probe_wall": 30,
                "hold_probe_deterministic": 1,
            },
            "comparison": (
                "Baseline-plus-hold subset versus expanded menu, EXACT same continuation solves"
            ),
            "metric": (
                "Paired weighted and raw forecast-net value; minimum node and expected hit costs"
            ),
            "scope": (
                "Single-capture constructed-squad sensitivity; not "
                "calibrated probabilities or realized returns"
            ),
            "tuning": False,
            "promotion": False,
            "outcomes_read": False,
        },
    )
    records: list[dict[str, Any]] = []
    for profile, window, weight, constrained in cases:
        case: dict[str, Any] = dict(
            profile=profile, window=window, weight=weight, constrained=constrained
        )
        started = time.perf_counter()
        print(f"START {case}", flush=True)
        try:
            raw = profiles[str(profile)]
            state = InitialSquadState(tuple(raw["ids"]), raw["bank"], raw["ft"])
            projection = forecast.build_horizon(tuple(range(first, first + window)))
            base = to_planning_horizon(projection)
            weighted = to_planning_horizon(weighted_horizon(projection, counts.counts, weight))
            star = int(
                base.table.loc[
                    base.table.gameweek.eq(first)
                    & base.table.player_id.isin(state.squad_player_ids)
                    & base.table.position.ne("GK")
                ]
                .sort_values(["expected_points", "player_id"], ascending=[False, True])
                .iloc[0]
                .player_id
            )
            preferences = (
                DecisionPreferences(keep_players=(star,), no_hits=True, save_chips=True)
                if constrained
                else DecisionPreferences()
            )
            nodes, raw_nodes = [], {}
            for label, multiplier in (("low", 0.7), ("high", 1.3)):
                future = weighted.table.loc[weighted.table.gameweek.gt(first)].copy()
                raw_future = base.table.loc[base.table.gameweek.gt(first)].copy()
                future.loc[future.player_id.eq(star), "expected_points"] *= multiplier
                raw_future.loc[raw_future.player_id.eq(star), "expected_points"] *= multiplier
                nodes.append(ObservationNode(label, 0.5, PlanningHorizon(future)))
                raw_nodes[label] = PlanningHorizon(raw_future)
            cutoff = datetime.fromisoformat(inputs.captured_at_utc.replace("Z", "+00:00"))
            review = review_observed_plans(
                base,
                state,
                [
                    ObservationNode(n.observation_id, n.probability, raw_nodes[n.observation_id])
                    for n in nodes
                ],
                config,
                context=ObservationContext(
                    snapshot_id,
                    analysis_at,
                    cutoff,
                    "Retrospective authored +/-30% sensitivity, not calibrated",
                ),
                decision_cutoff=analysis_at,
                selected_weight=weight,
                alternatives=(),
                counts=counts,
                preferences=preferences,
            )
            result = review.options[0].rollout
            candidates = []
            for candidate in result.candidates:
                week = candidate.first_week
                points = (
                    base.table.loc[base.table.gameweek.eq(first)]
                    .set_index("player_id")
                    .expected_points
                )
                current = (
                    float(points.loc[week.starting_xi.player_id].sum())
                    + float(points.loc[week.captain.player_id])
                    - week.transfer_hit_points
                )
                branches = []
                for branch, node in zip(candidate.continuations, nodes, strict=True):
                    audited = audit_plan(
                        branch.plan,
                        raw_nodes[node.observation_id],
                        node.horizon,
                        preferences,
                        ChipAvailability(),
                    )
                    branches.append(
                        {
                            "observation": branch.observation_id,
                            "probability": branch.probability,
                            "status": branch.plan.solver_status.name,
                            "diagnostics": dict(branch.plan.diagnostics),
                            **audited,
                        }
                    )
                weighted_score = net_week_points(week) + sum(
                    b["probability"] * b["weighted_net_points"] for b in branches
                )
                if not math.isclose(weighted_score, candidate.expected_net_points, abs_tol=1e-7):
                    raise ValueError("Independent branch scoring failed.")
                candidates.append(
                    {
                        "weighted_net": weighted_score,
                        "base_net": current
                        + sum(b["probability"] * b["base_net_points"] for b in branches),
                        "minimum_node_base_net": current
                        + min(b["base_net_points"] for b in branches),
                        "expected_hits": week.transfer_hit_points
                        + sum(b["probability"] * b["hit_points"] for b in branches),
                        "first_squad": sorted(int(p) for p in week.selected_squad.player_id),
                        "first_in": sorted(int(p) for p in week.transfers_in.player_id),
                        "first_out": sorted(int(p) for p in week.transfers_out.player_id),
                        "first_captain": int(week.captain.player_id),
                        "first_bank": week.bank_after_tenths,
                        "first_ft_next": week.free_transfers_for_next_gameweek,
                        "branches": branches,
                    }
                )
            control_index = max(
                result.baseline_candidate_indices, key=lambda i: candidates[i]["weighted_net"]
            )
            control, chosen = candidates[control_index], candidates[result.chosen_index]
            if review.selected_weight != weight or not math.isclose(
                chosen["base_net"], review.options[0].base_expected_net, abs_tol=1e-7
            ):
                raise ValueError("Application review selection/raw score parity failed.")
            case.update(
                status=result.selection_status,
                star=star,
                control_index=control_index,
                chosen_index=result.chosen_index,
                baseline_indices=result.baseline_candidate_indices,
                weighted_delta=chosen["weighted_net"] - control["weighted_net"],
                base_delta=chosen["base_net"] - control["base_net"],
                candidates=candidates,
                proposal_statuses=result.proposal_statuses,
                hold_feasible=result.hold_feasible,
            )
        except Exception as error:
            case.update(status="FAILED", error=str(error))
        case["wall_seconds"] = time.perf_counter() - started
        records.append(case)
        write("results.json", records)
        print(
            f"DONE {profile}/{window}/{weight}/{constrained}: {case['status']} "
            f"delta={case.get('weighted_delta')}",
            flush=True,
        )
    write(
        "summary.json",
        {
            "cases": len(records),
            "failures": sum(r["status"] == "FAILED" for r in records),
            "promotion": False,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "artifact-root", "evidence", "states", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    run(**vars(parser.parse_args()))
