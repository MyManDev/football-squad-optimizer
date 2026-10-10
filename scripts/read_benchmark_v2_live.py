"""Take the preregistered live reading once from a private explicit capture manifest."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.evaluation import EvaluationValidationError
from squadopt.experiments.benchmark_v2_live import (
    CLAIM_FILE,
    MINIMUM_WEEKS,
    MISSING_CAPTURE,
    READING_FILE,
    SEASON,
    LiveBenchmarkWeek,
    check_declared_gameweeks,
    read_live_benchmark_once,
)

ROOT = Path(__file__).resolve().parents[1]
_CAPTURE = re.compile(r"fpl-[a-z0-9-]+-(\d{8})T\d{6}Z-[0-9a-f]+")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--record-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if (args.record_root / CLAIM_FILE).exists() or (args.record_root / READING_FILE).exists():
            raise EvaluationValidationError("Benchmark V2 live reading has already been claimed.")
        raw_manifest = args.manifest.read_bytes()
        manifest = json.loads(raw_manifest)
        if not isinstance(manifest, dict) or manifest.get("season") != SEASON:
            raise EvaluationValidationError("Live Benchmark V2 admits only 2026-27.")
        listed = manifest.get("weeks")
        if not isinstance(listed, list) or not all(isinstance(item, dict) for item in listed):
            raise EvaluationValidationError("Invalid private Benchmark week manifest.")
        # A declared week without captures stays listed, with its reason, never left out.
        missing = [item for item in listed if item.get("exclusion") == MISSING_CAPTURE]
        specifications = [item for item in listed if "exclusion" not in item]
        if len(missing) + len(specifications) != len(listed) or any(
            set(item) != {"gameweek", "exclusion"} for item in missing
        ):
            raise EvaluationValidationError("Invalid private Benchmark week manifest.")
        if len(specifications) < MINIMUM_WEEKS:
            raise EvaluationValidationError("Benchmark V2 needs eight valid paired gameweeks.")
        check_declared_gameweeks(
            [item.get("gameweek") for item in specifications],
            [item["gameweek"] for item in missing],
            first_gameweek=manifest.get("first_gameweek"),
            last_gameweek=manifest.get("last_gameweek"),
        )
        # Validate every id before opening any capture. Never enumerate the store.
        roles = ("decision", "freeze", "cohort", "picks", "outcome")
        for specification in specifications:
            for role in roles:
                identifier = specification.get(role + "_snapshot_id")
                match = _CAPTURE.fullmatch(identifier) if isinstance(identifier, str) else None
                if match is None or not "20260801" <= match.group(1) < "20270801":
                    raise EvaluationValidationError(
                        "Benchmark capture id is outside the live season."
                    )
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        if dirty:
            raise EvaluationValidationError("Benchmark V2 refuses an uncommitted implementation.")
        weeks = [
            LiveBenchmarkWeek(
                specification["gameweek"],
                **{
                    role: read_snapshot(args.snapshot_root, specification[role + "_snapshot_id"])
                    for role in roles
                },
            )
            for specification in specifications
        ]
        preregistration = ROOT / "docs" / "benchmark_v2_prereg.md"
        result = read_live_benchmark_once(
            weeks,
            record_root=args.record_root,
            repository_commit=revision,
            preregistration_sha256=hashlib.sha256(preregistration.read_bytes()).hexdigest(),
            first_gameweek=manifest["first_gameweek"],
            last_gameweek=manifest["last_gameweek"],
            missing_gameweeks=[item["gameweek"] for item in missing],
            manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
        )
    except (
        DataError,
        EvaluationValidationError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.CalledProcessError,
    ):
        # Third-party parsers may include raw entry ids in errors. Keep this boundary private.
        print(
            "Benchmark V2 live reading refused; "
            "check the private inputs and persistent reading claim."
        )
        return 1
    print(f"Recorded {result['paired_gameweeks']} paired gameweeks.")
    print(args.record_root / READING_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
