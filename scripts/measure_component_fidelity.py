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

Read-only over the Phase C development artifact. On the default path the locked 2025-26
holdout is not read, listed or hashed: the runner refuses outright if any row carries that
season, and `ComponentScenarioProvenance` refuses it independently.

**Phase C v2 development path.** ``--phase-c-contract development_v2`` measures the same five
differences, by the same method, on the Phase C v2 equal-weight reference: it reads that
handoff through the explicit development reader, is pinned to the reference's three artifact
digests, draws on the declared candidate sampler, admits the 2025-26 decisions that handoff
carries as development data, and writes the distinct
`phase_d_component_fidelity_development_v2` document. The v1 path, its refusals and its
artifact are unchanged.

**Why this lives in a script.** The fold walk needs the whole Phase C export, and the package
layer that owns the sampler must not grow a reader for an artifact that sits above it. The
component-scenario contract deliberately takes a prepared frame; this shell prepares it.
"""

import argparse
import hashlib
import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, _git_revision

from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationValidationError,
    read_phase_c_component_handoff,
)
from squadopt.experiments.shadow_report import write_document_once
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.component_models import COMPONENT_MODEL_VERSION, EQUAL_WEIGHTING
from squadopt.scenarios import ScenarioConfig, ScenarioTarget, ScenarioValidationError
from squadopt.scenarios.components import (
    COMPONENT_MODEL_ROUTE,
    DIRECT_CONTROL_ROUTE,
    MINUTES_PER_FIXTURE,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    ConditionalResidualConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)

LOGGER = logging.getLogger(__name__)

FIDELITY_CONTRACT_VERSION: Final = "phase_d_component_fidelity_v1"
# The same diagnostic on the Phase C v2 equal-weight reference. Its own contract, so nothing
# that requires the frozen v1 record can read it as one and nothing that requires this one can
# be satisfied by the v1 artifact.
DEVELOPMENT_FIDELITY_CONTRACT_VERSION: Final = "phase_d_component_fidelity_development_v2"
PHASE_C_CONTRACTS: Final = ("v1", "development_v2")
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")
_DIGEST: Final = r"[0-9a-f]{64}"
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase_d_component_fidelity.json"

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

# The optimizer fields the decision roster supplies for a scenario input.
_ROSTER_FIELDS: Final = ("name", "team_id", "position", "price_tenths")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oof-table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--phase-c-contract", choices=PHASE_C_CONTRACTS, default="v1")
    parser.add_argument("--expected-table-sha256", default=None)
    parser.add_argument("--expected-roster-sha256", default=None)
    parser.add_argument("--expected-manifest-sha256", default=None)
    parser.add_argument("--conditional-residual-fraction", type=float, default=None)
    parser.add_argument("--conditional-residual-minimum-rows", type=int, default=None)
    return parser.parse_args()


class FidelityBindingError(ValueError):
    """Raised when a development run is not bound to the reference it claims."""


@dataclass(frozen=True, slots=True)
class DevelopmentInputs:
    """What one development_v2 fidelity run is pinned to: the reference and the sampler."""

    table_sha256: str
    roster_sha256: str
    manifest_sha256: str
    # ``None`` is the foundation sampler, which the calibration run also admits; the two
    # sides declare it the same way so a foundation run can be fidelity-verified too.
    conditional_residuals: ConditionalResidualConfig | None


def _development_from_arguments(arguments: argparse.Namespace) -> DevelopmentInputs | None:
    """The development binding the arguments ask for, or None for the frozen v1 diagnostic.

    Under v1 nothing changes and every v2-only option is refused. Under development_v2 the
    three digests are required so the run cannot silently measure another export (the
    season-weighted arm shares the reference's roster digest and differs only in its table),
    the two sampler controls are both-or-neither -- neither meaning the foundation sampler,
    exactly as the calibration run declares it -- and the v1 artifact path is refused.
    """

    contract = str(getattr(arguments, "phase_c_contract", "v1"))
    fraction = getattr(arguments, "conditional_residual_fraction", None)
    minimum_rows = getattr(arguments, "conditional_residual_minimum_rows", None)
    digest_names = ("expected_table_sha256", "expected_roster_sha256", "expected_manifest_sha256")
    if contract == "v1":
        for name in (*digest_names, "conditional_residual_fraction"):
            if getattr(arguments, name, None) is not None:
                raise FidelityBindingError(
                    f"--{name.replace('_', '-')} applies to --phase-c-contract development_v2 only."
                )
        if minimum_rows is not None:
            raise FidelityBindingError(
                "--conditional-residual-minimum-rows applies to "
                "--phase-c-contract development_v2 only."
            )
        return None
    if contract != "development_v2":
        raise FidelityBindingError(f"Unknown Phase C contract {contract!r}.")
    digests: dict[str, str] = {}
    for name in digest_names:
        value = getattr(arguments, name, None)
        if not isinstance(value, str) or re.fullmatch(_DIGEST, value) is None:
            raise FidelityBindingError(
                f"--{name.replace('_', '-')} must pin the reference with a 64-hex SHA-256 "
                "under --phase-c-contract development_v2."
            )
        digests[name] = value
    if (fraction is None) != (minimum_rows is None):
        raise FidelityBindingError(
            "A development_v2 run takes both --conditional-residual-fraction and "
            "--conditional-residual-minimum-rows or neither: the record has to name the same "
            "sampler the calibration run will use, and a half-declared sampler names nothing."
        )
    if Path(arguments.json_output).resolve() == DEFAULT_OUTPUT.resolve():
        raise FidelityBindingError(
            "A development_v2 run cannot write the frozen v1 artifact path; give --json-output."
        )
    return DevelopmentInputs(
        table_sha256=digests["expected_table_sha256"],
        roster_sha256=digests["expected_roster_sha256"],
        manifest_sha256=digests["expected_manifest_sha256"],
        conditional_residuals=(
            None
            if fraction is None
            else ConditionalResidualConfig(fraction=fraction, minimum_rows=minimum_rows)
        ),
    )


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
    development_contract: str | None = None,
) -> tuple[ComponentScenarioInputs, object]:
    """Join the roster onto one fold's component rows and build both typed inputs."""

    # Only the optimizer fields the component rows do not already carry: the v1 export has
    # none of them, while the v2 development handoff already joins `position`, and merging a
    # column that is present on both sides would suffix it out of existence.
    wanted = [name for name in _ROSTER_FIELDS if name not in fold_rows.columns]
    joined = (
        fold_rows.merge(
            roster_rows.loc[:, ["player_id", *wanted]],
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
            # None on the frozen path, which is what keeps the locked season refused there.
            development_contract=development_contract,
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
    development_contract: str | None = None,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> dict[str, object]:
    """Measure the five differences over every eligible fold and return one document.

    Pure over its frames: the caller's tables are never mutated, and no file is read or
    written here. Folds that cannot be measured are recorded with the reason rather than
    dropped silently, and the residual pool's own sufficiency rule decides eligibility rather
    than a second copy of that rule living here.

    ``development_contract`` is the one way to measure a table that carries the locked season,
    and it names the Phase C contract those rows came from. ``conditional_residuals`` selects
    the declared candidate sampler; both default to the frozen v1 behaviour, which is
    unchanged down to the document's keys.
    """

    settings = ScenarioConfig() if config is None else config
    development = development_contract is not None
    if development and development_contract != DEVELOPMENT_OOF_CONTRACT_VERSION:
        raise FidelityBindingError(
            f"Unsupported Phase C development contract {development_contract!r}."
        )
    seasons = sorted({str(value) for value in oof["season"]})
    if LOCKED_HOLDOUT_SEASON in seasons and not development:
        raise SystemExit(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout. It is not read, listed or measured "
            "here; spending it is a three-owner decision under its own protocol."
        )
    if development:
        # The refusal above is replaced, not dropped: the rows may carry the locked season
        # only because the manifest beside them says they are that development export, and
        # only for the seasons it declares.
        if manifest.get("contract_version") != DEVELOPMENT_OOF_CONTRACT_VERSION:
            raise FidelityBindingError(
                "The Phase C manifest does not declare the development contract "
                f"{DEVELOPMENT_OOF_CONTRACT_VERSION!r}."
            )
        if manifest.get("development_only") is not True:
            raise FidelityBindingError(
                "The Phase C manifest does not declare itself development-only."
            )
        outside = sorted(set(seasons) - set(_development_seasons(manifest)))
        if outside:
            raise FidelityBindingError(
                f"The table carries seasons the manifest does not declare: {outside!r}."
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
    sampler_records: set[tuple[str, str, float | None, int | None]] = set()

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
        inputs, snapshot = _fold_inputs(
            current, roster_rows, manifest, target, development_contract
        )
        draw = sample_component_scenarios(  # type: ignore[arg-type]
            inputs,
            snapshot,
            pool,
            target,
            settings,
            conditional_residuals=conditional_residuals,
        )
        # The draw declares the sampler it used; the record reports that rather than the
        # setting this run asked for, so the document cannot name a sampler it did not draw on.
        diagnostics = draw.scenarios.diagnostics
        drawn_fraction = diagnostics.get("conditional_residual_fraction")
        drawn_minimum = diagnostics.get("conditional_residual_minimum_rows")
        sampler_records.add(
            (
                str(diagnostics["component_sampler_contract_version"]),
                str(diagnostics["residual_selection"]),
                None if drawn_fraction is None else float(drawn_fraction),  # type: ignore[arg-type]
                None if drawn_minimum is None else int(drawn_minimum),  # type: ignore[call-overload]
            )
        )
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

        LOGGER.info(
            "measured %s (%d/%d folds, pool %d rows)",
            fold_id,
            len(fold_records),
            len(fold_ids),
            len(pool),
        )
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

    if len(sampler_records) > 1:
        raise FidelityBindingError(
            f"The folds were drawn on more than one sampler: {sorted(sampler_records)!r}."
        )
    development_block: dict[str, object] = {}
    if development:
        if not sampler_records:
            # A record with no measured fold would name a sampler nothing was drawn on: a
            # claim about a draw that never happened.
            raise FidelityBindingError(
                "No fold could be measured, so there is no sampler to record."
            )
        # Every field here is what the draws themselves declared, not what this run asked for.
        version, selection, drawn_fraction, drawn_minimum = sorted(sampler_records)[0]
        development_block = {
            "development_only": True,
            "phase_c_contract": development_contract,
            "locked_holdout_read": LOCKED_HOLDOUT_SEASON in seasons,
            "sampler": {
                "contract_version": version,
                "residual_selection": selection,
                "conditional_residual_fraction": drawn_fraction,
                "conditional_residual_minimum_rows": drawn_minimum,
            },
        }
    return {
        "contract_version": (
            DEVELOPMENT_FIDELITY_CONTRACT_VERSION if development else FIDELITY_CONTRACT_VERSION
        ),
        "diagnostic_only": True,
        "promotes_anything": False,
        "registers_any_threshold": False,
        "observation_unit": OBSERVATION_UNIT,
        **development_block,
        "config": {
            "scenario_count": int(settings.scenario_count),
            "deterministic_seed": int(settings.deterministic_seed),
            "min_history_folds": int(settings.min_history_folds),
        },
        "population": {
            "development_seasons": (
                [str(value) for value in _development_seasons(manifest)]
                if development
                else list(DEVELOPMENT_SEASONS)
            ),
            "seasons_present": seasons,
            "locked_holdout_season": LOCKED_HOLDOUT_SEASON,
            "locked_holdout_rows_present": (
                int((table["season"].astype("string") == LOCKED_HOLDOUT_SEASON).sum())
                if development
                else 0
            ),
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


def provenance_block(
    manifest: Mapping[str, object],
    *,
    revision: str,
    dirty: bool,
    files: Mapping[str, tuple[str, str]],
    development: bool,
) -> dict[str, object]:
    """What produced this record: the code, the input files and, for v2, the reference.

    Public because the consumer's verification is written against exactly these fields, and a
    test that builds the block by hand would let the writer and the reader drift apart.
    """

    block: dict[str, object] = {
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "prereg_document": "docs/phase_d_component_fidelity_prereg.md",
        "oof_table": files["oof_table"][0],
        "oof_table_sha256": files["oof_table"][1],
        "roster": files["roster"][0],
        "roster_sha256": files["roster"][1],
        "manifest": files["manifest"][0],
        "manifest_sha256": files["manifest"][1],
        "manifest_table_sha256": str(manifest["table_sha256"]),
        "manifest_roster_sha256": str(manifest["roster_sha256"]),
        "manifest_locked_holdout_read": bool(manifest["locked_holdout_read"]),
        "model_version": str(manifest["model_version"]),
        "feature_contract_version": str(manifest["feature_contract_version"]),
    }
    if not development:
        return block
    weighting = manifest.get("weighting")
    block.update(
        {
            "development_method_document": "docs/phase_d_v2_development_method.md",
            "phase_c_contract": DEVELOPMENT_OOF_CONTRACT_VERSION,
            "phase_c_weighting": str(weighting["label"]) if isinstance(weighting, dict) else None,
            "phase_c_producer_repository_commit": str(manifest["repository_commit"]),
            "target_contract_version": str(manifest["target_contract_version"]),
            "dataset_contract_version": str(manifest["dataset_contract_version"]),
            "pinned_by_arguments": True,
        }
    )
    return block


def _development_seasons(manifest: Mapping[str, object]) -> tuple[str, ...]:
    seasons = manifest.get("development_seasons")
    if not isinstance(seasons, list) or any(not isinstance(value, str) for value in seasons):
        raise FidelityBindingError("The Phase C manifest does not declare development_seasons.")
    return tuple(str(value) for value in seasons)


def _read_development_reference(
    arguments: argparse.Namespace, development: DevelopmentInputs
) -> tuple[pd.DataFrame, pd.DataFrame, Mapping[str, object]]:
    """Read the pinned equal-weight reference through the explicit development reader."""

    try:
        handoff = read_phase_c_component_handoff(
            arguments.oof_table,
            arguments.roster,
            arguments.manifest,
            development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        )
    except EvaluationValidationError as error:
        raise FidelityBindingError(f"Phase C development handoff refused: {error}") from error
    if (
        handoff.table_sha256 != development.table_sha256
        or handoff.roster_sha256 != development.roster_sha256
        or handoff.manifest_sha256 != development.manifest_sha256
    ):
        raise FidelityBindingError(
            "Phase C development handoff digests differ from the pinned reference "
            f"(table {handoff.table_sha256[:12]}..., roster {handoff.roster_sha256[:12]}..., "
            f"manifest {handoff.manifest_sha256[:12]}...)."
        )
    if handoff.weighting != EQUAL_WEIGHTING or handoff.model_version != COMPONENT_MODEL_VERSION:
        raise FidelityBindingError(
            "The development fidelity reading is bound to the equal-weight reference; got "
            f"weighting {handoff.weighting!r} and model {handoff.model_version!r}."
        )
    manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise FidelityBindingError("The Phase C manifest must be a JSON object.")
    return handoff.rows, handoff.roster, manifest


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    arguments = _parse_arguments()
    try:
        development = _development_from_arguments(arguments)
    except (FidelityBindingError, ScenarioValidationError) as error:
        LOGGER.error("Refused: %s", error)
        return 1

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

    if development is None:
        manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
        oof = pd.read_csv(arguments.oof_table, dtype={"team_id": "string", "position": "string"})
        roster = pd.read_csv(arguments.roster, dtype={"team_id": "string", "position": "string"})
    else:
        try:
            oof, roster, manifest = _read_development_reference(arguments, development)
        except FidelityBindingError as error:
            LOGGER.error("Refused: %s", error)
            return 1

    document = measure_fidelity(
        oof,
        roster,
        manifest,
        development_contract=None if development is None else DEVELOPMENT_OOF_CONTRACT_VERSION,
        conditional_residuals=None if development is None else development.conditional_residuals,
    )
    # ``generated_at_utc`` rather than a synonym: it is the one field the repository's own
    # ``replay_identity`` strips, so an identical re-run at the same commit is recognised as a
    # replay instead of colliding on the clock alone. A field this writer cannot see would
    # make create-once behave as create-only.
    document["generated_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    document["provenance"] = provenance_block(
        manifest,
        revision=revision,
        dirty=dirty,
        files={
            "oof_table": (arguments.oof_table.name, _sha256(arguments.oof_table)),
            "roster": (arguments.roster.name, _sha256(arguments.roster)),
            "manifest": (arguments.manifest.name, _sha256(arguments.manifest)),
        },
        development=development is not None,
    )

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
