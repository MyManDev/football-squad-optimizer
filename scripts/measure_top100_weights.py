"""Compare discrete Top-100 weights on captured member decisions, without publishing.

This is decision sensitivity, not evidence of realized improvement. The output explicitly
leaves realized points unavailable until matching settled, deadline-safe folds exist.
Raw member identifiers remain in the local, git-ignored output only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from squadopt.application.advice import AdviseEntryRequest, advise_entry, member_horizon_builder
from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.entries import EntryRegistry
from squadopt.application.top100_weight import weighted_member_inputs
from squadopt.data.snapshots import read_snapshot
from squadopt.features.evidence_artifact import read_player_evidence_artifact
from squadopt.live import project, read_inputs, read_projection_handoff, read_season_rules
from squadopt.prediction.elite_evidence import TOP100_WEIGHT_PERCENTAGES, apply_elite_evidence


def summarize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare decisions and base-model costs on matched solved members only."""
    baseline = {
        (row["window"], row["member"]): row
        for row in rows
        if row["weight_percent"] == 0 and row["status"] == "solved"
    }
    summaries = []
    for window, weight in sorted({(r["window"], r["weight_percent"]) for r in rows}):
        arm = [r for r in rows if (r["window"], r["weight_percent"]) == (window, weight)]
        solved = [r for r in arm if r["status"] == "solved"]
        pairs = [
            (r, baseline[(window, r["member"])])
            for r in solved
            if (window, r["member"]) in baseline
        ]

        def moves(row: dict[str, Any]) -> set[tuple[int, int]]:
            return {tuple(pair) for pair in row["moves"]}

        summaries.append(
            {
                "window": window,
                "weight_percent": weight,
                "members": len(arm),
                "solved": len(solved),
                "refused": len(arm) - len(solved),
                "matched": len(pairs),
                "optimal": sum(r["solver_status"] == "OPTIMAL" for r in solved),
                "changed_first_week": sum(
                    moves(r) != moves(b)
                    or set(r["starting_xi"]) != set(b["starting_xi"])
                    or r["captain"] != b["captain"]
                    for r, b in pairs
                ),
                "changed_moves": sum(moves(r) != moves(b) for r, b in pairs),
                "changed_captain": sum(r["captain"] != b["captain"] for r, b in pairs),
                "changed_xi": sum(set(r["starting_xi"]) != set(b["starting_xi"]) for r, b in pairs),
                "base_first_week_net_delta": statistics.mean(
                    r["base_first_week_net"] - b["base_first_week_net"] for r, b in pairs
                )
                if pairs
                else None,
                "mean_xi_support": statistics.mean(r["mean_xi_support"] for r in solved)
                if solved
                else None,
                "realized_net_points": None,
            }
        )
    return summaries


def measure_arm(arguments: dict[str, Any], weight: int, window: int) -> list[dict[str, Any]]:
    snapshot = read_snapshot(arguments["snapshots"], arguments["snapshot"])
    handoff = read_projection_handoff(Path(arguments["handoff"]))
    # Removing an unknown earlier adjustment would silently stack the signal.
    if handoff.evidence_fingerprint is not None:
        raise ValueError("Measurement requires the unadjusted component/control handoff.")
    inputs = read_inputs(snapshot, season=handoff.season, gameweek=handoff.gameweek)
    base = project(inputs, in_season=handoff)
    evidence_path = Path(arguments["evidence"])
    evidence = read_player_evidence_artifact(
        evidence_path, evidence_path.with_suffix(".manifest.json")
    )
    apply_elite_evidence(
        base.table,
        evidence,
        season=inputs.season,
        target_gameweek=handoff.gameweek,
        deadline_timestamp_utc=inputs.deadline.deadline_utc,
        decision_captured_at_utc=inputs.captured_at_utc,
        top100_weight_percent=weight,
    )
    counts = evidence.set_index("player_id")["elite_start_count_lag1"].to_dict()
    builder = member_horizon_builder(snapshot, season=inputs.season, in_season=handoff)

    candidate, candidate_horizon = weighted_member_inputs(
        base, builder, source_weight=0, requested_weight=weight, counts=counts
    )

    registry = EntryRegistry.load(Path(arguments["registry"]))
    members = sorted(registry.entries, key=lambda member: member.entry_id)
    if arguments["limit"]:
        members = members[: arguments["limit"]]
    if not members:
        raise ValueError("No registered members to measure.")
    provider = CapturePicksProvider(snapshot, inputs.snapshot_id)
    rules = read_season_rules(snapshot, season=inputs.season)
    base_points = base.table.set_index("player_id")["expected_points"].to_dict()
    rows = []
    for ordinal, member in enumerate(members, 1):
        started = time.perf_counter()
        row: dict[str, Any] = {
            "member": ordinal,
            "entry_id": member.entry_id,
            "weight_percent": weight,
            "window": window,
        }
        try:
            payload = advise_entry(
                AdviseEntryRequest(
                    inputs.season,
                    handoff.gameweek,
                    arguments["league"],
                    member.entry_id,
                    strategy="saf-puan",
                    window=window,
                ),
                provider=provider,
                inputs=inputs,
                projection=candidate,
                rules=rules,
                horizon_builder=candidate_horizon,
            )
            starters = [p["player_id"] for p in payload["starting_xi"]]
            bench = [p["player_id"] for p in payload["bench"]]
            captain = payload["captain"]["player_id"]
            hits = payload["transfer_hit_points"]
            weeks = payload.get("plan_weeks") or []
            signature = {
                "starting_xi": starters,
                "bench": bench,
                "captain": captain,
                "moves": payload["moves"],
                "plan_weeks": weeks,
            }
            # These identity-only fields support comparisons without score inflation.
            moves = [
                (m["player_out"]["player_id"], m["player_in"]["player_id"])
                for m in payload["moves"]
            ]
            future = [[p["player_id"] for p in w["transfers_in"]] for w in weeks]
            row.update(
                status="solved",
                solver_status=payload["solver_status"],
                optimality_gap=payload["optimality_gap"],
                starting_xi=starters,
                squad=sorted(starters + bench),
                captain=captain,
                moves=moves,
                future_transfers=future,
                hit_points=hits,
                base_first_week_net=sum(base_points[p] for p in starters)
                + base_points[captain]
                - hits,
                weighted_first_week_net=payload["expected_own_points"] - hits,
                weighted_window_net=(
                    sum(w["expected_points"] - w["transfer_hit_points"] for w in weeks)
                    if weeks
                    else payload["expected_own_points"] - hits
                ),
                mean_xi_support=sum(counts.get(p, 0) for p in starters) / 1100,
                realized_net_points=None,
                decision=signature,
            )
        except Exception as error:
            row.update(status="refused", reason=f"{type(error).__name__}: {error}")
        row["wall_seconds"] = time.perf_counter() - started
        rows.append(row)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", default="data/snapshots")
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--handoff", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--registry", default="data/entries/registry.json")
    parser.add_argument("--league", type=int, default=352490)
    parser.add_argument("--windows", type=int, nargs="+", choices=(1, 3, 5), default=[1])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    args = vars(parser.parse_args())
    out = args.pop("out")
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with ProcessPoolExecutor(max_workers=args["workers"]) as pool:
        tasks = {
            pool.submit(measure_arm, args, weight, window): (weight, window)
            for window in args["windows"]
            for weight in TOP100_WEIGHT_PERCENTAGES
        }
        for task in as_completed(tasks):
            weight, window = tasks[task]
            result = task.result()
            rows.extend(result)
            (out / f"weight-{weight}-window-{window}.json").write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            print(
                f"weight={weight} window={window}: "
                f"{sum(r['status'] == 'solved' for r in result)}/{len(result)} solved",
                flush=True,
            )
    report = {
        "measurement": "top100_weight_decision_sensitivity_v1",
        "status": "decision_sensitivity_only",
        "realized_effect_established": False,
        "weights": TOP100_WEIGHT_PERCENTAGES,
        "arguments": args,
        "handoff_sha256": hashlib.sha256(Path(args["handoff"]).read_bytes()).hexdigest(),
        "evidence_sha256": hashlib.sha256(Path(args["evidence"]).read_bytes()).hexdigest(),
        "rows": sorted(rows, key=lambda row: (row["window"], row["member"], row["weight_percent"])),
        "summary": summarize_rows(rows),
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
