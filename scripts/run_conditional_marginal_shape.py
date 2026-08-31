"""Run the pre-registered conditional marginal-shape diagnostic."""

import argparse
import hashlib
import json
import sys
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    artifact_metadata,
)
from scripts.run_downside_dependence import _control_replay
from scripts.run_tail_diagnostic import (
    MODEL_NAME,
    _projection_provider,
    _recorded_warnings,
    _tree_dirty_ignoring,
)

from squadopt.backtest.splits import walk_forward_decision_points
from squadopt.experiments.conditional_marginal_shape import (
    CONDITIONAL_SHAPE_CONTRACT_VERSION,
    attach_history_minutes,
    classify,
    compare_fold,
    reconcile_completed_canonical,
    summarise,
)
from squadopt.experiments.downside_dependence import (
    DownsideReading,
    read_fold_with_starters,
)
from squadopt.experiments.marginal_downside_sources import (
    FULL_APPEARANCE,
    enrich_starters,
)
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    SquadShadowConfig,
    SquadShadowError,
    _require,
    _scenario_config,
    build_squad_folds,
    declared_parameters,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
    loaded_seasons,
)
from squadopt.experiments.tail_diagnostic import (
    FROZEN_SHIFT_POINTS,
    SCREENING_SEASONS,
    SENSITIVITY_SEASON,
    STUDY_SEASONS,
    VALIDATION_SEASON,
    eligible_development_folds,
    refuse_the_holdout,
)
from squadopt.prediction import PredictionProvenance
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)

PRIOR_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_marginal_downside_sources.json"
SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    REPOSITORY_ROOT / "docs" / "phase2_downside_dependence.json",
    PRIOR_ARTIFACT,
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_conditional_marginal_shape.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _prior_buckets() -> dict[str, Mapping[str, object]]:
    document = json.loads(PRIOR_ARTIFACT.read_text(encoding="utf-8"))
    seasons = document.get("season_sensitivity")
    _require(isinstance(seasons, dict), "the prior marginal-source artifact has no seasons.")
    result: dict[str, Mapping[str, object]] = {}
    for season in STUDY_SEASONS:
        season_summary = seasons.get(season)
        _require(isinstance(season_summary, dict), f"prior artifact has no {season} summary.")
        buckets = season_summary.get("minute_buckets")
        _require(isinstance(buckets, dict), f"prior artifact has no {season} minute buckets.")
        bucket = buckets.get(FULL_APPEARANCE)
        _require(isinstance(bucket, dict), f"prior artifact has no {season} 60+ bucket.")
        result[season] = bucket
    return result


def _measure(arguments: argparse.Namespace, config: SquadShadowConfig) -> dict[str, object]:
    refuse_the_holdout(STUDY_SEASONS)
    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=IN_SEASON_MODEL_VERSION,
        expect_feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
    )
    panel = load_panel_without_the_holdout(arguments.archive_root)
    residuals = pd.read_csv(arguments.residual_table)
    history_with_minutes = attach_history_minutes(residuals, panel)
    decisions = tuple(
        decision
        for season in STUDY_SEASONS
        for decision in walk_forward_decision_points(
            panel,
            seasons=(season,),
            min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
        )
    )
    provide = _projection_provider(panel, decisions)
    provenance = PredictionProvenance(
        model_name=MODEL_NAME,
        model_version=IN_SEASON_MODEL_VERSION,
        feature_contract_version=IN_SEASON_FEATURE_CONTRACT_VERSION,
        training_cutoff="pre_fold_projection",
        training_data_fingerprint=manifest.table_sha256,
    )
    development = eligible_development_folds(
        build_squad_folds(
            panel, residuals, provide, seasons=(*SCREENING_SEASONS, VALIDATION_SEASON)
        ),
        config,
    )
    sensitivity = build_squad_folds(panel, residuals, provide, seasons=(SENSITIVITY_SEASON,))
    frozen_history = frozen_history_fold_ids(residuals)
    min_player_observations = _scenario_config(config).min_player_observations

    readings: list[DownsideReading] = []
    comparisons: list[pd.DataFrame] = []
    for fold, history_ids in (
        *((fold, fold.prior_fold_ids) for fold in development),
        *((fold, frozen_history) for fold in sensitivity),
    ):
        reading, starters = read_fold_with_starters(
            fold, residuals, history_ids, provenance, config
        )
        enriched = enrich_starters(starters, panel, residuals, history_ids)
        readings.append(reading)
        comparisons.append(
            compare_fold(
                enriched,
                history_with_minutes,
                history_ids,
                min_player_observations=min_player_observations,
            )
        )
    _require(
        len({reading.fold_id for reading in readings}) == len(readings),
        "the conditional marginal population repeats a fold.",
    )
    replay = _control_replay(readings)
    _require(
        bool(replay["reproduced"]),
        "the full-score control does not reproduce the recorded Phase 2 result.",
    )
    rows = pd.concat(comparisons, ignore_index=True)
    prior = _prior_buckets()
    by_season: dict[str, dict[str, object]] = {}
    for season in STUDY_SEASONS:
        summary = summarise(rows.loc[rows["season"].astype(str).eq(season)])
        reconcile_completed_canonical(summary, prior[season])
        by_season[season] = summary
    validation = by_season[VALIDATION_SEASON]
    return {
        "classification": classify(validation),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "season_sensitivity": by_season,
        "pooled": summarise(rows),
        "fold_universe": {
            "total_folds": len(readings),
            "completed_starter_rows_per_arm": len(rows) // 3,
            "seasons": list(STUDY_SEASONS),
        },
        "panel_seasons_loaded": list(loaded_seasons(panel)),
        "residual_source": {
            "export_label": manifest.export_label,
            "table_sha256": manifest.table_sha256,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
        },
        "panel_rows": len(panel),
    }


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)
    print(f"Study       {CONDITIONAL_SHAPE_CONTRACT_VERSION}")
    print(f"Validate    {VALIDATION_SEASON}   Sensitivity {SENSITIVITY_SEASON}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")
    if dirty:
        print("\nRefused: the working tree carries changes this study did not write.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured = _measure(arguments, config)
        except (
            SquadShadowError,
            ShadowReportError,
            ResidualSourceError,
            OSError,
            ValueError,
        ) as error:
            print(f"\nRefused: {error}")
            return 1
    completed = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=int(measured.pop("panel_rows")),  # type: ignore[arg-type]
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=measured["panel_seasons_loaded"],  # type: ignore[arg-type]
    )
    document: dict[str, object] = {
        "contract_version": CONDITIONAL_SHAPE_CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "selected-XI completed-appearance marginal shape",
        "measurement_only": True,
        "promotion_eligible": False,
        "development_reuse_exploratory": True,
        "independent_confirmation": False,
        "locked_holdout_accessed": False,
        "source_artifact_digests": _digests(),
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "deterministic_seed": config.scenario_seed,
            "warnings": _recorded_warnings(caught),
        },
        "provenance": {
            **{str(key): value for key, value in dict(metadata["provenance"]).items()},  # type: ignore[arg-type]
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            **declared_parameters(config, shift_points=FROZEN_SHIFT_POINTS),
            "empirical_quantile": "0.25_linear_strict_below",
        },
        "environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"\nRefused: {error}")
        return 1
    print(f"\nFolds       {measured['fold_universe']['total_folds']}")  # type: ignore[index]
    print(f"Class       {measured['classification']}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
