"""Prespecified factorial, optional BoTorch and current-season research; no promotion."""

from __future__ import annotations

import argparse
import hashlib
import os
import pickle
import time
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from measure_football_contextual import losses, write

from squadopt.bayesopt.football_search import search
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.football_history import archive_history, captured_history
from squadopt.experiments.football_components import (
    FACTORIAL,
    ComponentForecast,
    Components,
    StandingsHead,
)
from squadopt.prediction.football_contextual import ContextualFootballModel
from squadopt.prediction.football_features import football_features

KEYS = ["season", "fixture", "player_code"]


def current_training(raw: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for week, target in current.groupby("GW", sort=True):
        cutoff = target.kickoff.min()
        earlier = raw.season.lt("2026-27") | (raw.season.eq("2026-27") & raw.GW.lt(week))
        past = raw.loc[earlier & (raw.kickoff + pd.Timedelta(hours=3) < cutoff)]
        features = football_features(past, target, cutoff)
        frame = pd.concat([target.drop(columns="home"), features], axis=1)
        goal = frame.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
        frame["residual_target"] = frame.total_points - (
            frame.appeared
            + frame.long
            + goal * frame.goals_scored
            + 3 * frame.assists
            + frame.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}) * frame.clean_sheets
            + 2 * frame.dc_event.fillna(0)
        )
        frame["feature_cutoff"] = cutoff
        parts.append(frame)
    return pd.concat(parts, ignore_index=True)


def run(args: argparse.Namespace) -> None:
    output: Path = args.output
    output.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    code = [
        Path(__file__),
        *sorted((project / "src/squadopt/prediction").glob("football*.py")),
        project / "src/squadopt/experiments/football_components.py",
        project / "src/squadopt/bayesopt/football_search.py",
    ]
    write(
        output / "source-hashes.json",
        {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in code},
    )
    write(
        output / "protocol.json",
        {
            "inner": {"season": "2023-24", "weeks": [11, 15, 19, 23, 27, 31, 35]},
            "outer": {
                "reused_seasons": ["2024-25", "2025-26"],
                "weeks": list(range(11, 39)),
                "current": "2026-27 completed weeks",
            },
            "seeds": [0, 1, 2],
            "budget": 12,
            "common_initial": 4,
            "pool": "128 scrambled Sobol points per seed, random arm follows sequence order",
            "objective": "equal-origin point MSE, attack-only knobs, CS/DC frozen",
            "factorial_order": ["team", "roles", "uncertain_cs", "contextual_dc"],
            "future_candidate": "seed0 BoTorch winner chosen before outer results",
            "promotion": False,
            "retrospective_current_roster": True,
            "current_news_and_rank_backfill": False,
        },
    )
    raw = archive_history(args.archive)
    snapshot = read_snapshot(args.snapshots, args.snapshot_id)
    current = captured_history(snapshot, season="2026-27", gameweek=6)
    raw = pd.concat([raw, current], ignore_index=True)
    frame = pd.read_csv(args.training, low_memory=False)
    for col in ("kickoff", "feature_cutoff"):
        frame[col] = pd.to_datetime(frame[col], utc=True)
    missing = [c for c in ("starts", "appeared", "long") if c not in frame]
    if missing:
        frame = frame.merge(raw[[*KEYS, *missing]], on=KEYS, validate="one_to_one")
    # The first archived season supplies priors, never zero-history supervised examples.
    # Match causal_training() and the frozen contextual comparison exactly.
    frame = frame.loc[frame.season.ne("2022-23")].copy()
    fresh = current_training(raw, current)
    frame = pd.concat([frame, fresh], ignore_index=True)
    fresh.to_csv(output / "current-causal-training.csv", index=False)
    current.to_csv(output / "current-history.csv", index=False)
    write(
        output / "input-evidence.json",
        {
            "training_sha256": hashlib.sha256(args.training.read_bytes()).hexdigest(),
            "snapshot_id": snapshot.metadata.snapshot_id,
            "snapshot_fingerprint": snapshot.metadata.fingerprint,
            "captured_at": snapshot.metadata.captured_at_utc,
            "current_rows_by_week": current.groupby("GW").size().to_dict(),
            "current_appeared_by_week": current.groupby("GW").appeared.sum().to_dict(),
            "current_missing_dc": int(current.defensive_contribution.isna().sum()),
            "archive_sha256": {
                str(p.relative_to(args.archive)): hashlib.sha256(p.read_bytes()).hexdigest()
                for season in ("2022-23", "2023-24", "2024-25", "2025-26")
                for p in (
                    args.archive / "data" / season / "gws/merged_gw.csv",
                    args.archive / "data" / season / "players_raw.csv",
                    args.archive / "data" / season / "teams.csv",
                    args.archive / "data" / season / "fixtures.csv",
                )
            },
        },
    )
    records, failures = [], []

    def fit(season: str, week: int) -> tuple[ComponentForecast, pd.DataFrame, pd.DataFrame]:
        target = frame.loc[frame.season.eq(season) & frame.GW.eq(week)].copy()
        cutoff = target.feature_cutoff.min()
        past = raw.season.lt(season) | (raw.season.eq(season) & raw.GW.lt(week))
        history = raw.loc[past & (raw.kickoff + pd.Timedelta(hours=3) < cutoff)]
        earlier = frame.season.lt(season) | (frame.season.eq(season) & frame.GW.lt(week))
        train = frame.loc[earlier & (frame.kickoff + pd.Timedelta(hours=3) < cutoff)]
        model = ContextualFootballModel(train, history, cutoff=cutoff)
        return ComponentForecast(model, history, target), train, history

    if args.reference_losses is not None:
        reference = pd.read_csv(args.reference_losses)
        preflight, _, _ = fit("2024-25", 11)
        measured = losses(preflight.target, preflight.predict(Components()))["points_mse"]
        expected = float(
            reference.loc[
                reference.season.eq("2024-25") & reference.GW.eq(11) & reference.arm.eq("v1"),
                "points_mse",
            ].iloc[0]
        )
        if not np.isclose(measured, expected, rtol=0, atol=1e-10):
            raise ValueError("Frozen real-data v1 control does not reproduce prior evidence.")
        write(output / "control-parity.json", {"measured": measured, "reference": expected})
        print("REAL CONTROL PARITY PASS", flush=True)
    inner = []
    for week in (11, 15, 19, 23, 27, 31, 35):
        print(f"INNER FIT 2023-24 GW{week}", flush=True)
        cache, _, _ = fit("2023-24", week)
        inner.append(cache)
    with (output / "inner-caches.pkl").open("wb") as handle:
        pickle.dump(inner, handle)  # own generated local evidence only; never load remote pickle
    memo = {}

    def objective(params: dict[str, float]) -> float:
        key = tuple(sorted(params.items()))
        if key not in memo:
            memo[key] = float(
                np.mean(
                    [
                        np.mean(
                            (
                                cache.target.total_points.to_numpy(float)
                                - cache.predict(
                                    Components(team=True, roles=True), attack_only=True, **params
                                ).expected_points.to_numpy(float)
                            )
                            ** 2
                        )
                        for cache in inner
                    ]
                )
            )
        return memo[key]

    results, trial_rows = [], []
    import torch  # optional dependency: this CLI explicitly requests BoTorch

    torch.set_num_threads(1)
    for seed in (0, 1, 2):
        torch.manual_seed(seed)
        for method in ("random", "sklearn", "botorch"):
            start = time.perf_counter()
            print(f"SEARCH {method} seed{seed} START", flush=True)
            result = search(objective, method=method, seed=seed)
            document = asdict(result)
            document["wall_seconds"] = time.perf_counter() - start
            results.append(document)
            trial_rows.extend({"method": method, "seed": seed, **r} for r in result.trials)
            pd.DataFrame(trial_rows).to_csv(output / "search-trials.csv", index=False)
            print(f"SEARCH {method} seed{seed} loss={result.loss:.8f}", flush=True)
    # This immutable file is written before any outer evaluation.
    write(output / "frozen-recommendations.json", results)
    for season, weeks in (
        ("2024-25", range(11, 39)),
        ("2025-26", range(11, 39)),
        ("2026-27", range(1, 6)),
    ):
        for week in weeks:
            fold = f"{season}-gw{week:02d}"
            print(fold + " START", flush=True)
            try:
                cache, train, history = fit(season, week)
                with (output / (fold + "-cache.pkl")).open("wb") as handle:
                    pickle.dump(cache, handle)
                predictions = [(s.name, cache.predict(s)) for s in FACTORIAL]
                standings = StandingsHead(train, history).predict(cache.target)
                predictions.append(("standings", cache.predict(Components(), standings=standings)))
                predictions.append(
                    (
                        "attack_default",
                        cache.predict(Components(team=True, roles=True), attack_only=True),
                    )
                )
                parameter_cache = {}
                for result in results:
                    name = f"{result['method']}-seed{result['seed']}"
                    key = tuple(sorted(result["parameters"].items()))
                    if key not in parameter_cache:
                        parameter_cache[key] = cache.predict(
                            Components(team=True, roles=True),
                            attack_only=True,
                            **result["parameters"],
                        )
                    predictions.append((name, parameter_cache[key]))
                for arm, prediction in predictions:
                    for stratum, mask in (
                        ("all", np.ones(len(cache.target), bool)),
                        ("appeared", cache.target.minutes.gt(0).to_numpy()),
                    ):
                        records.append(
                            {
                                "season": season,
                                "GW": week,
                                "arm": arm,
                                "stratum": stratum,
                                **losses(cache.target.loc[mask], prediction.loc[mask]),
                            }
                        )
                print(fold + " PASS", flush=True)
            except Exception as error:
                failures.append(
                    {"fold": fold, "error": str(error), "traceback": traceback.format_exc()}
                )
                print(fold + " FAIL " + str(error), flush=True)
            pd.DataFrame(records).to_csv(output / "component-losses.csv", index=False)
            write(output / "failures.json", failures)
    write(
        output / "summary.json",
        {
            "records": len(records),
            "failures": len(failures),
            "promotion": False,
            "pid": os.getpid(),
        },
    )
    if failures:
        raise RuntimeError("Failed folds retained; do not select only successful folds.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "training", "snapshots", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--reference-losses", type=Path)
    run(parser.parse_args())
