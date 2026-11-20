"""Produce the Phase 6 gain report from a completed offline replay receipt."""

import argparse
import hashlib
import json
from pathlib import Path

from docs.research.llmopt_phase1 import benchmark
from docs.research.llmopt_phase6.measure import ARMS, METRICS, ROOT, SOURCES


def report(receipt: Path) -> dict:
    record = json.loads(receipt.read_text(encoding="utf-8"))
    expected = {
        f"gw{inputs.gameweek}-{entry}"
        for _, inputs in benchmark.snapshots()
        for entry in inputs.members
    }
    rows = record["rows"]
    if not record["complete"] or {row["case"] for row in rows} != expected or len(rows) != 20:
        raise ValueError("The report requires all twenty frozen member-weeks, including errors.")
    for source in SOURCES:
        digest = hashlib.sha256((ROOT / source).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if digest != record["provenance"]["phase6_source_sha256"][source.as_posix()]:
            raise ValueError(f"Measured source changed: {source}")
    frozen = json.loads((ROOT / "docs/research/llmopt_phase1_baseline.json").read_text())
    frozen_by_case = {row["case"]: row["expected_comparison"]["single"] for row in frozen["rows"]}
    arms = {}
    for name, _, _ in ARMS:
        valid = [r for r in rows if all(r["arms"][name][key] is not None for key in METRICS)]
        arms[name] = {
            "valid_member_weeks": len(valid),
            "error_member_weeks": [
                r["case"] for r in rows if r["arms"][name]["solver_status"] == "ERROR"
            ],
            "native_and_cp_within_122": all(
                r["arms"][name]["cp_work_charged"] + r["arms"][name]["native_work_reserved"] <= 122
                for r in rows
            ),
            "maximum_charged_units": max(
                r["arms"][name]["cp_work_charged"] + r["arms"][name]["native_work_reserved"]
                for r in rows
            ),
            "metrics": {},
        }
        for key in METRICS:
            gains = [r["arms"][name]["gain_points"][key] for r in valid]
            arms[name]["metrics"][key] = {
                "positive_member_weeks": sum(value > 0 for value in gains),
                "negative_member_weeks": sum(value < 0 for value in gains),
                "sum_gain_points": sum(gains),
                "minimum_gain_points": min(gains, default=None),
            }
        arms[name]["accepted_packages"] = sum(
            (r["arms"][name]["experiment"] or {}).get("accepted") is True for r in rows
        )
    baseline_valid = [r for r in rows if r["arms"]["disabled"]["has_solution"]]
    frozen_matches = sum(
        all(r["arms"]["disabled"][key] == frozen_by_case[r["case"]][key] for key in METRICS)
        for r in baseline_valid
    )
    summary = {
        "kind": "llmopt_phase6_full_pool_comparison_v1",
        "repository_commit": record["provenance"]["producer_commit"],
        "population": 20,
        "provenance": record["provenance"],
        "network_attempts": record["network_attempts"],
        "arms": arms,
        "disabled_exact_metric_matches_frozen": frozen_matches,
        "inherited_capacity_overruns": [
            {
                "case": r["case"],
                "charged_units": r["arms"]["disabled"]["cp_work_charged"]
                + r["arms"]["disabled"]["native_work_reserved"],
            }
            for r in rows
            if r["arms"]["disabled"]["cp_work_charged"]
            + r["arms"]["disabled"]["native_work_reserved"]
            > 122
        ],
        "acceptance_all_twenty_computed_without_regression": all(
            a["valid_member_weeks"] == 20
            and a["native_and_cp_within_122"]
            and all(m["negative_member_weeks"] == 0 for m in a["metrics"].values())
            for a in arms.values()
        ),
        "initial_capacity_probe": {
            "producer_commit": "404ad2168deab26dffd8845e0b1d63a2dfb044ef",
            "observed_overcommitted_units": [122.00005910826036, 122.07175244622803],
            "resolution": "reserve_native_and_cp_together_before_optional_work",
        },
        "rows": rows,
    }
    destination = ROOT / "docs/research/llmopt_phase6_results.json"
    benchmark.write(destination, summary)
    lines = [
        "# LLMOPT Phase 6: full-pool package comparison",
        "",
        f"Producer: `{record['provenance']['producer_commit']}`. "
        "Twenty unchanged frozen Phase 1 member-weeks.",
        "",
        "Decision: [ADR 0022](../architecture/decisions/0022-llmopt-transfer-packages.md).",
        "",
        "The retained prefix is computed once and charged in full to each comparison arm. "
        "Every arm has the same 60 CP-unit window, 122 admitted units, 1,800-second wall ceiling "
        "and a cap of 1,153 exact lineup evaluations. No tests run alongside this local replay. "
        "These are algorithm comparisons, not independent cold-request latency measurements. "
        "No realized scores or live service are used.",
        "",
        f"Frozen metrics match exactly in {frozen_matches}/{len(baseline_valid)} "
        "computed cases. "
        f"Network attempts: {record['network_attempts']}.",
        "",
        "| Arm | Computed | Errors | Accepted packages | Highest charged units | "
        "Raw XI gain | Expected net gain | Selection utility gain |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, _, _ in ARMS:
        arm = arms[name]
        sums = [arm["metrics"][key]["sum_gain_points"] for key in METRICS]
        lines.append(
            f"| {name} | {arm['valid_member_weeks']} | {len(arm['error_member_weeks'])} | "
            f"{arm['accepted_packages']} | {arm['maximum_charged_units']:.9f} | "
            + " | ".join(f"{gain:.9f}" for gain in sums)
            + " |"
        )
    lines.extend(
        [
            "",
            "Gains aggregate only computed cases. Error cases retain null gains and remain "
            "in the twenty-member denominator. The complete all-twenty condition is "
            f"`{summary['acceptance_all_twenty_computed_without_regression']}`.",
            "",
            "The two five-free-transfer member-weeks fail inside the unchanged retained "
            "algorithm. Both enabled arms retain those errors rather than replacing them "
            "with a zero gain. The actually served football input bundles needed to "
            "reproduce and fix them were unavailable in the separate preliminary probe.",
            "",
            "Inherited capacity overruns in the disabled algorithm: "
            + ", ".join(
                f"{r['case']} = {r['charged_units']:.12f}"
                for r in summary["inherited_capacity_overruns"]
            )
            + ". No new package work starts after that allocation is exhausted. "
            "This existing stopping-granularity issue remains visible; the cap and "
            "accounting tolerance were not increased.",
            "",
            "| Member-week | Arm | Raw XI difference | Expected net difference | "
            "Selection utility difference | Outcome |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        for name in ("packages", "opened_gate"):
            arm = row["arms"][name]
            values = [arm["gain_points"][key] for key in METRICS]
            experiment = arm["experiment"] or {}
            lines.append(
                f"| {row['case']} | {name} | "
                + " | ".join("null" if value is None else f"{value:.9f}" for value in values)
                + f" | {experiment.get('reason') or arm['solver_status']} |"
            )
    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```powershell",
            "$env:PYTHONPATH='src'",
            "python -m docs.research.llmopt_phase6.measure",
            "python -m docs.research.llmopt_phase6.report",
            "```",
            "",
            "The JSON includes proposed component metrics even when the conservative acceptance "
            "guard retains the incumbent. Review those tradeoffs before activating "
            "either disabled control.",
            "",
        ]
    )
    (ROOT / "docs/research/llmopt_phase6_results.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipt", type=Path, default=ROOT / "artifacts/llmopt_phase6/results.json"
    )
    arguments = parser.parse_args()
    result = report(arguments.receipt)
    print(
        json.dumps(
            {
                "arms": result["arms"],
                "acceptance": result["acceptance_all_twenty_computed_without_regression"],
            },
            indent=2,
        )
    )
