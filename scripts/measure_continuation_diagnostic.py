"""Compare chronological continuation predictors on previously consumed development chains."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

from squadopt.experiments.continuation_diagnostic import FEATURES, load_rows, study


def run(artifacts: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]

    def write(name: str, value: Any) -> None:
        (output / name).write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    write(
        "protocol.json",
        {
            "created_utc": datetime.now(UTC).isoformat(),
            "features": FEATURES,
            "train": ["2021-22", "2022-23"],
            "select": ["2023-24"],
            "diagnostic_test": ["2024-25"],
            "independent_holdout": False,
            "promotion": False,
            "sklearn": version("scikit-learn"),
            "source_hashes": {
                relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
                for relative in (
                    "src/squadopt/experiments/continuation_diagnostic.py",
                    "scripts/measure_continuation_diagnostic.py",
                    "docs/research/continuation_diagnostic_protocol.md",
                )
            },
        },
    )
    results = {}
    for window in (3, 5):
        print(f"START continuation window={window}", flush=True)
        frame, hashes = load_rows(artifacts, window)
        write(f"inputs-{window}.json", {"sha256": hashes, "rows": len(frame)})
        results[str(window)] = study(frame)
        write("results.json", results)
        print(f"DONE continuation window={window}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.artifacts, args.output)
