r"""Attribute the squad tail failure to the captain's second copy, or fail to.

    python -m scripts.run_captain_attribution \
        --residual-table    <path> \
        --residual-manifest <path> \
        --archive-root      <path>

Development diagnostic, re-reading data that has already been seen. **Not a promotion
gate and not independent confirmation.** Every scientific choice — the arms, the seasons,
the bands, the location conventions and the classification rule — lives in
``docs/phase2_captain_tail_attribution_prereg.md`` and its constants; the command line
carries paths and nothing else. Nothing is reoptimized, no probability reaches any
member-facing surface, and the locked 2025-26 season never reaches a loader.
"""

import argparse
import hashlib
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
from scripts.run_tail_diagnostic import (
    MODEL_NAME,
    _projection_provider,
    _recorded_warnings,
    _tree_dirty_ignoring,
)

from squadopt.backtest.splits import walk_forward_decision_points
from squadopt.experiments.captain_attribution import (
    CAPTAIN_ATTRIBUTION_CONTRACT_VERSION,
    FULL,
    CaptainReading,
    captain_component,
    classify,
    read_fold,
    refuse_unexpected_folds,
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

#: The recorded results this study explains. Their digests are carried into the artifact
#: so a reader can tell which measurements the attribution was computed against.
SOURCE_ARTIFACTS: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json",
    REPOSITORY_ROOT / "docs" / "phase2_tail_diagnostic.json",
)
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_captain_attribution.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _digests() -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in SOURCE_ARTIFACTS}


def _measure(arguments: argparse.Namespace, config: SquadShadowConfig) -> dict[str, object]:
    """Every number this study computes, in one call the warning recorder can wrap."""

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

    # The same fold universe the tail diagnostic read: the development chain minus its
    # burn-in, and the frozen evaluation season against the frozen history.
    development = eligible_development_folds(
        build_squad_folds(
            panel, residuals, provide, seasons=(*SCREENING_SEASONS, VALIDATION_SEASON)
        ),
        config,
    )
    sensitivity = build_squad_folds(panel, residuals, provide, seasons=(SENSITIVITY_SEASON,))
    frozen_history = frozen_history_fold_ids(residuals)

    readings: list[CaptainReading] = [
        read_fold(fold, residuals, fold.prior_fold_ids, provenance, config) for fold in development
    ]
    readings.extend(
        read_fold(fold, residuals, frozen_history, provenance, config) for fold in sensitivity
    )
    refuse_unexpected_folds(readings)

    classification_population = [
        reading for reading in readings if reading.season == SENSITIVITY_SEASON
    ]
    _require(
        bool(classification_population),
        f"the classification population {SENSITIVITY_SEASON} carries no folds; the "
        "attribution has nothing to classify.",
    )
    arms = summarise(classification_population)
    _require_full_arm_reproduces_the_record(arms[FULL])
    classification, reasons = classify(arms)

    return {
        "classification": classification,
        "classification_reasons": list(reasons),
        "classification_population": SENSITIVITY_SEASON,
        "arms": arms,
        "captain_component": captain_component(readings),
        "season_sensitivity": {
            season: {
                "arms": summarise(selected),
                "captain_component": captain_component(selected),
            }
            for season in STUDY_SEASONS
            if (selected := [reading for reading in readings if reading.season == season])
        },
        "fold_universe": {
            "total_folds": len(readings),
            "seasons": list(STUDY_SEASONS),
            "folds_by_season": {
                season: sum(1 for reading in readings if reading.season == season)
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


def _require_full_arm_reproduces_the_record(full: Mapping[str, float | bool]) -> None:
    """The full arm is the frozen instrument, so it has to return the recorded numbers.

    An attribution computed against a full score that no longer matches the measurement
    it explains is an attribution of something else.
    """

    pit = float(full["mean_probability_integral_transform"])
    rate = float(full["below_lower_quantile_rate"])
    _require(
        abs(pit - RECORDED_MEAN_PIT) <= REPLAY_TOLERANCE
        and abs(rate - RECORDED_BELOW_QUANTILE_RATE) <= REPLAY_TOLERANCE,
        f"the full arm reads mean PIT {pit!r} and below-q10 rate {rate!r} on "
        f"{SENSITIVITY_SEASON}, against the recorded {RECORDED_MEAN_PIT!r} and "
        f"{RECORDED_BELOW_QUANTILE_RATE!r}. This study explains the recorded result, "
        "so it stops rather than attributing a different one.",
    )


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)

    print(f"Study       {CAPTAIN_ATTRIBUTION_CONTRACT_VERSION}")
    print(f"Classify on {SENSITIVITY_SEASON}   Sensitivity {', '.join(STUDY_SEASONS)}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")
    if dirty:
        print(
            "\nRefused: the working tree carries changes this study did not write, so its "
            "numbers could not be reproduced from the commit it would record."
        )
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
        "contract_version": CAPTAIN_ATTRIBUTION_CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "study": "is the squad tail failure the captain's second copy",
        "measurement_only": True,
        "promotion_eligible": False,
        "development_reuse_exploratory": True,
        "independent_confirmation": False,
        "locked_holdout_accessed": False,
        "source_artifact_digests": _digests(),
        "frozen_shift_points": FROZEN_SHIFT_POINTS,
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
        },
        "environment": metadata["environment"],
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"\nRefused: {error}")
        return 1

    arms = measured["arms"]
    assert isinstance(arms, dict)
    print(f"\nFolds       {measured['fold_universe']['total_folds']}")  # type: ignore[index]
    for name, gates in arms.items():
        print(
            f"  {name:34} PIT {gates['mean_probability_integral_transform']:.4f}  "
            f"q10 {int(gates['below_lower_quantile_folds']):>2}/"
            f"{int(gates['fold_count'])} = {gates['below_lower_quantile_rate']:.4f}  "
            f"S1 {'in ' if gates['s1_within_band'] else 'OUT'}  "
            f"S2 {'in ' if gates['s2_within_band'] else 'OUT'}"
        )
    print(f"\nClass       {measured['classification']}")
    for reason in measured["classification_reasons"]:  # type: ignore[union-attr]
        print(f"Reason      {reason}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
