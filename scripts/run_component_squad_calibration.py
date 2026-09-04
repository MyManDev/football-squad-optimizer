"""Run the preregistered Phase D component-squad calibration once.

The command freezes each Phase C decision on the complete player pool before checking
scenario eligibility. It then simulates only the selected squad, scores every draw with
official autosub/captain rules, and evaluates the frozen S1/S2 gates. The result is internal
calibration evidence; it does not change the operational model or publish probabilities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import warnings
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Final, cast

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, artifact_metadata

from squadopt.backtest import (
    BacktestConfigurationError,
    build_walk_forward_folds,
    make_ridge_projection_builder,
)
from squadopt.data import DataError
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
    ScoringPolicy,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments import (
    COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
    ComponentCalibrationFold,
    ComponentSquadCalibrationError,
    evaluate_component_squad_calibration,
)
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.features import CrossSeasonConfig
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioError,
    ScenarioTarget,
    score_component_scenario_decision,
    summarize_component_decision_distribution,
)
from squadopt.scenarios.components import (
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    paired_conditional_residuals,
    sample_component_scenarios,
)

REPORT_VERSION: Final = "phase_d_component_squad_calibration_binding_v1"
FIDELITY_VERSION: Final = "phase_d_component_fidelity_v1"
HISTORY_SEASONS: Final = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
DECISION_SEASONS: Final = HISTORY_SEASONS[1:]
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
FULL_FOLD_COUNT: Final = 147
BINDING_FOLD_COUNT: Final = 137
FIRST_BINDING_FOLD: Final = "2021-22-gw11"
LAST_BINDING_FOLD: Final = "2024-25-gw38"
HISTORY_BURN_IN_FOLDS: Final = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
DIRECT_CONTROL_ABSTENTIONS: Final = ("2021-22-gw15",)
PHASE_C_TABLE_SHA256: Final = "b05f10c3fd3ab5058fe1ff720cc6ef0a4b1362a70a19dd979ad0eb0f47d12c01"
PHASE_C_ROSTER_SHA256: Final = "3ef0c5717fa63c3c4772512f019cd750d3fae6cd9a7567d20dd4bfa24003678e"
PHASE_C_MANIFEST_SHA256: Final = "1a06b69abb3d7fe98afde6983885a9a7723463d351a2432dc9e0a11082f5eba8"
FIDELITY_ARTIFACT_SHA256: Final = "cba8dd297386a1305a6a8142121dccb80c3551cb585a6ae4c4e858f89e553fa9"
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "phase_d_component_squad_calibration.json"


class BindingCalibrationError(ValueError):
    """Raised when the binding population or provenance differs from the preregistration."""


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--fidelity", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
    except OSError as error:
        raise BindingCalibrationError(f"Cannot read {path}: {error}") from error
    return digest.hexdigest()


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BindingCalibrationError(f"{name} must be a JSON object.")
    return cast(Mapping[str, object], value)


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BindingCalibrationError(f"{name} must be a JSON list of strings.")
    return tuple(cast(list[str], value))


def _finite_numbers(value: object, name: str = "fidelity") -> None:
    if isinstance(value, bool | str) or value is None:
        return
    if isinstance(value, int | float):
        if not math.isfinite(float(value)):
            raise BindingCalibrationError(f"{name} contains a non-finite number.")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite_numbers(item, f"{name}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _finite_numbers(item, f"{name}[{index}]")
        return
    raise BindingCalibrationError(f"{name} contains a non-JSON value.")


def _load_verified_fidelity(path: Path, handoff: PhaseCComponentHandoff) -> str:
    """Validate the committed diagnostic structurally, without inventing a numeric gate."""

    if (
        handoff.table_sha256 != PHASE_C_TABLE_SHA256
        or handoff.roster_sha256 != PHASE_C_ROSTER_SHA256
        or handoff.manifest_sha256 != PHASE_C_MANIFEST_SHA256
    ):
        raise BindingCalibrationError("Phase C handoff is not the frozen binding artifact.")
    fidelity_digest = _sha256(path)
    if fidelity_digest != FIDELITY_ARTIFACT_SHA256:
        raise BindingCalibrationError("Fidelity artifact is not the committed binding record.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BindingCalibrationError(f"Cannot read fidelity artifact {path}: {error}") from error
    fidelity = _mapping(document, "fidelity artifact")
    _finite_numbers(fidelity)
    if fidelity.get("contract_version") != FIDELITY_VERSION:
        raise BindingCalibrationError("Fidelity artifact uses an unsupported contract version.")
    if (
        fidelity.get("diagnostic_only") is not True
        or fidelity.get("promotes_anything") is not False
        or fidelity.get("registers_any_threshold") is not False
    ):
        raise BindingCalibrationError("Fidelity artifact changes its diagnostic-only meaning.")

    config = _mapping(fidelity.get("config"), "fidelity.config")
    expected_config = {
        "scenario_count": 1_000,
        "deterministic_seed": 0,
        "min_history_folds": 8,
    }
    if dict(config) != expected_config:
        raise BindingCalibrationError("Fidelity artifact does not use the frozen scenario config.")

    provenance = _mapping(fidelity.get("provenance"), "fidelity.provenance")
    if (
        provenance.get("working_tree_dirty") is not False
        or provenance.get("manifest_locked_holdout_read") is not False
        or provenance.get("manifest_table_sha256") != handoff.table_sha256
        or provenance.get("oof_table_sha256") != handoff.table_sha256
        or provenance.get("manifest_roster_sha256") != handoff.roster_sha256
        or provenance.get("roster_sha256") != handoff.roster_sha256
        or provenance.get("manifest_sha256") != handoff.manifest_sha256
        or provenance.get("model_version") != handoff.model_version
        or provenance.get("feature_contract_version") != handoff.feature_contract_version
    ):
        raise BindingCalibrationError("Fidelity artifact does not describe this Phase C handoff.")

    population = _mapping(fidelity.get("population"), "fidelity.population")
    measured_ids = _string_list(population.get("measured_fold_ids"), "measured_fold_ids")
    all_ids = tuple(str(value) for value in handoff.rows["fold_id"].drop_duplicates())
    expected_measured = all_ids[len(HISTORY_BURN_IN_FOLDS) :]
    if (
        population.get("fold_count_total") != FULL_FOLD_COUNT
        or population.get("fold_count_excluded") != len(HISTORY_BURN_IN_FOLDS)
        or population.get("fold_count_measured") != len(expected_measured)
        or population.get("locked_holdout_season") != LOCKED_HOLDOUT_SEASON
        or population.get("locked_holdout_rows_present") != 0
        or measured_ids != expected_measured
    ):
        raise BindingCalibrationError("Fidelity artifact has a different fold population.")

    exclusions = fidelity.get("excluded_folds")
    folds = fidelity.get("folds")
    if not isinstance(exclusions, list) or not isinstance(folds, list):
        raise BindingCalibrationError("Fidelity artifact fold records are missing.")
    excluded_ids = tuple(str(_mapping(item, "excluded fold").get("fold_id")) for item in exclusions)
    measured_record_ids = tuple(
        str(_mapping(item, "fidelity fold").get("fold_id")) for item in folds
    )
    if excluded_ids != HISTORY_BURN_IN_FOLDS or measured_record_ids != expected_measured:
        raise BindingCalibrationError("Fidelity artifact fold records contradict its population.")
    warnings_value = fidelity.get("warnings")
    if not isinstance(warnings_value, list) or any(
        not isinstance(item, str) for item in warnings_value
    ):
        raise BindingCalibrationError("Fidelity warnings must be a list of strings.")
    return fidelity_digest


def _load_development_panel(archive_root: Path) -> pd.DataFrame:
    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    observed = {str(value) for value in panel["season"].dropna().unique()}
    if observed != set(HISTORY_SEASONS):
        raise BindingCalibrationError(
            "Phase D panel seasons differ from the explicit development history."
        )
    return panel


def _target(fold_id: str) -> ScenarioTarget:
    season, separator, gameweek = fold_id.rpartition("-gw")
    if not separator:
        raise BindingCalibrationError(f"Invalid fold id {fold_id!r}.")
    return ScenarioTarget(season=season, gameweek=int(gameweek))


def _selected_component_inputs(
    handoff: PhaseCComponentHandoff,
    candidate: EvaluationFold,
    selected_ids: Sequence[int],
) -> tuple[ComponentScenarioInputs, PredictionSnapshot]:
    target = _target(candidate.fold_id)
    selected = set(selected_ids)
    rows = handoff.rows.loc[
        handoff.rows["fold_id"].eq(candidate.fold_id) & handoff.rows["player_id"].isin(selected)
    ].copy(deep=True)
    projections = candidate.projections.loc[candidate.projections["player_id"].isin(selected)].copy(
        deep=True
    )
    if len(rows) != 15 or len(projections) != 15 or set(rows["player_id"]) != selected:
        raise BindingCalibrationError(
            f"{candidate.fold_id} selected squad does not align to exactly 15 Phase C rows."
        )
    rows = rows.sort_values("player_id", kind="stable").reset_index(drop=True)
    projections = projections.sort_values("player_id", kind="stable").reset_index(drop=True)
    # The verified OOF rows carry position for component slices, while team identity stays in
    # the decision roster/projection. Bind it only after the full-pool decision is frozen.
    rows = rows.merge(
        projections.loc[:, ["player_id", "team_id"]],
        on="player_id",
        how="left",
        validate="one_to_one",
    )
    snapshot = prepare_optimizer_projection(
        projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        projections.loc[:, ["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=handoff.model_version,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            training_cutoff=candidate.fold_id,
            training_data_fingerprint=handoff.table_sha256,
        ),
    )
    inputs = ComponentScenarioInputs(
        table=rows.loc[
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
            phase_c_table_sha=handoff.table_sha256,
            roster_sha=handoff.roster_sha256,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            target_contract_version=handoff.target_contract_version,
            dataset_contract_version=handoff.dataset_contract_version,
            season=target.season,
            target_gameweek=target.gameweek,
            deterministic_seed=0,
        ),
    )
    return inputs, snapshot


def _binding_population(
    fold_ids: Sequence[str], direct_control_fold_ids: Sequence[str]
) -> tuple[str, ...]:
    ordered = tuple(fold_ids)
    if (
        len(ordered) != FULL_FOLD_COUNT
        or len(set(ordered)) != FULL_FOLD_COUNT
        or ordered[: len(HISTORY_BURN_IN_FOLDS)] != HISTORY_BURN_IN_FOLDS
        or ordered[-1] != LAST_BINDING_FOLD
    ):
        raise BindingCalibrationError(
            "Phase C OOF fold population differs from the preregistration."
        )
    direct = tuple(direct_control_fold_ids)
    if direct != DIRECT_CONTROL_ABSTENTIONS:
        raise BindingCalibrationError(
            "Selected direct-control abstentions differ from the preregistered fold."
        )
    eligible = tuple(
        fold_id
        for fold_id in ordered[len(HISTORY_BURN_IN_FOLDS) :]
        if fold_id not in DIRECT_CONTROL_ABSTENTIONS
    )
    if (
        len(eligible) != BINDING_FOLD_COUNT
        or eligible[0] != FIRST_BINDING_FOLD
        or eligible[-1] != LAST_BINDING_FOLD
    ):
        raise BindingCalibrationError("Binding population is not the frozen 137-fold population.")
    return eligible


def _measure(arguments: argparse.Namespace) -> tuple[dict[str, object], int]:
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    fidelity_sha256 = _load_verified_fidelity(arguments.fidelity, handoff)
    panel = _load_development_panel(arguments.archive_root)
    controls = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    candidates = prepare_phase_c_component_folds(handoff, controls)
    evaluation = evaluate_prepared_folds(
        candidates,
        EvaluationConfig(
            scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
            run_metadata={"study": REPORT_VERSION},
        ),
    )
    if len(evaluation.folds) != len(candidates):
        raise BindingCalibrationError("Candidate evaluation omitted a Phase C fold.")

    settings = ScenarioConfig()
    candidate_by_id = {fold.fold_id: fold for fold in candidates}
    result_by_id = {fold.fold_id: fold for fold in evaluation.folds}
    all_ids = tuple(fold.fold_id for fold in candidates)
    direct_control: list[str] = []
    selected_by_id: dict[str, tuple[int, ...]] = {}
    for fold_id in all_ids[len(HISTORY_BURN_IN_FOLDS) :]:
        result = result_by_id[fold_id].optimization_result
        if not result.has_solution:
            continue
        selected_ids = tuple(int(value) for value in result.selected_squad["player_id"])
        selected_by_id[fold_id] = selected_ids
        selected_rows = handoff.rows.loc[
            handoff.rows["fold_id"].eq(fold_id) & handoff.rows["player_id"].isin(selected_ids)
        ]
        if bool(selected_rows["composition_route"].eq(DIRECT_CONTROL_ROUTE).any()):
            direct_control.append(fold_id)
    expected_ids = _binding_population(all_ids, direct_control)

    readings: list[ComponentCalibrationFold] = []
    fold_records: list[dict[str, object]] = []
    for fold_id in expected_ids:
        evaluated_fold = result_by_id[fold_id]
        if (
            not evaluated_fold.optimization_result.has_solution
            or evaluated_fold.realized_squad_points is None
        ):
            continue
        candidate = candidate_by_id[fold_id]
        selected_ids = selected_by_id[fold_id]
        inputs, snapshot = _selected_component_inputs(handoff, candidate, selected_ids)
        if not bool(inputs.table["composition_route"].eq(COMPONENT_MODEL_ROUTE).all()):
            raise BindingCalibrationError(f"{fold_id} contains a selected non-component row.")
        target = _target(fold_id)
        history = handoff.rows.loc[handoff.rows["fold_id"].astype("string") < fold_id]
        residuals = paired_conditional_residuals(
            history,
            target=target,
            min_history_folds=settings.min_history_folds,
        )
        draw = sample_component_scenarios(inputs, snapshot, residuals, target, settings)
        scored = score_component_scenario_decision(evaluated_fold.optimization_result, draw)
        readout = summarize_component_decision_distribution(
            scored,
            realized_score=evaluated_fold.realized_squad_points,
        )
        readings.append(ComponentCalibrationFold(fold_id=fold_id, readout=readout))
        fold_records.append(
            {
                "fold_id": fold_id,
                "solver_status": evaluated_fold.optimization_result.solver_status.value,
                "realized_score": readout.realized_score,
                "scenario_mean_score": readout.mean_score,
                "scenario_standard_deviation": readout.score_standard_deviation,
                "q10_score": readout.lower_quantile_score,
                "probability_integral_transform": readout.probability_integral_transform,
                "realized_below_q10": readout.realized_below_lower_quantile,
                "scenario_fingerprint": readout.scenario_fingerprint,
                "component_fingerprint": readout.component_fingerprint,
            }
        )

    verdict = evaluate_component_squad_calibration(
        readings,
        expected_fold_ids=expected_ids,
        sampler_fidelity_verified=True,
    )
    return (
        {
            "source": {
                "table_sha256": handoff.table_sha256,
                "roster_sha256": handoff.roster_sha256,
                "manifest_sha256": handoff.manifest_sha256,
                "producer_repository_commit": handoff.repository_commit,
                "model_version": handoff.model_version,
                "feature_contract_version": handoff.feature_contract_version,
                "target_contract_version": handoff.target_contract_version,
                "dataset_contract_version": handoff.dataset_contract_version,
                "fidelity_artifact_sha256": fidelity_sha256,
            },
            "config": asdict(settings),
            "population": {
                "full_fold_count": len(all_ids),
                "history_burn_in_fold_ids": list(HISTORY_BURN_IN_FOLDS),
                "direct_control_abstention_fold_ids": direct_control,
                "expected_binding_fold_ids": list(expected_ids),
            },
            "folds": fold_records,
            "verdict": asdict(verdict),
        },
        len(panel),
    )


def _recorded_warnings(caught: list[warnings.WarningMessage]) -> list[str]:
    counted = Counter(f"{type(item.message).__name__}: {item.message}" for item in caught)
    return [
        text if count == 1 else f"{text} (raised {count} times)"
        for text, count in sorted(counted.items())
    ]


def main() -> int:
    arguments = _parse_arguments()
    started = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=0,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    provenance = cast(dict[str, object], metadata["provenance"])
    if provenance["working_tree_dirty"]:
        print("Refused: commit or stash working-tree changes before measuring Phase D.")
        return 1

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            measured, panel_rows = _measure(arguments)
        except (
            BacktestConfigurationError,
            BindingCalibrationError,
            ComponentSquadCalibrationError,
            DataError,
            EvaluationError,
            OSError,
            ScenarioError,
            ShadowReportError,
            ValueError,
        ) as error:
            print(f"Refused: {error}")
            return 1

    completed = datetime.now(UTC)
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=started.isoformat(timespec="seconds"),
        history_seasons=HISTORY_SEASONS,
    )
    environment = dict(cast(Mapping[str, object], metadata["environment"]))
    environment.update(
        {
            "numpy": version("numpy"),
            "scipy": version("scipy"),
            "scikit_learn": version("scikit-learn"),
        }
    )
    document: dict[str, object] = {
        "contract_version": REPORT_VERSION,
        "evaluation_contract_version": COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
        "generated_at_utc": metadata["created_utc"],
        "internal_only": True,
        "member_facing_probability_published": False,
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "prereg_document": "docs/phase_d_component_squad_calibration_prereg.md",
        "execution": {
            "started_at_utc": started.isoformat(timespec="seconds"),
            "completed_at_utc": completed.isoformat(timespec="seconds"),
            "elapsed_seconds": (completed - started).total_seconds(),
            "warnings": _recorded_warnings(caught),
        },
        "provenance": metadata["provenance"],
        "environment": environment,
        **measured,
    }
    try:
        outcome = write_document_once(document, arguments.json_output)
    except ShadowReportError as error:
        print(f"Refused: {error}")
        return 1
    verdict = cast(Mapping[str, object], document["verdict"])
    print(f"Folds  {verdict['fold_count']}/{verdict['expected_fold_count']}")
    print(f"S1     {verdict['s1_passes']}")
    print(f"S2     {verdict['s2_passes']}")
    print(f"Status {verdict['status']}")
    print(f"Wrote  {arguments.json_output} ({outcome})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
