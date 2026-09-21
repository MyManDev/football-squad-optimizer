"""Count the member window plans of one capture that are proved, at two solver settings.

Every member of a capture, every multi-week window, solved twice under the member window's own
deterministic budget: once at CP-SAT's default linearization level (what the site published
until now) and once at ``WINDOW_LINEARIZATION_LEVEL``. The record keeps, per solve, the status,
the plan's value, the bound and the deterministic work spent, so the movement of the incumbent
and the movement of the bound can be read apart.

Both arms stop on deterministic solver work, so the record does not move with machine load and
the solves may run side by side (``--jobs``). Nothing is published and no advice is recorded.

    python -m scripts.measure_member_window_proofs --data-root <checkout>/data \
        --snapshot-id fpl-live-20260918T122516Z-cd5c04029774 --jobs 5
"""

import argparse
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.application.advice import (
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
    window_horizon,
)
from squadopt.application.entries import held_squad_from_picks
from squadopt.live.transfers import plan_transfer_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.platform.capture_context import (
    AdviceCaptureContext,
    load_capture_context,
    load_capture_identity,
)

CONTRACT_VERSION = "member_window_proofs_v1"
ARMS: dict[str, int | None] = {"solver_default": None, "window_level": WINDOW_LINEARIZATION_LEVEL}
_CONTEXT: AdviceCaptureContext | None = None


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--windows", default="3,5")
    parser.add_argument("--entries", default="all")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "member_window_proofs.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "member_window_proofs.md"
    )
    return parser.parse_args(argv)


def _load(data_root: str, snapshot_id: str) -> None:
    global _CONTEXT
    root = Path(data_root)
    identity = load_capture_identity(
        snapshot_root=root / "snapshots",
        snapshot_id=snapshot_id,
        handoff_root=root / "handoffs",
        advice_contract_version=CONTRACT_VERSION,
        repository_commit=CONTRACT_VERSION,
        configuration_fingerprint=CONTRACT_VERSION,
    )
    _CONTEXT = load_capture_context(identity)


def _solve(task: tuple[int, int, str]) -> dict[str, Any]:
    entry_id, window, arm = task
    context = _CONTEXT
    assert context is not None
    inputs = context.inputs
    gameweek = int(inputs.deadline.gameweek)
    picks = context.provider.picks(entry_id, str(inputs.season), gameweek - 1)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    plan, _ = plan_transfer_horizon(
        inputs,
        window_horizon(inputs, window, context.horizon_builder),
        held_squad_from_picks(picks, current_prices=prices),
        context.rules,
        optimization=OptimizationConfig(
            solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
            solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * window,
        ),
        linearization_level=ARMS[arm],
    )
    diagnostics = plan.diagnostics
    return {
        "entry_id": entry_id,
        "window": window,
        "arm": arm,
        "solver_status": plan.solver_status.name,
        "plan_value": diagnostics.get("scaled_model_objective_value"),
        "best_bound": diagnostics.get("best_objective_bound"),
        "absolute_gap": diagnostics.get("absolute_optimality_gap"),
        "primary_deterministic_time": diagnostics.get("primary_deterministic_time"),
        "deterministic_time_used": diagnostics.get("deterministic_time_used"),
        "tiebreak_completed": diagnostics.get("tiebreak_completed"),
        "wall_seconds": diagnostics.get("solve_time_seconds"),
        "transfers": [
            [int(week.gameweek), [int(player) for player in week.transfers_in["player_id"]]]
            for week in plan.weeks
        ],
    }


def _summary(rows: list[dict[str, Any]], window: int, arm: str) -> dict[str, Any]:
    cell = [row for row in rows if row["window"] == window and row["arm"] == arm]
    gaps = [float(row["absolute_gap"]) for row in cell if row["solver_status"] != "OPTIMAL"]
    return {
        "solves": len(cell),
        "proved": sum(row["solver_status"] == "OPTIMAL" for row in cell),
        "largest_open_gap": max(gaps) if gaps else None,
        "mean_plan_value": sum(float(row["plan_value"]) for row in cell) / len(cell),
        "mean_deterministic_time": sum(float(row["deterministic_time_used"]) for row in cell)
        / len(cell),
        "total_wall_seconds": sum(float(row["wall_seconds"]) for row in cell),
    }


def _markdown(record: dict[str, Any]) -> str:
    lines = [
        "# Member window plans: proved, at the solver default and at the window level",
        "",
        f"Capture `{record['snapshot_id']}`, gameweek {record['gameweek']}, "
        f"{record['members']} members. Both arms spend at most "
        f"{record['deterministic_units_per_week']:.0f} deterministic units per week of window; "
        f"the second arm sets CP-SAT's linearization level to {record['window_level']}. Wall "
        "seconds are this machine's and are not a claim; everything else is a function of the "
        "inputs.",
        "",
        "| Window | Arm | Proved | Largest open gap | Mean plan value | "
        "Mean deterministic work | Wall seconds, summed |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for window, arms in record["summary"].items():
        for arm, cell in arms.items():
            gap = "none" if cell["largest_open_gap"] is None else f"{cell['largest_open_gap']:.2f}"
            lines.append(
                f"| {window} | `{arm}` | {cell['proved']} of {cell['solves']} | {gap} | "
                f"{cell['mean_plan_value']:.3f} | {cell['mean_deterministic_time']:.1f} | "
                f"{cell['total_wall_seconds']:.0f} |"
            )
    lines += [
        "",
        "Per member (plan value, then the gap to the bound; 0 is a proof):",
        "",
        "| Entry | Window | Default | Window level | Value gained |",
        "| ---: | ---: | --- | --- | ---: |",
    ]
    by_key = {(row["entry_id"], row["window"], row["arm"]): row for row in record["rows"]}
    for entry_id, window in sorted({(row["entry_id"], row["window"]) for row in record["rows"]}):
        before = by_key[entry_id, window, "solver_default"]
        after = by_key[entry_id, window, "window_level"]
        lines.append(
            f"| {entry_id} | {window} | {before['plan_value']:.3f}, {before['absolute_gap']:.2f} "
            f"| {after['plan_value']:.3f}, {after['absolute_gap']:.2f} "
            f"| {after['plan_value'] - before['plan_value']:+.3f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    data_root = str(arguments.data_root)
    _load(data_root, arguments.snapshot_id)
    assert _CONTEXT is not None
    season = str(_CONTEXT.inputs.season)
    gameweek = int(_CONTEXT.inputs.deadline.gameweek)
    if arguments.entries == "all":
        records = arguments.data_root / "advice_records" / season / f"gw{gameweek:02d}"
        entries = sorted(int(p.name.removeprefix("entry-")) for p in records.glob("entry-*"))
    else:
        entries = [int(value) for value in arguments.entries.split(",")]
    windows = [int(value) for value in arguments.windows.split(",")]
    tasks = [(entry, window, arm) for window in windows for entry in entries for arm in ARMS]
    with ProcessPoolExecutor(
        max_workers=arguments.jobs, initializer=_load, initargs=(data_root, arguments.snapshot_id)
    ) as pool:
        rows = list(pool.map(_solve, tasks))
    record = {
        "contract_version": CONTRACT_VERSION,
        "snapshot_id": arguments.snapshot_id,
        "season": season,
        "gameweek": gameweek,
        "members": len(entries),
        "deterministic_units_per_week": WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
        "window_level": WINDOW_LINEARIZATION_LEVEL,
        "summary": {
            str(window): {arm: _summary(rows, window, arm) for arm in ARMS} for window in windows
        },
        "rows": rows,
    }
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
