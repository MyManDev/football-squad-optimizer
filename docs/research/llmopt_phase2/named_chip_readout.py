"""Render the named-chip comparison directly from the measured JSON record."""

import argparse
import json
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[1] / "llmopt_phase2_named_chip.json"


def number(value):
    return "unavailable" if value is None else f"{value:.8f}".rstrip("0").rstrip(".")


def write_readout(report, path):
    rows = report["rows"]
    semantic = (
        "same_key",
        "same_spec",
        "same_status",
        "same_transfers",
        "same_objective",
        "same_published_net_points",
    )
    matching = sum(all(row[key] for key in semantic) for row in rows)
    lines = [
        "# Frozen named-chip cache parity",
        "",
        "The two cold workers agreed on solver status, weekly transfers, solver objective and "
        f"published net points at the same address and immutable specification in {matching} "
        f"of {len(rows)} paired controls. Each pair submitted the same chip, preferences, member "
        "and horizon to isolated local instances of the API, queue, cache and worker. "
        "The run-bound request included a run reference. Both used the same frozen API context.",
        "",
        f"Producer commit `{report['producer_repository_commit']}`. "
        f"OR-Tools `{report['solver_version']}`.",
        "",
    ]
    for key, description in (
        ("same_status", "Completed solver statuses"),
        ("same_transfers", "Weekly transfer decisions"),
        ("same_objective", "Solver objectives"),
        ("same_published_net_points", "Published net points"),
        ("same_key", "Cache addresses"),
        ("same_spec", "Immutable request specifications"),
        ("same_payload", "Cached bytes (audit)"),
    ):
        lines.append(f"- {description} matched in {sum(row[key] for row in rows)}/{len(rows)}.")
    lines += [
        "",
        "| Member-week | Chip | Weeks | Bound status | Legacy status | Bound objective | "
        "Legacy objective | Bound minus legacy | Bound net points | Legacy net points | "
        "Transfers equal | Bound work / allocation | Legacy CP units / native calls |",
        "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in rows:
        bound, legacy = row["run_bound"], row["legacy"]
        receipt = bound["receipt"]
        charged = None if receipt is None else receipt["cp_used"] + receipt["native_reserved"]
        cp = sum(
            c["deterministic_units"] for c in legacy["solver_calls"] if c["backend"] == "cp-sat"
        )
        native = sum(c["backend"] == "highs-native" for c in legacy["solver_calls"])
        values = (
            row["case"],
            row["scenario"],
            row["window"],
            bound["solver_status"] or bound["job_error"],
            legacy["solver_status"] or legacy["job_error"],
            number(bound["objective"]),
            number(legacy["objective"]),
            number(row["objective_delta"]),
            number(bound["published_net_points"]),
            number(legacy["published_net_points"]),
            "yes" if row["same_transfers"] else "no",
            f"{number(charged)} / {bound['allocation']}",
            f"{number(cp)} / {native}",
        )
        lines.append("| " + " | ".join(map(str, values)) + " |")
    mismatches = [row for row in rows if not row["same_payload"]]
    if mismatches:
        lines.extend(["", "## Cached document differences", ""])
        for row in mismatches:
            fields = ", ".join(f"`{key}`" for key in row["differing_payload_fields"])
            lines.append(
                f"- {row['case']}, {row['window']} weeks. "
                f"Changed payload fields include {fields or 'none; see job status'}."
            )
    lines += [
        "",
        "The JSON retains both cache addresses, specification and document hashes, the solver "
        "status, objective, published net points, transfer IDs for every week, individual solver "
        "calls and the durable run receipt. The frozen Phase 1 direct-planner control is recorded "
        "separately. The equality columns compare the two actual worker outcomes.",
        "",
        "The adapter uses frozen Phase 1 players, expected points, fixture counts, transfer "
        "balances, held players and sale proceeds. It reconstructs an equivalent purchase basis "
        "at the frozen prices. Both workers receive the capture timestamp and a synthetic deadline "
        "one day later. The replay grants the named chip for the requested week using synthetic "
        "chip rights. These controls compare worker behavior on fixed inputs.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, nargs="?", default=DEFAULT)
    args = parser.parse_args()
    write_readout(json.loads(args.record.read_bytes()), args.record.with_suffix(".md"))


if __name__ == "__main__":
    main()
