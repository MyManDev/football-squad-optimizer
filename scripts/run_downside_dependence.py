"""Run the pre-registered selected-XI downside-dependence diagnostic.

The command line carries paths only. Scientific choices are frozen in
``docs/phase2_downside_dependence_prereg.md`` and
``squadopt.experiments.downside_dependence``. This development reuse promotes nothing and
never reads the locked holdout.
"""

import argparse
import hashlib
import sys
import warnings
from collections.abc import Mapping, Sequence
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
from scripts.run_tail_diagnostic import (
    MODEL_NAME,
    _projection_provider,
    _recorded_warnings,
    _tree_dirty_ignoring,
)

from squadopt.backtest.splits import walk_forward_decision_points
from squadopt.experiments.downside_dependence import (
    DOWNSIDE_DEPENDENCE_CONTRACT_VERSION,
    DOWNSIDE_QUANTILE,
    DownsideReading,
    classify,
    read_fold,
    summarise,
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
    build_squad_folds,
    declared_parameters,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
    loaded_seasons,
)
from squadopt.experiments.tail_diagnostic import (
    FROZEN_SHIFT_POINTS,
    RECORDED_BELOW_QUANTILE_RATE,
    RECORDED_MEAN_PIT,
    REPLAY_TOLERANCE,
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

SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    REPOSITORY_ROOT / "docs" / "phase2_tail_diagnostic.json",
    REPOSITORY_ROOT / "docs" / "phase2_captain_attribution.json",
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_downside_dependence.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _control_replay(readings: Sequence[DownsideReading]) -> dict[str, float | bool]:
    selected = [reading for reading in readings if reading.season == SENSITIVITY_SEASON]
    _require(bool(selected), f"the replay population {SENSITIVITY_SEASON} is empty.")
    pit = float(sum(reading.full_score_pit for reading in selected) / len(selected))
    tail = float(sum(reading.full_score_below_q10 for reading in selected) / len(selected))
    return {
        "recorded_mean_probability_integral_transform": RECORDED_MEAN_PIT,
        "measured_mean_probability_integral_transform": pit,
        "recorded_below_lower_quantile_rate": RECORDED_BELOW_QUANTILE_RATE,
        "measured_below_lower_quantile_rate": tail,
        "tolerance": REPLAY_TOLERANCE,
        "reproduced": bool(
            abs(pit - RECORDED_MEAN_PIT) <= REPLAY_TOLERANCE
            and abs(tail - RECORDED_BELOW_QUANTILE_RATE) <= REPLAY_TOLERANCE
        ),
    }


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
    decisions = tuple(
        decision
        for season in STUDY_SEASONS
        for decision in walk_forward_decision_points(
            panel, seasons=(season,), min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON
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
    readings = [
        read_fold(fold, residuals, fold.prior_fold_ids, provenance, config) for fold in development
    ]
    readings.extend(
        read_fold(fold, residuals, frozen_history, provenance, config) for fold in sensitivity
    )
    _require(
        len({reading.fold_id for reading in readings}) == len(readings),
        "the downside population repeats a fold.",
    )

    replay = _control_replay(readings)
    _require(
        bool(replay["reproduced"]),
        "the full-score control does not reproduce the recorded Phase 2 result; this "
        "diagnostic refuses to explain a moved baseline.",
    )
    by_season = {
        season: summarise(selected)
        for season in STUDY_SEASONS
        if (selected := [reading for reading in readings if reading.season == season])
    }
    validation = by_season.get(VALIDATION_SEASON)
    _require(isinstance(validation, Mapping), "the declared validation population is absent.")
    tail_failures = [reading for reading in readings if reading.full_score_below_q10]
    elsewhere = [reading for reading in readings if not reading.full_score_below_q10]
    return {
        "classification": classify(validation),
        "classification_population": VALIDATION_SEASON,
        "control_replay": replay,
        "season_sensitivity": by_season,
        "pooled_development": summarise(readings),
        "full_score_tail_split": {
            "below_q10": summarise(tail_failures) if tail_failures else None,
            "elsewhere": summarise(elsewhere) if elsewhere else None,
        },
        "fold_universe": {
            "total_folds": len(readings),
            "seasons": list(STUDY_SEASONS),
            "folds_by_season": {
                season: sum(reading.season == season for reading in readings)
                for season in STUDY_SEASONS
            },
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
    print(f"Study       {DOWNSIDE_DEPENDENCE_CONTRACT_VERSION}")
    print(f"Threshold   player marginal q{int(DOWNSIDE_QUANTILE * 100)}")
    print(f"Validate    {VALIDATION_SEASON}   Sensitivity {SENSITIVITY_SEASON}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")
    if dirty:
        print("\nRefused: the working tree carries changes this study did not write.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured = _measure(arguments, config)
        except (SquadShadowError, ShadowReportError, ResidualSourceError, OSError) as error:
            print(f"\nRefused: {error}")
            return 1
    completed = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=int(measured.pop("panel_rows")),  # type: ignore[arg-type]
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=measured["panel_seasons_loaded"],  # type: ignore[arg-type]
    )
    document: dict[str, object] = {
        "contract_version": DOWNSIDE_DEPENDENCE_CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "selected-XI simultaneous downside against canonical scenarios",
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
            "downside_quantile": str(DOWNSIDE_QUANTILE),
        },
        "environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"\nRefused: {error}")
        return 1
    validation = measured["season_sensitivity"][VALIDATION_SEASON]  # type: ignore[index]
    print(f"\nFolds       {measured['fold_universe']['total_folds']}")  # type: ignore[index]
    print(f"Class       {measured['classification']}")
    print(
        f"Marginal    gap {validation['marginal_downside_rate']['gap']['mean']:+.4f}"  # type: ignore[index]
    )
    print(
        f"Joint       gap {validation['all_pair_joint_downside_rate']['gap']['mean']:+.4f}"  # type: ignore[index]
    )
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
