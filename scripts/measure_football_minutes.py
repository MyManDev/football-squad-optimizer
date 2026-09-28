"""Paired sequential-minute development comparison; no production promotion."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from measure_football_components import current_training
from measure_football_contextual import losses

from squadopt.data.sources.football_history import archive_history
from squadopt.experiments.football_minutes import MODEL_ID, SequentialMinuteForecast
from squadopt.prediction.football import FixtureFootballModel


def run(args):
    out, study = args.output, args.study
    out.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        (out / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")

    evidence = json.loads((study / "input-evidence.json").read_text())
    if hashlib.sha256(args.training.read_bytes()).hexdigest() != evidence["training_sha256"]:
        raise ValueError("Historical training evidence changed.")
    for relative, digest in evidence["archive_sha256"].items():
        if (
            hashlib.sha256((args.archive / relative.replace("\\", "/")).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Archive evidence changed.")
    root = Path(__file__).resolve().parents[1]
    sources = [
        Path(__file__),
        root / "src/squadopt/experiments/football_minutes.py",
        *sorted((root / "src/squadopt/prediction").glob("football*.py")),
    ]
    folds = [("2025-26", w) for w in range(11, 39)] + [("2026-27", w) for w in range(1, 6)]
    write(
        "protocol.json",
        {
            "candidate": MODEL_ID,
            "folds": folds,
            "development_only": True,
            "promotion": False,
            "tuning": False,
            "head": "P(appear), P(60+|appear), P(90+|60+); logistic C=1 seed0",
            "other_heads": "identical fitted control objects and minute exposure means",
            "cutoff": "strictly earlier GW and kickoff+3h < cutoff; 3h is a chosen proxy",
            "primary": ["minute_nll", "minute_brier", "minutes_mae", "appearance_brier"],
            "secondary": ["goals", "assists", "cs", "dc", "points"],
            "aggregation": "equal-week means by season and predeclared position",
            "inputs": evidence,
            "sources": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
        },
    )
    history = pd.concat(
        [archive_history(args.archive), pd.read_csv(study / "current-history.csv")],
        ignore_index=True,
    )
    history["kickoff"] = pd.to_datetime(history.kickoff, utc=True)
    frame = pd.read_csv(args.training, low_memory=False)
    keys = ["season", "fixture", "player_code"]
    missing = [c for c in ("starts", "appeared", "long") if c not in frame]
    frame = frame.merge(history[[*keys, *missing]], on=keys, validate="one_to_one")
    frame = pd.concat(
        [
            frame.loc[frame.season.ne("2022-23")],
            current_training(history, history.loc[history.season.eq("2026-27")]),
        ],
        ignore_index=True,
    )
    for col in ("kickoff", "feature_cutoff"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    reference = pd.read_csv(study / "component-losses.csv", dtype={"arm": str})
    rows = []
    for season, week in folds:
        target = frame.loc[frame.season.eq(season) & frame.GW.eq(week)].copy()
        if target.empty:
            raise ValueError("Missing declared fold.")
        cutoff = target.feature_cutoff.min()
        past = history.season.lt(season) | (history.season.eq(season) & history.GW.lt(week))
        earlier = frame.season.lt(season) | (frame.season.eq(season) & frame.GW.lt(week))
        raw = history.loc[past & (history.kickoff + pd.Timedelta(hours=3) < cutoff)]
        train = frame.loc[earlier & (frame.kickoff + pd.Timedelta(hours=3) < cutoff)]
        control = FixtureFootballModel(train, raw, cutoff=cutoff)
        baseline = control.predict(target)
        recorded = reference.loc[
            reference.season.eq(season)
            & reference.GW.eq(week)
            & reference.arm.eq("0000")
            & reference.stratum.eq("all")
        ]
        if len(recorded) != 1 or not np.isclose(
            losses(target, baseline)["points_mse"], recorded.iloc[0].points_mse, atol=1e-10, rtol=0
        ):
            raise ValueError(f"Frozen control parity failed: {season} GW{week}.")
        candidate = SequentialMinuteForecast(control, train).predict(target)
        for arm, prediction in (("control", baseline), (MODEL_ID, candidate)):
            for position in ("ALL", "GK", "DEF", "MID", "FWD"):
                mask = (
                    np.ones(len(target), dtype=bool)
                    if position == "ALL"
                    else target.position.eq(position).to_numpy()
                )
                actual, forecast = target.loc[mask], prediction.loc[mask]
                mass = forecast[[f"minute_probability_{i}" for i in range(4)]].to_numpy(float)
                category = actual.m_bin.to_numpy(int)
                if (
                    not np.isfinite(mass).all()
                    or (mass < 0).any()
                    or not np.allclose(mass.sum(axis=1), 1)
                ):
                    raise ValueError("Invalid probability mass.")
                score = losses(actual, forecast)
                score["minute_nll"] = float(
                    -np.log(np.clip(mass[np.arange(len(mass)), category], 1e-12, 1)).mean()
                )
                score["minute_brier"] = float(
                    np.mean(np.sum((mass - np.eye(4)[category]) ** 2, axis=1))
                )
                rows.append(
                    {"season": season, "GW": week, "arm": arm, "position": position, **score}
                )
        pd.DataFrame(rows).to_csv(out / "folds.csv", index=False)
        print(f"{season} GW{week}: control parity and paired components passed", flush=True)
    data = pd.DataFrame(rows)
    metrics = [c for c in data if c.endswith(("mse", "mae", "nll", "brier"))]
    summary = data.groupby(["season", "arm", "position"])[metrics].mean().reset_index()
    write(
        "summary.json",
        {
            "folds": len(folds),
            "control_parity": True,
            "promotion": False,
            "results": json.loads(summary.to_json(orient="records")),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "training", "study", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    run(parser.parse_args())
