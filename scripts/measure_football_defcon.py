"""Run the declared DEFCON-only development comparison on trusted local study evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from measure_football_components import current_training

from squadopt.data.sources.football_history import ARCHIVE_SEASONS, archive_history
from squadopt.experiments.football_components import ComponentForecast, Components
from squadopt.experiments.football_defcon import MODEL_ID, direct_tail
from squadopt.prediction.football_contextual import ContextualFootballModel


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run(args):
    output, study = args.output, args.study
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    protocol = project / "docs/research/football_defcon_development_scope.md"
    folds = [("2025-26", w) for w in range(11, 39)] + [("2026-27", w) for w in range(1, 6)]
    inputs = [
        args.history,
        study / "current-history.csv",
        study / "component-losses.csv",
        study / "current-causal-training.csv",
        study / "input-evidence.json",
    ]
    archives = [
        args.archive / "data" / s / name
        for s in ARCHIVE_SEASONS
        for name in ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv")
    ]
    sources = [
        Path(__file__),
        project / "scripts/measure_football_components.py",
        project / "src/squadopt/data/sources/football_history.py",
        protocol,
        project / "src/squadopt/experiments/football_defcon.py",
        project / "src/squadopt/experiments/football_components.py",
    ]
    sources.extend(sorted((project / "src/squadopt/prediction").glob("football*.py")))
    write(
        output / "manifest.json",
        {
            "candidate": MODEL_ID,
            "development_only": True,
            "promotion": False,
            "archive_hashes": {
                str(p.relative_to(args.archive)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in archives
            },
            "inputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
            "sources": {
                str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
            "folds": folds,
        },
    )
    evidence = json.loads((study / "input-evidence.json").read_text())
    if hashlib.sha256(args.history.read_bytes()).hexdigest() != evidence["training_sha256"]:
        raise ValueError("Historical training evidence changed since the original study.")
    for relative, digest in evidence["archive_sha256"].items():
        if (
            hashlib.sha256((args.archive / relative.replace("\\", "/")).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Archived input changed since the original study.")
    history = pd.concat(
        [archive_history(args.archive), pd.read_csv(study / "current-history.csv")],
        ignore_index=True,
    )
    history["kickoff"] = pd.to_datetime(history.kickoff, utc=True)
    frame = pd.read_csv(args.history, low_memory=False)
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
    for column in ("kickoff", "feature_cutoff"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    reference = pd.read_csv(study / "component-losses.csv", dtype={"arm": str})
    records = []
    for season, week in folds:
        target = frame.loc[frame.season.eq(season) & frame.GW.eq(week)].copy()
        cutoff = target.feature_cutoff.min()
        if target.empty or cutoff != target.kickoff.min():
            raise ValueError("Missing fold or decision cutoff mismatch.")
        past = history.season.lt(season) | (history.season.eq(season) & history.GW.lt(week))
        earlier = frame.season.lt(season) | (frame.season.eq(season) & frame.GW.lt(week))
        raw = history.loc[past & (history.kickoff + pd.Timedelta(hours=3) < cutoff)]
        train = frame.loc[earlier & (frame.kickoff + pd.Timedelta(hours=3) < cutoff)]
        print(f"{season} GW{week}: refit unchanged comparator", flush=True)
        model = ContextualFootballModel(train, raw, cutoff=cutoff)
        cache = ComponentForecast(model, raw, target)
        control = cache.predict(Components())
        contextual = cache.predict(Components(contextual_dc=True))
        for arm, prediction in (("0000", control), ("0001", contextual)):
            expected = reference.loc[
                reference.season.eq(season)
                & reference.GW.eq(week)
                & reference.arm.eq(arm)
                & reference.stratum.eq("all")
            ]
            point_loss = np.mean((target.total_points - prediction.expected_points) ** 2)
            dc_mask = target.position.ne("GK") & target.dc_event.notna()
            dc_loss = np.mean(
                (target.loc[dc_mask, "dc_event"] - prediction.loc[dc_mask, "defcon_probability"])
                ** 2
            )
            if len(expected) != 1 or not np.allclose(
                [point_loss, dc_loss],
                expected.iloc[0][["points_mse", "dc_brier"]].to_numpy(float),
                atol=1e-10,
                rtol=0,
            ):
                raise ValueError(
                    f"Frozen comparator parity failed: {season} GW{week} {arm}: "
                    f"measured={point_loss, dc_loss}; "
                    f"reference={expected[['points_mse', 'dc_brier']].to_dict('records')}"
                )
        mass = cache.context[[f"minute_probability_{i}" for i in range(4)]].to_numpy(float)
        probability = direct_tail(history, target, mass, cache.cutoff)
        candidate = control.copy()
        candidate["defcon_probability"] = probability
        candidate["expected_points"] = np.maximum(
            control.raw_expected_points + 2 * (probability - control.defcon_probability), 0
        )
        for arm, prediction in (
            ("control", control),
            ("contextual", contextual),
            (MODEL_ID, candidate),
        ):
            for position in ("ALL", "DEF", "MID", "FWD"):
                mask = (
                    target.position.ne("GK") if position == "ALL" else target.position.eq(position)
                )
                mask &= target.dc_event.notna()
                y = target.loc[mask, "dc_event"].to_numpy(float)
                p = prediction.loc[mask, "defcon_probability"].to_numpy(float)
                if not len(y) or not np.isfinite(p).all() or (p < 0).any() or (p > 1).any():
                    raise ValueError("Incomplete or invalid paired event predictions.")
                clipped = np.clip(p, 1e-12, 1 - 1e-12)
                records.append(
                    dict(
                        season=season,
                        GW=week,
                        arm=arm,
                        position=position,
                        n=len(y),
                        missing=int((target.position.ne("GK") & target.dc_event.isna()).sum()),
                        brier=float(np.mean((p - y) ** 2)),
                        log_loss=float(
                            np.mean(-y * np.log(clipped) - (1 - y) * np.log(1 - clipped))
                        ),
                        bias=float(np.mean(p - y)),
                        points_mse=float(
                            np.mean(
                                (
                                    target.loc[mask, "total_points"]
                                    - prediction.loc[mask, "expected_points"]
                                )
                                ** 2
                            )
                        ),
                    )
                )
        print(f"{season} GW{week}: comparator parity and three paired arms passed", flush=True)
    rows = pd.DataFrame(records)
    rows.to_csv(output / "folds.csv", index=False)
    summary = (
        rows.groupby(["season", "arm", "position"])[["brier", "log_loss", "bias", "points_mse"]]
        .mean()
        .reset_index()
        .to_dict("records")
    )
    write(
        output / "summary.json",
        {
            "candidate": MODEL_ID,
            "folds": len(folds),
            "parity_passed": True,
            "development_only": True,
            "promotion": False,
            "aggregation": "equal-week means; ALL excludes GK; missing event labels excluded",
            "results": summary,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("history", "study", "output", "archive"):
        parser.add_argument("--" + name, type=Path, required=True)
    run(parser.parse_args())
