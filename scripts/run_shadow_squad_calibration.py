r"""Run the whole Phase 2 protocol: P1 read from its record, S1 and S2 measured here.

    python -m scripts.run_shadow_squad_calibration \
        --residual-table    artifacts/residuals/in_season_residuals.csv \
        --residual-manifest artifacts/residuals/in_season_residuals.manifest.json

Internal measurement only. The result is a ``shadow_calibration_report_v2`` document
carrying the full protocol's verdict; nothing it can say publishes a probability, a
percentage or a ``P(...)`` to any member-facing surface, and the writer refuses a
destination under ``web/public``.

**There is nothing to choose here but where the inputs are.** Every control this
protocol runs under is pre-registered — the two squad-gate amendments fix the squad
weight, the decision universe, the residual history depth, the three generator
shrinkage knobs, the scenario count and seed, the quantile, the bands and the
bootstrap — so the command line carries paths and nothing else. A flag that could
change a number would be a number chosen after the fact.

P1 is not re-measured. It is merged from the recorded player-level artifact, and only
after every field of that artifact's residual provenance has been matched against the
export this run is bound to.

The run is create-once and atomic: an identical replay is accepted, different content
at an occupied path is refused rather than overwritten.
"""

import argparse
import subprocess
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, _git_revision
from scripts.measure_in_season_blend import _Inputs

from squadopt.backtest.splits import DecisionPoint, walk_forward_decision_points
from squadopt.experiments.residual_manifest import load_residual_source_manifest
from squadopt.experiments.shadow_report import (
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowResidualSource,
    write_shadow_report_once,
)
from squadopt.experiments.shadow_squad_calibration import (
    EVALUATION_SEASON,
    FIT_SEASONS,
    SQUAD_SHADOW_CONTRACT_VERSION,
    FrozenShift,
    PlayerEvidence,
    SquadFoldReading,
    SquadShadowConfig,
    SquadShadowError,
    bootstrap_diagnostics,
    build_squad_folds,
    combine_full_protocol,
    declared_parameters,
    evaluate_squad_gates,
    fit_frozen_shift,
    load_bound_player_report,
    load_panel_without_the_holdout,
)
from squadopt.prediction import PredictionProvenance
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
    InSeasonBlendConfig,
)

#: The model this protocol calibrates, read from the prediction package rather than
#: written as a literal: a run that could point at another model's residuals is what
#: the #45 rule forbids.
MODEL_NAME: Final = "squadopt-deterministic-baseline"
MODEL_VERSION: Final = IN_SEASON_MODEL_VERSION
FEATURE_CONTRACT_VERSION: Final = IN_SEASON_FEATURE_CONTRACT_VERSION

DEFAULT_CUTOFF_FOLD_ID: Final = "2023-24-gw38"

#: The recorded player-level measurement this run merges. The corrected one: the
#: earlier artifact was superseded by the corrective amendment and describes a
#: different residual export.
DEFAULT_PLAYER_REPORT: Final = (
    REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season_corrected.json"
)

#: Its own file. The player-level runner's default path holds that runner's artifact;
#: sharing it would turn every first run into a conflict rather than a record.
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "shadow_calibration_squad.json"


def _tree_dirty_ignoring(path: Path) -> bool:
    """Is anything but this run's own artifact modified?"""

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        # Provenance is only honest when it is known; an unreadable tree is dirty.
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
    parser.add_argument("--cutoff-fold-id", default=DEFAULT_CUTOFF_FOLD_ID)
    parser.add_argument(
        "--player-report",
        type=Path,
        default=DEFAULT_PLAYER_REPORT,
        help="The recorded player-level measurement whose P1 gates this run merges. "
        "It must be bound to the same residual export, or the run refuses.",
    )
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _projection_provider(
    panel: pd.DataFrame, decisions: tuple[DecisionPoint, ...]
) -> Callable[[DecisionPoint], pd.DataFrame]:
    """The target model's own per-fold table, from the assembly the export uses."""

    inputs = _Inputs(panel, decisions)
    settings = InSeasonBlendConfig()

    def provide(decision: DecisionPoint) -> pd.DataFrame:
        return inputs.blend(decision, settings)

    return provide


@dataclass(frozen=True, slots=True)
class _Measurement:
    """Everything the computation produced, so the caller only has to record it."""

    player: PlayerEvidence
    gates: tuple[ShadowGateResult, ...]
    readings: tuple[SquadFoldReading, ...]
    shift: FrozenShift
    diagnostics: dict[str, float | None]
    provenance: dict[str, str]


def _measure(
    arguments: argparse.Namespace,
    config: SquadShadowConfig,
    residual_source: ShadowResidualSource,
    player: PlayerEvidence,
    *,
    revision: str,
    dirty: bool,
) -> _Measurement:
    """Every number this run computes, in one call.

    It is one function so that the caller can wrap the whole of it in the warning
    recorder. A warning raised while the scenarios are generated is a fact about the
    measurement; a recorder that only spans the metadata construction records nothing
    and leaves an artifact claiming there were no warnings.
    """

    panel = load_panel_without_the_holdout(arguments.archive_root)
    residuals = pd.read_csv(arguments.residual_table)

    fit_decisions = walk_forward_decision_points(
        panel, seasons=FIT_SEASONS, min_prior_gameweeks_in_season=1
    )
    evaluation_decisions = walk_forward_decision_points(
        panel, seasons=(EVALUATION_SEASON,), min_prior_gameweeks_in_season=1
    )
    provide = _projection_provider(panel, (*fit_decisions, *evaluation_decisions))
    provenance = PredictionProvenance(
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        training_cutoff="pre_fold_projection",
        # The residual export's digest: the scenarios and the decision are then bound
        # to one artifact, and a reader of the scenario snapshot can tell which.
        training_data_fingerprint=residual_source.table_sha256,
    )

    fit_folds = build_squad_folds(panel, residuals, provide, seasons=FIT_SEASONS)
    shift = fit_frozen_shift(fit_folds, residuals, provenance, config)
    evaluation_folds = build_squad_folds(panel, residuals, provide, seasons=(EVALUATION_SEASON,))
    gates, readings, diagnostics = evaluate_squad_gates(
        evaluation_folds, residuals, provenance, config, shift
    )
    return _Measurement(
        player=player,
        gates=gates,
        readings=readings,
        shift=shift,
        diagnostics=diagnostics,
        provenance={
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            "run_contract_version": SQUAD_SHADOW_CONTRACT_VERSION,
            # Clause 18: the shift's fit population, named rather than implied by the
            # season list, because min_history_folds drops the earliest eligible folds.
            "frozen_shift_points": repr(shift.shift_points),
            "shift_fit_folds": str(shift.fold_count),
            "shift_fit_first_fold": shift.first_fold_id,
            "shift_fit_last_fold": shift.last_fold_id,
            # Clause 24: every parameter of every configuration the run constructed,
            # read off the objects themselves rather than from a list kept by hand.
            **declared_parameters(config, shift_points=shift.shift_points),
        },
    )


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()

    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=MODEL_VERSION,
        expect_feature_contract_version=FEATURE_CONTRACT_VERSION,
    )
    residual_source = manifest.to_shadow_source(cutoff_fold_id=arguments.cutoff_fold_id)
    try:
        player = load_bound_player_report(arguments.player_report, residual_source, config)
    except SquadShadowError as error:
        # Before the panel, before the residual table: a mismatched record is a reason
        # not to start, not a reason to discard an hour of scenarios at the end.
        print(f"Refused: {error}")
        return 1

    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)

    print(f"Contract    {SQUAD_SHADOW_CONTRACT_VERSION}")
    print(f"Identity    {manifest.model_name} / {manifest.model_version}")
    print(f"Residuals   {manifest.table_sha256[:16]}... ({manifest.row_count} rows)")
    print(f"Player P1   {arguments.player_report.name} ({len(player.gates)} gates merged)")
    print(f"Fit         {', '.join(FIT_SEASONS)}   Frozen evaluation  {EVALUATION_SEASON}")
    print(f"Scenarios   {config.scenario_count} at seed {config.scenario_seed}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        measurement = _measure(
            arguments, config, residual_source, player, revision=revision, dirty=dirty
        )
    completed = datetime.now(UTC)

    readings = measurement.readings
    intervals = bootstrap_diagnostics(readings, config) if readings else {}
    report = combine_full_protocol(
        generated_at_utc=started.isoformat(timespec="seconds"),
        execution=ShadowExecutionMetadata(
            started_at_utc=started.isoformat(timespec="seconds"),
            completed_at_utc=completed.isoformat(timespec="seconds"),
            elapsed_seconds=(completed - started).total_seconds(),
            deterministic_seed=config.scenario_seed,
            warnings=tuple(str(item.message) for item in caught),
        ),
        residual_source=residual_source,
        player=player,
        squad_gates=measurement.gates,
        calibration_diagnostics=measurement.diagnostics,
        interval_diagnostics=intervals,
        evaluation_folds=len(readings),
        provenance_fingerprints=measurement.provenance,
        abstention_reasons=(
            ()
            if measurement.gates
            else (
                f"{len(readings)} evaluation folds are fewer than the pre-registered "
                f"minimum of {config.min_evaluation_folds}.",
            )
        ),
    )
    outcome = write_shadow_report_once(report, arguments.json_output)

    print(
        f"Shift       {measurement.shift.shift_points:.4f} over "
        f"{measurement.shift.fold_count} development folds"
    )
    print(f"Status      {report.shadow_status} ({outcome})")
    for gate in report.gate_results:
        print(f"Gate        {gate.gate}: {'pass' if gate.passes else 'FAIL'} ({gate.observed})")
    tail = report.calibration_diagnostics.get("realized_below_lower_quantile_folds")
    if tail is not None:
        print(f"S2 events   {int(tail)} of {len(readings)} folds below the tenth percentile")
    for reason in report.reasons:
        print(f"Reason      {reason}")
    print(f"Wrote       {arguments.json_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
