"""Probe one saved, normally selected football window without network or model fitting."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.entries import held_squad_from_picks
from squadopt.data.snapshots import read_snapshot
from squadopt.live import project, read_inputs, read_projection_handoff, read_season_rules
from squadopt.live import transfers as live
from squadopt.optimization import OptimizationConfig
from squadopt.platform.advice_switches import load_switch_inputs


def probe(data_root, snapshot_id, entry_id):
    snapshot_root = data_root / "data/snapshots"
    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season="2026-27")
    rules = read_season_rules(snapshot, season=inputs.season)
    handoff = read_projection_handoff(
        data_root / f"artifacts/football/{snapshot_id}.bundle/handoff.json"
    )
    switches = load_switch_inputs(
        artifact_root=data_root / "artifacts",
        club_news_source=None,
        snapshot_root=snapshot_root,
        inputs=inputs,
        projection=project(inputs, in_season=handoff),
    )
    result = dict(
        producer_repository_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        runner_sha256=hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        snapshot_id=snapshot_id,
        entry_id=entry_id,
        football_selected=switches.football is not None,
        notes=switches.notes,
        routes=[],
        network_requests=0,
    )
    if switches.football is None:
        return {**result, "conclusion": "served_football_input_unavailable"}
    football = switches.football
    dates = tuple(range(inputs.deadline.gameweek, inputs.deadline.gameweek + 3))
    provider = CapturePicksProvider(snapshot, snapshot_id)
    picks = provider.picks(entry_id, inputs.season, inputs.deadline.gameweek - 1)
    prices = {int(r.player_id): int(r.price_tenths) for r in inputs.players.itertuples()}
    held = held_squad_from_picks(picks, current_prices=prices)
    result.update(
        model=football.horizon.model_name,
        model_version=football.horizon.model_version,
        free_transfers=held.free_transfers,
        bank_tenths=held.bank_tenths,
        roles_bound=switches.football_components_bound,
        deterministic_cap=60,
        wall_safety_seconds=1800,
        input_sha256={
            name: hashlib.sha256((data_root / name).read_bytes()).hexdigest()
            for name in (
                f"artifacts/football/{snapshot_id}.json",
                f"artifacts/football/{snapshot_id}.bundle.json",
            )
        },
    )

    def trace(name, function):
        def call(*args, **kwargs):
            result["routes"].append(name)
            return function(*args, **kwargs)

        return call

    started = perf_counter()
    try:
        with (
            patch.object(
                live, "optimize_expected_window", trace("expected", live.optimize_expected_window)
            ),
            patch.object(
                live, "optimize_observed_window", trace("observed", live.optimize_observed_window)
            ),
        ):
            plan, _ = live.plan_transfer_horizon(
                inputs,
                football.build_horizon(dates),
                held,
                rules,
                optimization=OptimizationConfig(
                    solver_deterministic_time_limit=60, solver_time_limit_seconds=1800
                ),
                linearization_level=2,
            )
        result.update(status=plan.solver_status.name, has_solution=plan.has_solution)
        result["conclusion"] = "accounting_error_not_reproduced"
    except (ValueError, RuntimeError) as error:
        result.update(error=type(error).__name__, message=str(error))
        result["conclusion"] = (
            "accounting_error_reproduced"
            if str(error) == "Invalid deterministic-work accounting for expected windows."
            else "different_failure"
        )
    result["seconds"] = perf_counter() - started
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--entry-id", type=int, default=3832237)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = probe(args.data_root, args.snapshot_id, args.entry_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value.get(key) for key in ("conclusion", "routes", "status")}))
