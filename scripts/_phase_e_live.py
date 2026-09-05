"""Capture-bound component draws for the in-season E2 diagnostic pools."""

from pathlib import Path

import pandas as pd
from scripts import build_projection_handoff as producer
from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as binding
from scripts._phase_e_inputs import PhaseDBindingEvidence

from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD, live_payload
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.live import InSeasonProjection, infer_season
from squadopt.live.recommendation import project, read_inputs
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import ScenarioConfig, ScenarioTarget
from squadopt.scenarios.components import (
    COMPONENT_INPUT_COLUMNS,
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    paired_conditional_residuals,
    sample_component_scenarios,
)


def live_component_decision(
    capture: CapturedSnapshot,
    projection: InSeasonProjection,
    handoff: PhaseCComponentHandoff,
    archive_root: Path,
    *,
    binding_evidence: PhaseDBindingEvidence,
) -> probe.DecisionPoint:
    """Recover raw components with the existing producer and verify the frozen projection.

    Only the original capture's prior settled event documents are passed to the model.
    The producer reads its explicit development training seasons, never the unrestricted
    opening/blend entry point. Direct-control players stay in the optimizer pool and remain
    uncovered by the sampler. No calibration pin or candidate-count rule is changed here.
    """

    if (
        binding_evidence.status != "calibrated_internal"
        or binding_evidence.model_version != projection.model_version
    ):
        raise probe.ProbeError(
            "The preregistered live draw requires calibrated Phase D binding evidence."
        )
    if projection.season != "2026-27" or projection.gameweek not in (2, 3):
        raise probe.ProbeError("Live component E2 inputs support only 2026-27 GW2 and GW3.")
    if infer_season(capture) != projection.season:
        raise probe.ProbeError("The capture season differs from the frozen projection.")
    if (
        projection.model_version != producer.COMPONENT_MODEL_VERSION
        or projection.feature_contract_version != producer.COMPONENT_FEATURE_CONTRACT_VERSION
        or handoff.model_version != projection.model_version
        or handoff.feature_contract_version != projection.feature_contract_version
    ):
        raise probe.ProbeError("A live component draw requires the frozen Phase C model.")
    if (
        handoff.table_sha256 != binding.PHASE_C_TABLE_SHA256
        or handoff.roster_sha256 != binding.PHASE_C_ROSTER_SHA256
        or handoff.manifest_sha256 != binding.PHASE_C_MANIFEST_SHA256
    ):
        raise probe.ProbeError("Live residuals require the exact frozen Phase C handoff.")
    inputs = read_inputs(capture, season=projection.season)
    # Inferring the open deadline also prevents a later capture being used for an older GW.
    pool = project(inputs, in_season=projection).table.loc[:, list(probe.POOL_COLUMNS)].copy()
    weeks = range(
        max(1, projection.gameweek - producer.COMPONENT_HISTORY_WINDOW), projection.gameweek
    )
    missing = [week for week in weeks if live_payload(week) not in capture.payloads]
    if missing:
        raise probe.ProbeError(
            f"Original capture lacks settled live history for gameweeks {missing}."
        )
    if FIXTURES_PAYLOAD not in capture.payloads:
        raise probe.ProbeError("Original capture lacks its fixture payload.")
    frozen = pd.DataFrame(
        {
            "player_id": list(projection.expected_points),
            "expected_points": list(projection.expected_points.values()),
        }
    )
    try:
        components, diagnostics = producer._component_table(
            archive_root,
            bootstrap=capture.payloads[BOOTSTRAP_PAYLOAD],
            fixtures=capture.payloads[FIXTURES_PAYLOAD],
            event_payloads={week: capture.payloads[live_payload(week)] for week in weeks},
            season=projection.season,
            target=projection.gameweek,
            source_snapshot_id=projection.source_snapshot_id,
            captured_at_utc=capture.metadata.captured_at_utc,
            deadline_utc=inputs.deadline.deadline_utc,
            fallback=frozen,
            include_components=True,
        )
    except SystemExit as error:
        raise probe.ProbeError(str(error)) from error
    if (
        not projection.diagnostics.get("component_fingerprint")
        or diagnostics["component_fingerprint"] != projection.diagnostics["component_fingerprint"]
    ):
        raise probe.ProbeError("Rebuilt components differ from the original handoff fingerprint.")
    rebuilt = components.set_index("player_id")["expected_points"].sort_index()
    original = frozen.set_index("player_id")["expected_points"].sort_index()
    if not rebuilt.equals(original):
        raise probe.ProbeError("Rebuilt component means differ from the frozen projection.")
    eligible = components.loc[components["composition_route"].eq(COMPONENT_MODEL_ROUTE)]
    joined = eligible.merge(pool, on="player_id", suffixes=("_raw", ""), validate="one_to_one")
    joined = joined.sort_values("player_id", kind="stable").reset_index(drop=True)
    if joined.empty:
        raise probe.ProbeError("No component-eligible players remain in the live decision pool.")
    table = joined.loc[:, list(COMPONENT_INPUT_COLUMNS)]
    snapshot = prepare_optimizer_projection(
        joined.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        joined.loc[:, ["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=projection.model_name,
            model_version=projection.model_version,
            feature_contract_version=projection.feature_contract_version,
            training_cutoff=str(diagnostics["component_training_cutoff"]),
            training_data_fingerprint=str(diagnostics["component_training_data_fingerprint"]),
        ),
    )
    target = ScenarioTarget(season=projection.season, gameweek=projection.gameweek)
    history = handoff.rows.loc[
        handoff.rows["season"].astype("string").isin(binding.DECISION_SEASONS)
    ]
    residuals = paired_conditional_residuals(
        history, target=target, min_history_folds=ScenarioConfig().min_history_folds
    )

    def factory(seed: int) -> ComponentScenarioDraw:
        scenario_inputs = ComponentScenarioInputs(
            table=table,
            provenance=ComponentScenarioProvenance(
                phase_c_table_sha=handoff.table_sha256,
                roster_sha=handoff.roster_sha256,
                model_version=projection.model_version,
                feature_contract_version=projection.feature_contract_version,
                target_contract_version=handoff.target_contract_version,
                dataset_contract_version=handoff.dataset_contract_version,
                season=target.season,
                target_gameweek=target.gameweek,
                deterministic_seed=seed,
            ),
        )
        return sample_component_scenarios(
            scenario_inputs, snapshot, residuals, target, ScenarioConfig(deterministic_seed=seed)
        )

    return probe.DecisionPoint(
        label=f"{projection.season}-gw{projection.gameweek:02d}",
        kind="live",
        pool=pool,
        draw_factory=factory,
        covered_player_ids=frozenset(int(value) for value in joined["player_id"]),
        source={
            "snapshot_id": projection.source_snapshot_id,
            "captured_at_utc": capture.metadata.captured_at_utc,
            "deadline_utc": inputs.deadline.deadline_utc,
            "projection_fingerprint": projection.fingerprint,
            "component_prediction_fingerprint": str(diagnostics["component_fingerprint"]),
            "binding_artifact_sha256": binding_evidence.sha256,
        },
    )
