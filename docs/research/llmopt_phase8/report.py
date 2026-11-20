"""Generate the English closing report from the completed two-mode load record."""

import argparse
import json
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median

from docs.research.llmopt_phase8.measure import OUTPUT, RESEARCH


def quantiles(values):
    if not values:
        return "n/a"
    ordered = sorted(values)
    return f"{median(ordered):.3f} / {ordered[ceil(len(ordered) * 0.95) - 1]:.3f}"


def table(header, rows):
    def line(cells):
        return "| " + " | ".join(map(str, cells)) + " |"

    return "\n".join([line(header), line(["---"] * len(header)), *map(line, rows)])


def group_summary(passes):
    jobs = [job for p in passes for job in p["jobs"]]
    workers = [w for p in passes for w in p["device_work"]]
    outcomes = [slot for p in passes for key, slot in p["answers"].items() if key != "base"]
    completed = sum(row.get("path") is not None for row in outcomes)
    yield_count = sum(p["distinct_alternative_paths"] for p in passes)
    return {
        "runs": len(passes),
        "jobs": len(jobs),
        "job_calls": sum(j["solver_calls"] for j in jobs),
        "device_workers": len(workers),
        "device_calls": sum(len(w["calls"]) for w in workers),
        "queue_s": quantiles([j["queue_seconds"] for j in jobs]),
        "job_s": quantiles([j["worker_seconds"] for j in jobs]),
        "job_units": quantiles([j["cp_units"] for j in jobs]),
        "job_solves": quantiles([j["solver_calls"] for j in jobs]),
        "device_s": quantiles([w["elapsed_seconds"] for w in workers]),
        "elapsed_s": quantiles([p["seconds"] for p in passes]),
        "completed": completed,
        "eligible": len(outcomes),
        "distinct": yield_count,
        "yield_runs": sum(p["distinct_alternative_paths"] > 0 for p in passes),
    }


def stats_by_window(receipt, members):
    by_mode = {(r["window"], r["release"], r["case"]): r for r in receipt["rows"]}
    if len(by_mode) != len(receipt["rows"]) or set(by_mode) != {
        (window, mode, case) for window in (1, 3) for mode in ("off", "on") for case in members
    }:
        raise ValueError("Both cold/warm, on/off arms and windows must cover every frozen member.")
    overview, costs, alternatives, scores = [], [], [], []
    totals = {}
    statuses = []
    for window in (1, 3):
        for cache in ("cold", "warm"):
            for mode in ("off", "on"):
                values = [by_mode[window, mode, member][cache] for member in members]
                s = group_summary(values)
                totals[window, mode, cache] = s
                group = [window, mode, cache]
                overview.append(
                    [
                        *group,
                        s["jobs"],
                        s["job_calls"],
                        s["device_workers"],
                        s["device_calls"],
                        s["elapsed_s"],
                    ]
                )
                costs.append(
                    [
                        *group,
                        s["queue_s"],
                        s["job_s"],
                        s["job_units"],
                        s["job_solves"],
                        s["device_s"],
                    ]
                )
                alternatives.append(
                    [
                        *group,
                        f"{s['completed']} / {s['eligible']}",
                        s["distinct"],
                        f"{s['yield_runs']} / {s['runs']}",
                    ]
                )
                for member, value in zip(members, values, strict=True):
                    for label, slot in value["answers"].items():
                        if slot.get("path") is None:
                            statuses.append(
                                [member, *group, label, slot.get("reason") or slot["status"]]
                            )
        for slot in ("base", "combined"):
            deltas = []
            same_decision = 0
            for member in members:
                off, on = [
                    by_mode[window, m, member]["cold"]["answers"][slot] for m in ("off", "on")
                ]
                if off.get("net") is None or on.get("net") is None:
                    continue
                deltas.append(on["net"] - off["net"])
                same_decision += on["path"] == off["path"]
            signs = Counter(1 if d > 1e-8 else -1 if d < -1e-8 else 0 for d in deltas)
            scores.append(
                [
                    window,
                    slot,
                    f"{len(deltas)} / {len(members)}",
                    same_decision,
                    signs[1],
                    signs[0],
                    signs[-1],
                    f"{sum(deltas):+.3f}" if deltas else "n/a",
                ]
            )
    return overview, costs, alternatives, scores, totals, statuses


def render(receipt, baseline, packages):
    members = sorted(row["case"] for row in baseline["rows"])
    if len(members) != 20 or len(set(members)) != 20:
        raise ValueError("Phase 1 must identify twenty distinct members.")
    overview, costs, alternatives, scores, totals, statuses = stats_by_window(receipt, members)
    count_change = []
    for window in (1, 3):
        off, on = [totals[window, m, "cold"]["jobs"] for m in ("off", "on")]
        count_change.append(f"{off} to {on} at {window} week{'s' if window == 3 else ''}")
    frozen = sorted(
        (r["case"], int(window), v["pricing"])
        for r in baseline["rows"]
        for window, v in r["windows"].items()
        if v["pricing"]
    )
    history = [
        [name, w, row["backend_jobs"], row["solver_calls"], f"{row['total_seconds']:.3f}"]
        for name, w, row in frozen
    ]
    warm_rows = []
    for window in (1, 3):
        for mode in ("off", "on"):
            selected = [
                r for r in receipt["rows"] if r["release"] == mode and r["window"] == window
            ]
            matches = sum(r["cold"]["answers"] == r["warm"]["answers"] for r in selected)
            old_jobs = sum(
                len(set(s["returned_job_ids"]) - set(s["job_ids"]))
                for r in selected
                for s in r["warm"]["stages"]
            )
            warm_rows.append(
                [
                    window,
                    mode,
                    f"{matches} / {len(selected)}",
                    old_jobs,
                    sum(len(r["warm"]["jobs"]) for r in selected),
                    sum(len(r["warm"]["device_work"]) for r in selected),
                ]
            )
    arms = packages["arms"]
    package_rows = []
    for mode, data in arms.items():
        measured = data["metrics"]
        package_rows.append(
            [
                mode,
                f"{data['valid_member_weeks']} / {packages['population']}",
                data["accepted_packages"],
                *(
                    f"{measured[metric]['sum_gain_points']:+.3f}"
                    for metric in (
                        "raw_xi_net_points",
                        "expected_lineup_net_points",
                        "selection_utility",
                    )
                ),
            ]
        )
    sections = [
        "# LLMOPT local workload and closing report",
        f"The fresh comparison opened {' and '.join(count_change)}. Each count covers the same "
        "twenty frozen member-weeks with the same three preferences. Each mode also repeats every "
        "run against its own warm cache. [Per-run measurements](llmopt_phase8_load.json)",
        "## Work and elapsed time",
        table(
            [
                "Weeks",
                "Release",
                "Cache",
                "Server jobs",
                "Server solver calls",
                "Device workers",
                "Device solver calls",
                "Total seconds p50 / p95",
            ],
            overview,
        ),
        "The two individual prices can wait together in the real file queue. One local worker "
        "drains them, then the combined stage can start. Every queue wait runs from durable "
        "publication to successful claim. Worker time runs from claim through terminal result. "
        "Total time includes capability lookup, admission, solver work, result reads and local "
        "process communication. An arm with zero jobs has no per-job sample.",
        table(
            [
                "Weeks",
                "Release",
                "Cache",
                "Queue seconds p50 / p95",
                "Worker seconds p50 / p95",
                "CP units/job p50 / p95",
                "Solver calls/job p50 / p95",
                "Device seconds p50 / p95",
            ],
            costs,
        ),
        "CP units are measured deterministic solver work. Native HiGHS and device HiGHS have "
        "separate wall limits. Per-job receipts retain measured native seconds and calls, "
        "CP seconds and units, and configured allocations when supplied. Device worker rows "
        "retain actual WASM calls, solve times and load time. Local elapsed values describe "
        "this single-worker replay. The median and nearest-rank p95 describe independent cases "
        "within each row.",
        table(
            [
                "Weeks",
                "Release",
                "Warm runs matching cold",
                "Existing jobs returned",
                "New warm jobs",
                "New warm device workers",
            ],
            warm_rows,
        ),
        "Warm confirmation repeats the same draft against its own completed or failed run. "
        "The comparison covers each slot's outcome, reason, source, expected net points and "
        "transfer path. Returning an existing terminal job does not create a queue entry.",
        "## Alternative yield and paired scores",
        table(
            [
                "Weeks",
                "Release",
                "Cache",
                "Completed / possible preference results",
                "Distinct additional paths",
                "Runs yielding another path",
            ],
            alternatives,
        ),
        "The three preference result slots comprise the two individual prices and the combined "
        "plan. A completed price may return the same transfers as the base or another price. "
        "The yield column counts unique transfer and chip paths across the whole window after "
        "removing those duplicates and the base. These are the alternatives in this pricing "
        "workload. Separate hard-only menus and package-search experiments use other workloads.",
        table(
            [
                "Weeks",
                "Result",
                "Paired / total",
                "Same transfer path",
                "Higher",
                "Equal",
                "Lower",
                "Total expected net difference",
            ],
            scores,
        ),
        "Score differences use enabled minus disabled published expected net points. Transfer "
        "identity excludes changes confined to the lineup or captain. The equal-score count "
        "uses an absolute numerical comparison of 1e-8 points. Incomplete pairs keep their "
        "status in the row record and contribute no numeric difference.",
        "## Phase 1 reference",
        table(["Member-week", "Weeks", "Server jobs", "Solver calls", "Solver seconds"], history),
        "Phase 1 froze all twenty member-weeks. It measured this complete four-job workload "
        "for the first member of each capture only. Its solver timings and isolated queue "
        "counts did not include API orchestration. The fresh disabled arm extends the same "
        "two unbounded keep preferences and unbounded no-hit preference over the full twenty. "
        "The original rotated standalone controls serve another purpose and were not substituted "
        "for those three preferences. [Phase 1 baseline](llmopt_phase1_baseline.md)",
        "## Package search",
        table(
            [
                "Full-pool arm",
                "Computed / total",
                "Accepted packages",
                "Raw XI gain",
                "Expected lineup net gain",
                "Selection utility gain",
            ],
            package_rows,
        ),
        "The separate Phase 6 record counts all twenty member-weeks. Numeric gains cover the "
        "completed pairs only. Sixteen full-pool proposals produced zero accepted packages. "
        "Both package settings remain at their default value of zero. "
        "[Full-pool comparison](llmopt_phase6_results.md)",
        "## Reproduction and scope",
        "Run the commands from the repository root with its Python environment and installed "
        "web dependencies. Use a local checkout containing both publication commits listed in "
        "the frozen inputs. The frozen inputs and Phase 1 records are read-only.",
        "```powershell\n$env:PYTHONPATH='src'\npython -m docs.research.llmopt_phase8.measure"
        "\npython -m docs.research.llmopt_phase8.report\n```",
        f"Measured source commit `{receipt['provenance']['commit']}`. The JSON also records source "
        "digests. The server parses each isolated configuration through its normal environment "
        "reader. The local API advertises the capability to the production planner. The measured "
        "transport submits the resulting production requests via an in-process FastAPI adapter. "
        "For the enabled one-week draft, every new device worker requires another matching "
        "capability response. Each new worker records its permission read number. The server "
        "retains its legacy cache reader in both modes. The local solver uses the original "
        "published table and member documents, verified "
        "against the frozen solver inputs. Only the worker message port, browser session-storage "
        "medium and HTTP connection are adapted for local replay. Each asset loads locally.",
        "Cold arms start with independent empty queues, caches and storage. Warm arms rebuild "
        "the device client while retaining the same run identity and stored results. Runs use "
        "the original member inputs and the saved expected-point table. No deployment, live "
        "traffic, load from unrelated users, provider call, historical realized-score comparison "
        "or live-latency measurement forms part of this experiment.",
        "## Unfinished",
        "The Phase 6 full-pool record retains accounting failures for gw8-3832237 and "
        "gw9-3832237. Its disabled main solve for gw8-5349883 used 122.000084823223 units "
        "against 122. The cap and tolerance are unchanged. The paired package result still "
        "covers 18 of 20 cases. [Original probe](llmopt_window_budget_probe.md)",
        (
            "The following workload result slots did not complete.\n\n"
            + table(["Member-week", "Weeks", "Release", "Cache", "Slot", "Outcome"], statuses)
        )
        if statuses
        else "All four answer slots completed in every measured workload pass.",
        "The release setting defaults to disabled. The project owner decides whether and when "
        "to activate it. "
        "[Release decision](../architecture/decisions/0024-llmopt-release-control.md)",
    ]
    return "\n\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--output", type=Path, default=RESEARCH / "llmopt_phase8_closing.md")
    args = parser.parse_args()
    baseline = json.loads((RESEARCH / "llmopt_phase1_baseline.json").read_bytes())
    full_pool = json.loads((RESEARCH / "llmopt_phase6_results.json").read_bytes())
    report = render(json.loads(args.input.read_bytes()), baseline, full_pool)
    args.output.write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
