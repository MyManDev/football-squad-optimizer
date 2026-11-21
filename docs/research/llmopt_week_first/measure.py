"""Measure window-specific release behavior and real one-week first-plan rendering offline."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from docs.research.llmopt_phase1.benchmark import snapshots
from docs.research.llmopt_phase8.measure import HERE as H2_RUNNER
from docs.research.llmopt_phase8.measure import OUTPUT as H2
from docs.research.llmopt_phase8.measure import RESEARCH, ROOT, provenance, replay, sha, write
from docs.research.llmopt_week_first.browser import BUILD, HERE, ORIGIN, browser_replay

OUTPUT = RESEARCH / "llmopt_week_first.json"
CHECKPOINT = ROOT / ".codex-tmp/week-first-checkpoint.json"


def source(require_clean):
    ident = provenance(require_clean=require_clean)
    names = (
        *HERE.glob("*.py"),
        *HERE.glob("*.mjs"),
        RESEARCH / "llmopt_phase1/gw8.json",
        RESEARCH / "llmopt_phase1/gw9.json",
        H2,
        ROOT / "web/src/features/league/llmopt/LLMOptPage.tsx",
        ROOT / "web/src/features/league/llmopt/PlanResult.tsx",
        ROOT / "web/src/features/league/advice/adviceCapabilities.ts",
        ROOT / "web/vite.config.ts",
    )
    if require_clean:
        subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", str(HERE), str(H2), "web/vite.config.ts"],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", *map(str, names)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            check=True,
        )
    ident["source_sha256"].update({p.relative_to(ROOT).as_posix(): sha(p) for p in names})
    return ident


def build():
    # Build once from this producer. All subsequent samples use these identical local assets.
    import os

    vite = ROOT / "web/node_modules/vite/bin/vite.js"
    subprocess.run(
        ["node", str(vite), "build", "--outDir", str(BUILD), "--emptyOutDir"],
        cwd=ROOT / "web",
        env={**os.environ, "VITE_ADVICE_API_ORIGIN": ORIGIN, "VITE_BASE_PATH": "/"},
        check=True,
    )
    files = sorted((BUILD / "assets").glob("*"))
    if not files or not (BUILD / "index.html").exists():
        raise ValueError("The production browser assets are unavailable.")
    combined = hashlib.sha256()
    for item in [BUILD / "index.html", *files]:
        combined.update(item.name.encode())
        combined.update(hashlib.sha256(item.read_bytes()).digest())
    return combined.hexdigest()


def mixed_row(root, frozen, inputs, entry, window, producer, setup_only):
    row = replay(
        root, frozen, inputs, entry, window, True, producer, three_week=False, setup_only=setup_only
    )
    if setup_only:
        return None
    row["release"] = "mixed"
    for cache in ("cold", "warm"):
        result = row[cache]
        # Keep every POST body, stage, job receipt and solver call in these small passes.
        # Repeated HTTP GET addresses are already present in the H2 record.
        http = result.pop("http")
        result["transport"] = [
            {"method": r["method"], "status": r["status"], "path": r["path"]} for r in http
        ]
        result["post_bodies"] = [r["body"] for r in http if r["method"] == "POST"]
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--check-setup", action="store_true", help="No worker or solver is started."
    )
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument(
        "--check-browser",
        action="store_true",
        help="Exercise both real browser arms for the first member without retaining timings.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    producer = source(not (args.check_setup or args.check_browser))
    if args.check_browser:
        build()
        frozen, inputs = next(iter(snapshots()))
        entry = min(inputs.members)
        with TemporaryDirectory() as tmp:
            for enabled in (True, False):
                sample = browser_replay(
                    Path(tmp) / str(enabled), frozen, inputs, entry, enabled, producer["commit"]
                )
                jobs = [len(sample[c]["jobs"]) for c in ("cold", "warm")]
                if jobs != ([0, 0] if enabled else [4, 0]):
                    raise ValueError(f"Unexpected queue receipts for {sample['case']}: {jobs}")
                workers = [sample[c]["device_workers"] for c in ("cold", "warm")]
                if workers != ([2, 0] if enabled else [0, 0]):
                    raise ValueError(f"Unexpected Chromium workers for {sample['case']}: {workers}")
                print(
                    f"Verified cold and warm main and combined cards for {sample['release']}.",
                    flush=True,
                )
        return
    subprocess.run(["node", str(H2_RUNNER / "bundle.mjs")], cwd=ROOT, check=True)
    if args.check_setup:
        with TemporaryDirectory() as tmp:
            for frozen, inputs in snapshots():
                for entry in sorted(inputs.members):
                    for window in (1, 3):
                        mixed_row(
                            Path(tmp), frozen, inputs, entry, window, producer["commit"], True
                        )
        print("Confirmed 40 mixed workflows and frozen inputs with zero submissions.")
        return
    assets = build()
    record = {
        "contract_version": "llmopt_week_first_v1",
        "producer_repository_commit": producer["commit"],
        "provenance": producer,
        "browser_assets_sha256": assets,
        "rows": [],
    }
    if args.resume and args.checkpoint.exists():
        previous = json.loads(args.checkpoint.read_bytes())
        if any(previous.get(k) != v for k, v in record.items() if k != "rows"):
            raise ValueError("The checkpoint names a different producer, input or browser build.")
        record["rows"] = previous["rows"]
    done = {(r["probe"], r["case"], r["window"], r["release"]) for r in record["rows"]}
    expected = set()
    with TemporaryDirectory(prefix="llmopt-week-first-") as tmp:
        for frozen, inputs in snapshots():
            for index, entry in enumerate(sorted(inputs.members)):
                case = f"gw{inputs.gameweek}-{entry}"
                modes = ("mixed", "off") if (index + inputs.gameweek) % 2 else ("off", "mixed")
                tasks = [("browser", 1, mode) for mode in modes]
                tasks.extend(("workload", window, "mixed") for window in (1, 3))
                for probe, window, release in tasks:
                    key = (probe, case, window, release)
                    expected.add(key)
                    if key in done:
                        continue
                    root = Path(tmp) / f"{probe}-{case}-{window}-{release}"
                    print(f"Starting {key}", flush=True)
                    if probe == "browser":
                        row = browser_replay(
                            root, frozen, inputs, entry, release == "mixed", producer["commit"]
                        )
                    else:
                        row = mixed_row(
                            root, frozen, inputs, entry, window, producer["commit"], False
                        )
                    record["rows"].append({"probe": probe, **row})
                    write(args.checkpoint, record)
                    print(f"Completed {len(record['rows'])}/80 {key}", flush=True)
    if (
        len(expected) != 80
        or len(record["rows"]) != 80
        or expected != {(r["probe"], r["case"], r["window"], r["release"]) for r in record["rows"]}
    ):
        raise ValueError("Expected forty independent browser arms and forty mixed workloads.")
    if source(True) != producer:
        raise ValueError("Source changed while measuring.")
    write(args.output, record, compact=True)
    from docs.research.llmopt_week_first.report import report

    report(record)


if __name__ == "__main__":
    main()
