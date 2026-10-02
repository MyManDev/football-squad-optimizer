"""Fixed causal development comparison of frozen v1 and joint role minutes.

This command has no archive default, tuning, availability/news backfill or promotion
action. The first allowed season supplies priors; exactly eight historical origins
and all settled weeks in an optional explicit current capture are reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import poisson

from squadopt.application.football_live import causal_training
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.football_history import archive_history, captured_history
from squadopt.live import infer_season, read_inputs
from squadopt.prediction.football import (
    FOOTBALL_MODEL_VERSION,
    JOINT_ROLE_MODEL_VERSION,
    FixtureFootballModel,
    JointRoleFootballModel,
)
from squadopt.prediction.football_features import FEATURES, football_features
from squadopt.prediction.football_minutes_role import MINUTE_PRIOR_ROWS

SEASONS = ("2022-23", "2023-24", "2024-25")
CURRENT_SEASON = "2026-27"
ORIGINS = tuple((season, week) for season in SEASONS[1:] for week in (11, 19, 27, 35))
ARCHIVE_FILES = ("gws/merged_gw.csv", "players_raw.csv", "teams.csv", "fixtures.csv")
ARMS = ("frozen_v1", "joint_role")
POSITIONS = ("ALL", "GK", "DEF", "MID", "FWD")
LOG_FLOOR = 1e-12
SOURCE_FILES = (
    "scripts/measure_football_role_minutes.py",
    "src/squadopt/application/football_live.py",
    "src/squadopt/data/sources/football_history.py",
    "src/squadopt/prediction/football.py",
    "src/squadopt/prediction/football_features.py",
    "src/squadopt/prediction/football_minutes_role.py",
)


def validate_seasons(seasons: tuple[str, ...]) -> None:
    """Validate the complete allowlist before any file is opened."""
    if seasons != SEASONS:
        raise ValueError("Explicit training seasons must be exactly 2022-23,2023-24,2024-25.")


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _hashes(root: Path, paths: tuple[str, ...]) -> dict[str, str]:
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}


def _counts(frame: pd.DataFrame) -> dict[str, int]:
    return {str(k): int(v) for k, v in frame.groupby("season", sort=True).size().items()}


def _earlier(frame: pd.DataFrame, season: str, week: int, cutoff: pd.Timestamp) -> pd.Series:
    return ((frame.season < season) | (frame.season.eq(season) & frame.GW.lt(week))) & (
        frame.kickoff + pd.Timedelta(hours=3) < cutoff
    )


def _categorical_loss(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    if (
        not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
        or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-9, rtol=0)
    ):
        raise ValueError("Forecast class probabilities must form one finite probability law.")
    return {
        "nll": float(
            -np.log(np.maximum(probabilities[np.arange(len(labels)), labels], LOG_FLOOR)).mean()
        ),
        "brier": float(
            ((probabilities - np.eye(probabilities.shape[1])[labels]) ** 2).sum(axis=1).mean()
        ),
    }


def losses(actual: pd.DataFrame, prediction: pd.DataFrame) -> dict[str, object]:
    """Comparable per-player-fixture losses; unsupported role/DC scores stay null."""
    if len(actual) != len(prediction) or not actual.index.equals(prediction.index) or actual.empty:
        raise ValueError("Measurement rows must be nonempty and exactly aligned.")
    result: dict[str, object] = {"rows": len(actual)}
    for name, observed, forecast, binary in (
        ("points", "total_points", "expected_points", False),
        ("minutes", "minutes", "expected_minutes", False),
        ("appearance", "appeared", "appearance_probability", True),
        ("p60", "long", "p60", True),
        ("goals", "goals_scored", "goals", False),
        ("assists", "assists", "assists", False),
        ("cs", "clean_sheets", "clean_sheet_probability", True),
        ("dc", "dc_event", "defcon_probability", True),
    ):
        mask = actual[observed].notna()
        if name == "dc":
            mask &= actual.position.ne("GK") & actual.season.eq(CURRENT_SEASON)
        result[name + "_rows"] = int(mask.sum())
        keys = ("brier", "bias") if binary else ("mae", "mse", "bias")
        if name in ("goals", "assists"):
            keys = (*keys, "poisson_nll")
        for key in keys:
            result[name + "_" + key] = None
        if not mask.any():
            continue
        y = actual.loc[mask, observed].to_numpy(float)
        p = prediction.loc[mask, forecast].to_numpy(float)
        if not np.isfinite(y).all() or not np.isfinite(p).all():
            raise ValueError("Nonfinite scoring outcomes or forecasts.")
        if binary and (not np.isin(y, [0, 1]).all() or ((p < 0) | (p > 1)).any()):
            raise ValueError("Binary scores require observed events and probability forecasts.")
        d = p - y
        result[name + "_bias"] = float(d.mean())
        result[name + ("_brier" if binary else "_mse")] = float((d**2).mean())
        if not binary:
            result[name + "_mae"] = float(np.abs(d).mean())
        if name in ("goals", "assists"):
            if (p < 0).any() or (y < 0).any() or not np.equal(y, np.floor(y)).all():
                raise ValueError("Count scores require nonnegative forecasts and integer outcomes.")
            result[name + "_poisson_nll"] = float(
                -poisson.logpmf(y, np.maximum(p, LOG_FLOOR)).mean()
            )
    minute = prediction[[f"minute_probability_{b}" for b in range(4)]].to_numpy(float)
    bins = actual.m_bin.to_numpy(int)
    if not np.isin(bins, range(4)).all():
        raise ValueError("Observed minute classes must be in 0..3.")
    result.update({"minute_bin_" + k: v for k, v in _categorical_loss(minute, bins).items()})
    starts = actual.get("starts", pd.Series(np.nan, index=actual.index))
    known = actual.minutes.eq(0) | (actual.minutes.gt(0) & starts.isin([0, 1]))
    result.update(
        role_known_rows=int(known.sum()),
        role_unknown_rows=int((~known).sum()),
        role_scored_rows=0,
        role_nll=None,
        role_brier=None,
    )
    fields = ["zero_probability", "start_probability", "cameo_probability"]
    if set(fields) <= set(prediction) and prediction[fields].notna().all().all() and known.any():
        role = np.where(actual.loc[known, "minutes"].eq(0), 0, np.where(starts[known].eq(1), 1, 2))
        result.update(
            {
                "role_" + k: v
                for k, v in _categorical_loss(
                    prediction.loc[known, fields].to_numpy(float), role
                ).items()
            }
        )
        result["role_scored_rows"] = int(known.sum())
    return result


def summarize(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Pair the same folds, then give each origin equal weight; retain losses too."""
    result = []
    for position in POSITIONS:
        selected = [r for r in records if r["position"] == position]
        pairs: dict[str, dict[str, dict[str, object]]] = {}
        for record in selected:
            pairs.setdefault(str(record["fold"]), {})[str(record["arm"])] = record
        keys = sorted(
            {
                k
                for r in selected
                for k in r
                if k.endswith(("_mae", "_mse", "_brier", "_nll", "_bias"))
            }
        )
        for metric in keys:
            paired = [
                (float(p[ARMS[0]][metric]), float(p[ARMS[1]][metric]))
                for p in pairs.values()
                if all(arm in p and p[arm].get(metric) is not None for arm in ARMS)
            ]
            delta = np.array([b - a for a, b in paired])
            result.append(
                {
                    "position": position,
                    "metric": metric,
                    "paired_origins": len(paired),
                    "frozen_v1": float(np.mean([a for a, _ in paired])) if paired else None,
                    "joint_role": float(np.mean([b for _, b in paired])) if paired else None,
                    "joint_minus_frozen": float(delta.mean()) if paired else None,
                    "negative_deltas": int((delta < -1e-12).sum()),
                    "positive_deltas": int((delta > 1e-12).sum()),
                    "ties": int((np.abs(delta) <= 1e-12).sum()),
                    "interpretation": "signed_bias_not_ranked"
                    if metric.endswith("_bias")
                    else "lower_loss_is_better",
                }
            )
    return result


def run(
    archive: Path,
    output: Path,
    *,
    training_seasons: tuple[str, ...],
    snapshot_root: Path | None = None,
    snapshot_id: str | None = None,
) -> bool:
    validate_seasons(training_seasons)
    if (snapshot_root is None) != (snapshot_id is None):
        raise ValueError("Current evidence requires both snapshot root and snapshot ID.")
    if "data" in (part.lower() for part in output.resolve().parts):
        raise ValueError("Measurement output must be outside data directories.")
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    project = Path(__file__).resolve().parents[1]
    source_hashes = _hashes(project, SOURCE_FILES)
    hashes = _hashes(archive, tuple(f"data/{s}/{name}" for s in SEASONS for name in ARCHIVE_FILES))
    protocol = {
        "contract": "football_joint_role_measurement_v1",
        "archive_seasons": list(SEASONS),
        "prior_only_season": SEASONS[0],
        "historical_origins": [[s, w] for s, w in ORIGINS],
        "current_policy": "all_settled_single_fixture_weeks_from_explicit_capture",
        "current_requested": snapshot_id is not None,
        "model_versions": [FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSION],
        "fit_budget": {
            "candidate_fits_per_fold": 1,
            "control_additional_fits": 0,
            "maximum_origins": 46,
        },
        "cutoff": (
            "first_target_kickoff_minus_90_minutes; earlier_gameweeks_only; "
            "kickoff_plus_3h_settlement_proxy"
        ),
        "minute_prior_rows": MINUTE_PRIOR_ROWS,
        "logistic_C": 1.0,
        "random_state": 0,
        "log_score_floor": LOG_FLOOR,
        "role_population": (
            "positive_minutes_with_recorded_binary_starts; no_minutes_based_role_labels"
        ),
        "metric_aggregation": (
            "equal_origin_pairs; all_positions; lower_losses_better; signed_bias_not_ranked"
        ),
        "defcon_policy": "known_current_outcomes_only; no_historical_zero_fill",
        "availability_or_news_backfill": False,
        "hyperparameter_search": False,
        "promotion_rule": None,
        "limitations": [
            "Retrospective development data, not independent predictive superiority evidence.",
            "Final historical fixtures and reconstructed observed player population, "
            "not archived deadline rosters.",
            "Current capture uses its recorded roster; "
            "former/transferred player coverage can be incomplete.",
            "Three-hour settlement proxy and 90-minute deadline proxy "
            "are not verified historical publication times.",
            "Control has no start/cameo law; its role scores remain null.",
            "Points residual stays fixed per appearance; "
            "it is not decomposed into minute-specific events.",
        ],
    }
    write(output / "protocol.json", protocol)
    write(output / "input-hashes.json", hashes)
    write(output / "source-hashes.json", source_hashes)
    history = archive_history(archive, seasons=SEASONS)
    current_metadata: dict[str, object] = {"status": "not_requested"}
    origins = list(ORIGINS)
    if snapshot_root is not None and snapshot_id is not None:
        snapshot = read_snapshot(snapshot_root, snapshot_id)
        if infer_season(snapshot) != CURRENT_SEASON:
            raise ValueError("Current evidence must belong to explicit season 2026-27.")
        inputs = read_inputs(snapshot, season=CURRENT_SEASON)
        current = captured_history(
            snapshot, season=CURRENT_SEASON, gameweek=inputs.deadline.gameweek
        )
        weeks = sorted(int(w) for w in current.GW.unique()) if not current.empty else []
        if len(weeks) > 38 or any(not 1 <= w <= 38 for w in weeks):
            raise ValueError("Invalid captured current gameweeks.")
        origins.extend((CURRENT_SEASON, w) for w in weeks)
        if not current.empty:
            history = pd.concat([history, current], ignore_index=True)
        current_metadata = {
            "status": "available" if weeks else "no_settled_rows",
            "snapshot_id": snapshot.metadata.snapshot_id,
            "fingerprint": snapshot.metadata.fingerprint,
            "captured_at_utc": snapshot.metadata.captured_at_utc,
            "payload_sha256": dict(snapshot.metadata.checksums),
            "gameweeks": weeks,
            "rows": len(current),
        }
    write(output / "current-evidence.json", current_metadata)
    write(output / "folds.json", [[s, w] for s, w in origins])
    training = causal_training(history, prior_only_season=SEASONS[0])
    preparation_seconds = time.perf_counter() - started
    records, budgets, failures = [], [], []
    for season, week in origins:
        fold = f"{season}-gw{week:02d}"
        fold_started = time.perf_counter()
        budget: dict[str, object] = {
            "fold": fold,
            "candidate_fit_attempts": 0,
            "control_additional_fits": 0,
        }
        try:
            actual = history.loc[history.season.eq(season) & history.GW.eq(week)].copy()
            if actual.empty:
                raise ValueError("Required fixed-origin outcomes are missing.")
            cutoff = actual.kickoff.min() - pd.Timedelta(minutes=90)
            past = history.loc[_earlier(history, season, week, cutoff)]
            train = training.loc[_earlier(training, season, week, cutoff)]
            target = pd.concat(
                [actual.drop(columns="home"), football_features(past, actual, cutoff)], axis=1
            )
            budget.update(
                cutoff=cutoff.isoformat(),
                history_rows=_counts(past),
                training_rows=_counts(train),
                target_rows=len(target),
                feature_count=len(FEATURES),
            )
            budget["candidate_fit_attempts"] = 1
            fit_started = time.perf_counter()
            candidate = JointRoleFootballModel(train, past, cutoff=cutoff)
            budget["fit_seconds"] = time.perf_counter() - fit_started
            budget["role_metadata"] = dict(candidate.role_metadata)
            control = FixtureFootballModel.predict(candidate, target)
            full = candidate.predict(target)
            fold_records = []
            for arm, prediction in zip(ARMS, (control, full), strict=True):
                for position in POSITIONS:
                    mask = (
                        pd.Series(True, index=actual.index)
                        if position == "ALL"
                        else actual.position.eq(position)
                    )
                    if not mask.any():
                        continue
                    fold_records.append(
                        {
                            "fold": fold,
                            "position": position,
                            "arm": arm,
                            **losses(actual.loc[mask], prediction.loc[mask]),
                        }
                    )
            records.extend(fold_records)
            budget["status"] = "complete"
        except Exception as error:
            # Do not leak paths or data in a public-ready result; retain the fold and class.
            failures.append({"fold": fold, "error_type": type(error).__name__})
            budget["status"] = "failed"
        budget["wall_seconds"] = time.perf_counter() - fold_started
        budgets.append(budget)
        write(output / "scores.json", records)
        write(output / "budgets.json", budgets)
        write(output / "failures.json", failures)
        print(f"{fold}: {budget['status']}", flush=True)
    unchanged = _hashes(project, SOURCE_FILES) == source_hashes
    complete = not failures and unchanged
    write(output / "comparison.json", summarize(records))
    write(
        output / "result.json",
        {
            "status": "complete" if complete else "incomplete",
            "required_origins": len(origins),
            "completed_origins": sum(b["status"] == "complete" for b in budgets),
            "candidate_fit_attempts": sum(int(b["candidate_fit_attempts"]) for b in budgets),
            "preparation_seconds": preparation_seconds,
            "wall_seconds": time.perf_counter() - started,
            "source_unchanged": unchanged,
            "predictive_superiority_verified": False,
            "promotion": False,
        },
    )
    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training-seasons", required=True)
    parser.add_argument("--snapshot-root", type=Path)
    parser.add_argument("--snapshot-id")
    args = parser.parse_args()
    return (
        0
        if run(
            args.archive_root,
            args.output,
            training_seasons=tuple(args.training_seasons.split(",")),
            snapshot_root=args.snapshot_root,
            snapshot_id=args.snapshot_id,
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
