"""Preregistered, outcome-free comparison of certified lookahead paths.

Research shell only. Never writes served forecasts or promotes a planner default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
from scripts.measure_shortlist_matrix import audit_plan, score_plan

import squadopt.application.football_live as producer
import squadopt.data.sources.football_history as history_source
import squadopt.planning.segmented as segmented
from squadopt.application.advice_variants import weighted_horizon
from squadopt.application.top100_weight import load_top100_counts, top100_manifest_path
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.data.snapshots import read_snapshot
from squadopt.live.football_artifact import (
    football_artifact_path,
    read_football_forecast,
)
from squadopt.live.recommendation import read_inputs
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    TransferPlanningConfig,
    to_planning_horizon,
)
from squadopt.planning.models import TransferPlanResult
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse_chips import net_week_points
from squadopt.prediction.availability import apply_availability

ALLOWED_SEASONS = ("2022-23", "2023-24", "2024-25")
CAPS = {"sequential": 28.0, "window_tail": 84.0, "certify_each": 10.0, "final": 148.0}
SINGLE_CAPS = {"sequential": 28.0, "final": 252.0}
METHODS = ("two_seed_v1", "single_seed_v1")
CONTROL_CAP = 279.0  # Existing hold probe adds 1 outside this cap.
WALL_LIMIT = 1800.0  # Per primary/tie phase, not a total wall-budget claim.
CUTOFF = datetime(2026, 10, 1, 5, tzinfo=UTC)


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, default=str, allow_nan=False) + "\n", encoding="utf-8"
    )


def budgets(method: str = "two_seed_v1") -> tuple[float, float]:
    if method not in METHODS:
        raise ValueError("Unknown study method.")
    if method == "single_seed_v1":
        return CONTROL_CAP + 1.0, sum(SINGLE_CAPS.values())
    return CONTROL_CAP + 1.0, CAPS["sequential"] + CAPS["window_tail"] + 2 * CAPS[
        "certify_each"
    ] + CAPS["final"]


def case_list() -> list[tuple[int, int, int, str]]:
    return (
        [(p, w, 0, "plain") for p in (1000, 900) for w in (3, 5)]
        + [(p, w, a, "plain") for p in (1000, 900) for w in (3, 5) for a in (20, 50)]
        + [(p, 5, 20, m) for p in (1000, 900) for m in ("preferences", "freehit")]
    )


def screen(records: list[dict[str, Any]], expected: int) -> dict[str, Any]:
    valid = [
        r
        for r in records
        if all(r.get("arms", {}).get(a, {}).get("valid") is True for a in ("control", "candidate"))
    ]
    deltas = [
        r["arms"]["candidate"]["weighted_net_points"] - r["arms"]["control"]["weighted_net_points"]
        for r in valid
    ]
    return dict(
        expected_pairs=expected,
        recorded_pairs=len(records),
        valid_pairs=len(valid),
        gains_over_0_1=sum(d > 0.1 for d in deltas),
        losses_over_0_1=sum(d < -0.1 for d in deltas),
        deltas=deltas,
        passed=len(records) == expected
        and len(valid) == expected
        and any(d > 0.1 for d in deltas)
        and all(d >= -0.1 for d in deltas),
        independent_future_performance=False,
        promotion=False,
    )


def safe_produce(snapshot, archive: Path, weeks: tuple[int, ...] | None):
    """Restrict BOTH archive loading and producer hashing before either can read files.

    Single-process research scope, restored even after a producer error. Production
    modules/files and defaults stay untouched. This is a different fitted forecast
    from the served artifact, which can include the excluded season.
    """
    with (
        patch.object(history_source, "ARCHIVE_SEASONS", ALLOWED_SEASONS),
        patch.object(producer, "ARCHIVE_SEASONS", ALLOWED_SEASONS),
    ):
        return producer.produce_football_forecast(snapshot, archive, gameweeks=weeks)


def prepare(snapshot_root, artifact_root, snapshot_id, archive_root, output):
    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season="2026-27")
    if inputs.deadline.gameweek != 6:
        raise ValueError("Protocol requires the fixed GW6 capture.")
    print("BUILD restricted-history explicit GW6..19 forecast", flush=True)
    long_document = safe_produce(snapshot, archive_root, tuple(range(6, 20)))
    write_json(output / "forecast14.json", long_document)
    print("BUILD independent five-week parity forecast", flush=True)
    five = safe_produce(snapshot, archive_root, None)
    write_json(output / "forecast5.json", five)
    left = pd.DataFrame(long_document["rows"])
    right = pd.DataFrame(five["rows"])
    shared = left.loc[left.gameweek.le(10)].reset_index(drop=True)
    pd.testing.assert_frame_equal(shared, right, check_exact=False, atol=1e-10, rtol=0)
    forecast5 = read_football_forecast(output / "forecast5.json", inputs)
    adjusted = pd.concat(
        [
            apply_availability(frame, inputs.availability).table
            for _, frame in left.groupby("gameweek", sort=True)
        ],
        ignore_index=True,
    )
    projection = replace(forecast5.horizon, table=adjusted)
    if tuple(sorted(projection.table.gameweek.unique())) != tuple(range(6, 20)):
        raise ValueError("Missing explicit continuation weeks.")
    # The production reader intentionally still admits only five weeks. Reuse its
    # first-week projection for ownership provenance, not to overwrite that contract.
    expected5 = projection.table.loc[projection.table.gameweek.le(10)].reset_index(drop=True)
    common = list(forecast5.horizon.table.columns)
    pd.testing.assert_frame_equal(
        expected5[common], forecast5.horizon.table[common], check_exact=False, atol=1e-10, rtol=0
    )
    served = read_football_forecast(football_artifact_path(artifact_root, snapshot_id), inputs)
    comparison = served.horizon.table[["gameweek", "player_id", "expected_points"]].merge(
        expected5[["gameweek", "player_id", "expected_points"]],
        on=["gameweek", "player_id"],
        suffixes=("_served", "_restricted"),
        validate="one_to_one",
    )
    write_json(
        output / "forecast-provenance.json",
        dict(
            allowed_archive_seasons=ALLOWED_SEASONS,
            excluded_season_accessed=False,
            training_rows=long_document["training_rows"],
            archive_hashes=long_document["archive_hashes"],
            source_snapshot_id=snapshot_id,
            source_fingerprint=snapshot.metadata.fingerprint,
            forecast_fingerprint=long_document["fingerprint"],
            five_week_rebuild_parity=True,
            served_forecast_fingerprint=served.fingerprint,
            served_max_absolute_points_difference=float(
                (comparison.expected_points_served - comparison.expected_points_restricted)
                .abs()
                .max()
            ),
            served_equivalence_required=False,
            limitations=[
                "Restricted training excludes 2025-26: not the live fitted forecast.",
                "Different capture from #904, no replication of its reported gaps.",
                "Availability and prices frozen across explicit published fixtures.",
                "No independent future outcomes or policy evaluation.",
            ],
        ),
    )
    return inputs, projection, forecast5


def phase_fair(diagnostics: dict[str, Any], status: str) -> bool:
    """An unproved early stop cannot pass as deterministic-budget evidence."""
    hold = diagnostics.get("hold_protection")
    if (
        hold is not None
        and hold.get("status") not in ("OPTIMAL", "INFEASIBLE")
        and float(hold.get("deterministic_time", 0))
        < float(hold["deterministic_time_limit"]) - 1e-6
    ):
        return False
    primary = diagnostics.get("primary_search_status", status)
    if primary != "OPTIMAL" and not diagnostics.get("deterministic_time_budget_exhausted", False):
        return False
    return not (
        diagnostics.get("tiebreak_attempted")
        and not diagnostics.get("tiebreak_completed")
        and not diagnostics.get("deterministic_time_budget_exhausted")
    )


def chosen_seed(plans: list[TransferPlanResult]) -> int:
    # Stable tie order is sequential, then window-tail. Values were computed by
    # the full current model; never use the segmented or submitted claimed score.
    return max(
        range(len(plans)), key=lambda i: plans[i].diagnostics["scaled_model_objective_value"]
    )


def validate_reference(output: Path, reference: Path) -> None:
    """Stop before any solve if this reused-development comparison changed its inputs."""
    current = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    previous = json.loads((reference / "protocol.json").read_text(encoding="utf-8"))
    for key in (
        "states_sha256",
        "top100_sha256",
        "top100_manifest_sha256",
        "allowed_archive_seasons",
    ):
        if current[key] != previous[key]:
            raise ValueError(f"Reference input mismatch: {key}")
    for name, digest in previous["source_sha256"].items():
        if name.replace("\\", "/") == "scripts/measure_guarded_lookahead.py":
            continue
        if current["source_sha256"].get(name) != digest:
            raise ValueError(f"Reference source mismatch: {name}")
    for filename in ("forecast14.json", "forecast5.json"):
        left = json.loads((output / filename).read_text(encoding="utf-8"))
        right = json.loads((reference / filename).read_text(encoding="utf-8"))
        for key in ("fingerprint", "source_snapshot_id", "archive_hashes"):
            if left[key] != right[key]:
                raise ValueError(f"Reference forecast mismatch: {filename}/{key}")
    left = json.loads((output / "forecast-provenance.json").read_text(encoding="utf-8"))
    right = json.loads((reference / "forecast-provenance.json").read_text(encoding="utf-8"))
    for key in ("source_fingerprint", "source_snapshot_id", "archive_hashes"):
        if left[key] != right[key]:
            raise ValueError(f"Reference provenance mismatch: {key}")
    write_json(
        output / "reference-check.json",
        dict(
            matched=True,
            reused_development_data=True,
            reference_protocol_sha256=hashlib.sha256(
                (reference / "protocol.json").read_bytes()
            ).hexdigest(),
            reference_results_sha256=hashlib.sha256(
                (reference / "results.json").read_bytes()
            ).hexdigest(),
        ),
    )


def run(
    snapshot_root: Path,
    artifact_root: Path,
    snapshot_id: str,
    archive_root: Path,
    evidence: Path,
    states: Path,
    output: Path,
    *,
    method: str = "two_seed_v1",
    reference_study: Path | None = None,
) -> None:
    if budgets(method) != (280.0, 280.0):
        raise ValueError("Changed preregistered budget.")
    if method == "single_seed_v1" and reference_study is None:
        raise ValueError("Single-seed follow-up requires the previous study reference.")
    if datetime.now(UTC) >= CUTOFF:
        raise ValueError("Night cutoff passed; no new heavy work.")
    output.mkdir(parents=True, exist_ok=False)
    start = datetime.now(UTC)
    deadline = min(CUTOFF, start + timedelta(hours=4 if method == "single_seed_v1" else 6))
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "docs/research/lookahead_budget_protocol.md",
        root / "scripts/measure_shortlist_matrix.py",
        *sorted((root / "src/squadopt/planning").glob("*.py")),
        root / "src/squadopt/application/football_live.py",
        root / "src/squadopt/data/sources/football_history.py",
    ]
    if method == "single_seed_v1":
        sources.append(root / "docs/research/single_seed_lookahead_protocol.md")
    write_json(
        output / "protocol.json",
        dict(
            method=method,
            started_at=start.isoformat(),
            stop_by=deadline.isoformat(),
            cases=case_list(),
            budgets=budgets(method),
            phase_caps=SINGLE_CAPS if method == "single_seed_v1" else CAPS,
            wall_seconds_per_primary_or_tie=WALL_LIMIT,
            allowed_archive_seasons=ALLOWED_SEASONS,
            states_sha256=hashlib.sha256(states.read_bytes()).hexdigest(),
            source_sha256={
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
            top100_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
            top100_manifest_sha256=hashlib.sha256(
                top100_manifest_path(evidence).read_bytes()
            ).hexdigest(),
        ),
    )
    inputs, projection, forecast5 = prepare(
        snapshot_root, artifact_root, snapshot_id, archive_root, output
    )
    if method == "single_seed_v1":
        assert reference_study is not None
        validate_reference(output, reference_study)
    counts = load_top100_counts(evidence, inputs=inputs, projection=forecast5.projection)
    profiles = json.loads(states.read_text(encoding="utf-8"))
    config = OptimizationConfig(
        bench_weight=0,
        solver_time_limit_seconds=WALL_LIMIT,
        solver_deterministic_time_limit=CONTROL_CAP,
    )
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    records: list[dict[str, Any]] = []
    for index, (profile, window, weight, mode) in enumerate(case_list()):
        if index == 4:
            core = screen(records, 4)
            write_json(output / "core-summary.json", core)
            if not core["passed"]:
                break
        if datetime.now(UTC) >= deadline:
            break
        record: dict[str, Any] = dict(
            profile=profile, window=window, weight=weight, mode=mode, arms={}
        )
        records.append(record)
        raw = profiles[str(profile)]
        state = InitialSquadState(tuple(raw["ids"]), raw["bank"], raw["ft"])
        base = to_planning_horizon(projection)
        weighted = to_planning_horizon(weighted_horizon(projection, counts.counts, weight))
        ordered = base.table.loc[
            base.table.gameweek.eq(6)
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
            ChipAvailability(available={"freehit": frozenset({6})}, forced={6: "freehit"})
            if mode == "freehit"
            else ChipAvailability()
        )
        if mode == "preferences":
            chips = ChipAvailability(
                available={c: frozenset(base.gameweeks) for c in ("3xc", "bboost")}
            )
        for arm in ("control", "candidate") if index % 2 == 0 else ("candidate", "control"):
            entry: dict[str, Any] = dict(valid=False, phases=[])
            record["arms"][arm] = entry
            began = time.perf_counter()
            entry["stage"] = "control"

            def solve(*args, _entry=entry, _index=index, _arm=arm, **kwargs):
                cfg = args[2]
                # Reserve both solver phases plus certification before starting.
                if (
                    deadline - datetime.now(UTC)
                ).total_seconds() < 2 * cfg.solver_time_limit_seconds + 30:
                    raise TimeoutError("Insufficient remaining night budget for this phase.")
                phase: dict[str, Any] = dict(
                    stage=_entry["stage"],
                    weeks=args[0].gameweeks,
                    configured_det=cfg.solver_deterministic_time_limit,
                    primary_or_tie_wall_cap=cfg.solver_time_limit_seconds,
                    complete=False,
                )
                _entry["phases"].append(phase)
                write_json(output / "results.json", records)
                tick = time.perf_counter()
                print(
                    f"START case{_index + 1} {_arm}/{_entry['stage']} weeks={args[0].gameweeks}",
                    flush=True,
                )
                try:
                    plan = optimize_transfer_plan(*args, **kwargs)
                    diag = dict(plan.diagnostics)
                    phase.update(
                        status=plan.solver_status.name,
                        diagnostics=diag,
                        complete=True,
                        fair_stop=phase_fair(diag, plan.solver_status.name),
                        actual_det=float(diag["deterministic_time_used"])
                        + float(diag.get("hold_protection", {}).get("deterministic_time", 0)),
                    )
                    return plan
                except Exception as error:
                    phase.update(error_type=type(error).__name__, error=str(error), actual_det=None)
                    raise
                finally:
                    phase["wall_seconds"] = time.perf_counter() - tick
                    write_json(output / "results.json", records)

            try:
                if arm == "control":
                    plan = solve(
                        weighted,
                        state,
                        config,
                        settings,
                        chips=chips,
                        preferences=preferences,
                        protect_hold=True,
                        linearization_level=2,
                    )
                elif method == "single_seed_v1":
                    entry["stage"] = "sequential"
                    with patch.object(segmented, "optimize_transfer_plan", solve):
                        seed = segmented.plan_in_segments(
                            weighted,
                            state,
                            replace(
                                config, solver_deterministic_time_limit=SINGLE_CAPS["sequential"]
                            ),
                            segment_lengths=(1,) * 14,
                            transfer=settings,
                            chips=chips,
                            preferences=preferences,
                        )
                    entry["stage"] = "final"
                    plan = solve(
                        weighted,
                        state,
                        replace(config, solver_deterministic_time_limit=SINGLE_CAPS["final"]),
                        settings,
                        chips=chips,
                        preferences=preferences,
                        incumbent_plan=seed,
                        protect_incumbent=True,
                        linearization_level=2,
                    )
                    seed_value = plan.diagnostics["incumbent_protection"]["scaled_objective_value"]
                    entry["selected_seed"] = 0
                    entry["certified_seed_scores"] = [seed_value]
                    if plan.diagnostics["scaled_model_objective_value"] < seed_value:
                        raise ValueError("Certified incumbent regression.")
                else:
                    seeds = []
                    for stage, lengths in (
                        ("sequential", (1,) * 14),
                        ("window_tail", (window, 14 - window)),
                    ):
                        entry["stage"] = stage
                        with patch.object(segmented, "optimize_transfer_plan", solve):
                            seed = segmented.plan_in_segments(
                                weighted,
                                state,
                                replace(config, solver_deterministic_time_limit=CAPS[stage]),
                                segment_lengths=lengths,
                                transfer=settings,
                                chips=chips,
                                preferences=preferences,
                            )
                        seeds.append(seed)
                    certified = []
                    for i, seed in enumerate(seeds):
                        entry["stage"] = f"certify_{i}"
                        certified.append(
                            solve(
                                weighted,
                                state,
                                replace(
                                    config, solver_deterministic_time_limit=CAPS["certify_each"]
                                ),
                                settings,
                                chips=chips,
                                preferences=preferences,
                                incumbent_plan=seed,
                                protect_incumbent=True,
                                linearization_level=2,
                            )
                        )
                    selected = chosen_seed(certified)
                    entry["selected_seed"] = selected
                    entry["certified_seed_scores"] = [
                        p.diagnostics["scaled_model_objective_value"] for p in certified
                    ]
                    entry["stage"] = "final"
                    plan = solve(
                        weighted,
                        state,
                        replace(config, solver_deterministic_time_limit=CAPS["final"]),
                        settings,
                        chips=chips,
                        preferences=preferences,
                        incumbent_plan=certified[selected],
                        protect_incumbent=True,
                        linearization_level=2,
                    )
                    if (
                        plan.diagnostics["scaled_model_objective_value"]
                        < entry["certified_seed_scores"][selected]
                    ):
                        raise ValueError("Certified incumbent regression.")
                entry.update(
                    audit_plan(plan, base, weighted, preferences, chips),
                    status=plan.solver_status.name,
                    diagnostics=dict(plan.diagnostics),
                )
                window_plan = replace(plan, weeks=plan.weeks[:window])
                entry.update(
                    weighted_window=score_plan(window_plan, weighted),
                    base_window=score_plan(window_plan, base),
                    base_tail=score_plan(plan, base) - score_plan(window_plan, base),
                    weighted_tail=sum(net_week_points(w) for w in plan.weeks[window:]),
                    actual_det=sum(p["actual_det"] for p in entry["phases"]),
                )
                if not all(p["fair_stop"] for p in entry["phases"]):
                    entry.update(
                        valid=False,
                        failure=(
                            "Phase stopped without proof or deterministic budget exhaustion; "
                            "wall/early stop invalidates screen."
                        ),
                    )
            except Exception as error:
                entry.update(valid=False, error_type=type(error).__name__, error=str(error))
            known_costs = [
                p["actual_det"] for p in entry["phases"] if p.get("actual_det") is not None
            ]
            entry["recorded_det"] = sum(known_costs)
            entry["cost_complete"] = len(known_costs) == len(entry["phases"])
            entry["actual_det"] = entry["recorded_det"] if entry["cost_complete"] else None
            entry["wall_seconds"] = time.perf_counter() - began
            write_json(output / "results.json", records)
            print(
                f"DONE case{index + 1} {arm} valid={entry['valid']} "
                f"score={entry.get('weighted_net_points')}",
                flush=True,
            )
    write_json(output / "core-summary.json", screen(records[:4], 4))
    write_json(
        output / "summary.json",
        dict(
            method=method,
            core=screen(records[:4], 4),
            expanded=screen(records, 16),
            finished_at=datetime.now(UTC).isoformat(),
        ),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "artifact-root", "archive-root", "evidence", "states", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--method", choices=METHODS, default="two_seed_v1")
    parser.add_argument("--reference-study", type=Path)
    run(**vars(parser.parse_args()))
