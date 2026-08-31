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
shrinkage knobs, the scenario count and seed, the quantile, the bands, the bootstrap
and the fit cutoff — so the command line carries paths and nothing else. A flag that
could change a number would be a number chosen after the fact.

P1 is not re-measured. It is merged from the recorded player-level artifact, whose
exact bytes are pinned here, and only after every field of that artifact's residual
provenance has been matched against the export this run is bound to.

The run is create-once and atomic: an identical replay is accepted, different content
at an occupied path is refused rather than overwritten.
"""

import argparse
import subprocess
import sys
import warnings
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    artifact_metadata,
)
from scripts.measure_in_season_blend import _Inputs

from squadopt.backtest.splits import DecisionPoint, walk_forward_decision_points
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY
from squadopt.experiments.residual_manifest import (
    ResidualSourceError,
    load_residual_source_manifest,
)
from squadopt.experiments.shadow_report import (
    ShadowExecutionMetadata,
    ShadowGateResult,
    ShadowReportError,
    ShadowResidualSource,
    write_shadow_report_once,
)
from squadopt.experiments.shadow_squad_calibration import (
    EVALUATION_SEASON,
    FIT_SEASONS,
    HISTORY_SEASONS,
    MIN_PRIOR_GAMEWEEKS_IN_SEASON,
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
    loaded_seasons,
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

#: The prereg's split: fit on 2021-22..2023-24, score 2024-25 frozen. A constant rather
#: than a flag — it decides what a fit may see, and it is one of the seven fields the
#: recorded P1 measurement is matched on, so it decides whether P1 merges at all.
CUTOFF_FOLD_ID: Final = "2023-24-gw38"

#: The recorded player-level measurement this run merges, and its exact bytes. The
#: corrected one: the earlier artifact was superseded by the corrective amendment and
#: describes a different residual export. Pinning the digest is what makes "the
#: recorded artifact" a fact rather than whichever file a path happens to reach; a new
#: P1 measurement is a new protocol input, and updating this is a deliberate act.
PLAYER_REPORT: Final = REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season_corrected.json"
PLAYER_REPORT_SHA256: Final = "9dd3ec75d11924a1390e1086974cb0243ae1a44791b4b9e6f1477aaa137f0139"

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


def _recorded_warnings(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    """One line per distinct warning, counted rather than repeated.

    Two things this has to survive. A warning constructed with no arguments stringifies
    to nothing and the report contract refuses a blank one — which would discard a
    finished measurement at the last step — so the category name always leads. And
    ``simplefilter("always")`` defeats deduplication, so one warning raised inside a
    148-fold loop would otherwise be written to the artifact 148 times.
    """

    counted = Counter(f"{type(item.message).__name__}: {item.message}" for item in caught)
    return tuple(
        text if count == 1 else f"{text} (raised {count} times)"
        for text, count in sorted(counted.items())
    )


def _environment(panel: pd.DataFrame, seasons: tuple[str, ...]) -> dict[str, str]:
    """The parts of the machine that can move a number, and none of the parts that cannot.

    Versions only. The platform string, the processor and the CPU count identify a
    machine rather than a measurement, and provenance is part of replay identity — so
    recording them would make the same measurement on another machine read as a
    different one.
    """

    metadata = artifact_metadata(panel_rows=len(panel), history_seasons=seasons)
    environment = metadata["environment"]
    provenance = metadata["provenance"]
    assert isinstance(environment, dict) and isinstance(provenance, dict)
    return {
        "environment_python": str(environment["python"]),
        "environment_pandas": str(environment["pandas"]),
        "environment_numpy": np.__version__,
        "environment_ortools": str(environment["ortools"]),
        "archive_manifest_sha256": str(provenance["archive_manifest_sha256"]),
    }


@dataclass(frozen=True, slots=True)
class _Measurement:
    """Everything the computation produced, so the caller only has to record it."""

    player: PlayerEvidence
    residual_source: ShadowResidualSource
    gates: tuple[ShadowGateResult, ...]
    readings: tuple[SquadFoldReading, ...]
    shift: FrozenShift
    diagnostics: dict[str, float | None]
    intervals: dict[str, float | None]
    provenance: dict[str, str]


def _measure(
    arguments: argparse.Namespace, config: SquadShadowConfig, *, revision: str, dirty: bool
) -> _Measurement:
    """Every number this run computes and every input it reads, in one call.

    It is one function so that the caller can wrap the whole of it in the warning
    recorder. A warning raised while the residual table is parsed, while the scenarios
    are generated, or while the bootstrap resamples is a fact about the measurement; a
    recorder spanning only part of it leaves an artifact claiming there were none.
    """

    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=MODEL_VERSION,
        expect_feature_contract_version=FEATURE_CONTRACT_VERSION,
    )
    residual_source = manifest.to_shadow_source(cutoff_fold_id=CUTOFF_FOLD_ID)
    # Before the panel and before the residual table: a record that does not match is
    # a reason not to start, not a discovery to make after an hour of scenarios.
    player = load_bound_player_report(
        PLAYER_REPORT,
        residual_source,
        config,
        expect_sha256=PLAYER_REPORT_SHA256,
        expect_fingerprints={
            "dataset_snapshot_id": manifest.dataset_snapshot_id,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
        },
    )

    panel = load_panel_without_the_holdout(arguments.archive_root)
    residuals = pd.read_csv(arguments.residual_table)

    fit_decisions = walk_forward_decision_points(
        panel, seasons=FIT_SEASONS, min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON
    )
    evaluation_decisions = walk_forward_decision_points(
        panel,
        seasons=(EVALUATION_SEASON,),
        min_prior_gameweeks_in_season=MIN_PRIOR_GAMEWEEKS_IN_SEASON,
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
    loaded = loaded_seasons(panel)
    return _Measurement(
        player=player,
        residual_source=residual_source,
        gates=gates,
        readings=readings,
        shift=shift,
        diagnostics=diagnostics,
        intervals=bootstrap_diagnostics(readings, config) if readings else {},
        provenance={
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            "run_contract_version": SQUAD_SHADOW_CONTRACT_VERSION,
            # What the numbers were computed from, on both sides of the merge.
            "dataset_snapshot_id": manifest.dataset_snapshot_id,
            "residual_generation_commit": manifest.generation_commit,
            "residual_table_sha256": manifest.table_sha256,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            # The seasons actually read, beside the ones requested. The holdout clause
            # asks for this precisely because those are the same only if someone looks.
            "panel_seasons_loaded": ",".join(loaded),
            "panel_seasons_requested": ",".join(HISTORY_SEASONS),
            # Clause 18: the shift's fit population, named rather than implied by the
            # season list, because min_history_folds decides which folds are eligible.
            "frozen_shift_points": repr(shift.shift_points),
            "shift_fit_folds": str(shift.fold_count),
            "shift_fit_first_fold": shift.first_fold_id,
            "shift_fit_last_fold": shift.last_fold_id,
            # Every evaluation fold faces one frozen history at one seed, so they share
            # a draw of the common gameweek shock. Recorded because a reader of the
            # bootstrap needs to know the 37 readings are not independent of each other.
            "scenario_draw_shared_across_evaluation_folds": "true",
            # Clause 24: every parameter of every configuration the run constructed,
            # read off the objects themselves rather than from a list kept by hand.
            **declared_parameters(config, shift_points=shift.shift_points),
            **_environment(panel, loaded),
        },
    )


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    config = SquadShadowConfig()
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)

    print(f"Contract    {SQUAD_SHADOW_CONTRACT_VERSION}")
    print(f"Identity    {MODEL_NAME} / {MODEL_VERSION}")
    print(f"Player P1   {PLAYER_REPORT.name} at {PLAYER_REPORT_SHA256[:16]}...")
    print(f"Fit         {', '.join(FIT_SEASONS)}   Frozen evaluation  {EVALUATION_SEASON}")
    print(f"Scenarios   {config.scenario_count} at seed {config.scenario_seed}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")

    if dirty:
        # The corrective amendment makes a clean tree a condition of an eligible
        # execution, and the artifact path is written once. Measuring anyway would
        # spend that path on an abstention and leave the eligible run with nowhere to
        # record itself, so this stops before anything is read.
        print(
            "\nRefused: the working tree carries changes this run did not write, so "
            "its numbers could not be reproduced from the commit it would record. "
            "Nothing was measured and nothing was written."
        )
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measurement = _measure(arguments, config, revision=revision, dirty=dirty)
        except (SquadShadowError, ShadowReportError, ResidualSourceError, OSError) as error:
            # A refusal is something an operator can act on; a traceback from two
            # layers down is not. Nothing has been written at this point either way.
            print(f"\nRefused: {error}")
            return 1
    completed = datetime.now(UTC)

    readings = measurement.readings
    abstentions: list[str] = []
    if not measurement.gates:
        abstentions.append(
            f"{len(readings)} evaluation folds are fewer than the pre-registered "
            f"minimum of {config.min_evaluation_folds}."
        )
    report = combine_full_protocol(
        generated_at_utc=started.isoformat(timespec="seconds"),
        execution=ShadowExecutionMetadata(
            started_at_utc=started.isoformat(timespec="seconds"),
            completed_at_utc=completed.isoformat(timespec="seconds"),
            elapsed_seconds=(completed - started).total_seconds(),
            deterministic_seed=config.scenario_seed,
            warnings=_recorded_warnings(caught),
        ),
        residual_source=measurement.residual_source,
        player=measurement.player,
        squad_gates=measurement.gates,
        calibration_diagnostics=measurement.diagnostics,
        interval_diagnostics=measurement.intervals,
        evaluation_folds=len(readings),
        provenance_fingerprints=measurement.provenance,
        abstention_reasons=tuple(abstentions),
    )

    # Printed before the write, so a create-once conflict still tells the operator what
    # this run measured rather than only that something disagreed.
    print(
        f"Shift       {measurement.shift.shift_points:.6f} over "
        f"{measurement.shift.fold_count} development folds "
        f"({measurement.shift.first_fold_id} to {measurement.shift.last_fold_id})"
    )
    for gate in report.gate_results:
        print(f"Gate        {gate.gate}: {'pass' if gate.passes else 'FAIL'} ({gate.observed})")
    tail = report.calibration_diagnostics.get("realized_below_lower_quantile_folds")
    if tail is not None:
        print(f"S2 events   {int(tail)} of {len(readings)} folds below the tenth percentile")
    print(f"Status      {report.shadow_status}")
    for reason in report.reasons:
        print(f"Reason      {reason}")

    try:
        outcome = write_shadow_report_once(report, arguments.json_output)
    except ShadowReportError as error:
        print(f"\nRefused: {error}")
        return 1
    print(f"Wrote       {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
