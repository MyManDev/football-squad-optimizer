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
from itertools import pairwise
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
ROLE_ARMS = ("pooled_empirical_role", "joint_role")
MEASUREMENT_CONTRACT = "football_joint_role_measurement_v2"
POSITIONS = ("ALL", "GK", "DEF", "MID", "FWD")
LOG_FLOOR = 1e-12
PROBABILITY_BIN_EDGES = tuple(i / 10 for i in range(11))
ROLE_RATIO_ROUNDOFF_ATOL = 1e-12
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
    result.update(role_losses(actual, prediction))
    return result


def role_losses(actual: pd.DataFrame, prediction: pd.DataFrame) -> dict[str, object]:
    """Score the same known zero/start/cameo outcomes for either role forecast."""
    if len(actual) != len(prediction) or not actual.index.equals(prediction.index) or actual.empty:
        raise ValueError("Role measurement rows must be nonempty and exactly aligned.")
    result: dict[str, object] = {}
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


def pooled_role_baseline(
    train: pd.DataFrame, control: pd.DataFrame, joint: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Use the exact causal supervised train, not priors or target labels.

    Both predictions call the unchanged four-bin appearance head on the same
    target. Require exact elementwise q equality; no statistical tolerance or
    availability adjustment belongs in this restricted role comparison.
    """
    if control.empty or not control.index.equals(joint.index):
        raise ValueError("Restricted role predictions must share their target rows.")
    q = control.appearance_probability.to_numpy(float)
    candidate_q = joint.appearance_probability.to_numpy(float)
    if (
        not np.isfinite(q).all()
        or not np.isfinite(candidate_q).all()
        or ((q < 0) | (q > 1)).any()
        or ((candidate_q < 0) | (candidate_q > 1)).any()
        or not np.array_equal(q, candidate_q)
    ):
        raise ValueError("Restricted role comparison requires identical finite appearance q.")
    labels = train.get("starts", pd.Series(np.nan, index=train.index))
    appeared = train.minutes.gt(0)
    if (labels.notna() & ~labels.isin([0, 1])).any() or (labels.eq(1) & ~appeared).any():
        raise ValueError("Recorded starts must be binary and have positive minutes.")
    known = appeared & labels.isin([0, 1])
    count = int(known.sum())
    starting = int(labels.loc[known].sum())
    rate = starting / count if count else None
    prediction = pd.DataFrame(
        {
            "zero_probability": 1 - q,
            "start_probability": q * rate if rate is not None else np.nan,
            "cameo_probability": q * (1 - rate) if rate is not None else np.nan,
        },
        index=control.index,
    )
    return prediction, {
        "status": "available" if count else "unavailable_no_known_start_labels",
        "training_appearance_rows": int(appeared.sum()),
        "known_start_label_rows": count,
        "unknown_start_label_rows": int((appeared & labels.isna()).sum()),
        "starting_label_rows": starting,
        "pooled_start_given_appearance": rate,
    }


def _binary_calibration(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, object]:
    """Fixed bins and binary losses; an empty population has no measured loss."""
    if (
        probabilities.ndim != 1
        or probabilities.shape != labels.shape
        or not np.isfinite(probabilities).all()
        or ((probabilities < 0) | (probabilities > 1)).any()
        or not np.isin(labels, [0, 1]).all()
    ):
        raise ValueError("Calibration requires aligned binary labels and finite probabilities.")
    observed_probability = np.where(labels == 1, probabilities, 1 - probabilities)
    bins = np.minimum(np.searchsorted(PROBABILITY_BIN_EDGES, probabilities, side="right") - 1, 9)
    cells = []
    for index, (lower, upper) in enumerate(pairwise(PROBABILITY_BIN_EDGES)):
        selected = bins == index
        count = int(selected.sum())
        cells.append(
            {
                "lower": lower,
                "upper": upper,
                "upper_inclusive": index == 9,
                "count": count,
                "mean_pred": float(probabilities[selected].mean()) if count else None,
                "event_rate": float(labels[selected].mean()) if count else None,
            }
        )
    return {
        "rows": len(labels),
        "nll": float(-np.log(np.maximum(observed_probability, LOG_FLOOR)).mean())
        if len(labels)
        else None,
        "brier": float(((probabilities - labels) ** 2).mean()) if len(labels) else None,
        "floor_active_rows": int((observed_probability < LOG_FLOOR).sum()),
        "zero_observed_probability_rows": int((observed_probability == 0).sum()),
        "bins": cells,
    }


def role_diagnostics(
    actual: pd.DataFrame, prediction: pd.DataFrame, appearance: pd.Series
) -> dict[str, object]:
    """Separate appearance and conditional-start evidence without inventing q=0 roles.

    Like role_losses, a partially missing role forecast is unavailable as a whole.
    Appearance can still be diagnosed on known role rows. No row payload is retained.
    """
    if (
        actual.empty
        or not actual.index.equals(prediction.index)
        or not actual.index.equals(appearance.index)
    ):
        raise ValueError("Role diagnostics require nonempty aligned rows.")
    q = appearance.to_numpy(float)
    if not np.isfinite(q).all() or ((q < 0) | (q > 1)).any():
        raise ValueError("Role diagnostics require finite appearance probabilities.")
    starts = actual.get("starts", pd.Series(np.nan, index=actual.index))
    positive = actual.minutes.gt(0) & starts.isin([0, 1])
    known = actual.minutes.eq(0) | positive
    positive_q = positive.to_numpy() & (q > 0)
    fields = ["zero_probability", "start_probability", "cameo_probability"]
    supported = set(fields) <= set(prediction) and prediction[fields].notna().all().all()
    conditional = np.array([], dtype=float)
    conditional_labels = np.array([], dtype=float)
    joint_floor_rows = None
    if supported:
        roles = prediction[fields].to_numpy(float)
        if (
            not np.isfinite(roles).all()
            or ((roles < 0) | (roles > 1)).any()
            or not np.allclose(roles[:, 0], 1 - q, atol=ROLE_RATIO_ROUNDOFF_ATOL, rtol=0)
            or not np.allclose(roles.sum(axis=1), 1, atol=ROLE_RATIO_ROUNDOFF_ATOL, rtol=0)
        ):
            raise ValueError("Role diagnostic probabilities do not share the appearance law.")
        conditional = roles[positive_q, 1] / q[positive_q]
        if (conditional > 1 + ROLE_RATIO_ROUNDOFF_ATOL).any():
            raise ValueError("Conditional start probability exceeds the appearance mass.")
        # Only floating summation/division roundoff is clipped. q=0 is never divided,
        # floored or replaced; these undefined conditional observations are counted.
        conditional = np.clip(conditional, 0, 1)
        conditional_labels = starts.loc[positive_q].to_numpy(float)
        observed_roles = np.where(
            actual.loc[known, "minutes"].eq(0), 0, np.where(starts.loc[known].eq(1), 1, 2)
        )
        observed_probability = roles[known.to_numpy()][np.arange(int(known.sum())), observed_roles]
        joint_floor_rows = int((observed_probability < LOG_FLOOR).sum())
    return {
        "rows": len(actual),
        "role_known_rows": int(known.sum()),
        "role_unknown_rows": int((~known).sum()),
        "positive_known_rows": int(positive.sum()),
        "role_forecast_available": bool(supported),
        "appearance": _binary_calibration(
            q[known.to_numpy()], actual.loc[known, "minutes"].gt(0).to_numpy(float)
        ),
        "conditional_start": _binary_calibration(conditional, conditional_labels),
        "conditional_q_zero_rows": int((positive.to_numpy() & (q == 0)).sum()),
        "conditional_unsupported_rows": int(positive_q.sum()) if not supported else 0,
        "joint_scored_rows": int(known.sum()) if supported else 0,
        "joint_floor_active_rows": joint_floor_rows,
    }


def summarize_roles(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Equal-origin role pairs only; unsupported or missing arms never become zero."""
    result = []
    for position in POSITIONS:
        pairs: dict[str, dict[str, dict[str, object]]] = {}
        for record in records:
            if record["position"] != position:
                continue
            fold, arm = str(record["fold"]), str(record["arm"])
            pair = pairs.setdefault(fold, {})
            if arm not in ROLE_ARMS or arm in pair:
                raise ValueError("Each role fold/position must have unique declared arms.")
            pair[arm] = record
        for metric in ("role_nll", "role_brier"):
            paired = []
            for pair in pairs.values():
                if not all(arm in pair and pair[arm].get(metric) is not None for arm in ROLE_ARMS):
                    continue
                before, after = (pair[arm] for arm in ROLE_ARMS)
                counts = ("rows", "role_known_rows", "role_unknown_rows", "role_scored_rows")
                if (
                    any(before[k] != after[k] for k in counts)
                    or int(before["role_scored_rows"]) < 1
                ):
                    raise ValueError("Paired role losses must score the same nonempty population.")
                a, b = float(before[metric]), float(after[metric])
                if not np.isfinite([a, b]).all():
                    raise ValueError("Paired role losses must be finite.")
                paired.append((a, b, int(before["role_scored_rows"])))
            delta = np.array([b - a for a, b, _ in paired])
            result.append(
                {
                    "position": position,
                    "metric": metric,
                    "reported_origins": len(pairs),
                    "paired_origins": len(paired),
                    "unpaired_origins": len(pairs) - len(paired),
                    "paired_scored_rows": sum(rows for _, _, rows in paired),
                    "pooled_empirical_role": float(np.mean([a for a, _, _ in paired]))
                    if paired
                    else None,
                    "joint_role": float(np.mean([b for _, b, _ in paired])) if paired else None,
                    "joint_minus_pooled": float(delta.mean()) if paired else None,
                    "negative_deltas": int((delta < -1e-12).sum()),
                    "positive_deltas": int((delta > 1e-12).sum()),
                    "ties": int((np.abs(delta) <= 1e-12).sum()),
                    "interpretation": "lower_loss_is_better_shared_appearance",
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
        "contract": MEASUREMENT_CONTRACT,
        "archive_seasons": list(SEASONS),
        "prior_only_season": SEASONS[0],
        "historical_origins": [[s, w] for s, w in ORIGINS],
        "current_policy": "all_settled_single_fixture_weeks_from_explicit_capture",
        "current_requested": snapshot_id is not None,
        "model_versions": [FOOTBALL_MODEL_VERSION, JOINT_ROLE_MODEL_VERSION],
        "fit_budget": {
            "candidate_fits_per_fold": 1,
            "control_additional_fits": 0,
            "role_baseline_additional_fits": 0,
            "role_diagnostic_additional_fits": 0,
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
        "role_baseline": {
            "name": ROLE_ARMS[0],
            "training": "exact_causal_supervised_train; pooled_across_positions",
            "support": "positive_minutes_with_recorded_binary_starts",
            "rate": "count_starts_1 / count_known_positive_minute_starts",
            "probabilities": ["1-q", "q*r", "q*(1-r)"],
            "appearance": "frozen_control; exact_elementwise_equal_to_joint",
            "unsupported": "null_rate_and_role_losses; no_default_or_smoothing",
            "evaluation": "same_known_zero_start_cameo_rows; equal_origin_pairs",
            "outputs": ["role-scores.json", "role-comparison.json"],
        },
        "metric_aggregation": (
            "equal_origin_pairs; all_positions; lower_losses_better; signed_bias_not_ranked"
        ),
        "role_diagnostics": {
            "version": "role_calibration_diagnostics_v1",
            "output": "role-diagnostics.json",
            "probability_bin_edges": list(PROBABILITY_BIN_EDGES),
            "bin_closure": "left_closed_right_open; last_bin_includes_one",
            "appearance_population": "known_zero_or_positive_binary_start_rows",
            "conditional_population": "observed_positive_binary_start_rows_with_q_gt_zero",
            "q_zero_conditional": "undefined_counted_and_excluded; no_probability_floor",
            "missing_role_forecast": "unavailable_whole_origin_position; no_zero_loss",
            "conditional_ratio_roundoff_atol": ROLE_RATIO_ROUNDOFF_ATOL,
            "brier": "binary_squared_error; role_scores_remain_three_class_sum_squared_error",
            "nll_floor_active": "observed_outcome_probability_strictly_less_than_log_score_floor",
            "decomposition": "unfloored_only; separately_floored_terms_need_not_sum_to_role_nll",
            "additional_fits": 0,
        },
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
            "Frozen v1 control has no start/cameo law; its role scores remain null.",
            "The separate pooled role reference reuses control appearance; "
            "it is not a standalone model or independent calibration evidence.",
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
    records, role_records, diagnostic_records, budgets, failures = [], [], [], [], []
    for season, week in origins:
        fold = f"{season}-gw{week:02d}"
        fold_started = time.perf_counter()
        budget: dict[str, object] = {
            "fold": fold,
            "candidate_fit_attempts": 0,
            "control_additional_fits": 0,
            "role_baseline_additional_fits": 0,
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
            pooled, baseline_metadata = pooled_role_baseline(train, control, full)
            budget["role_baseline"] = baseline_metadata
            budget["appearance_q_identical"] = True
            fold_records = []
            fold_role_records = []
            fold_diagnostics = []
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
            for arm, prediction in zip(ROLE_ARMS, (pooled, full), strict=True):
                for position in POSITIONS:
                    mask = (
                        pd.Series(True, index=actual.index)
                        if position == "ALL"
                        else actual.position.eq(position)
                    )
                    if not mask.any():
                        continue
                    fold_role_records.append(
                        {
                            "fold": fold,
                            "position": position,
                            "arm": arm,
                            "rows": int(mask.sum()),
                            **role_losses(actual.loc[mask], prediction.loc[mask]),
                        }
                    )
                    fold_diagnostics.append(
                        {
                            "fold": fold,
                            "position": position,
                            "arm": arm,
                            **role_diagnostics(
                                actual.loc[mask],
                                prediction.loc[mask],
                                control.loc[mask, "appearance_probability"],
                            ),
                        }
                    )
            records.extend(fold_records)
            role_records.extend(fold_role_records)
            diagnostic_records.extend(fold_diagnostics)
            budget["status"] = "complete"
        except Exception as error:
            # Do not leak paths or data in a public-ready result; retain the fold and class.
            failures.append({"fold": fold, "error_type": type(error).__name__})
            budget["status"] = "failed"
        budget["wall_seconds"] = time.perf_counter() - fold_started
        budgets.append(budget)
        write(output / "scores.json", records)
        write(output / "role-scores.json", role_records)
        write(output / "role-diagnostics.json", diagnostic_records)
        write(output / "budgets.json", budgets)
        write(output / "failures.json", failures)
        print(f"{fold}: {budget['status']}", flush=True)
    unchanged = _hashes(project, SOURCE_FILES) == source_hashes
    complete = not failures and unchanged
    write(output / "comparison.json", summarize(records))
    write(output / "role-comparison.json", summarize_roles(role_records))
    write(
        output / "result.json",
        {
            "contract": MEASUREMENT_CONTRACT,
            "status": "complete" if complete else "incomplete",
            "required_origins": len(origins),
            "role_baseline_additional_fits": 0,
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
