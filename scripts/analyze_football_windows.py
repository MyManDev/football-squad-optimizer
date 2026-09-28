"""Re-score saved development forecasts without retraining or selecting a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from squadopt.data.sources.football_history import archive_history
from squadopt.experiments.football_windows import paired_window_losses


def run(study: Path, archive: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        (output / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

    hashes = json.loads((study / "input-hashes.json").read_text())
    for name, expected in hashes.items():
        if "/" in name and (
            hashlib.sha256((archive / "data" / name).read_bytes()).hexdigest() != expected
        ):
            raise ValueError("Archive differs from the original study: " + name)
    if json.loads((study / "summary.json").read_text())["failures"] != 0:
        raise ValueError("Source study has failed folds.")
    protocol = {
        "seasons": ["2024-25", "2025-26"],
        "origins": [11, 15, 19, 23, 27, 31],
        "windows": [1, 3, 5],
        "arms": ["v1", "contextual"],
        "retraining": False,
        "development_only": True,
        "promotion": False,
        "missing": "Exclude entire incomplete player sum, paired across arms.",
        "population": "Players represented by frozen fixture forecasts in each window.",
        "calendar": "Final historical calendar, not verified at the deadline.",
        "uncertainty": "Descriptive paired origins, not independent promotion evidence.",
    }
    write("protocol.json", protocol)
    inputs = [study / "input-hashes.json", study / "future-losses.csv"]
    actual = archive_history(archive)
    reference = pd.read_csv(study / "future-losses.csv")
    records = []
    for season in protocol["seasons"]:
        for origin in protocol["origins"]:
            paths = [
                study / f"{season}-gw{origin:02d}-{arm}-future.csv" for arm in protocol["arms"]
            ]
            inputs.extend(paths)
            tables = [pd.read_csv(path) for path in paths]
            for window in protocol["windows"]:
                slices = [
                    table.loc[table.GW.between(origin, origin + window - 1)] for table in tables
                ]
                metrics = paired_window_losses(*slices, actual)
                for arm, scores in metrics.items():
                    old = reference.loc[
                        reference.season.eq(season)
                        & reference.origin.eq(origin)
                        & reference.window.eq(window)
                        & reference.arm.eq(arm)
                    ]
                    if len(old) != 1 or not math.isclose(
                        scores["fixture_mse"], old.iloc[0].points_mse, rel_tol=0, abs_tol=1e-10
                    ):
                        raise ValueError(f"Fixture parity failed: {season}/{origin}/{window}/{arm}")
                    records.append(
                        {
                            "season": season,
                            "origin": origin,
                            "window": window,
                            "arm": arm,
                            **scores,
                            "mean_week_mse": scores["sum_mse"] / window**2,
                        }
                    )
    frame = pd.DataFrame(records)
    frame.to_csv(output / "folds.csv", index=False)
    means = (
        frame.groupby(["season", "window", "arm"])[
            ["fixture_mse", "sum_mse", "sum_mae", "sum_bias", "mean_week_mse"]
        ]
        .mean()
        .reset_index()
    )
    write(
        "summary.json",
        {
            "records": len(records),
            "fixture_parities": len(records),
            "equal_origin_means": means.to_dict("records"),
            "folds": records,
        },
    )
    source = Path(__file__).resolve().parents[1]
    inputs.extend([Path(__file__), source / "src/squadopt/experiments/football_windows.py"])
    write(
        "hashes.json", {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    )
    print(means.to_string(index=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("study", "archive", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.study, args.archive, args.output)
