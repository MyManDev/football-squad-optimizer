"""Re-draw the boundary folds of the joint sampler's calibration record under further seeds.

A descriptive reading added after the result of `docs/research/moe_sampler.json`. The S2 gate
counts the folds whose realized squad score falls below the scenario tenth percentile, and a
fold whose PIT sits near 0.10 can change that flag with the Monte Carlo draw alone: with 1,000
scenarios the standard error of the empirical distribution near 0.10 is about 0.0095. The
protocol reads seed 0 once and that verdict stands. This runner asks how far the count moves
under other seeds, for the candidate (`team_match_joint_v1`) and the block control
(`team_match_block_v1`), with the calibration runner's own functions and the frozen inputs:

- the three input files must hash to the binding pins, which the record's reference names too;
- the boundary folds are those whose recorded PIT lies in [0.06, 0.14] under either arm;
- their decisions are re-solved on the walk-forward controls under the measurement
  optimization profile, as the calibration run solves them, and both arms are drawn on the
  pools the calibration run builds, once per seed;
- nothing is written unless seed 0 reproduces the record's readout of both arms on every
  boundary fold;
- every other fold keeps its recorded seed-0 flag, and S2 is counted per seed.

From the record's own fold entries, without drawing, it also reads the candidate's location and
spread against the block control, and a plug-in expectation of each arm's lower-tail count from
the recorded PITs. The reading is added under one new key of a copy of the record; nothing
recorded before is changed, and the verdict stays the seed-0 protocol's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Final, cast

import pandas as pd
import scripts.run_component_squad_calibration as calibration
from scipy.stats import binom
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, repository_provenance

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.atomic import write_document_once
from squadopt.evaluation import (
    EvaluationConfig,
    ScoringPolicy,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.experiments.component_squad_calibration import (
    BOUND_TOLERANCE,
    S2_LOWER_TAIL_BOUNDS,
)
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import OptimizationResult
from squadopt.prediction import PredictionSnapshot
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import (
    ScenarioConfig,
    score_component_scenario_decision,
    summarize_component_decision_distribution,
)
from squadopt.scenarios.components import (
    TEAM_MATCH_JOINT_CONTRACT_VERSION,
    ComponentScenarioInputs,
    TeamMatchBlockConfig,
    TeamMatchJointConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
    team_match_joint_pool,
)

#: The record key this reading is written under. A record that already has it is refused.
ADDED_KEY: Final = "seed_sensitivity_added_after_the_result"
DEFAULT_RECORD: Final = REPOSITORY_ROOT / "docs" / "research" / "moe_sampler.json"
DEFAULT_SEEDS: Final = tuple(range(10))
#: A fold is re-drawn when its recorded PIT lies in this interval under either arm.
BOUNDARY_PIT: Final = (0.06, 0.14)
#: The two arms re-drawn: the candidate's readout sits on the fold record itself, the block
#: control's under ``block_arm``.
CANDIDATE: Final = "candidate"
BLOCK: Final = "block_arm"
ARMS: Final = (CANDIDATE, BLOCK)
#: The readout fields kept for every seed; seed 0 is compared on every recorded field.
KEPT_FIELDS: Final = (
    "probability_integral_transform",
    "q10_score",
    "realized_below_q10",
    "scenario_mean_score",
    "scenario_standard_deviation",
)
SCENARIO_COUNT: Final = ScenarioConfig().scenario_count
TAIL_QUANTILE: Final = 0.10


class SeedReadingError(ValueError):
    """Raised when the record or the inputs are not the ones this reading is defined on."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SeedReadingError(f"{name} must be a JSON object.")
    return cast(Mapping[str, object], value)


def _folds(record: Mapping[str, object]) -> list[Mapping[str, object]]:
    folds = record.get("folds")
    if not isinstance(folds, list) or not folds:
        raise SeedReadingError("The record carries no fold entries.")
    return [_mapping(fold, "fold") for fold in folds]


def arm_reading(fold: Mapping[str, object], arm: str) -> Mapping[str, object]:
    """One arm's recorded readout of a fold: the fold record itself for the candidate."""

    if arm == CANDIDATE:
        return fold
    return _mapping(fold.get(arm), arm)


def _pit(fold: Mapping[str, object], arm: str) -> float:
    return float(cast(float, arm_reading(fold, arm)["probability_integral_transform"]))


def _flag(fold: Mapping[str, object], arm: str) -> bool:
    return bool(arm_reading(fold, arm)["realized_below_q10"])


def _number(fold: Mapping[str, object], arm: str, name: str) -> float:
    return float(cast(float, arm_reading(fold, arm)[name]))


def boundary_fold_ids(
    folds: Sequence[Mapping[str, object]], low: float, high: float
) -> tuple[str, ...]:
    """The folds whose recorded PIT lies in [low, high] under either arm, in record order."""

    return tuple(
        str(fold["fold_id"])
        for fold in folds
        if any(low <= _pit(fold, arm) <= high for arm in ARMS)
    )


def _within_s2(count: int, fold_count: int) -> bool:
    low, high = S2_LOWER_TAIL_BOUNDS
    rate = count / fold_count
    return low - BOUND_TOLERANCE <= rate <= high + BOUND_TOLERANCE


def lower_tail_counts_by_seed(
    folds: Sequence[Mapping[str, object]],
    redrawn: Mapping[str, Mapping[str, Mapping[str, Mapping[str, object]]]],
    seeds: Sequence[int],
    arm: str,
) -> dict[str, object]:
    """One arm's S2 count under every seed: the re-drawn folds' flags under that seed plus the
    recorded seed-0 flags of every fold that was not re-drawn."""

    fixed = sum(_flag(fold, arm) for fold in folds if str(fold["fold_id"]) not in redrawn)
    counts = {
        str(seed): fixed
        + sum(bool(readings[str(seed)][arm]["realized_below_q10"]) for readings in redrawn.values())
        for seed in seeds
    }
    values = list(counts.values())
    within = [seed for seed, count in counts.items() if _within_s2(count, len(folds))]
    return {
        "fixed_count_outside_the_redrawn_folds": fixed,
        "counts_by_seed": counts,
        "mean_count": sum(values) / len(values),
        "min_count": min(values),
        "max_count": max(values),
        "seeds_within_s2_band": len(within),
        "seeds_within_s2_band_ids": within,
    }


def _poisson_binomial_at_most(probabilities: Sequence[float], ceiling: int) -> float:
    """P(sum of independent Bernoulli(p_i) <= ceiling), by the exact recursion."""

    distribution = [1.0]
    for probability in probabilities:
        shifted = [0.0, *distribution]
        kept = [*distribution, 0.0]
        distribution = [
            (1.0 - probability) * stay + probability * move
            for stay, move in zip(kept, shifted, strict=True)
        ]
    return sum(distribution[: ceiling + 1])


def plug_in_lower_tail(
    folds: Sequence[Mapping[str, object]], arm: str, scenario_count: int = SCENARIO_COUNT
) -> dict[str, object]:
    """A plug-in expectation of one arm's S2 count from its recorded PITs.

    Taking a fold's recorded PIT as the true probability that a scenario scores at or below the
    realized score, the number of such scenarios in a fresh draw is binomial, and the realized
    score falls below the linear tenth percentile when at most 99 of 1,000 do, possibly when
    exactly 100 do, and never when more do. The two cuts bracket the flag probability. The
    recorded PIT is itself one noisy draw, so this is a rough reading, not an estimate with a
    stated error.
    """

    pits = [_pit(fold, arm) for fold in folds]
    sure = math.floor(TAIL_QUANTILE * scenario_count) - 1
    band_ceiling = math.floor(S2_LOWER_TAIL_BOUNDS[1] * len(folds) + BOUND_TOLERANCE)
    reading: dict[str, object] = {"band_ceiling_count": band_ceiling}
    for name, cut in (("at_most_99", sure), ("at_most_100", sure + 1)):
        probabilities = [float(binom.cdf(cut, scenario_count, pit)) for pit in pits]
        reading[name] = {
            "expected_count": sum(probabilities),
            "probability_count_within_band_ceiling": _poisson_binomial_at_most(
                probabilities, band_ceiling
            ),
        }
    return reading


def location_against_block(folds: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """The candidate's scenario distribution against the block control's, fold by fold.

    Mean, q10 and standard deviation differences, the q10 measured from each arm's own mean,
    and the block arm's lower-tail count when its q10 is moved by the candidate's per-fold mean
    difference and nothing else.
    """

    def mean(values: Sequence[float]) -> float:
        return sum(values) / len(values)

    mean_shift = [
        _number(fold, CANDIDATE, "scenario_mean_score")
        - _number(fold, BLOCK, "scenario_mean_score")
        for fold in folds
    ]
    q10_shift = [
        _number(fold, CANDIDATE, "q10_score") - _number(fold, BLOCK, "q10_score") for fold in folds
    ]
    spread = [
        _number(fold, CANDIDATE, "scenario_standard_deviation")
        - _number(fold, BLOCK, "scenario_standard_deviation")
        for fold in folds
    ]
    centred = [q10 - shift for q10, shift in zip(q10_shift, mean_shift, strict=True)]
    leaving: list[str] = []
    entering: list[str] = []
    for fold, shift in zip(folds, mean_shift, strict=True):
        moved = _number(fold, BLOCK, "realized_score") < _number(fold, BLOCK, "q10_score") + shift
        if moved != _flag(fold, BLOCK):
            (entering if moved else leaving).append(str(fold["fold_id"]))
    block_count = sum(_flag(fold, BLOCK) for fold in folds)
    return {
        "fold_count": len(folds),
        "mean_score_difference_mean": mean(mean_shift),
        "q10_difference_mean": mean(q10_shift),
        "standard_deviation_difference_mean": mean(spread),
        "centred_q10_difference_mean": mean(centred),
        "folds_with_candidate_mean_lower": sum(value < 0 for value in mean_shift),
        "folds_with_candidate_centred_q10_lower": sum(value < 0 for value in centred),
        "block_count_with_q10_moved_by_the_mean_difference": block_count
        - len(leaving)
        + len(entering),
        "block_folds_leaving_the_tail_when_moved": leaving,
        "block_folds_entering_the_tail_when_moved": entering,
    }


def _seed_zero_mismatches(
    folds: Sequence[Mapping[str, object]],
    redrawn: Mapping[str, Mapping[str, Mapping[str, Mapping[str, object]]]],
) -> list[str]:
    """The (fold, arm) pairs whose seed-0 re-draw differs from the record on any field."""

    by_id = {str(fold["fold_id"]): fold for fold in folds}
    mismatches: list[str] = []
    for fold_id, readings in redrawn.items():
        for arm in ARMS:
            recorded = arm_reading(by_id[fold_id], arm)
            drawn = readings["0"][arm]
            if any(recorded.get(name) != value for name, value in drawn.items()):
                mismatches.append(f"{fold_id}/{arm}")
    return mismatches


def seed_reading(
    folds: Sequence[Mapping[str, object]],
    redrawn: Mapping[str, Mapping[str, Mapping[str, Mapping[str, object]]]],
    seeds: Sequence[int],
) -> dict[str, object]:
    """The per-seed counts of both arms and the per-fold flags the counts rest on."""

    if 0 not in seeds:
        raise SeedReadingError("Seed 0 must be re-drawn: it is checked against the record.")
    mismatches = _seed_zero_mismatches(folds, redrawn)
    if mismatches:
        raise SeedReadingError(f"Seed 0 does not reproduce the record on {mismatches!r}.")
    outside = [fold for fold in folds if str(fold["fold_id"]) not in redrawn]
    standard_error = math.sqrt(TAIL_QUANTILE * (1.0 - TAIL_QUANTILE) / SCENARIO_COUNT)
    nearest = {
        arm: min(abs(_pit(fold, arm) - TAIL_QUANTILE) for fold in outside) if outside else None
        for arm in ARMS
    }
    return {
        "arms": {arm: lower_tail_counts_by_seed(folds, redrawn, seeds, arm) for arm in ARMS},
        "folds_outside_the_boundary": {
            "count": len(outside),
            "nearest_pit_distance_from_0_10": nearest,
            "monte_carlo_standard_error_at_0_10": standard_error,
        },
        "folds": {
            fold_id: {
                "realized_score": readings["0"][CANDIDATE]["realized_score"],
                "flags_by_seed": {
                    arm: [
                        int(bool(readings[str(seed)][arm]["realized_below_q10"])) for seed in seeds
                    ]
                    for arm in ARMS
                },
                "seeds": {
                    str(seed): {
                        arm: {name: readings[str(seed)][arm][name] for name in KEPT_FIELDS}
                        for arm in ARMS
                    }
                    for seed in seeds
                },
            }
            for fold_id, readings in redrawn.items()
        },
    }


@dataclass(frozen=True, slots=True)
class FoldTask:
    """Everything one boundary fold's re-draws need: its frozen decision, the selected
    squad's component inputs and the history rows strictly before it."""

    fold_id: str
    inputs: ComponentScenarioInputs
    snapshot: PredictionSnapshot
    history: pd.DataFrame
    result: OptimizationResult
    realized_score: float
    seeds: tuple[int, ...]
    #: The calibration run's ``ScenarioConfig()``; only the seed is replaced per draw.
    base: ScenarioConfig


def redraw_fold(task: FoldTask) -> dict[str, dict[str, dict[str, object]]]:
    """Both arms of one frozen decision under every seed, on the calibration run's pools."""

    target = calibration._target(task.fold_id)
    base = task.base
    residuals = paired_conditional_residuals(
        task.history,
        target=target,
        min_history_folds=base.min_history_folds,
        team_match_block=TeamMatchBlockConfig(),
    )
    joint_pool = team_match_joint_pool(
        task.history, target=target, min_history_folds=base.min_history_folds
    )
    readings: dict[str, dict[str, dict[str, object]]] = {}
    for seed in task.seeds:
        settings = replace(base, deterministic_seed=seed)
        draws = {
            CANDIDATE: sample_component_scenarios(
                task.inputs,
                task.snapshot,
                joint_pool,
                target,
                settings,
                team_match_joint=TeamMatchJointConfig(),
            ),
            BLOCK: sample_component_scenarios(
                task.inputs,
                task.snapshot,
                residuals,
                target,
                settings,
                team_match_block=TeamMatchBlockConfig(),
            ),
        }
        readings[str(seed)] = {
            arm: calibration._readout_record(
                summarize_component_decision_distribution(
                    score_component_scenario_decision(task.result, draw),
                    realized_score=task.realized_score,
                )
            )
            for arm, draw in draws.items()
        }
    return readings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_record(path: Path) -> dict[str, object]:
    record = cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))
    candidate = _mapping(record.get("candidate"), "candidate")
    reference = _mapping(record.get("reference"), "reference")
    if (
        record.get("contract_version") != calibration.CANDIDATE_REPORT_VERSION
        or candidate.get("sampler_contract_version") != TEAM_MATCH_JOINT_CONTRACT_VERSION
        or reference.get("table_sha256") != calibration.PHASE_C_TABLE_SHA256
        or reference.get("roster_sha256") != calibration.PHASE_C_ROSTER_SHA256
        or reference.get("manifest_sha256") != calibration.PHASE_C_MANIFEST_SHA256
    ):
        raise SeedReadingError(
            "The record is not the joint sampler's calibration record on the frozen table."
        )
    if ADDED_KEY in record:
        raise SeedReadingError(f"The record already carries {ADDED_KEY!r}.")
    return record


def _verify_inputs(table: Path, roster: Path, manifest: Path) -> dict[str, str]:
    digests = {"table": _sha256(table), "roster": _sha256(roster), "manifest": _sha256(manifest)}
    pins = {
        "table": calibration.PHASE_C_TABLE_SHA256,
        "roster": calibration.PHASE_C_ROSTER_SHA256,
        "manifest": calibration.PHASE_C_MANIFEST_SHA256,
    }
    if digests != pins:
        raise SeedReadingError(f"The inputs do not hash to the binding pins: {digests!r}.")
    return digests


def _tasks(
    arguments: argparse.Namespace, fold_ids: Sequence[str], seeds: tuple[int, ...]
) -> list[FoldTask]:
    """Re-solve the boundary folds' decisions as the calibration run does and bind their
    inputs and history rows."""

    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    panel = calibration._load_development_panel(arguments.archive_root)
    controls = build_walk_forward_folds(
        panel,
        seasons=calibration.DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    wanted = set(fold_ids)
    prepared = [
        fold
        for fold in prepare_phase_c_component_folds(handoff, controls)
        if fold.fold_id in wanted
    ]
    if {fold.fold_id for fold in prepared} != wanted:
        raise SeedReadingError("A boundary fold is missing from the prepared Phase C folds.")
    evaluation = evaluate_prepared_folds(
        prepared,
        EvaluationConfig(
            optimization_config=calibration.measurement_optimization_config(),
            scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
            run_metadata={"study": calibration.REPORT_VERSION},
        ),
    )
    result_by_id = {fold.fold_id: fold for fold in evaluation.folds}
    rows = calibration._history_rows(handoff, TeamMatchJointConfig())
    tasks: list[FoldTask] = []
    for fold in prepared:
        evaluated = result_by_id[fold.fold_id]
        result = evaluated.optimization_result
        if not result.has_solution or evaluated.realized_squad_points is None:
            raise SeedReadingError(f"{fold.fold_id} has no scored decision.")
        selected = tuple(int(value) for value in result.selected_squad["player_id"])
        inputs, snapshot = calibration._selected_component_inputs(handoff, fold, selected)
        if not bool(inputs.table["composition_route"].eq(COMPONENT_MODEL_ROUTE).all()):
            raise SeedReadingError(f"{fold.fold_id} contains a selected non-component row.")
        tasks.append(
            FoldTask(
                fold_id=fold.fold_id,
                inputs=inputs,
                snapshot=snapshot,
                history=rows.loc[rows["fold_id"].astype("string") < fold.fold_id].copy(),
                result=result,
                realized_score=float(evaluated.realized_squad_points),
                seeds=seeds,
                base=ScenarioConfig(),
            )
        )
    return tasks


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument(
        "--json-output",
        type=Path,
        required=True,
        help="where the record with the added reading is written, once; never the record",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    provenance = repository_provenance()
    if provenance["working_tree_dirty"]:
        print("Refused: commit working-tree changes before measuring.")
        return 1
    if Path(arguments.json_output).resolve() == Path(arguments.record).resolve():
        print("Refused: write the reading beside the record, not over it.")
        return 1
    try:
        record = _verified_record(arguments.record)
        digests = _verify_inputs(arguments.table, arguments.roster, arguments.manifest)
        folds = _folds(record)
        fold_ids = boundary_fold_ids(folds, *BOUNDARY_PIT)
        tasks = _tasks(arguments, fold_ids, DEFAULT_SEEDS)
        prepared_at = datetime.now(UTC)
        by_id = {task.fold_id: redraw_fold(task) for task in tasks}
        redrawn = {fold_id: by_id[fold_id] for fold_id in fold_ids}
        reading = seed_reading(folds, redrawn, DEFAULT_SEEDS)
    except (OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1
    completed = datetime.now(UTC)
    document = {
        **record,
        ADDED_KEY: {
            "status": "descriptive, added after the result; the verdict stays the seed-0 "
            "protocol's and this reading decides nothing",
            "added_on": completed.date().isoformat(),
            "runner": "scripts/redraw_component_calibration_seeds.py",
            "repository_commit": provenance["repository_commit"],
            "working_tree_dirty": provenance["working_tree_dirty"],
            "input_sha256": digests,
            "seeds": list(DEFAULT_SEEDS),
            "boundary_pit_interval": list(BOUNDARY_PIT),
            "boundary_fold_ids": list(fold_ids),
            "solver_profile": "measurement_optimization_config, as the calibration run",
            "seed_0_reproduces_the_record": True,
            **reading,
            "location_against_block_arm": location_against_block(folds),
            "plug_in_lower_tail_count": {arm: plug_in_lower_tail(folds, arm) for arm in ARMS},
            "execution": {
                "started_at_utc": started.isoformat(timespec="seconds"),
                "decisions_ready_at_utc": prepared_at.isoformat(timespec="seconds"),
                "completed_at_utc": completed.isoformat(timespec="seconds"),
                "elapsed_seconds": (completed - started).total_seconds(),
                "python": sys.version.split()[0],
                "numpy": version("numpy"),
                "pandas": version("pandas"),
                "ortools": version("ortools"),
            },
        },
    }
    write_document_once(document, arguments.json_output)
    for arm in ARMS:
        counts = _mapping(_mapping(reading["arms"], "arms")[arm], arm)
        print(arm, dict(_mapping(counts["counts_by_seed"], "counts")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
