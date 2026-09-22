"""Summarize complete paired factorial evidence without selecting a new candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

BITS = ("team", "roles", "uncertain_cs", "contextual_dc")
METRICS = ("points_mse", "goals_mse", "assists_mse", "cs_brier", "dc_brier")


def interval(values):
    """Exploratory paired circular four-week block interval, not an IID claim."""
    values = np.asarray(values, float)
    if not len(values) or not np.isfinite(values).all():
        raise ValueError("Paired evidence must be complete and finite.")
    n, rng = len(values), np.random.default_rng(120)
    block = min(4, n)
    starts = rng.integers(0, n, size=(2000, int(np.ceil(n / block))))
    indices = ((starts[:, :, None] + np.arange(block)) % n).reshape(2000, -1)[:, :n]
    return [float(x) for x in np.quantile(values[indices].mean(axis=1), [0.025, 0.975])]


def summarize(rows):
    report = {}
    for season, group in rows.groupby("season"):
        pivot = group.pivot(index="GW", columns="arm", values="points_mse")
        if pivot.isna().any().any():
            raise ValueError("Cannot omit failed/missing paired arms.")
        factorial = [a for a in pivot.columns if len(a) == 4 and set(a) <= {"0", "1"}]
        if len(factorial) != 16:
            raise ValueError("Complete sixteen-arm factorial evidence is required.")
        arms = {}
        for arm, data in group.groupby("arm"):
            delta = (pivot[arm] - pivot["0000"]).to_numpy()
            arms[arm] = {
                **{k: float(data[k].mean()) for k in METRICS if data[k].notna().any()},
                "delta_mse": float(delta.mean()),
                "delta_percent": float(100 * delta.mean() / pivot["0000"].mean()),
                "delta_interval": interval(delta),
                "better_weeks": int((delta < 0).sum()),
                "weeks": len(delta),
            }

        def flip(arm, bit):
            return arm[:bit] + "1" + arm[bit + 1 :]

        main, interactions = {}, {}
        for bit, name in enumerate(BITS):
            effect = np.mean(
                [(pivot[flip(a, bit)] - pivot[a]).to_numpy() for a in factorial if a[bit] == "0"],
                axis=0,
            )
            main[name] = {"average_delta_mse": float(effect.mean()), "interval": interval(effect)}
        for a in range(4):
            for b in range(a + 1, 4):
                effect = np.mean(
                    [
                        (
                            pivot[flip(flip(s, a), b)]
                            - pivot[flip(s, a)]
                            - pivot[flip(s, b)]
                            + pivot[s]
                        ).to_numpy()
                        for s in factorial
                        if s[a] == "0" and s[b] == "0"
                    ],
                    axis=0,
                )
                interactions[f"{a}-{b}"] = {
                    "delta_mse": float(effect.mean()),
                    "interval": interval(effect),
                }
        report[season] = {"arms": arms, "main_effects": main, "interactions": interactions}
    return report


def run(args):
    frame = pd.read_csv(args.losses, dtype={"arm": str})
    report = {
        "method": (
            "Equal-gameweek means; paired circular moving blocks of four weeks, "
            "2000 resamples, seed 120. Exploratory, not multiple-testing adjusted; "
            "five current-season weeks are insufficient for promotion."
        ),
        "strata": {str(k): summarize(v) for k, v in frame.groupby("stratum")},
    }
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, allow_nan=False)
        handle.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--losses", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
