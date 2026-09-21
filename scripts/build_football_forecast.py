"""Build a capture-specific optional football artifact; never replaces the current handoff."""

import argparse
import json
import os
from pathlib import Path

from squadopt.application.football_live import produce_football_forecast
from squadopt.data.snapshots import read_snapshot
from squadopt.live import infer_season, read_inputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args()
    snapshot = read_snapshot(args.snapshot_root, args.snapshot_id)
    document = produce_football_forecast(snapshot, args.archive_root)
    target = football_artifact_path(args.artifact_root, args.snapshot_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != document:
            raise ValueError("A different football forecast already exists for this capture.")
    else:
        temporary = target.with_suffix(".pending")
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(document, handle, sort_keys=True, allow_nan=False)
        read_football_forecast(temporary, read_inputs(snapshot, season=infer_season(snapshot)))
        os.replace(temporary, target)
    print(
        json.dumps(
            {
                "fingerprint": document["fingerprint"],
                "rows": len(document["rows"]),
                "model_version": document["model_version"],
            }
        )
    )


if __name__ == "__main__":
    main()
