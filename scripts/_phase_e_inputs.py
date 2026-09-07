"""Verified Phase D evidence and historical full-pool inputs for the E3 runner."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts import run_component_squad_calibration as binding

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationFold,
    prepare_phase_c_component_folds,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments.component_squad_calibration import (
    COMPONENT_SQUAD_CALIBRATION_STATUSES,
    ComponentCalibrationFold,
    evaluate_component_squad_calibration,
)
from squadopt.experiments.phase_e_shadow import PhaseEShadowError
from squadopt.features import CrossSeasonConfig
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    ConditionalResidualConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)
from squadopt.scenarios.decision_scoring import (
    COMPONENT_DECISION_SCORING_CONTRACT_VERSION,
    ComponentDecisionDistributionReadout,
)


@dataclass(frozen=True, slots=True)
class PhaseDBindingEvidence:
    """A Phase D verdict, fixed population, digest and sampler to carry into the E3 artifact.

    ``binding`` is False only for the candidate-sampler development evidence loaded by
    ``load_phase_d_candidate``; ``sampler_contract_version`` names the sampler the evidence
    calibrated, and the E3 draw must declare the same one.
    """

    status: str
    fold_ids: tuple[str, ...]
    sha256: str
    model_version: str
    binding: bool = True
    sampler_contract_version: str = COMPONENT_SCENARIO_CONTRACT_VERSION
    development_contract: str | None = None
    phase_c_source: dict[str, object] | None = None
    phase_c_producer: str | None = None
    history_seasons: tuple[str, ...] = ()
    history_eligible_fold_ids: tuple[str, ...] = ()
    history_burn_in_fold_ids: tuple[str, ...] = ()
    direct_control_fold_ids: tuple[str, ...] = ()
    control_identities: dict[str, dict] | None = None


def _phase_d_document(path: Path, *, contract_version: str, label: str) -> tuple[dict, bytes]:
    payload = path.read_bytes()
    document = binding._mapping(json.loads(payload), label)
    binding._finite_numbers(document, label)
    if (
        document.get("contract_version") != contract_version
        or document.get("evaluation_contract_version")
        != binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION
        or document.get("locked_holdout_accessed") is not False
        or document.get("operational_control_changed") is not False
        or document.get("internal_only") is not True
    ):
        raise PhaseEShadowError(f"Phase D evidence is not the internal {label}.")
    return dict(document), payload


def load_phase_d_binding(path: Path) -> PhaseDBindingEvidence:
    """Require binding evidence before loading historical inputs or evaluating anything."""

    document, payload = _phase_d_document(
        path, contract_version=binding.REPORT_VERSION, label="binding artifact"
    )
    if document.get("binding", True) is not True or document.get("candidate") is not None:
        raise PhaseEShadowError("Phase D binding evidence must not carry a candidate sampler.")
    return _phase_d_evidence(document, payload)


def load_phase_d_candidate(
    path: Path, *, conditional_residuals: ConditionalResidualConfig
) -> PhaseDBindingEvidence:
    """Development evidence for exactly this candidate sampler; never a binding verdict.

    The candidate report keeps the binding population, inputs and gates but declares
    ``binding: false`` and its sampler settings. It is accepted only when those settings are
    the ones the E3 development run will draw with, so evidence and draw name one sampler.
    """

    document, payload = _phase_d_document(
        path, contract_version=binding.CANDIDATE_REPORT_VERSION, label="candidate artifact"
    )
    expected = {
        "sampler_contract_version": conditional_residuals.contract_version,
        "conditional_residual_fraction": conditional_residuals.fraction,
        "conditional_residual_minimum_rows": conditional_residuals.minimum_rows,
        "reference_contract_version": binding.REPORT_VERSION,
        "development_data_only": True,
        "binding": False,
    }
    if document.get("binding") is not False or document.get("candidate") != expected:
        raise PhaseEShadowError(
            "Phase D candidate evidence must declare binding: false and exactly the requested "
            "conditional residual settings."
        )
    folds = document.get("folds")
    if not isinstance(folds, list) or any(
        not isinstance(fold, dict)
        or fold.get("sampler_contract_version") != conditional_residuals.contract_version
        for fold in folds
    ):
        raise PhaseEShadowError("Every candidate fold must record the candidate sampler.")
    evidence = _phase_d_evidence(document, payload)
    return PhaseDBindingEvidence(
        evidence.status,
        evidence.fold_ids,
        evidence.sha256,
        evidence.model_version,
        binding=False,
        sampler_contract_version=conditional_residuals.contract_version,
    )


def _phase_d_evidence(document: dict, payload: bytes) -> PhaseDBindingEvidence:
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


def load_phase_d_development(
    path: Path,
    *,
    development: binding.DevelopmentInputs,
    conditional_residuals: ConditionalResidualConfig,
) -> PhaseDBindingEvidence:
    """Accept a complete v2 reading on the pinned A reference, never a selected pilot.

    Fold membership is checked again against the handoff during preparation. The recorded
    verdict is recomputed from its fold readings so its label cannot authorize selection.
    """

    payload = path.read_bytes()
    document = binding._mapping(json.loads(payload), "Phase D v2")
    binding._finite_numbers(document, "Phase D v2")
    if (
        document.get("contract_version") != binding.DEVELOPMENT_REPORT_VERSION
        or document.get("evaluation_contract_version")
        != binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION
        or document.get("binding") is not False
        or document.get("development_only") is not True
        or document.get("internal_only") is not True
        or document.get("operational_control_changed") is not False
        or document.get("member_facing_probability_published") is not False
        or document.get("config") != asdict(ScenarioConfig())
        or document.get("solver_profile") != binding._solver_profile()
        or document.get("candidate")
        != binding._candidate_record(
            conditional_residuals, reference=binding.DEVELOPMENT_REPORT_VERSION
        )
        or document.get("sampler_contract_version") != conditional_residuals.contract_version
        or document.get("sampler_fidelity_verified") is not True
    ):
        raise PhaseEShadowError(
            "Phase D v2 must be verified development evidence for this sampler/config."
        )
    provenance = binding._mapping(document.get("provenance"), "Phase D v2 provenance")
    if provenance.get("working_tree_dirty") is not False or not re.fullmatch(
        r"[0-9a-f]{40}", str(provenance.get("repository_commit", ""))
    ):
        raise PhaseEShadowError("Phase D v2 must name a clean repository revision.")
    source = binding._mapping(document.get("source"), "Phase D v2 source")
    for name in ("table_sha256", "roster_sha256", "manifest_sha256"):
        if source.get(name) != getattr(development, name):
            raise PhaseEShadowError(f"Phase D v2 {name} differs from the pinned A reference.")
    if (
        source.get("phase_c_contract") != DEVELOPMENT_OOF_CONTRACT_VERSION
        or source.get("phase_c_weighting") != "equal_weights_v1"
        or source.get("model_version") != "phase_c_control_components_v1"
        or source.get("pinned_by_arguments") is not True
        or source.get("fidelity_contract_version") != binding.DEVELOPMENT_FIDELITY_VERSION
        or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("fidelity_artifact_sha256", "")))
    ):
        raise PhaseEShadowError(
            "Phase D v2 must name the A reference and its verified fidelity record."
        )
    population = binding._mapping(document.get("population"), "Phase D v2 population")

    def ordered_ids(name: str) -> tuple[str, ...]:
        ids = binding._string_list(population.get(name), name)
        if tuple(sorted(set(ids))) != ids:
            raise PhaseEShadowError(f"Phase D v2 {name} must contain unique ordered folds.")
        return ids

    ids = ordered_ids("measured_fold_ids")
    verdict_population = ordered_ids("verdict_population_fold_ids")
    evaluated = ordered_ids("evaluated_fold_ids")
    burn_in = ordered_ids("history_burn_in_fold_ids")
    direct = ordered_ids("direct_control_abstention_fold_ids")
    seasons = binding._string_list(population.get("history_seasons"), "history seasons")
    if (
        population.get("requested_fold_ids") is not None
        or population.get("unsolved_fold_ids") != []
        or population.get("unscored_fold_ids") != []
        or not ids
        or ids != verdict_population
        or set(ids) & set(direct)
        or tuple(sorted((*ids, *direct))) != evaluated
        or set(evaluated) & set(burn_in)
        or population.get("history_eligible_fold_count") != len(evaluated)
        or population.get("full_fold_count") != len(evaluated) + len(burn_in)
        or population.get("min_history_folds") != ScenarioConfig().min_history_folds
        or source.get("fidelity_measured_fold_count") != len(evaluated)
        or not seasons
        or tuple(season for season in binding.DEVELOPMENT_HISTORY_SEASONS if season in seasons)
        != seasons
        or seasons[0] != binding.DEVELOPMENT_HISTORY_SEASONS[0]
        or population.get("decision_seasons") != list(seasons[1:])
        or document.get("locked_holdout_accessed") is not ("2025-26" in seasons)
        or any(
            binding._target(fold_id).season not in seasons[1:] for fold_id in (*evaluated, *burn_in)
        )
    ):
        raise PhaseEShadowError(
            "Phase D v2 must cover the complete population, without pilot or failed folds."
        )
    records = document.get("folds")
    if (
        not isinstance(records, list)
        or tuple(binding._mapping(record, "Phase D v2 fold").get("fold_id") for record in records)
        != ids
    ):
        raise PhaseEShadowError("Phase D v2 fold records disagree with the population.")
    readings = []
    identities = {}
    for record in records:
        numeric_fields = (
            "scenario_mean_score",
            "scenario_standard_deviation",
            "q10_score",
            "realized_score",
            "probability_integral_transform",
        )
        if (
            any(type(record.get(name)) not in (int, float) for name in numeric_fields)
            or not isinstance(record.get("realized_below_q10"), bool)
            or record["realized_below_q10"] != (record["realized_score"] < record["q10_score"])
            or record["scenario_standard_deviation"] < 0
            or any(
                not isinstance(record.get(name), str) or not record[name]
                for name in ("scenario_fingerprint", "component_fingerprint")
            )
        ):
            raise PhaseEShadowError(
                "Phase D v2 folds require complete numeric distribution readings."
            )
        if record.get(
            "sampler_contract_version"
        ) != conditional_residuals.contract_version or record.get("solver_status") not in (
            "OPTIMAL",
            "FEASIBLE",
        ):
            raise PhaseEShadowError(
                "Phase D v2 folds require solved controls and the declared sampler."
            )
        identity = dict(binding._mapping(record.get("decision_identity"), "D control identity"))
        digest = identity.pop("sha256", None)
        if (
            digest
            != hashlib.sha256(
                json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        ):
            raise PhaseEShadowError("Phase D v2 control identity digest differs from its decision.")
        identities[record["fold_id"]] = {**identity, "sha256": digest}
        readings.append(
            ComponentCalibrationFold(
                record["fold_id"],
                ComponentDecisionDistributionReadout(
                    scenario_count=1000,
                    mean_score=record["scenario_mean_score"],
                    score_standard_deviation=record["scenario_standard_deviation"],
                    lower_quantile_probability=0.1,
                    lower_quantile_score=record["q10_score"],
                    realized_score=record["realized_score"],
                    probability_integral_transform=record["probability_integral_transform"],
                    realized_below_lower_quantile=record["realized_below_q10"],
                    scenario_fingerprint=record["scenario_fingerprint"],
                    component_fingerprint=record["component_fingerprint"],
                    decision_scoring_contract_version=COMPONENT_DECISION_SCORING_CONTRACT_VERSION,
                ),
            )
        )
    verdict = asdict(
        evaluate_component_squad_calibration(
            readings, expected_fold_ids=verdict_population, sampler_fidelity_verified=True
        )
    )
    # JSON converts the evaluator's tuple of fold IDs to a list.
    if json.loads(json.dumps(verdict)) != document.get("verdict"):
        raise PhaseEShadowError("Phase D v2 verdict contradicts its recorded S1/S2 readings.")
    phase_c_source = {
        key: source.get(key)
        for key in (
            "table_sha256",
            "roster_sha256",
            "manifest_sha256",
            "model_version",
            "feature_contract_version",
            "target_contract_version",
            "dataset_contract_version",
        )
    }
    phase_c_source.update(
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION, weighting=source["phase_c_weighting"]
    )
    return PhaseDBindingEvidence(
        str(verdict["status"]),
        ids,
        hashlib.sha256(payload).hexdigest(),
        str(source["model_version"]),
        binding=False,
        sampler_contract_version=conditional_residuals.contract_version,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        phase_c_source=phase_c_source,
        phase_c_producer=str(source.get("producer_repository_commit")),
        history_seasons=seasons,
        history_eligible_fold_ids=evaluated,
        history_burn_in_fold_ids=burn_in,
        direct_control_fold_ids=direct,
        control_identities=identities,
    )


def prepare_phase_e_folds(
    handoff: PhaseCComponentHandoff, evidence: PhaseDBindingEvidence, archive_root: Path
) -> tuple[tuple[EvaluationFold, ...], int]:
    """Reuse Phase C preparation; only the binding population can enter the E3 runner."""

    if evidence.development_contract is not None:
        return _prepare_development_folds(handoff, evidence, archive_root)
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


def _prepare_development_folds(
    handoff: PhaseCComponentHandoff, evidence: PhaseDBindingEvidence, archive_root: Path
) -> tuple[tuple[EvaluationFold, ...], int]:
    observed = {
        key: getattr(handoff, key)
        for key in (
            "table_sha256",
            "roster_sha256",
            "manifest_sha256",
            "development_contract",
            "model_version",
            "feature_contract_version",
            "target_contract_version",
            "dataset_contract_version",
            "weighting",
        )
    }
    if (
        observed != evidence.phase_c_source
        or handoff.repository_commit != evidence.phase_c_producer
    ):
        raise PhaseEShadowError("E3 handoff does not match the Phase D v2 reference.")
    panel = binding._load_development_panel(archive_root, evidence.history_seasons)
    controls = build_walk_forward_folds(
        panel,
        seasons=evidence.history_seasons[1:],
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    prepared = prepare_phase_c_component_folds(
        handoff, controls, development_contract=evidence.development_contract
    )
    burn_in, eligible = binding._development_population(
        handoff.rows,
        tuple(fold.fold_id for fold in prepared),
        min_history_folds=ScenarioConfig().min_history_folds,
    )
    if (
        burn_in != evidence.history_burn_in_fold_ids
        or eligible != evidence.history_eligible_fold_ids
    ):
        raise PhaseEShadowError("Prepared C v2 folds disagree with the Phase D v2 population.")
    return tuple(fold for fold in prepared if fold.fold_id in evidence.fold_ids), len(panel)


def draw_phase_e_fold(
    handoff: PhaseCComponentHandoff,
    fold: EvaluationFold,
    *,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> ComponentScenarioDraw:
    """Draw every scenario-eligible player once; never narrow the optimizer's pool.

    Direct-control rows have no component prediction and cannot be simulated. They remain
    in the optimizer roster and their candidates are subject to the selector's coverage rule.
    Target outcomes are never passed into the sampler or its residual history. With
    ``conditional_residuals`` given, the draw uses the candidate sampler and declares it.
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
            development_contract=handoff.development_contract,
        ),
    )
    settings = ScenarioConfig()
    history = handoff.rows.loc[handoff.rows["fold_id"].astype("string") < fold.fold_id]
    residuals = paired_conditional_residuals(
        history, target=target, min_history_folds=settings.min_history_folds
    )
    return sample_component_scenarios(
        inputs,
        snapshot,
        residuals,
        target,
        settings,
        conditional_residuals=conditional_residuals,
    )
