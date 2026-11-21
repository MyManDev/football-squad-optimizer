"""Generate the English closing report from the completed two-mode load record."""

import argparse
import json
import subprocess
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median

from docs.research.llmopt_phase8.measure import OUTPUT, RESEARCH, ROOT

PRIOR_RECORD_REF = "d9a99fa421fda5ee27b735f969940597da61f6d3"
SLOTS = ("base", "first", "second", "combined")
NET_TOLERANCE = 1e-8


def percentiles(values):
    if not values:
        return None
    ordered = sorted(values)
    return median(ordered), ordered[ceil(len(ordered) * 0.95) - 1]


def format_pair(values, *, signed=False):
    if values is None:
        return "n/a"
    return " / ".join(format(v, "+.3f" if signed else ".3f") for v in values)


def quantiles(values):
    return format_pair(percentiles(values))


def time_change(before, after):
    if before is None or after is None:
        return "n/a"
    return format_pair([new - old for old, new in zip(before, after, strict=True)], signed=True)


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


def index_rows(receipt, members):
    by_mode = {(r["window"], r["release"], r["case"]): r for r in receipt["rows"]}
    if len(by_mode) != len(receipt["rows"]) or set(by_mode) != {
        (window, mode, case) for window in (1, 3) for mode in ("off", "on") for case in members
    }:
        raise ValueError("Both cold/warm, on/off arms and windows must cover every frozen member.")
    for key, row in by_mode.items():
        for cache in ("cold", "warm"):
            if set(row[cache]["answers"]) != set(SLOTS):
                raise ValueError(f"Missing or extra answer slot in {key}, {cache}.")
    return by_mode


def stats_by_window(receipt, members, failures):
    by_mode = index_rows(receipt, members)
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
                same_path_and_score = 0
                sources = Counter()
                for member in members:
                    off, on = [
                        by_mode[window, m, member][cache]["answers"][slot] for m in ("off", "on")
                    ]
                    sources[off.get("source"), on.get("source")] += 1
                    if not (completed(off) and completed(on)):
                        continue
                    delta = on["net"] - off["net"]
                    deltas.append(delta)
                    same_decision += on["path"] == off["path"]
                    same_path_and_score += on["path"] == off["path"] and abs(delta) <= NET_TOLERANCE
                signs = Counter(
                    1 if d > NET_TOLERANCE else -1 if d < -NET_TOLERANCE else 0 for d in deltas
                )
                if same_path_and_score != len(members):
                    failures.append(
                        f"{window}-week {cache} {slot}: {same_path_and_score} of {len(members)} "
                        "OFF/ON pairs completed with matching transfer paths and net points."
                    )
                scores.append(
                    [
                        window,
                        cache,
                        slot,
                        f"{len(deltas)} / {len(members)}",
                        same_decision,
                        same_path_and_score,
                        signs[1],
                        signs[0],
                        signs[-1],
                        f"{sum(deltas):+.3f}" if deltas else "n/a",
                        source_counts(sources),
                    ]
                )
    return overview, costs, alternatives, scores, totals, statuses


def completed(answer):
    return (
        answer["status"] in {"OPTIMAL", "FEASIBLE", "done"}
        and answer.get("path") is not None
        and answer.get("net") is not None
    )


def source_counts(transitions):
    return ", ".join(
        f"{left or 'unreported'} → {right or 'unreported'} ({n})"
        for (left, right), n in transitions.items()
    )


def max_job(jobs, field):
    if not jobs:
        return "n/a"
    case, job = max(jobs, key=lambda pair: pair[1][field])
    return f"{job[field]:.3f} ({case}, {job['stage']})"


def compare_records(receipt, prior, prior_commit, members, failures):
    if receipt["contract_version"] != prior["contract_version"]:
        raise ValueError("The workload contracts differ.")
    for name in (
        "docs/research/llmopt_phase1/inputs.json",
        "docs/research/llmopt_phase1_baseline.json",
    ):
        if (
            receipt["provenance"]["source_sha256"][name]
            != prior["provenance"]["source_sha256"][name]
        ):
            raise ValueError(f"The frozen workload has changed: {name}.")
    earlier, current = (index_rows(r, members) for r in (prior, receipt))
    comparisons, differences, timings, elapsed_changes = [], [], [], []
    for window in (1, 3):
        for cache in ("cold", "warm"):
            elapsed = {}
            for mode in ("off", "on"):
                exact = paired = same_plan = same_terminal = count = 0
                sources = Counter()
                for case in members:
                    key = window, mode, case
                    for slot in SLOTS:
                        old, new = (r[key][cache]["answers"][slot] for r in (earlier, current))
                        count += 1
                        sources[old.get("source"), new.get("source")] += 1
                        same_terminal += (old["status"], old.get("reason")) == (
                            new["status"],
                            new.get("reason"),
                        )
                        exact += old == new
                        if completed(old) and completed(new):
                            paired += 1
                            same_plan += (
                                old["path"] == new["path"]
                                and abs(old["net"] - new["net"]) <= NET_TOLERANCE
                            )
                        if old != new:
                            differences.append(
                                [
                                    case,
                                    window,
                                    mode,
                                    cache,
                                    slot,
                                    json.dumps(old, ensure_ascii=False),
                                    json.dumps(new, ensure_ascii=False),
                                ]
                            )
                comparisons.append(
                    [
                        window,
                        mode,
                        cache,
                        count,
                        exact,
                        same_terminal,
                        paired,
                        same_plan,
                        source_counts(sources),
                    ]
                )
                if mode == "off" and exact != count:
                    failures.append(
                        f"{window}-week {cache} OFF: {exact} of {count} answers exactly "
                        "matched the previous record."
                    )
                for label, record in (("Earlier", earlier), ("H2", current)):
                    passes = [(case, record[window, mode, case][cache]) for case in members]
                    jobs = [(case, j) for case, p in passes for j in p["jobs"]]
                    waits = [job["queue_seconds"] for _, job in jobs]
                    durations = [job["worker_seconds"] for _, job in jobs]
                    elapsed[label, mode, "Run"] = percentiles([p["seconds"] for _, p in passes])
                    elapsed[label, mode, "Worker per job"] = percentiles(durations)
                    timings.append(
                        [
                            window,
                            mode,
                            cache,
                            label,
                            len(jobs),
                            quantiles(waits),
                            max_job(jobs, "queue_seconds"),
                            quantiles(durations),
                            max_job(jobs, "worker_seconds"),
                        ]
                    )
            for metric in ("Run", "Worker per job"):
                off, on = (elapsed["H2", m, metric] for m in ("off", "on"))
                previous_on = elapsed["Earlier", "on", metric]
                elapsed_changes.append(
                    [
                        window,
                        cache,
                        metric,
                        format_pair(off),
                        format_pair(on),
                        time_change(off, on),
                        format_pair(previous_on),
                        time_change(previous_on, on),
                    ]
                )
    sections = [
        "## Comparison with the previous workload",
        f"The previous record comes from Git commit `{prior_commit}` and identifies measured "
        f"producer `{prior['producer_repository_commit']}`. H2 measures producer "
        f"`{receipt['producer_repository_commit']}` on the same frozen inputs. Both records "
        "cover 640 answer slots across twenty member-weeks, two windows, two release modes "
        "and cold and warm caches. "
        f"[Previous measurement](https://github.com/MyManDev/football-squad-optimizer/blob/"
        f"{prior_commit}/docs/research/llmopt_phase8_load.json)",
        table(
            [
                "Weeks",
                "Release",
                "Cache",
                "Slots",
                "Exact answers",
                "Same status and reason",
                "Both completed",
                "Same path and points",
                "Source, earlier → H2",
            ],
            comparisons,
        ),
        "Exact answers include every recorded field. Successful answers carry solver status, "
        "source, full-window transfers and chip use, and expected net points. Failed or idle "
        "slots carry their recorded status and reason and contribute no plan or score. "
        "The path-and-points column requires a completed pair, the same transfer and chip path "
        "and an absolute difference of at most 1e-8 points. The historical record omits "
        "lineups, captain choices and bank balances.",
    ]
    if differences:
        sections += [
            "### Changed answer slots",
            table(
                ["Member-week", "Weeks", "Release", "Cache", "Slot", "Earlier answer", "H2 answer"],
                differences,
            ),
        ]
    sections += [
        "### Queue and worker time",
        table(
            [
                "Weeks",
                "Release",
                "Cache",
                "Record",
                "Jobs",
                "Queue p50 / p95 (s)",
                "Queue max (s), member-week and stage",
                "Worker p50 / p95 (s)",
                "Worker max (s), member-week and stage",
            ],
            timings,
        ),
        "Each queue publication contributes one wait and one worker duration. An arm with "
        "zero new server jobs has no per-job observations.",
        "### Change in elapsed time",
        table(
            [
                "Weeks",
                "Cache",
                "Seconds p50 / p95",
                "H2 off",
                "H2 on",
                "H2 on minus off",
                "Earlier on",
                "H2 on minus earlier on",
            ],
            elapsed_changes,
        ),
        "Run durations cover the entire member workload. Worker durations cover one server job. "
        "Signed columns compare the median and nearest-rank p95 within each arm. Positive "
        "values indicate longer elapsed time.",
    ]
    return sections


def render(receipt, baseline, packages, prior, prior_commit):
    members = sorted(row["case"] for row in baseline["rows"])
    if len(members) != 20 or len(set(members)) != 20:
        raise ValueError("Phase 1 must identify twenty distinct members.")
    failures = []
    overview, costs, alternatives, scores, totals, statuses = stats_by_window(
        receipt, members, failures
    )
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
            new_jobs = sum(len(r["warm"]["jobs"]) for r in selected)
            new_workers = sum(len(r["warm"]["device_work"]) for r in selected)
            if matches != len(selected) or new_jobs or new_workers:
                failures.append(
                    f"{window}-week warm {mode.upper()}: {matches} of {len(selected)} runs "
                    f"matched cold answers, with {new_jobs} new server jobs and "
                    f"{new_workers} new device workers."
                )
            warm_rows.append(
                [
                    window,
                    mode,
                    f"{matches} / {len(selected)}",
                    old_jobs,
                    new_jobs,
                    new_workers,
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
        *compare_records(receipt, prior, prior_commit, members, failures),
        "## Workload checks",
        "\n".join(f"- {message}" for message in failures)
        if failures
        else (
            "All 320 OFF answers exactly matched the previous record. All 160 cross-mode "
            "base and combined pairs completed with matching transfer paths and net points. "
            "All 80 warm runs matched cold answers with zero new server jobs or device workers."
        ),
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
        "this single-worker replay. Run percentiles use the twenty member-weeks in an arm. "
        "Per-job and per-worker percentiles use the individual jobs and workers.",
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
                "Cache",
                "Result",
                "Both completed / total",
                "Same transfer path",
                "Same path and points",
                "Higher",
                "Equal",
                "Lower",
                "Total expected net difference",
                "Source, off → on",
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
        f"\npython -m docs.research.llmopt_phase8.report --check --compare-ref {prior_commit}\n```",
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
        "A separate develop-based change returned feasible three-week plans for both "
        "five-transfer cases and preserved the other eighteen on the frozen expected-window "
        "workload. The Phase 6 package comparison above uses its original measurements. "
        "[Independent before-and-after record](https://github.com/MyManDev/football-squad-optimizer/"
        "blob/fc2a6d9c4931d8da25df0b272dcf8211f4574429/docs/research/expected_window_guard.md) · "
        "[Pull request #1478](https://github.com/MyManDev/football-squad-optimizer/pull/1478)",
        (
            "The following workload result slots did not complete.\n\n"
            + table(["Member-week", "Weeks", "Release", "Cache", "Slot", "Outcome"], statuses)
        )
        if statuses
        else "All four answer slots completed in every measured workload pass.",
        "The release setting defaults to disabled. The project owner decides whether and when "
        "to activate it. "
        "[Release decision](../architecture/decisions/0024-llmopt-release-control.md)",
        "Provider acceptance is a separate owner check. The local workload made no provider "
        "calls. [One-message checks for each provider](llmopt_provider_acceptance.md)",
    ]
    return "\n\n".join(sections) + "\n", failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=OUTPUT)
    parser.add_argument("--output", type=Path, default=RESEARCH / "llmopt_phase8_closing.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit unsuccessfully on an answer or warm-work mismatch after writing the report.",
    )
    parser.add_argument(
        "--compare-ref",
        default=PRIOR_RECORD_REF,
        help="Git reference containing the previous workload record.",
    )
    args = parser.parse_args()
    try:
        baseline = json.loads((RESEARCH / "llmopt_phase1_baseline.json").read_bytes())
        full_pool = json.loads((RESEARCH / "llmopt_phase6_results.json").read_bytes())
        prior_commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", args.compare_ref + "^{commit}"],
            cwd=ROOT,
            text=True,
        ).strip()
        prior = json.loads(
            subprocess.check_output(
                ["git", "show", f"{prior_commit}:docs/research/llmopt_phase8_load.json"],
                cwd=ROOT,
            )
        )
        report, failures = render(
            json.loads(args.input.read_bytes()), baseline, full_pool, prior, prior_commit
        )
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        diagnostic = f"The workload comparison could not be constructed. {error}"
        args.output.write_text(f"# Incomplete workload report\n\n{diagnostic}\n", encoding="utf-8")
        raise SystemExit(diagnostic) from error
    args.output.write_text(report, encoding="utf-8", newline="\n")
    if args.check and failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
