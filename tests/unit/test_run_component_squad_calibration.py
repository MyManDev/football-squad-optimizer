"""Tests for the Phase D binding-run orchestration guards."""

import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from scripts.run_component_squad_calibration import (
    BINDING_FOLD_COUNT,
    CANDIDATE_REPORT_VERSION,
    DEFAULT_OUTPUT,
    DIRECT_CONTROL_ABSTENTIONS,
    HISTORY_BURN_IN_FOLDS,
    PHASE_C_MANIFEST_SHA256,
    PHASE_C_ROSTER_SHA256,
    PHASE_C_TABLE_SHA256,
    REPORT_VERSION,
    BindingCalibrationError,
    _binding_population,
    _candidate_from_arguments,
    _candidate_record,
    _load_verified_fidelity,
    _measure_fold,
    _report_contract_version,
    _selected_component_inputs,
)

from squadopt.evaluation import EvaluationFold
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ConditionalResidualConfig,
)


def _all_fold_ids() -> tuple[str, ...]:
    return (
        *(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2022-23-gw{gameweek:02d}" for gameweek in range(2, 39) if gameweek != 7),
        *(f"2023-24-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2024-25-gw{gameweek:02d}" for gameweek in range(2, 39)),
    )


def _handoff() -> PhaseCComponentHandoff:
    return PhaseCComponentHandoff(
        rows=pd.DataFrame({"fold_id": _all_fold_ids()}),
        roster=pd.DataFrame(),
        table_sha256=PHASE_C_TABLE_SHA256,
        roster_sha256=PHASE_C_ROSTER_SHA256,
        manifest_sha256=PHASE_C_MANIFEST_SHA256,
        repository_commit="d" * 40,
        model_version="component-v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )


def _fidelity_document() -> dict[str, object]:
    measured = _all_fold_ids()[len(HISTORY_BURN_IN_FOLDS) :]
    return {
        "contract_version": "phase_d_component_fidelity_v1",
        "diagnostic_only": True,
        "promotes_anything": False,
        "registers_any_threshold": False,
        "config": {
            "scenario_count": 1_000,
            "deterministic_seed": 0,
            "min_history_folds": 8,
        },
        "population": {
            "fold_count_total": 147,
            "fold_count_excluded": 9,
            "fold_count_measured": 138,
            "locked_holdout_season": "2025-26",
            "locked_holdout_rows_present": 0,
            "measured_fold_ids": list(measured),
        },
        "provenance": {
            "working_tree_dirty": False,
            "manifest_locked_holdout_read": False,
            "manifest_table_sha256": PHASE_C_TABLE_SHA256,
            "oof_table_sha256": PHASE_C_TABLE_SHA256,
            "manifest_roster_sha256": PHASE_C_ROSTER_SHA256,
            "roster_sha256": PHASE_C_ROSTER_SHA256,
            "manifest_sha256": PHASE_C_MANIFEST_SHA256,
            "model_version": "component-v1",
            "feature_contract_version": "features-v1",
        },
        "excluded_folds": [
            {"fold_id": fold_id, "reason": "burn-in"} for fold_id in HISTORY_BURN_IN_FOLDS
        ],
        "folds": [{"fold_id": fold_id, "mean": 1.0} for fold_id in measured],
        "warnings": [],
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_fidelity(path: Path, value: object, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_json(path, value)
    # Unit tests exercise structure with a compact fixture; patching the digest avoids copying
    # the 6,135-line measured artifact into a second test fixture.
    from scripts import run_component_squad_calibration as runner

    monkeypatch.setattr(runner, "FIDELITY_ARTIFACT_SHA256", runner._sha256(path))


def test_verified_fidelity_is_bound_to_the_phase_c_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, _fidelity_document(), monkeypatch)

    digest = _load_verified_fidelity(path, _handoff())

    assert len(digest) == 64


def test_fidelity_from_a_different_phase_c_table_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _fidelity_document()
    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    provenance["oof_table_sha256"] = "e" * 64
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, document, monkeypatch)

    with pytest.raises(BindingCalibrationError, match="does not describe"):
        _load_verified_fidelity(path, _handoff())


def test_non_finite_fidelity_reading_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _fidelity_document()
    folds = document["folds"]
    assert isinstance(folds, list)
    assert isinstance(folds[0], dict)
    folds[0]["mean"] = float("nan")
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, document, monkeypatch)

    with pytest.raises(BindingCalibrationError, match="non-finite"):
        _load_verified_fidelity(path, _handoff())


def test_binding_population_is_exactly_the_preregistered_137_folds() -> None:
    eligible = _binding_population(_all_fold_ids(), DIRECT_CONTROL_ABSTENTIONS)

    assert len(eligible) == BINDING_FOLD_COUNT
    assert eligible[0] == "2021-22-gw11"
    assert eligible[-1] == "2024-25-gw38"
    assert "2021-22-gw15" not in eligible


def test_a_different_direct_control_abstention_is_rejected() -> None:
    with pytest.raises(BindingCalibrationError, match="direct-control"):
        _binding_population(_all_fold_ids(), ("2021-22-gw16",))


def test_a_missing_middle_fold_cannot_silently_change_the_denominator() -> None:
    fold_ids = list(_all_fold_ids())
    fold_ids.remove("2023-24-gw20")

    with pytest.raises(BindingCalibrationError, match="OOF fold population"):
        _binding_population(fold_ids, DIRECT_CONTROL_ABSTENTIONS)


def test_selected_component_inputs_align_the_same_fifteen_players() -> None:
    fold_id = "2021-22-gw11"
    ids = list(range(1, 16))
    rows = pd.DataFrame(
        {
            "fold_id": [fold_id] * 15,
            "player_id": ids,
            "position": ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)],
            "fixture_count": [1] * 15,
            "appearance_probability": [0.8] * 15,
            "expected_minutes_if_appearance": [60.0] * 15,
            "raw_expected_points_if_appearance": [3.0] * 15,
            "composition_route": [COMPONENT_MODEL_ROUTE] * 15,
            "evidence_status": ["not_requested"] * 15,
        }
    )
    handoff = PhaseCComponentHandoff(
        rows=rows,
        roster=pd.DataFrame(),
        table_sha256="a" * 64,
        roster_sha256="b" * 64,
        manifest_sha256="c" * 64,
        repository_commit="d" * 40,
        model_version="component-v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )
    projections = pd.DataFrame(
        {
            "player_id": list(reversed(ids)),
            "name": [f"Player {player_id}" for player_id in reversed(ids)],
            "team_id": [f"T{player_id // 3}" for player_id in reversed(ids)],
            "position": list(
                reversed(["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)])
            ),
            "price_tenths": [50] * 15,
            "expected_points": [2.0] * 15,
        }
    )
    candidate = EvaluationFold(
        fold_id=fold_id,
        projections=projections,
        realized_points=pd.DataFrame({"player_id": ids, "total_points": [0.0] * 15}),
    )

    inputs, snapshot = _selected_component_inputs(handoff, candidate, ids)

    assert inputs.player_ids == tuple(ids)
    assert tuple(snapshot.table["player_id"]) == tuple(ids)
    assert tuple(inputs.table["team_id"]) == tuple(snapshot.table["team_id"])


def _arguments(fraction: object, minimum_rows: object, output: Path) -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        conditional_residual_fraction=fraction,
        conditional_residual_minimum_rows=minimum_rows,
        json_output=output,
    )


def test_candidate_mode_needs_both_controls_and_its_own_output_path(tmp_path: Path) -> None:
    assert _candidate_from_arguments(_arguments(None, None, DEFAULT_OUTPUT)) is None
    with pytest.raises(BindingCalibrationError):
        _candidate_from_arguments(_arguments(0.15, None, tmp_path / "candidate.json"))
    with pytest.raises(BindingCalibrationError):
        _candidate_from_arguments(_arguments(0.15, 30, DEFAULT_OUTPUT))
    candidate = _candidate_from_arguments(_arguments(0.15, 30, tmp_path / "candidate.json"))
    assert candidate is not None
    assert (candidate.fraction, candidate.minimum_rows) == (0.15, 30)


def test_a_candidate_report_never_carries_the_binding_contract() -> None:
    candidate = _candidate_from_arguments(_arguments(0.15, 30, Path("candidate.json")))
    assert _report_contract_version(None) == REPORT_VERSION
    assert _report_contract_version(candidate) == CANDIDATE_REPORT_VERSION
    assert CANDIDATE_REPORT_VERSION != REPORT_VERSION


def _squad_positions() -> dict[int, str]:
    return {
        1: "GK",
        2: "GK",
        3: "DEF",
        4: "DEF",
        5: "DEF",
        6: "DEF",
        7: "DEF",
        8: "MID",
        9: "MID",
        10: "MID",
        11: "MID",
        12: "MID",
        13: "FWD",
        14: "FWD",
        15: "FWD",
    }


def _component_rows(fold_ids: Sequence[str]) -> pd.DataFrame:
    """Phase C rows for one squad across folds: history folds feed the residual pool."""

    records: list[dict[str, object]] = []
    for fold_index, fold_id in enumerate(fold_ids):
        for player_id, position in _squad_positions().items():
            expectation = 0.5 * player_id
            records.append(
                {
                    "fold_id": fold_id,
                    "player_id": player_id,
                    "position": position,
                    "fixture_count": 1,
                    "appearance_probability": 0.9,
                    "expected_minutes_if_appearance": 70.0,
                    "raw_expected_points_if_appearance": expectation,
                    "composition_route": COMPONENT_MODEL_ROUTE,
                    "evidence_status": "not_requested",
                    "appearance_target": 1,
                    "minutes_target": 70.0 + ((player_id + fold_index) % 5) * 4.0,
                    "points_target": expectation + ((player_id * 3 + fold_index) % 7) - 3.0,
                }
            )
    return pd.DataFrame(records)


def _frozen_decision() -> tuple[PhaseCComponentHandoff, EvaluationFold, OptimizationResult]:
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    handoff = PhaseCComponentHandoff(
        rows=_component_rows((*history, fold_id)),
        roster=pd.DataFrame(),
        table_sha256="a" * 64,
        roster_sha256="b" * 64,
        manifest_sha256="c" * 64,
        repository_commit="d" * 40,
        model_version="component-v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )
    positions = _squad_positions()
    squad = pd.DataFrame(
        {
            "player_id": list(positions),
            "name": [f"Player {player_id}" for player_id in positions],
            "team_id": [f"T{(player_id - 1) // 3}" for player_id in positions],
            "position": list(positions.values()),
            "price_tenths": [50] * len(positions),
            "expected_points": [0.45 * player_id for player_id in positions],
        }
    )
    starters = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    result = OptimizationResult(
        solver_status=SolverStatus.OPTIMAL,
        selected_squad=squad,
        starting_xi=squad.loc[squad["player_id"].isin(starters)].copy(),
        bench=squad.loc[~squad["player_id"].isin(starters)].copy(),
        captain=squad.loc[squad["player_id"] == 15].iloc[0].copy(),
        total_cost_tenths=750,
        projected_score=0.0,
        objective_value=0.0,
        diagnostics={},
    )
    prepared = EvaluationFold(
        fold_id=fold_id,
        projections=squad,
        realized_points=pd.DataFrame(
            {"player_id": list(positions), "total_points": [2.0] * len(positions)}
        ),
    )
    return handoff, prepared, result


def test_measure_fold_draws_on_the_sampler_the_run_asked_for() -> None:
    """Regression: the sampler setting reached the draw as a prepared fold once, and was refused."""

    handoff, prepared, result = _frozen_decision()
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())

    frozen_reading, frozen = _measure_fold(
        handoff, prepared, result, 40.0, selected, settings, None
    )
    candidate_reading, candidate = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        selected,
        settings,
        ConditionalResidualConfig(fraction=0.25, minimum_rows=4),
    )

    assert frozen["sampler_contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION
    assert candidate["sampler_contract_version"] == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    assert frozen["scenario_fingerprint"] != candidate["scenario_fingerprint"]
    assert frozen_reading.fold_id == candidate_reading.fold_id == prepared.fold_id
    assert frozen["realized_score"] == candidate["realized_score"] == 40.0


def test_candidate_record_names_the_candidate_sampler_and_nothing_for_the_binding_one() -> None:
    assert _candidate_record(None) is None
    record = _candidate_record(ConditionalResidualConfig(fraction=0.15, minimum_rows=30))
    assert record is not None
    assert record["sampler_contract_version"] == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    assert record["reference_contract_version"] == REPORT_VERSION
    assert record["binding"] is False
