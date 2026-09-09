r"""Diagnose why the squad distribution's lower tail is thin.

    python -m scripts.run_tail_diagnostic \
        --residual-table    <path> \
        --residual-manifest <path> \
        --archive-root      <path>

Development diagnostic, not a measurement of a gate and not a promotion. It reads the
pre-registered scale levels, seasons and seeds from
``docs/phase2_tail_diagnostic_prereg.md``'s constants in
``squadopt.experiments.tail_diagnostic``; **the command line carries paths and nothing
else**, so no arm of this study can be chosen from a shell.

The recorded Phase 2 verdict is not touched. Nothing here publishes a probability, a
percentage or a ``P(...)`` to any member-facing surface, and the locked 2025-26 season
never reaches a loader.
"""

import argparse
import subprocess
import sys
import warnings
from collections import Counter
from collections.abc import Callable
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
from scripts.measure_in_season_blend import _Inputs

from squadopt.backtest.splits import DecisionPoint, walk_forward_decision_points
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.experiments.shadow_squad_calibration import (
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
    SquadShadowConfig,
    SquadShadowError,
    build_squad_folds,
    declared_parameters,
    frozen_history_fold_ids,
    load_panel_without_the_holdout,
    loaded_seasons,
)
from squadopt.experiments.tail_diagnostic import (
    CONTROL_SCALE,
    FROZEN_SHIFT_POINTS,
    SCALE_LEVELS,
    SCREENING_SEASONS,
    SENSITIVITY_SEASON,
    STUDY_SEASONS,
    TAIL_DIAGNOSTIC_CONTRACT_VERSION,
    VALIDATION_SEASON,
    ArmReading,
    FoldFacts,
    captain_description,
    classify,
    common_shock_description,
    control_replay,
    eligible_development_folds,
    read_fold_at_every_scale,
    refuse_the_holdout,
    summarise_arm,
)
from squadopt.prediction import PredictionProvenance
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
)

MODEL_NAME: Final = "squadopt-deterministic-baseline"
CUTOFF_FOLD_ID: Final = "2023-24-gw38"
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase2_tail_diagnostic.json"


def _tree_dirty_ignoring(path: Path) -> bool:
    """Is anything but this study's own artifact modified?"""

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return True
    try:
        relative = path.resolve().relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        relative = None
    return any(
        entry and entry != relative
        for entry in (line[3:].strip().strip('"') for line in status.splitlines())
    )


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _projection_provider(
    panel: pd.DataFrame, decisions: tuple[DecisionPoint, ...]
) -> Callable[[DecisionPoint], pd.DataFrame]:
    inputs = _Inputs(panel, decisions)
    settings = InSeasonBlendConfig()

    def provide(decision: DecisionPoint) -> pd.DataFrame:
        return inputs.blend(decision, settings)

    return provide


def _recorded_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    counted = Counter(f"{type(item.message).__name__}: {item.message}" for item in caught)
    return [
        text if count == 1 else f"{text} (raised {count} times)"
        for text, count in sorted(counted.items())
    ]


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

    # The development chain, built exactly as Phase 2 builds it, minus its burn-in; and
    # the frozen evaluation season, against the history frozen at the end of 2023-24.
    development = eligible_development_folds(
        build_squad_folds(
            panel, residuals, provide, seasons=(*SCREENING_SEASONS, VALIDATION_SEASON)
        ),
        config,
    )
    sensitivity = build_squad_folds(panel, residuals, provide, seasons=(SENSITIVITY_SEASON,))
    frozen_history = frozen_history_fold_ids(residuals)

    readings: list[ArmReading] = []
    facts: list[FoldFacts] = []
    for fold in development:
        arm, fact = read_fold_at_every_scale(
            fold, residuals, fold.prior_fold_ids, provenance, config
        )
        readings.extend(arm)
        facts.append(fact)
    for fold in sensitivity:
        arm, fact = read_fold_at_every_scale(fold, residuals, frozen_history, provenance, config)
        readings.extend(arm)
        facts.append(fact)

    seasons: dict[str, dict[str, object]] = {}
    for season in STUDY_SEASONS:
        role = (
            "screening"
            if season in SCREENING_SEASONS
            else "validation"
            if season == VALIDATION_SEASON
            else "labelled development sensitivity"
        )
        arms: dict[str, object] = {"role": role}
        for scale in SCALE_LEVELS:
            selected = [r for r in readings if r.season == season and r.scale == scale]
            if selected:
                arms[f"{scale:.2f}"] = summarise_arm(selected)
        seasons[season] = arms

    validation = {
        float(scale): summary
        for scale in SCALE_LEVELS
        if isinstance(summary := seasons[VALIDATION_SEASON].get(f"{scale:.2f}"), dict)
    }
    classification, eligible = classify(validation)  # type: ignore[arg-type]
    control = seasons[SENSITIVITY_SEASON].get(f"{CONTROL_SCALE:.2f}")
    replay = control_replay(control) if isinstance(control, dict) else {"reproduced": False}

    return {
        "seasons": seasons,
        "classification": classification,
        "eligible_scales": list(eligible),
        "control_replay": replay,
        "common_shock": common_shock_description(facts, residuals),
        "captain": captain_description(facts),
        "panel_seasons_loaded": list(loaded_seasons(panel)),
        "residual_source": {
            "export_label": manifest.export_label,
            "table_sha256": manifest.table_sha256,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
            "cutoff_fold_id": CUTOFF_FOLD_ID,
        },
        "panel_rows": len(panel),
        "fold_count": len(facts),
    }


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)

    print(f"Study       {TAIL_DIAGNOSTIC_CONTRACT_VERSION}")
    print(f"Scales      {', '.join(f'{scale:.2f}' for scale in SCALE_LEVELS)}")
    print(f"Screen      {', '.join(SCREENING_SEASONS)}   Validate  {VALIDATION_SEASON}")
    print(f"Sensitivity {SENSITIVITY_SEASON} (seen before this study; cannot decide)")
    print(f"Shift       {FROZEN_SHIFT_POINTS} (frozen, not refitted)")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")

    if dirty:
        print(
            "\nRefused: the working tree carries changes this study did not write, so its "
            "numbers could not be reproduced from the commit it would record. Nothing was "
            "measured and nothing was written."
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

    replay = measured["control_replay"]
    assert isinstance(replay, dict)
    if not replay.get("reproduced"):
        print(
            "\nRefused: the control arm does not reproduce the recorded S1/S2 within the "
            f"declared tolerance. {replay!r}. A comparison whose baseline has drifted is "
            "not a comparison; nothing was written."
        )
        return 1

    metadata = artifact_metadata(
        panel_rows=int(measured.pop("panel_rows")),  # type: ignore[arg-type]
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=measured["panel_seasons_loaded"],  # type: ignore[arg-type]
    )
    document: dict[str, object] = {
        "contract_version": TAIL_DIAGNOSTIC_CONTRACT_VERSION,
        "created_utc": metadata["created_utc"],
        "measurement_only": True,
        "promotes_nothing": True,
        "locked_holdout_accessed": False,
        "study": "why the squad distribution's lower tail is thin",
        "scale_levels": [float(scale) for scale in SCALE_LEVELS],
        "control_scale": float(CONTROL_SCALE),
        "frozen_shift_points": FROZEN_SHIFT_POINTS,
        "hypotheses": {
            "H1": "global underdispersion — decides the classification",
            "H2": "common gameweek shock — descriptive only",
            "H3": "captain amplification — descriptive only",
        },
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

    print(f"\nFolds       {measured['fold_count']}")
    for season in STUDY_SEASONS:
        arms = measured["seasons"][season]  # type: ignore[index]
        assert isinstance(arms, dict)
        print(f"  {season} ({arms['role']})")
        for scale in SCALE_LEVELS:
            summary = arms.get(f"{scale:.2f}")
            if not isinstance(summary, dict):
                continue
            print(
                f"    scale {scale:.2f}  folds {int(summary['fold_count']):>3}  "
                f"mean PIT {summary['mean_probability_integral_transform']:.4f}  "
                f"below-q10 {int(summary['below_lower_quantile_folds']):>2} "
                f"({summary['below_lower_quantile_rate']:.4f})  "
                f"tail width {summary['mean_tail_width']:.2f}"
            )
    print(f"\nClass       {measured['classification']}")
    print(f"Eligible    {measured['eligible_scales']}")
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
