"""Run the pre-registered projection-conditional return-shape diagnostic."""

import argparse
import hashlib
import json
import sys
import warnings
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, cast

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
from squadopt.experiments.conditional_marginal_shape import attach_history_minutes
from squadopt.experiments.downside_dependence import DownsideReading, read_fold_with_starters
from squadopt.experiments.marginal_downside_sources import enrich_starters
from squadopt.experiments.projection_conditional_returns import (
    ARMS,
    CONTRACT_VERSION,
    EXPECTED_POINTS_EDGES,
    MIN_DIRECT_COVERAGE,
    MIN_GROUP_PLAYERS,
    MIN_GROUP_ROWS,
    MIN_SOURCE_OBSERVATIONS,
    RECENT_FOLDS,
    RETURN_STATES,
    classify,
    compare_fold,
    summarise,
)
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_calibration import BOOTSTRAP_SEED, CONFIDENCE_LEVEL
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    SquadShadowConfig,
    SquadShadowError,
    _require,
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

PRIOR_ARTIFACT: Final = REPOSITORY_ROOT / "docs" / "phase2_conditional_marginal_shape.json"
SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    REPOSITORY_ROOT / "docs" / "phase2_downside_dependence.json",
    REPOSITORY_ROOT / "docs" / "phase2_marginal_downside_sources.json",
    PRIOR_ARTIFACT,
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_projection_conditional_returns.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _prior_rows() -> dict[str, int]:
    document = json.loads(PRIOR_ARTIFACT.read_text(encoding="utf-8"))
    seasons = document.get("season_sensitivity")
    _require(isinstance(seasons, Mapping), "the prior conditional-shape artifact has no seasons.")
    rows: dict[str, int] = {}
    for season in STUDY_SEASONS:
        summary = seasons.get(season)
        _require(isinstance(summary, Mapping), f"the prior artifact has no {season} summary.")
        arms = summary.get("arms")
        _require(isinstance(arms, Mapping), f"the prior artifact has no {season} arms.")
        canonical = arms.get("canonical")
        _require(
            isinstance(canonical, Mapping), f"the prior artifact has no {season} canonical arm."
        )
        value = canonical.get("starter_rows")
        _require(type(value) is int, f"the prior artifact has no {season} starter count.")
        rows[season] = value
    return rows


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
        comparisons.append(compare_fold(enriched, history_with_minutes, history_ids))
    _require(
        len({reading.fold_id for reading in readings}) == len(readings),
        "the projection-conditional population repeats a fold.",
    )
    replay = _control_replay(readings)
    _require(
        bool(replay["reproduced"]),
        "the full-score control does not reproduce the recorded Phase 2 result.",
    )
    rows = pd.concat(comparisons, ignore_index=True)
    prior_rows = _prior_rows()
    by_season: dict[str, dict[str, object]] = {}
    for season in STUDY_SEASONS:
        season_rows = rows.loc[rows["season"].astype(str).eq(season)]
        target_rows = len(season_rows.loc[season_rows["arm"].eq(ARMS[0])])
        _require(
            target_rows == prior_rows[season],
            f"the {season} completed-appearance population does not reproduce the prior artifact.",
        )
        by_season[season] = summarise(season_rows)
    validation = by_season[VALIDATION_SEASON]
    return {
        "classification": classify(validation),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "season_sensitivity": by_season,
        "pooled": summarise(rows),
        "fold_universe": {
            "total_folds": len(readings),
            "target_rows_per_arm": len(rows) // len(ARMS),
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
    print(f"Study       {CONTRACT_VERSION}")
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
        panel_rows=cast(int, measured.pop("panel_rows")),
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=measured["panel_seasons_loaded"],  # type: ignore[arg-type]
    )
    document: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "selected-XI completed-appearance projection-conditional returns",
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
            **{
                str(key): value
                for key, value in cast(Mapping[object, object], metadata["provenance"]).items()
            },
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            **declared_parameters(config, shift_points=FROZEN_SHIFT_POINTS),
            "return_states": list(RETURN_STATES),
            "expected_points_edges": list(EXPECTED_POINTS_EDGES),
            "minimum_source_observations": MIN_SOURCE_OBSERVATIONS,
            "recent_history_folds": RECENT_FOLDS,
            "minimum_group_rows": MIN_GROUP_ROWS,
            "minimum_group_players": MIN_GROUP_PLAYERS,
            "minimum_direct_cell_coverage": MIN_DIRECT_COVERAGE,
            "brier_definition": "sum_squared_four_class_error_fold_mean",
            "empirical_quantile": "0.25_linear_strict_below",
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_confidence_level": CONFIDENCE_LEVEL,
            "bootstrap_seed": BOOTSTRAP_SEED,
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
