"""How do the component sampler's draws relate to the Phase C predictions behind them?

    python -m scripts.measure_component_fidelity \
        --oof-table artifacts/phase_c/phase_c_component_oof_v1.csv \
        --roster artifacts/phase_c/phase_c_component_oof_v1.roster.csv \
        --manifest artifacts/phase_c/phase_c_component_oof_v1.manifest.json

A **diagnostic**, pre-registered in `docs/phase_d_component_fidelity_prereg.md`. It measures
five signed differences and records them. It registers no threshold, promotes nothing, and
nothing about the seed, the scenario count, the residual pool, the clipping or the floor is
adjusted because of what comes out.

Exact agreement is not expected and its absence is not a defect. The residual pool is
empirical and not required to have mean zero, so

    E[Y_i] = p_i * (mu_points_i + E[eps_points])

and equality with `p_i * mu_points_i` holds only where `E[eps_points]` happens to vanish over
the fold a scenario drew from. Minutes carry two more reasons: the ceiling at
`90 * fixture_count` and the one-minute floor an appearance takes.

Read-only over the Phase C development artifact. The locked 2025-26 holdout is not read,
listed or hashed: the runner refuses outright if any row carries that season, and
`ComponentScenarioProvenance` refuses it independently.

**Why this lives in a script.** The fold walk needs the whole Phase C export, and the package
layer that owns the sampler must not grow a reader for an artifact that sits above it. The
component-scenario contract deliberately takes a prepared frame; this shell prepares it.
"""

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, _git_revision

from squadopt.experiments.shadow_report import write_document_once
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig, ScenarioTarget, ScenarioValidationError
from squadopt.scenarios.components import (
    COMPONENT_MODEL_ROUTE,
    DIRECT_CONTROL_ROUTE,
    MINUTES_PER_FIXTURE,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    paired_conditional_residuals,
    sample_component_scenarios,
)

LOGGER = logging.getLogger(__name__)

FIDELITY_CONTRACT_VERSION: Final = "phase_d_component_fidelity_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")

# The five differences, in the pre-registration's own order. Each is sampled minus predicted,
# so a positive number means the sampler produced more than the component prediction.
METRIC_NAMES: Final = (
    "appearance",
    "points_unconditional",
    "minutes_unconditional",
    "minutes_conditional",
    "points_conditional",
)

# The unit of observation is one (fold, player) pair: each per-player statistic is compared
# against that player's own prediction, then pooled. Pooling cells instead would weight a
# player by how often they appeared, which is not what the targets are stated per.
OBSERVATION_UNIT: Final = "fold_player"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oof-table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "phase_d_component_fidelity.json",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _number(value: float) -> float | None:
    """A finite float, or ``None``. The artifact writer refuses NaN, and rightly."""

    number = float(value)
    return number if np.isfinite(number) else None


def _distribution(values: Sequence[float]) -> Mapping[str, object]:
    """Summarise per-fold differences without inventing an interval for them."""

    array = np.asarray([value for value in values if np.isfinite(value)], dtype="float64")
    if array.size == 0:
        return {"fold_count": 0, "mean": None, "minimum": None, "maximum": None}
    return {
        "fold_count": int(array.size),
        "mean": _number(array.mean()),
        "minimum": _number(array.min()),
        "maximum": _number(array.max()),
        # Quantiles, not a confidence interval: no bootstrap or gate is registered.
        "p10": _number(np.quantile(array, 0.10)),
        "p50": _number(np.quantile(array, 0.50)),
        "p90": _number(np.quantile(array, 0.90)),
    }


def _fold_target(fold_id: str) -> ScenarioTarget:
    season, _, gameweek = str(fold_id).rpartition("-gw")
    return ScenarioTarget(season=season, gameweek=int(gameweek))


def _fold_inputs(
    fold_rows: pd.DataFrame,
    roster_rows: pd.DataFrame,
    manifest: Mapping[str, object],
    target: ScenarioTarget,
) -> tuple[ComponentScenarioInputs, object]:
    """Join the roster onto one fold's component rows and build both typed inputs."""

    joined = (
        fold_rows.merge(
            roster_rows.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
            on="player_id",
            how="inner",
        )
        .sort_values("player_id", kind="stable")
        .reset_index(drop=True)
    )
    if len(joined) != len(fold_rows):
        raise ScenarioValidationError(
            f"{len(fold_rows) - len(joined)} component row(s) in {target.fold_id} have no "
            "decision-roster entry, so their team and position are unknown."
        )
    # ``control_expected_points`` is the export's own non-negative composition, which is what
    # the optimizer projection contract requires. The *raw* conditional column is used for the
    # comparison targets instead, so this study does not inherit that lower bound.
    snapshot = prepare_optimizer_projection(
        joined.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        joined.loc[:, ["player_id"]].assign(
            expected_points=joined["control_expected_points"].to_numpy(dtype="float64")
        ),
        PredictionProvenance(
            model_name=str(manifest["model_version"]),
            model_version=str(manifest["model_version"]),
            feature_contract_version=str(manifest["feature_contract_version"]),
            training_cutoff=target.fold_id,
            training_data_fingerprint=str(manifest["table_sha256"]),
        ),
    )
    inputs = ComponentScenarioInputs(
        table=joined.loc[
            :,
            [
                "player_id",
                "team_id",
                "position",
                "fixture_count",
                "appearance_probability",
                "expected_minutes_if_appearance",
                "raw_expected_points_if_appearance",
                "composition_route",
                "evidence_status",
            ],
        ],
        provenance=ComponentScenarioProvenance(
            phase_c_table_sha=str(manifest["table_sha256"]),
            roster_sha=str(manifest["roster_sha256"]),
            model_version=str(manifest["model_version"]),
            feature_contract_version=str(manifest["feature_contract_version"]),
            target_contract_version=str(manifest["target_contract_version"]),
            dataset_contract_version=str(manifest["dataset_contract_version"]),
            season=target.season,
            target_gameweek=target.gameweek,
            deterministic_seed=0,
        ),
    )
    return inputs, snapshot


def _fold_differences(
    inputs: ComponentScenarioInputs,
    points: "np.ndarray[tuple[int, int], np.dtype[np.float64]]",
    minutes: "np.ndarray[tuple[int, int], np.dtype[np.float64]]",
    appeared: "np.ndarray[tuple[int, int], np.dtype[np.bool_]]",
) -> tuple[dict[str, tuple[object, object, object]], dict[str, int]]:
    """Per fold and per metric: the difference, the sampled level and the predicted level."""

    table = inputs.table
    probability = table["appearance_probability"].to_numpy(dtype="float64")
    conditional_minutes = table["expected_minutes_if_appearance"].to_numpy(dtype="float64")
    conditional_points = table["raw_expected_points_if_appearance"].to_numpy(dtype="float64")
    fixtures = table["fixture_count"].to_numpy(dtype="float64")

    appeared_per_player = appeared.sum(axis=0)
    observed = appeared_per_player > 0

    # Conditional means are undefined for a player who never appeared in any scenario. Such a
    # player is dropped from D and E and counted, rather than contributing a zero that would
    # read as a measured conditional outcome.
    with np.errstate(invalid="ignore", divide="ignore"):
        conditional_minutes_mean = np.where(
            observed, np.where(appeared, minutes, 0.0).sum(axis=0) / appeared_per_player, np.nan
        )
        conditional_points_mean = np.where(
            observed, np.where(appeared, points, 0.0).sum(axis=0) / appeared_per_player, np.nan
        )

    # Both levels are kept beside the difference, not just the difference. A signed gap of
    # +1.0 says nothing about whether the sampler produced 5 against 4 or -5 against -6, and
    # this measurement is run once, so a level that is not recorded now is not recoverable.
    sampled = {
        "appearance": appeared.mean(axis=0),
        "points_unconditional": points.mean(axis=0),
        "minutes_unconditional": minutes.mean(axis=0),
        "minutes_conditional": conditional_minutes_mean[observed],
        "points_conditional": conditional_points_mean[observed],
    }
    predicted = {
        "appearance": probability,
        "points_unconditional": probability * conditional_points,
        "minutes_unconditional": probability * conditional_minutes,
        "minutes_conditional": conditional_minutes[observed],
        "points_conditional": conditional_points[observed],
    }
    differences = {name: sampled[name] - predicted[name] for name in METRIC_NAMES}

    # Floor engagement is a stated upper bound: the sampler does not expose the pre-clip
    # minute, so a cell sitting exactly on the floor is counted even though a legitimate draw
    # could land there. See the pre-registration.
    ceiling = fixtures * MINUTES_PER_FIXTURE
    counts = {
        "players": len(table),
        "scenarios": int(points.shape[0]),
        "cells": int(points.size),
        "appeared_cells": int(appeared_per_player.sum()),
        "players_never_appearing": int((~observed).sum()),
        "blank_fixture_cells": int(points.shape[0] * int((fixtures <= 0.0).sum())),
        "floor_engaged_cells": int(np.count_nonzero(appeared & (minutes == 1.0))),
        "ceiling_engaged_cells": int(np.count_nonzero(appeared & (minutes == ceiling[None, :]))),
    }
    series = {
        name: (
            np.asarray(differences[name], dtype="float64"),
            np.asarray(sampled[name], dtype="float64"),
            np.asarray(predicted[name], dtype="float64"),
        )
        for name in METRIC_NAMES
    }
    return series, counts


def measure_fidelity(
    oof: pd.DataFrame,
    roster: pd.DataFrame,
    manifest: Mapping[str, object],
    *,
    config: ScenarioConfig | None = None,
) -> dict[str, object]:
    """Measure the five differences over every eligible fold and return one document.

    Pure over its frames: the caller's tables are never mutated, and no file is read or
    written here. Folds that cannot be measured are recorded with the reason rather than
    dropped silently, and the residual pool's own sufficiency rule decides eligibility rather
    than a second copy of that rule living here.
    """

    settings = ScenarioConfig() if config is None else config
    seasons = sorted({str(value) for value in oof["season"]})
    if LOCKED_HOLDOUT_SEASON in seasons:
        raise SystemExit(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout. It is not read, listed or measured "
            "here; spending it is a three-owner decision under its own protocol."
        )

    table = oof.copy(deep=True)
    route = table["composition_route"].astype("string")
    fold_ids = sorted({str(value) for value in table["fold_id"]})

    pooled: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    pooled_sampled: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    pooled_predicted: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    per_fold_means: dict[str, list[float]] = {name: [] for name in METRIC_NAMES}
    fold_records: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    totals = {
        "direct_control_excluded_rows": int((route == DIRECT_CONTROL_ROUTE).sum()),
        "cells": 0,
        "appeared_cells": 0,
        "blank_fixture_cells": 0,
        "floor_engaged_cells": 0,
        "ceiling_engaged_cells": 0,
        "players_never_appearing": 0,
    }
    warnings: list[str] = []

    for fold_id in fold_ids:
        target = _fold_target(fold_id)
        current = table.loc[(table["fold_id"] == fold_id) & (route == COMPONENT_MODEL_ROUTE)]
        control_rows = int(((table["fold_id"] == fold_id) & (route == DIRECT_CONTROL_ROUTE)).sum())
        if current.empty:
            excluded.append(
                {
                    "fold_id": fold_id,
                    "reason": "no component_model row in this fold",
                    "direct_control_rows": control_rows,
                }
            )
            continue
        # The pool's own rule decides sufficiency. Catching its refusal keeps one implementation
        # of "enough history" rather than predicting it here and risking a different answer.
        history = table.loc[table["fold_id"] < fold_id]
        try:
            pool = paired_conditional_residuals(
                history, target=target, min_history_folds=settings.min_history_folds
            )
        except ScenarioValidationError as error:
            excluded.append(
                {
                    "fold_id": fold_id,
                    "reason": str(error),
                    "direct_control_rows": control_rows,
                }
            )
            continue

        roster_rows = roster.loc[roster["fold_id"] == fold_id]
        inputs, snapshot = _fold_inputs(current, roster_rows, manifest, target)
        draw = sample_component_scenarios(inputs, snapshot, pool, target, settings)  # type: ignore[arg-type]
        series, counts = _fold_differences(
            inputs,
            draw.scenarios.scenario_points.to_numpy(dtype="float64"),
            draw.sampled_minutes.to_numpy(dtype="float64"),
            draw.sampled_appearances.to_numpy(dtype=bool),
        )

        record: dict[str, object] = {
            "fold_id": fold_id,
            "season": target.season,
            "target_gameweek": target.gameweek,
            "residual_pool_rows": len(pool),
            "residual_history_folds": len(pool.history_fold_ids),
            "component_fingerprint": draw.component_fingerprint,
            "direct_control_rows": control_rows,
            **counts,
        }
        for name in METRIC_NAMES:
            values, sampled_values, predicted_values = series[name]
            pooled[name].extend(float(value) for value in values)
            pooled_sampled[name].extend(float(value) for value in sampled_values)
            pooled_predicted[name].extend(float(value) for value in predicted_values)
            fold_mean = float(values.mean()) if values.size else float("nan")
            per_fold_means[name].append(fold_mean)
            record[f"{name}_mean_difference"] = _number(fold_mean)
            record[f"{name}_mean_absolute_difference"] = (
                _number(np.abs(values).mean()) if values.size else None
            )
            record[f"{name}_sampled_mean"] = (
                _number(sampled_values.mean()) if sampled_values.size else None
            )
            record[f"{name}_predicted_mean"] = (
                _number(predicted_values.mean()) if predicted_values.size else None
            )
            record[f"{name}_sample_count"] = int(values.size)
        fold_records.append(record)

        for key in (
            "cells",
            "appeared_cells",
            "blank_fixture_cells",
            "floor_engaged_cells",
            "ceiling_engaged_cells",
            "players_never_appearing",
        ):
            totals[key] += int(counts[key])
        if counts["players_never_appearing"]:
            warnings.append(
                f"{fold_id}: {counts['players_never_appearing']} player(s) never appeared in any "
                "scenario, so they carry no conditional observation."
            )

    pooled_report: dict[str, object] = {}
    for name in METRIC_NAMES:
        values = np.asarray(pooled[name], dtype="float64")
        finite = values[np.isfinite(values)]
        sampled_values = np.asarray(pooled_sampled[name], dtype="float64")
        predicted_values = np.asarray(pooled_predicted[name], dtype="float64")
        mask = np.isfinite(values)
        pooled_report[name] = {
            "mean_signed_difference": _number(finite.mean()) if finite.size else None,
            "mean_absolute_difference": _number(np.abs(finite).mean()) if finite.size else None,
            "sampled_mean": _number(sampled_values[mask].mean()) if finite.size else None,
            "predicted_mean": _number(predicted_values[mask].mean()) if finite.size else None,
            "sample_count": int(finite.size),
            "non_finite_dropped": int(values.size - finite.size),
        }

    return {
        "contract_version": FIDELITY_CONTRACT_VERSION,
        "diagnostic_only": True,
        "promotes_anything": False,
        "registers_any_threshold": False,
        "observation_unit": OBSERVATION_UNIT,
        "config": {
            "scenario_count": int(settings.scenario_count),
            "deterministic_seed": int(settings.deterministic_seed),
            "min_history_folds": int(settings.min_history_folds),
        },
        "population": {
            "development_seasons": list(DEVELOPMENT_SEASONS),
            "seasons_present": seasons,
            "locked_holdout_season": LOCKED_HOLDOUT_SEASON,
            "locked_holdout_rows_present": 0,
            "composition_route_measured": COMPONENT_MODEL_ROUTE,
            "fold_count_total": len(fold_ids),
            "fold_count_measured": len(fold_records),
            "fold_count_excluded": len(excluded),
            "measured_fold_ids": [str(record["fold_id"]) for record in fold_records],
        },
        "counts": {
            **totals,
            "floor_engaged_rate": (
                _number(totals["floor_engaged_cells"] / totals["appeared_cells"])
                if totals["appeared_cells"]
                else None
            ),
            "floor_engagement_is_upper_bound": True,
        },
        "pooled": pooled_report,
        "fold_summary": {name: _distribution(per_fold_means[name]) for name in METRIC_NAMES},
        "folds": fold_records,
        "excluded_folds": excluded,
        "warnings": warnings,
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arguments = _parse_arguments()

    revision, dirty = _git_revision()
    if dirty:
        # The same refusal `export_component_oof` makes: a commit recorded beside a measurement
        # has to describe the code that produced it, and a dirty tree cannot promise that.
        LOGGER.error(
            "The working tree is dirty. Commit the pre-registration and the runner before "
            "measuring; an artifact whose recorded commit does not describe its code is not "
            "evidence."
        )
        return 1

    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    oof = pd.read_csv(arguments.oof_table, dtype={"team_id": "string", "position": "string"})
    roster = pd.read_csv(arguments.roster, dtype={"team_id": "string", "position": "string"})

    document = measure_fidelity(oof, roster, manifest)
    document["created_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    document["provenance"] = {
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "prereg_document": "docs/phase_d_component_fidelity_prereg.md",
        "oof_table": arguments.oof_table.name,
        "oof_table_sha256": _sha256(arguments.oof_table),
        "roster": arguments.roster.name,
        "roster_sha256": _sha256(arguments.roster),
        "manifest": arguments.manifest.name,
        "manifest_sha256": _sha256(arguments.manifest),
        "manifest_table_sha256": str(manifest["table_sha256"]),
        "manifest_roster_sha256": str(manifest["roster_sha256"]),
        "manifest_locked_holdout_read": bool(manifest["locked_holdout_read"]),
        "model_version": str(manifest["model_version"]),
        "feature_contract_version": str(manifest["feature_contract_version"]),
    }

    outcome = write_document_once(document, arguments.json_output)
    LOGGER.info(
        "%s %s (%d folds measured, %d excluded)",
        outcome,
        arguments.json_output,
        document["population"]["fold_count_measured"],  # type: ignore[index]
        document["population"]["fold_count_excluded"],  # type: ignore[index]
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
