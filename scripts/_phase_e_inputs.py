"""Verified Phase D evidence and historical full-pool inputs for the E3 runner."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts import run_component_squad_calibration as binding

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.evaluation import EvaluationFold, prepare_phase_c_component_folds
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments.component_squad_calibration import COMPONENT_SQUAD_CALIBRATION_STATUSES
from squadopt.experiments.phase_e_shadow import PhaseEShadowError
from squadopt.features import CrossSeasonConfig
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    paired_conditional_residuals,
    sample_component_scenarios,
)


@dataclass(frozen=True, slots=True)
class PhaseDBindingEvidence:
    """A binding verdict, fixed population and digest to carry into the E3 artifact."""

    status: str
    fold_ids: tuple[str, ...]
    sha256: str
    model_version: str


def load_phase_d_binding(path: Path) -> PhaseDBindingEvidence:
    """Require binding evidence before loading historical inputs or evaluating anything."""

    payload = path.read_bytes()
    document = binding._mapping(json.loads(payload), "Phase D binding artifact")
    binding._finite_numbers(document, "Phase D binding artifact")
    if (
        document.get("contract_version") != binding.REPORT_VERSION
        or document.get("evaluation_contract_version")
        != binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION
        or document.get("locked_holdout_accessed") is not False
        or document.get("operational_control_changed") is not False
        or document.get("internal_only") is not True
    ):
        raise PhaseEShadowError("Phase D evidence is not the internal binding artifact.")
    provenance = binding._mapping(document.get("provenance"), "binding.provenance")
    if provenance.get("working_tree_dirty") is not False:
        raise PhaseEShadowError("Binding evidence must name a clean repository revision.")
    source = binding._mapping(document.get("source"), "binding.source")
    for key, expected in (
        ("table_sha256", binding.PHASE_C_TABLE_SHA256),
        ("roster_sha256", binding.PHASE_C_ROSTER_SHA256),
        ("manifest_sha256", binding.PHASE_C_MANIFEST_SHA256),
        ("fidelity_artifact_sha256", binding.FIDELITY_ARTIFACT_SHA256),
    ):
        if source.get(key) != expected:
            raise PhaseEShadowError(f"Binding {key} differs from the frozen Phase D input.")
    if source.get("model_version") != "phase_c_control_components_v1":
        raise PhaseEShadowError("Binding model version is not the Phase C control.")
    if document.get("config") != asdict(ScenarioConfig()):
        raise PhaseEShadowError("Binding sampler configuration is not the frozen default.")
    population = binding._mapping(document.get("population"), "binding.population")
    ids = binding._string_list(population.get("expected_binding_fold_ids"), "binding fold ids")
    if (
        population.get("full_fold_count") != binding.FULL_FOLD_COUNT
        or population.get("history_burn_in_fold_ids") != list(binding.HISTORY_BURN_IN_FOLDS)
        or population.get("direct_control_abstention_fold_ids")
        != list(binding.DIRECT_CONTROL_ABSTENTIONS)
        or len(ids) != binding.BINDING_FOLD_COUNT
        or tuple(sorted(set(ids))) != ids
        or ids[0] != binding.FIRST_BINDING_FOLD
        or ids[-1] != binding.LAST_BINDING_FOLD
        or any(binding._target(fold_id).season not in binding.DECISION_SEASONS for fold_id in ids)
        or any(fold_id in binding.DIRECT_CONTROL_ABSTENTIONS for fold_id in ids)
    ):
        raise PhaseEShadowError("Binding evidence does not name the frozen 137-fold population.")
    verdict = binding._mapping(document.get("verdict"), "binding.verdict")
    status = verdict.get("status")
    if not isinstance(status, str) or status not in COMPONENT_SQUAD_CALIBRATION_STATUSES:
        raise PhaseEShadowError("Binding verdict must be calibrated_internal, failed or abstained.")
    if verdict.get("expected_fold_count") != len(ids):
        raise PhaseEShadowError("Binding verdict population contradicts its recorded population.")
    if status == "calibrated_internal" and (
        verdict.get("fold_count") != len(ids)
        or verdict.get("fold_ids") != list(ids)
        or verdict.get("s1_passes") is not True
        or verdict.get("s2_passes") is not True
    ):
        raise PhaseEShadowError("A calibrated binding verdict requires all folds and both gates.")
    return PhaseDBindingEvidence(
        status, ids, hashlib.sha256(payload).hexdigest(), str(source["model_version"])
    )


def prepare_phase_e_folds(
    handoff: PhaseCComponentHandoff, evidence: PhaseDBindingEvidence, archive_root: Path
) -> tuple[tuple[EvaluationFold, ...], int]:
    """Reuse Phase C preparation; only the binding population can enter the E3 runner."""

    if (
        handoff.table_sha256 != binding.PHASE_C_TABLE_SHA256
        or handoff.roster_sha256 != binding.PHASE_C_ROSTER_SHA256
        or handoff.manifest_sha256 != binding.PHASE_C_MANIFEST_SHA256
    ):
        raise PhaseEShadowError("E3 requires the binding run's exact Phase C handoff.")
    panel = binding._load_development_panel(archive_root)
    controls = build_walk_forward_folds(
        panel,
        seasons=binding.DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    prepared = prepare_phase_c_component_folds(handoff, controls)
    eligible = binding._binding_population(
        [fold.fold_id for fold in prepared], binding.DIRECT_CONTROL_ABSTENTIONS
    )
    if eligible != evidence.fold_ids:
        raise PhaseEShadowError("Prepared Phase C folds disagree with the binding population.")
    return tuple(fold for fold in prepared if fold.fold_id in eligible), len(panel)


def draw_phase_e_fold(
    handoff: PhaseCComponentHandoff, fold: EvaluationFold
) -> ComponentScenarioDraw:
    """Draw every scenario-eligible player once; never narrow the optimizer's pool.

    Direct-control rows have no component prediction and cannot be simulated. They remain
    in the optimizer roster and their candidates are subject to the selector's coverage rule.
    Target outcomes are never passed into the sampler or its residual history.
    """

    target = binding._target(fold.fold_id)
    rows = handoff.rows.loc[
        handoff.rows["fold_id"].eq(fold.fold_id)
        & handoff.rows["composition_route"].eq(COMPONENT_MODEL_ROUTE)
    ].copy(deep=True)
    projections = fold.projections.loc[fold.projections["player_id"].isin(rows["player_id"])].copy(
        deep=True
    )
    if rows.empty or len(rows) != len(projections):
        raise PhaseEShadowError("Component rows must align to the full scenario-eligible pool.")
    rows = rows.sort_values("player_id", kind="stable").reset_index(drop=True)
    projections = projections.sort_values("player_id", kind="stable").reset_index(drop=True)
    rows = rows.merge(projections[["player_id", "team_id"]], on="player_id", validate="one_to_one")
    snapshot = prepare_optimizer_projection(
        projections[["player_id", "name", "team_id", "position", "price_tenths"]],
        projections[["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=handoff.model_version,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            training_cutoff=fold.fold_id,
            training_data_fingerprint=handoff.table_sha256,
        ),
    )
    inputs = ComponentScenarioInputs(
        table=rows[
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
            ]
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
    settings = ScenarioConfig()
    history = handoff.rows.loc[handoff.rows["fold_id"].astype("string") < fold.fold_id]
    residuals = paired_conditional_residuals(
        history, target=target, min_history_folds=settings.min_history_folds
    )
    return sample_component_scenarios(inputs, snapshot, residuals, target, settings)
