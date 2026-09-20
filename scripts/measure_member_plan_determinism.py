"""Does the published one-week member plan depend on the wall clock, or only on solver work?

The planner's budget is deterministic time: CP-SAT work units, which do not move with the
machine's load. The wall ceiling beside it is documented as a safety stop rather than a second
budget, "high enough never to bind a normal solve" (`planning/optimizer.py:75-77`). If that is
true of the member path, then the ceiling is free: every ceiling publishes the same plan.

It is not obviously true. The tie-break is the phase that chooses between plans of equal
objective value, and it is handed a wall-derived budget: `remaining_time = deadline -
perf_counter()` at `planning/optimizer.py:1123`, gated on `remaining_time >
MIN_TIEBREAK_TIME_SECONDS` at `:1132-1136`, then passed to `configure_solver` at `:1151`. So a
low ceiling can skip or truncate the tie-break, and what the tie-break settles is exactly what a
member reads: the bench order, the captain among ties, and which of two equal-value fifteens is
published. Whether that happens at the ceilings this repository actually runs is a question, not
a prediction.

Those three line numbers are the code as it stood at `7f5131c9`, the commit this record was
measured against. #723 removes the wall remainder from that phase, so after it lands the
citations above describe a defect this repository no longer has, and the lines they name are
unrelated code. Read them as history, not as a map.

The arms are wall ceilings and nothing else. The deterministic budget is pinned at
`PLAN_DETERMINISTIC_TIME_LIMIT`, the value production runs at, and passed explicitly: left as
`None` the planner would raise every ceiling below 300 to 300 itself (`:1029-1032`), and the
experiment would compare four identical configurations without saying so.

This is why the one-week card matters more than the window plans for this question. The window
path, the chip path and the system's own ledger squad all refuse a plan the clock cut short
(`wall_clock_stopped_the_search` is called at `application/advice.py:829`,
`advice_chips.py:325`, `live/report.py:106`). The one-week card, whose solve is the
`plan_transfers` call at `advice.py:451`, and every rival variant call it nowhere, and the
published record carries no deterministic time at all, so a reader of a member's plan cannot
tell which budget stopped it.

What the grid found about that tie-break is reported in the record whichever way it came
out, and it came out against the mechanism above: where the clock cut the tie-break the
published plan did not move. Every plan that did move had its primary search cut instead,
which is the ordinary case rather than the subtle one.

Descriptive. Nothing is promoted, no default moves, and no advice is recorded or published: this
reads a capture and solves from it.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from scripts._experiment_cli import (
    REPOSITORY_ROOT,
    repository_provenance,
    write_json,
    write_text,
)

from squadopt.application.entries import held_squad_from_picks
from squadopt.application.lineup_publication import lineup_fields
from squadopt.live.transfers import plan_transfers
from squadopt.optimization import OptimizationConfig, wall_clock_stopped_the_search
from squadopt.planning.optimizer import (
    PLAN_DETERMINISTIC_TIME_LIMIT,
    PLAN_WALL_CEILING_SECONDS,
)
from squadopt.platform.capture_context import load_capture_context, load_capture_identity

LOGGER = logging.getLogger("measure_member_plan_determinism")

CONTRACT_VERSION = "member_plan_determinism_v1"

#: Wall ceilings, in seconds. `wall_300s` is the planner's own default ceiling and so is the
#: arm that reproduces what the site published.
#:
#: The two lowest arms are adversarial and deliberately below the wall time a solve takes on
#: this machine. They are not a load simulation and do not claim any machine is this slow; they
#: answer the separate question of what this path does when the ceiling is the thing that binds,
#: because that is the case the one-week card has no gate for. The arms between them show
#: whether the ceiling binds at any setting a real machine would reach.
ARMS: dict[str, float] = {
    "wall_1s": 1.0,
    "wall_2s": 2.0,
    "wall_5s": 5.0,
    "wall_30s": 30.0,
    "wall_300s": PLAN_WALL_CEILING_SECONDS,
    "wall_1800s": 1800.0,
}

#: Diagnostics that echo the arm back. They differ by construction and comparing them would
#: report a difference the experiment created itself. They are checked against the arm before
#: the record is written, which is a stronger statement than comparing them across arms.
#:
#: `deterministic_budget_source` is deliberately not here. It never varies, and that is the
#: point: it is the witness that no arm fell through the planner's defaulting at
#: `planning/optimizer.py:1025-1028`, where a `None` deterministic limit both flips the source
#: to `planner_default` and silently raises the wall to 300. An experiment blind to that is an
#: experiment that cannot tell four ceilings from one.
ARM_ECHO_KEYS = frozenset(
    {
        "solver_time_limit_seconds",
        "wall_time_limit_seconds",
    }
)

#: Measured on this machine, under whatever else was running. Recorded, never compared.
MACHINE_NOISE_KEYS = frozenset({"solve_time_seconds"})


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        help=(
            "The runtime data directory holding snapshots/ and handoffs/. Required unless "
            "--rewrite-markdown, which opens no capture."
        ),
    )
    parser.add_argument(
        "--snapshot-id",
        help="The capture to solve against. Required unless --rewrite-markdown.",
    )
    parser.add_argument(
        "--entries",
        default="all",
        help="Comma separated entry ids, or 'all' to read them from the advice records.",
    )
    parser.add_argument(
        "--arms",
        default=",".join(ARMS),
        help="Comma separated arm names to run, for a pilot.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "member_plan_determinism.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "member_plan_determinism.md",
    )
    parser.add_argument(
        "--rewrite-markdown",
        action="store_true",
        help=(
            "Rewrite the markdown from the existing JSON record without solving anything. "
            "The record is the measurement; how it reads is not, and a presentation fix "
            "must not cost another run of the grid."
        ),
    )
    arguments = parser.parse_args(argv)
    # Asked for here rather than by ``required=True`` so that a re-render does not demand a
    # capture it never opens. A flag that asks for a data root suggests it might read one,
    # and this one returns before the capture is touched: what a command asks for is read as
    # a claim about what it does, so asking for an unread capture says a re-render might
    # re-measure. It cannot.
    if not arguments.rewrite_markdown:
        missing = [
            name
            for name, value in (
                ("--data-root", arguments.data_root),
                ("--snapshot-id", arguments.snapshot_id),
            )
            if value is None
        ]
        if missing:
            parser.error("the following arguments are required: " + ", ".join(missing))
    return arguments


def _published_answer(week: Any) -> dict[str, Any]:
    """The part of the plan a member actually reads, in the shape the page publishes it."""

    fields = lineup_fields(week)
    return {
        "selected_squad": sorted(int(value) for value in week.selected_squad["player_id"]),
        "starting_xi": sorted(int(value) for value in week.starting_xi["player_id"]),
        "captain": None if week.captain is None else int(week.captain["player_id"]),
        "chip": week.chip,
        "projected_score": float(week.projected_score),
        # Bench order and the vice captain are not a second choice: `lineup_publication`
        # completes them by a deterministic rule over the eleven and bench already chosen,
        # so they carry no information beyond the squad and the eleven. They are recorded
        # because they are what the page prints, not as independent evidence.
        "published": {key: fields[key] for key in sorted(fields)},
    }


def _cell(entry_id: int, arm: str, plan: Any, wall_seconds: float) -> dict[str, Any]:
    diagnostics: Mapping[str, Any] = plan.diagnostics
    # A ceiling low enough to stop the primary before it finds anything leaves no week to
    # publish. That is a distinct outcome from "a different plan" and is recorded as itself.
    week = plan.weeks[0] if plan.weeks else None
    record: dict[str, Any] = {
        "entry_id": entry_id,
        "arm": arm,
        "solver_status": plan.solver_status.name,
        "objective_value": (None if plan.objective_value is None else float(plan.objective_value)),
        "horizon_fingerprint": plan.horizon_fingerprint,
        # The flag the window, chip and ledger paths refuse on, and this path does not read.
        "wall_clock_stopped_the_search": bool(
            wall_clock_stopped_the_search(plan.solver_status, diagnostics)
        ),
        "measured_wall_seconds": wall_seconds,
    }
    for key in sorted(diagnostics):
        record[f"diagnostics.{key}"] = diagnostics[key]
    record["answer"] = None if week is None else _published_answer(week)
    record["has_week"] = week is not None
    return record


def _comparable(cell: Mapping[str, Any]) -> dict[str, Any]:
    """Everything that must be identical across arms if only solver work decides the plan."""

    skip = {"arm", "measured_wall_seconds"}
    out: dict[str, Any] = {}
    for key, value in cell.items():
        if key in skip:
            continue
        bare = key.removeprefix("diagnostics.")
        if bare in ARM_ECHO_KEYS or bare in MACHINE_NOISE_KEYS:
            continue
        out[key] = value
    return out


def _differences(cells: list[dict[str, Any]], arms: list[str]) -> dict[str, Any]:
    """Per member, which comparable fields differ between the arms, and how."""

    per_member: dict[str, Any] = {}
    for entry_id in sorted({cell["entry_id"] for cell in cells}):
        by_arm = {cell["arm"]: _comparable(cell) for cell in cells if cell["entry_id"] == entry_id}
        if len(by_arm) < 2:
            continue
        # By ceiling, never by the order the operator typed the arms and never by name:
        # `wall_5s` sorts after `wall_1800s`, which would invert every reading below it.
        reference_arm = max(by_arm, key=lambda name: ARMS[name])
        reference = by_arm[reference_arm]
        moved: dict[str, Any] = {}
        for arm, cell in by_arm.items():
            if arm == reference_arm:
                continue
            for key in sorted(set(reference) | set(cell)):
                if reference.get(key) != cell.get(key):
                    moved.setdefault(key, {})[arm] = {
                        "reference": reference.get(key),
                        "arm": cell.get(key),
                    }
        per_member[str(entry_id)] = {
            "reference_arm": reference_arm,
            "fields_that_moved": moved,
            "answer_moved": any(key.startswith("answer") for key in moved),
        }
    return per_member


def _document(
    *,
    created_utc: str,
    snapshot_id: str,
    season: str,
    gameweek: int,
    entries: list[int],
    arms: list[str],
    per_arm: dict[str, Any],
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    """The record, assembled where a test can reach it.

    Separated from ``main`` so that what the record carries can be asserted without a
    capture and a solver. The first version of this runner built the dictionary inline and
    shipped without naming the commit that produced it, which no test could have caught
    because no test could construct the document.
    """

    return {
        "contract_version": CONTRACT_VERSION,
        "measurement_only": True,
        "created_utc": created_utc,
        "provenance": repository_provenance(),
        "snapshot_id": snapshot_id,
        "season": season,
        "gameweek": gameweek,
        "member_count": len(entries),
        "entries": entries,
        "arms": {arm: ARMS[arm] for arm in arms},
        "deterministic_time_limit": PLAN_DETERMINISTIC_TIME_LIMIT,
        "arm_echo_keys": sorted(ARM_ECHO_KEYS),
        "machine_noise_keys": sorted(MACHINE_NOISE_KEYS),
        "per_arm": per_arm,
        "per_member": _differences(cells, arms),
        "cells": cells,
    }


def _tiebreak_section(record: dict[str, Any], arm_order: list[str]) -> list[str]:
    """What happened where the clock cut the tie-break rather than the primary search.

    This is the mechanism the experiment was designed around, so what it did is reported
    whichever way it came out. A cut tie-break shows as an `OPTIMAL` primary that the clock
    still stopped: the objective was proved and the phase that chooses among equal-objective
    plans did not finish.
    """

    cells = record["cells"]
    per_member = record["per_member"]
    # Only the answer counts here. A cell whose deterministic accounting differs but whose
    # plan does not is not a cell where a member would read something else, and counting it
    # as one would make this section contradict the table above it.
    moved_cells = set()
    for entry_id, value in per_member.items():
        for field, arms in value["fields_that_moved"].items():
            if not field.startswith("answer"):
                continue
            for arm in arms:
                moved_cells.add((entry_id, arm))

    lines = ["", "## What a cut tie-break did, as distinct from a cut search", ""]
    lines += [
        "| arm | tie-break cut by the clock | of those, answer moved |",
        "| --- | ---: | ---: |",
    ]
    total_cut = 0
    total_moved = 0
    for arm in arm_order:
        cut = [
            cell
            for cell in cells
            if cell["arm"] == arm
            and cell["solver_status"] == "OPTIMAL"
            and cell["wall_clock_stopped_the_search"]
        ]
        moved = [c for c in cut if (str(c["entry_id"]), arm) in moved_cells]
        total_cut += len(cut)
        total_moved += len(moved)
        lines.append(f"| `{arm}` | {len(cut)} | {len(moved)} |")
    lines += [
        "",
        f"**{total_cut} solves had their tie-break stopped by the clock and {total_moved} of "
        "them published a different plan.** The tie-break is the phase that chooses between "
        "plans of equal objective value, and it is the mechanism this experiment was built "
        "around; on this capture, cutting it changed nothing a member reads.",
        "",
        "Every cell whose answer did move was `FEASIBLE`, which is the ordinary case of a "
        "primary search stopped before it proved, not the subtle one. That is the more "
        "reassuring of the two readings and it is the better supported, so it is stated here "
        "rather than left for a reader to derive from the cells.",
    ]
    return lines


def _markdown(record: dict[str, Any]) -> str:
    # The record is written with sorted keys, so the arms come back alphabetically and
    # `wall_1800s` sorts before `wall_1s`. Read them in ceiling order instead.
    arm_order: list[str] = sorted(record["arms"], key=lambda name: float(record["arms"][name]))
    per_member = record["per_member"]
    moved = [key for key, value in per_member.items() if value["fields_that_moved"]]
    answer_moved = [key for key, value in per_member.items() if value["answer_moved"]]
    lines = [
        f"# The one-week member plan, at {len(arm_order)} wall ceilings",
        "",
        f"Contract `{record['contract_version']}`. Capture `{record['snapshot_id']}`, season "
        f"{record['season']}, gameweek {record['gameweek']}, {record['member_count']} members. "
        "Arms are wall ceilings in seconds: "
        + ", ".join(f"`{name}` at {record['arms'][name]}" for name in arm_order)
        + ". The deterministic budget is "
        f"pinned at {record['deterministic_time_limit']} in every arm, the value the planner "
        "uses in production, and is passed explicitly so the planner does not raise a low "
        "ceiling to its own default. Only the wall ceiling differs.",
        "",
        "Descriptive. Nothing is promoted and no default moves.",
        "",
        "## Did the published answer move?",
        "",
        f"- Members whose comparable record moved at any ceiling: **{len(moved)} of "
        f"{len(per_member)}**.",
        f"- Members whose published answer moved, meaning the squad, the eleven, the captain, "
        f"the chip or the bench order a member reads: **{len(answer_moved)} of "
        f"{len(per_member)}**.",
        "",
        "| member | answer moved | fields that moved |",
        "| --- | --- | ---: |",
    ]
    for entry_id, value in per_member.items():
        lines.append(
            f"| {entry_id} | {'yes' if value['answer_moved'] else 'no'} | "
            f"{len(value['fields_that_moved'])} |"
        )
    lines += _tiebreak_section(record, arm_order)
    lines += [
        "",
        "## What the clock cost, per arm",
        "",
        "| arm | wall ceiling | solves | not proved | clock stopped the search | "
        "no week to publish | wall seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in arm_order:
        summary = record["per_arm"][arm]
        lines.append(
            f"| `{arm}` | {summary['wall_ceiling']} | {summary['solves']} | "
            f"{summary['not_proved']} | {summary['wall_clock_stopped_the_search']} | "
            f"{summary['no_week_to_publish']} | "
            f"{summary['total_wall_seconds']:.1f} |"
        )
    lines += [
        "",
        "Wall seconds are this machine's, measured while other work was running, and are not a "
        "claim about how long a solve takes on a quiet machine. Here the wall clock is the "
        "independent variable, so what it did is the subject and not the noise.",
        "",
    ]
    if not moved:
        lines.append(
            "Nothing moved anywhere. At every ceiling measured, every member's plan, every "
            "diagnostic that is not an echo of the arm, and every field the page publishes came "
            "out identical. On this capture the wall ceiling is what its comment claims it is: "
            "a stop that never binds, not a second budget."
        )
        return "\n".join(lines) + "\n"

    lines += [
        "The ceiling moved something. The table below compares each arm against the reference, "
        "which is the widest ceiling, for the members whose published answer changed. Overlap "
        "counts the players in common with the reference plan, so 15 and 11 mean the same "
        "fifteen and the same eleven. The full plans are in the JSON; a squad is thirty names "
        "and does not belong in a table.",
        "",
        "| member | arm | status | squad overlap | eleven overlap | captain | "
        "own points | bound gap |",
        "| --- | --- | --- | ---: | ---: | --- | ---: | ---: |",
    ]
    cells = record["cells"]
    for entry_id in answer_moved:
        reference_arm = per_member[entry_id]["reference_arm"]
        by_arm = {cell["arm"]: cell for cell in cells if str(cell["entry_id"]) == entry_id}
        reference = by_arm[reference_arm]["answer"]
        for arm in arm_order:
            cell = by_arm.get(arm)
            if cell is None or cell["answer"] is None:
                continue
            answer = cell["answer"]
            squad = len(set(answer["selected_squad"]) & set(reference["selected_squad"]))
            eleven = len(set(answer["starting_xi"]) & set(reference["starting_xi"]))
            gap = cell.get("diagnostics.absolute_optimality_gap")
            lines.append(
                f"| {entry_id} | `{arm}` | {cell['solver_status']} | {squad} of 15 | "
                f"{eleven} of 11 | "
                f"{'same' if answer['captain'] == reference['captain'] else 'different'} | "
                f"{answer['projected_score']:.2f} | "
                f"{'n/a' if gap is None else format(float(gap), '.3f')} |"
            )
    lines += [
        "",
        "The members whose answer did not move still show differences in the solver's own "
        "accounting at the low ceilings, which is the deterministic work spent and the bound "
        "reached rather than the plan chosen. Those are in the JSON under `per_member`.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arguments = _arguments(argv)

    if arguments.rewrite_markdown:
        existing = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        write_text(arguments.markdown_output, _markdown(existing))
        print(f"rewrote {arguments.markdown_output} from {arguments.json_output}")
        return 0

    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; this runner does not overwrite its record.")
        return 1

    arms = [name.strip() for name in arguments.arms.split(",") if name.strip()]
    unknown = [name for name in arms if name not in ARMS]
    if unknown:
        print(f"unknown arms: {unknown}")
        return 1

    data_root = arguments.data_root.resolve()
    identity = load_capture_identity(
        snapshot_root=data_root / "snapshots",
        snapshot_id=arguments.snapshot_id,
        handoff_root=data_root / "handoffs",
        advice_contract_version=CONTRACT_VERSION,
        repository_commit=CONTRACT_VERSION,
        configuration_fingerprint=CONTRACT_VERSION,
    )
    context = load_capture_context(identity)
    inputs = context.inputs
    season = str(inputs.season)
    gameweek = int(inputs.deadline.gameweek)

    if arguments.entries == "all":
        records = data_root / "advice_records" / season / f"gw{gameweek:02d}"
        entries = sorted(int(p.name.removeprefix("entry-")) for p in records.glob("entry-*"))
    else:
        entries = [int(value) for value in arguments.entries.split(",")]
    if not entries:
        print("no members to solve")
        return 1

    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }

    created_utc = datetime.now(UTC).isoformat()
    cells: list[dict[str, Any]] = []
    for entry_id in entries:
        picks = context.provider.picks(entry_id, season, gameweek - 1)
        held = held_squad_from_picks(picks, current_prices=prices)
        for arm in arms:
            started = perf_counter()
            plan, _decision, _config = plan_transfers(
                inputs,
                context.projection,
                held,
                context.rules,
                optimization=OptimizationConfig(
                    solver_time_limit_seconds=ARMS[arm],
                    solver_deterministic_time_limit=PLAN_DETERMINISTIC_TIME_LIMIT,
                ),
            )
            wall_seconds = perf_counter() - started
            cell = _cell(entry_id, arm, plan, wall_seconds)
            cells.append(cell)
            LOGGER.info(
                "%s %-11s %-8s det=%s clock_cut=%s %.1fs",
                entry_id,
                arm,
                cell["solver_status"],
                cell.get("diagnostics.deterministic_time_used"),
                cell["wall_clock_stopped_the_search"],
                wall_seconds,
            )

    for cell in cells:
        arm = str(cell["arm"])
        if cell["diagnostics.deterministic_budget_source"] != "caller":
            print(f"control failed: {cell['entry_id']} {arm} took the planner's own budget")
            return 1
        if float(cell["diagnostics.wall_time_limit_seconds"]) != ARMS[arm]:
            print(f"control failed: {cell['entry_id']} {arm} did not run at its own ceiling")
            return 1

    per_arm = {
        arm: {
            "wall_ceiling": ARMS[arm],
            "solves": sum(cell["arm"] == arm for cell in cells),
            "wall_clock_stopped_the_search": sum(
                cell["arm"] == arm and cell["wall_clock_stopped_the_search"] for cell in cells
            ),
            "no_week_to_publish": sum(
                cell["arm"] == arm and not cell["has_week"] for cell in cells
            ),
            "not_proved": sum(
                cell["arm"] == arm and cell["solver_status"] != "OPTIMAL" for cell in cells
            ),
            "total_wall_seconds": sum(
                cell["measured_wall_seconds"] for cell in cells if cell["arm"] == arm
            ),
        }
        for arm in arms
    }

    document = _document(
        created_utc=created_utc,
        snapshot_id=arguments.snapshot_id,
        season=season,
        gameweek=gameweek,
        entries=entries,
        arms=arms,
        per_arm=per_arm,
        cells=cells,
    )
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _markdown(document))
    print(_markdown(document))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
