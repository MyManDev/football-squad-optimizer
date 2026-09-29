"""Development-only chronological prediction of recorded continuation returns.

Compressed historical chains are not Markov state/action logs. This diagnostic
never supplies an optimizer value or claims an off-policy improvement.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor  # type: ignore[import-untyped]
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]
from sklearn.neural_network import MLPRegressor  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

FEATURES = (
    "gameweek",
    "bank_after_tenths",
    "squad_sell_value_tenths",
    "free_transfers_after",
    "projected_points",
    "transfer_count",
)
SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
DIRECTORIES = (
    "season_chain",
    "season_chain_blind",
    "season_chain_fh",
    "season_chain_hybrid",
    "season_chain_value",
    "chain_tuned",
)
CONFIGS = ((16, 1.0), (16, 10.0), (32, 1.0), (32, 10.0))


def load_rows(root: Path, window: int) -> tuple[pd.DataFrame, dict[str, str]]:
    """Read only the named development seasons; refuse incomplete source schemas."""
    if window not in (3, 5) or isinstance(window, bool):
        raise ValueError("Continuation window must be 3 or 5.")
    records, digests = [], {}
    for directory in DIRECTORIES:
        for season in SEASONS:
            relative = f"{directory}/{season}.json"
            path = root / relative
            payload = path.read_bytes()
            document = json.loads(payload)
            digests[relative] = hashlib.sha256(payload).hexdigest()
            for chain_index, chain in enumerate(document["chains"]):
                if chain.get("season", season) != season:
                    raise ValueError("Chain season differs from its source partition.")
                weeks = chain["weeks"]
                dates = [w["gameweek"] for w in weeks]
                if dates != sorted(set(dates)):
                    raise ValueError("Decision weeks must be unique and increasing.")
                for index, week in enumerate(weeks[:-window]):
                    future = weeks[index + 1 : index + 1 + window]
                    if [w["gameweek"] for w in future] != list(
                        range(week["gameweek"] + 1, week["gameweek"] + 1 + window)
                    ):
                        continue
                    records.append(
                        {
                            "season": season,
                            "source": f"{relative}#{chain_index}",
                            **{name: float(week[name]) for name in FEATURES},
                            "target": sum(float(w["net_points"]) for w in future) / window,
                        }
                    )
    frame = pd.DataFrame(records)
    if frame.empty or not np.isfinite(frame[[*FEATURES, "target"]].to_numpy()).all():
        raise ValueError("Finite complete training observations are required.")
    return frame, digests


def group_weights(frame: pd.DataFrame) -> np.ndarray:
    """One deadline is one weight, regardless of how many policies were recorded."""
    size = frame.groupby(["season", "gameweek"])["source"].transform("size").to_numpy()
    weights = 1.0 / size
    return weights * len(weights) / weights.sum()


def fit_predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    kind: str,
    *,
    configuration: tuple[int, float] = CONFIGS[0],
    seed: int = 0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Training-only scaling and observation-domain fallback, shared by all models."""
    x = train[list(FEATURES)].to_numpy(dtype=float)
    y = train.target.to_numpy(dtype=float)
    z = test[list(FEATURES)].to_numpy(dtype=float)
    if not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Training data must be nonempty and finite.")
    weights = group_weights(train)
    baseline = float(np.average(y, weights=weights))
    valid = (
        np.isfinite(z).all(axis=1)
        & (z >= x.min(axis=0)).all(axis=1)
        & (z <= x.max(axis=0)).all(axis=1)
    )
    result = np.full(len(z), baseline)
    info: dict[str, Any] = {
        "kind": kind,
        "fallback_rows": int((~valid).sum()),
        "rows": len(z),
        "warnings": [],
    }
    if kind == "constant":
        return result, info
    scaler = StandardScaler().fit(x, sample_weight=weights)
    models = {
        "ridge": Ridge(alpha=10),
        "tree": HistGradientBoostingRegressor(
            max_leaf_nodes=7,
            max_iter=100,
            min_samples_leaf=30,
            l2_regularization=20,
            random_state=seed,
        ),
        "mlp": MLPRegressor(
            hidden_layer_sizes=(configuration[0],),
            alpha=configuration[1],
            solver="lbfgs",
            max_iter=500,
            random_state=seed,
        ),
    }
    if kind not in models:
        raise ValueError("Unknown continuation model.")
    model = models[kind]
    if "sample_weight" not in inspect.signature(model.fit).parameters:
        raise ValueError(
            "This diagnostic requires an existing sklearn model with weighted fitting."
        )
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        model.fit(scaler.transform(x), y, sample_weight=weights)
        if valid.any():
            values = model.predict(scaler.transform(z[valid]))
            finite = np.isfinite(values)
            indices = np.flatnonzero(valid)
            result[indices[finite]] = values[finite]
            info["fallback_rows"] += int((~finite).sum())
    info["warnings"] = [str(w.message) for w in recorded]
    return result, info


def metrics(rows: pd.DataFrame, prediction: np.ndarray) -> dict[str, float]:
    error = prediction - rows.target.to_numpy()
    weights = group_weights(rows)
    return {
        "mae": float(np.average(abs(error), weights=weights)),
        "rmse": float(np.sqrt(np.average(error**2, weights=weights))),
    }


def block_interval(rows: pd.DataFrame, delta: np.ndarray) -> tuple[float, float]:
    """95% development error-difference interval; overlapping outcomes stay grouped."""
    frame = rows[["season", "gameweek"]].assign(delta=delta)
    groups = frame.groupby(["season", "gameweek"]).delta.mean()
    rng = np.random.default_rng(0)
    draws = []
    for _ in range(2000):
        parts: list[float] = []
        for season in groups.index.get_level_values(0).unique():
            values = groups.loc[season].to_numpy()
            length = min(5, len(values))
            starts = rng.integers(
                0, len(values) - length + 1, size=int(np.ceil(len(values) / length))
            )
            parts.extend(
                np.concatenate([values[start : start + length] for start in starts])[: len(values)]
            )
        draws.append(float(np.mean(parts)))
    low, high = np.quantile(draws, [0.025, 0.975])
    return float(low), float(high)


def study(frame: pd.DataFrame) -> dict[str, Any]:
    """Select on 2023-24, evaluate on previously consumed 2024-25 development data."""
    train = frame.loc[frame.season.isin(SEASONS[:2])]
    selection = frame.loc[frame.season.eq(SEASONS[2])]
    test = frame.loc[frame.season.eq(SEASONS[3])]
    if any(f.empty for f in (train, selection, test)):
        raise ValueError("Every chronological partition is required.")
    trials = []
    for configuration in CONFIGS:
        pred, info = fit_predict(train, selection, "mlp", configuration=configuration)
        trials.append({"configuration": configuration, **metrics(selection, pred), **info})
    chosen = min(range(len(trials)), key=lambda i: trials[i]["mae"])
    fit_rows = pd.concat([train, selection], ignore_index=True)
    scores, predictions = {}, {}
    for kind, seed in [
        ("constant", 0),
        ("ridge", 0),
        ("tree", 0),
        ("mlp", 0),
        ("mlp", 1),
        ("mlp", 2),
    ]:
        pred, info = fit_predict(fit_rows, test, kind, configuration=CONFIGS[chosen], seed=seed)
        name = f"{kind}_{seed}"
        predictions[name] = pred
        scores[name] = {**metrics(test, pred), **info}
    baseline_error = abs(predictions["constant_0"] - test.target.to_numpy())
    for name, pred in predictions.items():
        scores[name]["mae_gain_interval_95"] = block_interval(
            test, baseline_error - abs(pred - test.target.to_numpy())
        )
    return {
        "partition_rows": {
            "train": len(train),
            "selection": len(selection),
            "diagnostic_test": len(test),
        },
        "selection_trials": trials,
        "selected_configuration": CONFIGS[chosen],
        "scores": scores,
        "development_only": True,
        "policy_evaluated": False,
        "promotion": False,
        "independent_holdout": False,
    }
