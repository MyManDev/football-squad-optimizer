"""Run gates S1 and S2 of the Phase 2 protocol against one bound residual export.

    python -m scripts.run_shadow_squad_calibration \
        --residual-table    artifacts/residuals/in_season_residuals.csv \
        --residual-manifest artifacts/residuals/in_season_residuals.manifest.json \
        --bench-weight <value> --decision-universe <choice> --min-history-folds <value>

Internal measurement only. The result is a ``shadow_calibration_report_v1`` document
carrying the full protocol's verdict; nothing it can say publishes a probability, a
percentage or a ``P(...)`` to any member-facing surface, and the writer refuses a
destination under ``web/public``.

**Three arguments have no defaults on purpose.** ``--bench-weight``,
``--decision-universe`` and ``--min-history-folds`` change which squad is chosen or
which folds are fitted, and the squad-gate amendment records all three as still
unfixed. A run that cannot name them does not start; a default here would be choosing
the result. Until that amendment lands, ``--i-have-a-further-amendment`` is required
as well, so an eligible-looking command cannot be assembled by accident.

The run is create-once and atomic: an identical replay is accepted, different content
at an occupied path is refused rather than overwritten.
"""

import argparse
import subprocess
import sys
import warnings
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
    write_shadow_report_once,
)
from squadopt.experiments.shadow_squad_calibration import (
    EVALUATION_SEASON,
    FIT_SEASONS,
    SQUAD_SHADOW_CONTRACT_VERSION,
    SquadShadowConfig,
    SquadShadowError,
    build_squad_folds,
    combine_full_protocol,
    evaluate_squad_gates,
    fit_frozen_shift,
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

#: Its own file. The player-level runner's default path holds a non-binding artifact
#: written before the execution block existed; sharing it would turn every first run
#: into a conflict rather than a record.
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
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--bench-weight",
        type=float,
        required=True,
        help="Recorded as unfixed by the squad-gate amendment; two precedents disagree "
        "(0.1 and 0.0). It must be named, never defaulted.",
    )
    parser.add_argument(
        "--decision-universe",
        choices=("full_roster", "candidate_pool"),
        required=True,
        help="Recorded as unfixed by the squad-gate amendment; the two universes give "
        "different squads and different PIT.",
    )
    parser.add_argument(
        "--min-history-folds",
        type=int,
        required=True,
        help="Recorded as unfixed by the squad-gate amendment; it reshapes the "
        "development fit that produces the frozen shift.",
    )
    parser.add_argument(
        "--i-have-a-further-amendment",
        action="store_true",
        help="Assert that a further amendment has fixed the three controls above. "
        "Without it the run refuses: the protocol, not the code, is what is missing.",
    )
    return parser.parse_args()


def _projection_provider(panel: pd.DataFrame, decisions: tuple[DecisionPoint, ...]) -> "object":
    """The target model's own per-fold table, from the assembly the export uses."""

    inputs = _Inputs(panel, decisions)
    settings = InSeasonBlendConfig()

    def provide(decision: DecisionPoint) -> pd.DataFrame:
        return inputs.blend(decision, settings)

    return provide


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)

    try:
        config = SquadShadowConfig(
            bench_weight=float(arguments.bench_weight),
            decision_universe=str(arguments.decision_universe),
            min_history_folds=int(arguments.min_history_folds),
        )
    except SquadShadowError as error:
        print(f"Refused: {error}")
        return 1

    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=MODEL_VERSION,
        expect_feature_contract_version=FEATURE_CONTRACT_VERSION,
    )
    revision, _ = _git_revision()
    dirty = _tree_dirty_ignoring(arguments.json_output)

    print(f"Contract    {SQUAD_SHADOW_CONTRACT_VERSION}")
    print(f"Identity    {manifest.model_name} / {manifest.model_version}")
    print(f"Residuals   {manifest.table_sha256[:16]}... ({manifest.row_count} rows)")
    print(f"Fit         {', '.join(FIT_SEASONS)}   Frozen evaluation  {EVALUATION_SEASON}")
    print(f"Universe    {config.decision_universe}   bench_weight {config.bench_weight}")
    print(f"Scenarios   {config.scenario_count} at seed {config.scenario_seed}")
    print(f"Commit      {revision} (tree dirty: {str(dirty).lower()})")

    if not arguments.i_have_a_further_amendment:
        print()
        print(
            "Refused: no binding S1/S2 run is eligible. The squad-gate amendment "
            "records bench_weight, the decision universe and min_history_folds as "
            "still unfixed, and a further amendment must fix them before this protocol "
            "may be measured. Nothing was written."
        )
        return 1

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
        training_data_fingerprint=manifest.table_sha256,
    )

    fit_folds = build_squad_folds(panel, residuals, provide, seasons=FIT_SEASONS)  # type: ignore[arg-type]
    shift = fit_frozen_shift(fit_folds, residuals, provenance, config)
    print(f"Shift       {shift.shift_points:.4f} over {shift.fold_count} development folds")

    evaluation_folds = build_squad_folds(  # type: ignore[arg-type]
        panel, residuals, provide, seasons=(EVALUATION_SEASON,)
    )
    squad_gates, readings, diagnostics = evaluate_squad_gates(
        evaluation_folds, residuals, provenance, config, shift
    )

    completed = datetime.now(UTC)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        execution = ShadowExecutionMetadata(
            started_at_utc=started.isoformat(timespec="seconds"),
            completed_at_utc=completed.isoformat(timespec="seconds"),
            elapsed_seconds=(completed - started).total_seconds(),
            deterministic_seed=config.scenario_seed,
            warnings=tuple(str(item.message) for item in caught),
        )

    report = combine_full_protocol(
        generated_at_utc=started.isoformat(timespec="seconds"),
        execution=execution,
        residual_source=manifest.to_shadow_source(cutoff_fold_id=arguments.cutoff_fold_id),
        player_gates=(),
        squad_gates=squad_gates,
        calibration_diagnostics=diagnostics,
        interval_diagnostics={},
        evaluation_folds=len(readings),
        provenance_fingerprints={
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            "dataset_snapshot_id": manifest.dataset_snapshot_id,
            "residual_generation_commit": manifest.generation_commit,
            "residual_table_sha256": manifest.table_sha256,
            "model_identity": f"{manifest.model_name}/{manifest.model_version}",
            "run_contract_version": SQUAD_SHADOW_CONTRACT_VERSION,
            # The amendment records these three as unfixed. Whatever a run declares,
            # the artifact says so — otherwise two runs under different controls are
            # indistinguishable to a reader, or collide as an unexplained conflict.
            "declared_bench_weight": repr(config.bench_weight),
            "declared_decision_universe": config.decision_universe,
            "declared_min_history_folds": str(config.min_history_folds),
            "scenario_count": str(config.scenario_count),
            "scenario_seed": str(config.scenario_seed),
        },
        abstention_reasons=(
            ()
            if squad_gates
            else (
                f"{len(readings)} evaluation folds are fewer than the pre-registered "
                f"minimum of {config.min_evaluation_folds}.",
            )
        ),
    )
    outcome = write_shadow_report_once(report, arguments.json_output)

    print(f"Status      {report.shadow_status} ({outcome})")
    for gate in report.gate_results:
        print(f"Gate        {gate.gate}: {'pass' if gate.passes else 'FAIL'} ({gate.observed})")
    for reason in report.reasons:
        print(f"Reason      {reason}")
    print(f"Wrote       {arguments.json_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
