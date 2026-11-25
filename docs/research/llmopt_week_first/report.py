"""Compare every mixed-mode slot to its matching H2 arm and describe local timing tails."""

import argparse
import json
from collections import Counter

from docs.research.llmopt_phase1.freeze import digest
from docs.research.llmopt_phase8.measure import OUTPUT as H2
from docs.research.llmopt_phase8.measure import RESEARCH, sha
from docs.research.llmopt_phase8.report import (
    NET_TOLERANCE,
    SLOTS,
    completed,
    format_pair,
    index_rows,
    percentiles,
    table,
)

OUTPUT = RESEARCH / "llmopt_week_first.json"
MARKDOWN = RESEARCH / "llmopt_week_first.md"


def timings(values, key):
    return format_pair(percentiles([v[key] for v in values]))


def shape(pass_):
    return [(s["label"], tuple(s["submissions"])) for s in pass_["stages"]]


def transport(pass_, key):
    def path(row):
        raw = row["path"]
        return "/api/v1/advice-jobs/{id}" if raw.startswith("/api/v1/advice-jobs/") else raw

    return [(r["method"], path(r), r["status"]) for r in pass_[key]]


def device_stages(pass_):
    return [
        (
            "preferences" if w["bundle"] else "base",
            w["elapsed_seconds"],
            sum(call["seconds"] for call in w["calls"]),
            len(w["calls"]),
        )
        for w in pass_["device_work"]
    ]


def render(record, historical):
    manifest = json.loads((RESEARCH / "llmopt_phase1/inputs.json").read_bytes())
    members = set()
    held = {}
    for original in manifest["snapshots"]:
        path = RESEARCH / "llmopt_phase1" / original["path"]
        capture = json.loads(path.read_bytes())
        if digest(capture) != original["sha256"]:
            raise ValueError(f"Frozen document changed: {path.name}")
        for entry, member in capture["members"].items():
            case = f"gw{capture['table']['gameweek']}-{entry}"
            members.add(case)
            held[case] = set(member["held"])
    if len(members) != 20:
        raise ValueError("The sample must contain twenty distinct archived member-weeks.")
    h2 = index_rows(historical, members)
    workload = {(r["window"], r["case"]): r for r in record["rows"] if r["probe"] == "workload"}
    browser = {(r["release"], r["case"]): r for r in record["rows"] if r["probe"] == "browser"}
    if (
        len(record["rows"]) != 80
        or set(workload) != {(w, c) for w in (1, 3) for c in members}
        or set(browser) != {(m, c) for m in ("off", "mixed") for c in members}
    ):
        raise ValueError("Incomplete or duplicate workload or browser samples.")
    if record["provenance"]["source_sha256"]["docs/research/llmopt_phase8_load.json"] != sha(H2):
        raise ValueError("The referenced H2 data file changed.")
    totals, durations, result_differences, transport_differences = [], [], [], []
    issues = []
    for window, arm in ((1, "on"), (3, "off")):
        for cache in ("cold", "warm"):
            counts = Counter()
            earlier, current = [], []
            for case in sorted(members):
                old, new = h2[window, arm, case][cache], workload[window, case][cache]
                earlier.append(old)
                current.append(new)
                if set(new["answers"]) != set(SLOTS):
                    raise ValueError(f"{case}/{window}/{cache}: missing or extra slot")
                for slot in SLOTS:
                    a, b = (p["answers"][slot] for p in (old, new))
                    counts["slots"] += 1
                    counts["status"] += (a["status"], a.get("reason")) == (
                        b["status"],
                        b.get("reason"),
                    )
                    counts["source"] += a.get("source") == b.get("source")
                    counts["path"] += completed(a) and completed(b) and a["path"] == b["path"]
                    counts["points"] += (
                        completed(a) and completed(b) and abs(a["net"] - b["net"]) <= NET_TOLERANCE
                    )
                    counts["exact"] += a == b
                    if a != b:
                        result_differences.append([case, window, cache, slot, a, b])
                counts["jobs"] += len(new["jobs"])
                counts["workers"] += len(new["device_work"])
                if (
                    shape(old) != shape(new)
                    or transport(old, "http") != transport(new, "transport")
                    or len(old["jobs"]) != len(new["jobs"])
                    or len(old["device_work"]) != len(new["device_work"])
                ):
                    transport_differences.append([case, window, cache, shape(old), shape(new)])
                if window == 3 and (
                    len(new["post_bodies"]) != 4
                    or len(new["jobs"]) != (4 if cache == "cold" else 0)
                    or any(
                        j["worker_contract"] != "backend_jobs_v1"
                        or j["allocated_units"] is not None
                        or j["work_receipt"] is not None
                        for j in new["jobs"]
                    )
                    or new["device_work"]
                    or new["device_units_cumulative"] != 0
                    or any(
                        "run" in body or "preference_bundle" in body for body in new["post_bodies"]
                    )
                ):
                    issues.append(f"{case}/{cache}: incorrect three-week legacy request bodies.")
            totals.append(
                [
                    window,
                    arm,
                    cache,
                    *(
                        counts[k]
                        for k in (
                            "slots",
                            "status",
                            "source",
                            "path",
                            "points",
                            "exact",
                            "jobs",
                            "workers",
                        )
                    ),
                ]
            )
            durations.append(
                [window, cache, timings(earlier, "seconds"), timings(current, "seconds")]
            )
    users, tails = [], []
    for cache in ("cold", "warm"):
        for release, arm in (("off", "off"), ("mixed", "on")):
            rows = [(c, browser[release, c][cache]) for c in members]
            samples = [r for _, r in rows]
            jobs = sum(len(r["jobs"]) for r in samples)
            workers = sum(r["device_workers"] for r in samples)
            users.append(
                [
                    cache,
                    release,
                    len(rows),
                    timings(samples, "first_visible_seconds"),
                    timings(samples, "total_seconds"),
                    jobs,
                    workers,
                ]
            )
            for case, sample in rows:
                if (
                    not 0
                    < sample["first_visible_seconds"]
                    <= sample["total_seconds"]
                    <= sample["observer_seconds"]
                ):
                    issues.append(
                        f"{case}/{release}/{cache}: timeline exceeds the independent observer."
                    )
                for slot in ("base", "combined"):
                    expected = h2[1, arm, case][cache]["answers"][slot]
                    opening = json.loads(expected["path"])
                    _, _, incoming, outgoing, chip, _ = opening
                    planned = sorted((held[case] - set(outgoing)) | set(incoming))
                    if sample[f"{slot}_decision"] != [chip, planned]:
                        issues.append(f"{case}/{release}/{cache}: {slot} card differs from H2.")
                expected_jobs = 4 if release == "off" and cache == "cold" else 0
                if len(sample["jobs"]) != expected_jobs or any(
                    j["status"] != "completed" for j in sample["jobs"]
                ):
                    issues.append(f"{case}/{release}/{cache}: unexpected browser queue receipts.")
                expected_workers = 2 if release == "mixed" and cache == "cold" else 0
                if sample["device_workers"] != expected_workers:
                    issues.append(f"{case}/{release}/{cache}: unexpected browser worker count.")
            # Always name the p95 member and maximum, plus the two H2 total-time tail members.
            ranked = sorted(rows, key=lambda pair: (pair[1]["total_seconds"], pair[0]))
            old_ranked = sorted(members, key=lambda c: (h2[1, arm, c][cache]["seconds"], c))
            labels = {}
            for label, member in (
                ("browser p95", ranked[-2][0]),
                ("browser max", ranked[-1][0]),
                ("H2 p95", old_ranked[-2]),
                ("H2 max", old_ranked[-1]),
            ):
                labels.setdefault(member, []).append(label)
            for case, ranks in labels.items():
                sample = browser[release, case][cache]
                archive = h2[1, arm, case][cache]
                local = workload[1, case][cache] if release == "mixed" else None
                old_work = (
                    device_stages(archive)
                    if release == "mixed"
                    else [
                        (
                            j["stage"],
                            j["worker_seconds"],
                            j["cp_seconds"] + j["native_seconds"],
                            j["solver_calls"],
                        )
                        for j in archive["jobs"]
                    ]
                )
                stage_times = (
                    [(stage["label"], stage["elapsed_seconds"]) for stage in local["stages"]]
                    if local
                    else [(j["stage"], j["worker_seconds"]) for j in sample["jobs"]]
                )
                tail = [
                    case,
                    cache,
                    release,
                    ", ".join(ranks),
                    f"{sample['first_visible_seconds']:.3f}",
                    f"{sample['total_seconds']:.3f}",
                    f"{sample['total_seconds'] - sample['first_visible_seconds']:.3f}",
                    f"{archive['seconds']:.3f}",
                    ", ".join(f"{s} {t:.3f}" for s, t in stage_times) or "cached",
                    ", ".join(f"{s} {t:.3f} ({n})" for s, t, _, n in old_work) or "cached",
                ]
                tails.append(tail)
    issue_count = len(issues) + len(result_differences) + len(transport_differences)
    tail_notes = []
    old_order = sorted(members, key=lambda c: (h2[1, "on", c]["cold"]["seconds"], c))
    new_order = sorted(members, key=lambda c: (browser["mixed", c]["cold"]["total_seconds"], c))
    for name, case in zip(("p95", "maximum"), old_order[-2:], strict=True):
        work = device_stages(h2[1, "on", case]["cold"])
        tail_notes.append(
            f"The H2 one-week cold {name} was {case}. Its base worker took {work[0][1]:.3f} s "
            f"over {work[0][3]} solves, and the preference worker took {work[1][1]:.3f} s "
            f"over {work[1][3]} solves."
        )
    for name, case in zip(("p95", "maximum"), new_order[-2:], strict=True):
        sample = browser["mixed", case]["cold"]
        tail_notes.append(
            f"The mixed browser cold {name} was {case}. Its main plan appeared at "
            f"{sample['first_visible_seconds']:.3f} s and its combined plan completed "
            f"{sample['total_seconds'] - sample['first_visible_seconds']:.3f} s later."
        )
    text = [
        "# One-week release on twenty frozen member-weeks",
        f"Measured source `{record['producer_repository_commit']}`. The mixed setting enables "
        "the one-week workflow and leaves the separate three-week setting disabled. Both package "
        "settings and the three-week path setting retain their defaults. "
        f"H2 measured source `{historical['producer_repository_commit']}`. "
        "[Raw measurements](llmopt_week_first.json) · [H2 comparison](llmopt_phase8_closing.md)",
        "## Mixed workload and historical slots",
        table(
            [
                "Weeks",
                "Matching H2 arm",
                "Cache",
                "Slots",
                "Same status/reason",
                "Same source",
                "Same path",
                "Same net",
                "All fields exact",
                "Server jobs",
                "Device workers",
            ],
            totals,
        ),
        "Each member contributed the base, two individual prices and the combined plan. Transfer "
        "paths include chip use. The points column uses the historical absolute tolerance of "
        "1e-8. Exact matches include every field recorded on the original answer slot. H2 did "
        "not record individual lineup decisions. The transport comparison includes stage order, "
        "submission result, public method, route, status and counts of real publications and "
        "workers. Job-specific status paths are compared without their generated identifiers.",
        table(
            ["Weeks", "Cache", "H2 complete p50 / p95 (s)", "Mixed complete p50 / p95 (s)"],
            durations,
        ),
        "## Time to a visible main plan in Chromium",
        table(
            [
                "Cache",
                "Release",
                "Member-weeks",
                "Visible main p50 / p95 (s)",
                "Complete p50 / p95 (s)",
                "Server jobs",
                "Browser device workers",
            ],
            users,
        ),
        "Cold samples start at the Compute click. Warm samples reload the confirmed run in the "
        "same tab. Both use the production page, its normal job polling, the original member "
        "and capture publications, and local server or device solvers. The page uses the capture "
        "date for deadline decisions. At each animation frame the observer checks the completed "
        "base card. It scrolls its first populated calculated value fully into the 1280 by 900 "
        "viewport when needed and verifies that value's visibility and opacity. "
        "Completion records the first frame with the completed combined card in the document. "
        "Both visible decisions are checked against the H2 chip and held squad after transfers. "
        "The worker count comes from the browser. Each warm restore must reuse its cached "
        "results without starting a worker or publishing a server job. "
        "Only Date is fixed for deadline decisions. Navigation, performance timing, animation "
        "frames and timers use Chromium's native clock. The recording also verifies that each "
        "pass finishes inside the independent monotonic interval observed by the browser driver. "
        "The median and the "
        "nearest-rank 95th percentile over 20 samples are reported independently for each arm.",
        "### Members and stages at the one-week total-time tail",
        " ".join(tail_notes),
        table(
            [
                "Member-week",
                "Cache",
                "Release",
                "Rank",
                "Main visible (s)",
                "Complete (s)",
                "After main (s)",
                "H2 complete (s)",
                "Current stage time (s)",
                "H2 worker time (s), calls in parentheses",
            ],
            tails,
        ),
        "Current mixed stage times come from the separate in-process transport replay. Current "
        "disabled stages use the actual browser run's server worker times. The browser total "
        "also includes page scheduling, polling, rendering and, on reload, navigation. H2 "
        "recorded complete transport latency and worker time. It did not measure first paint. "
        "Cached returns use no worker. These are local samples on one machine.",
        "## Reproduce",
        "```powershell\n$env:PYTHONPATH='src'\n"
        "python -m docs.research.llmopt_week_first.measure --resume\n"
        "python -m docs.research.llmopt_week_first.report --check\n```",
        "Run with the pinned source, installed Python and web dependencies and local Git objects "
        "for both original publications. The collector builds the frontend with its API at "
        "127.0.0.1:8818. Each cold arm starts from empty local queue, cache and browser storage. "
        "The warm pass preserves the state of that arm. The experiment made no provider calls and "
        "uses published expected points only.",
    ]
    if issue_count:
        text.append("## Unfinished")
        if result_differences:
            text.append(
                table(["Member-week", "Weeks", "Cache", "Slot", "H2", "Mixed"], result_differences)
            )
        if transport_differences:
            text.append(
                table(
                    ["Member-week", "Weeks", "Cache", "H2 stages", "Mixed stages"],
                    transport_differences,
                )
            )
        text.extend(issues)
    return "\n\n".join(text) + "\n", issue_count


def report(record, *, check=False):
    body, issues = render(record, json.loads(H2.read_bytes()))
    if check:
        if MARKDOWN.read_text(encoding="utf-8") != body:
            raise ValueError("The report differs from the committed rows.")
    else:
        MARKDOWN.write_text(body, encoding="utf-8", newline="\n")
    if issues:
        raise ValueError(f"{issues} discrepancies recorded in {MARKDOWN.name}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    report(json.loads(OUTPUT.read_bytes()), check=parser.parse_args().check)
