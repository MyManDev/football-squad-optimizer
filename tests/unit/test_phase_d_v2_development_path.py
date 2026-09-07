"""Tests for the Phase D v2 development binding to the Phase C v2 equal-weight reference.

The v1 binding path must be untouched; the development path must be chosen by name, bound
to the pinned A artifacts, refuse the season-weighted B arm and any digest drift, compute its
population from the handoff under the preregistered rule, admit a 2025-26 decision only
through a development handoff, and carry the decision identity a repeat can be compared to.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts import run_component_squad_calibration as runner
from scripts.measure_component_fidelity import measure_fidelity, provenance_block
from scripts.run_component_squad_calibration import (
    CANDIDATE_REPORT_VERSION,
    DEFAULT_OUTPUT,
    DEVELOPMENT_FIDELITY_VERSION,
    DEVELOPMENT_REPORT_VERSION,
    HISTORY_BURN_IN_FOLDS,
    REPORT_VERSION,
    BindingCalibrationError,
    DevelopmentInputs,
    _candidate_record,
    _decision_identity,
    _development_from_arguments,
    _development_observation,
    _development_population,
    _load_verified_development_fidelity,
    _measure_development,
    _measure_fold,
    _read_handoff,
    _report_contract_version,
    _sampler_record,
    _selected_component_inputs,
    _solver_profile,
    main,
)

from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationFold,
    EvaluationValidationError,
    complete_optimization_decision,
    prepare_phase_c_component_folds,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments import ComponentCalibrationFold
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHTED_MODEL_VERSION,
)
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE
from squadopt.scenarios import ScenarioConfig, ScenarioTarget
from squadopt.scenarios.components import (
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ComponentScenarioProvenance,
    ConditionalResidualConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)
from squadopt.scenarios.models import ScenarioValidationError

LOCKED = "2025-26"
TABLE = "1" * 64
ROSTER = "2" * 64
MANIFEST = "3" * 64


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
                    "season": fold_id[:7],
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


def _handoff(
    rows: pd.DataFrame,
    *,
    development: bool,
    weighting: str | None = None,
    model_version: str = COMPONENT_MODEL_VERSION,
    table: str = TABLE,
) -> PhaseCComponentHandoff:
    return PhaseCComponentHandoff(
        rows=rows,
        roster=pd.DataFrame(),
        table_sha256=table,
        roster_sha256=ROSTER,
        manifest_sha256=MANIFEST,
        repository_commit="d" * 40,
        model_version=model_version,
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION if development else None,
        weighting=(EQUAL_WEIGHTING if weighting is None else weighting) if development else None,
    )


def _frozen_decision(fold_id: str) -> tuple[EvaluationFold, OptimizationResult]:
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
    return prepared, result


def _history_before(fold_id: str, season: str, count: int = 9) -> tuple[str, ...]:
    """``count`` history folds of ``season`` that sort strictly before ``fold_id``."""

    return tuple(f"{season}-gw{gameweek:02d}" for gameweek in range(30, 30 + count))


def _provenance(**overrides: object) -> ComponentScenarioProvenance:
    fields: dict[str, object] = {
        "phase_c_table_sha": TABLE,
        "roster_sha": ROSTER,
        "model_version": COMPONENT_MODEL_VERSION,
        "feature_contract_version": "features-v1",
        "target_contract_version": "targets-v1",
        "dataset_contract_version": "dataset-v1",
        "season": "2024-25",
        "target_gameweek": 2,
        "deterministic_seed": 0,
    }
    fields.update(overrides)
    return ComponentScenarioProvenance(**fields)  # type: ignore[arg-type]


# --- sampler ------------------------------------------------------------------------------


def test_the_sampler_admits_the_development_season_only_by_the_named_contract() -> None:
    with pytest.raises(ScenarioValidationError, match="locked holdout"):
        _provenance(season=LOCKED)
    with pytest.raises(ScenarioValidationError, match="Unsupported development contract"):
        _provenance(season=LOCKED, development_contract="phase_c_component_oof_v3")

    admitted = _provenance(season=LOCKED, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION)

    assert admitted.development_contract == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert _provenance().development_contract is None


def test_a_development_draw_carries_the_contract_in_its_identity() -> None:
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    rows = _component_rows((*history, fold_id))
    prepared, result = _frozen_decision(fold_id)
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())

    _, frozen = _measure_fold(
        _handoff(rows, development=False), prepared, result, 40.0, selected, settings, None
    )
    _, development = _measure_fold(
        _handoff(rows, development=True),
        prepared,
        result,
        40.0,
        selected,
        settings,
        None,
        development=True,
    )

    assert frozen["realized_score"] == development["realized_score"] == 40.0
    assert frozen["component_fingerprint"] != development["component_fingerprint"]
    assert "decision_identity" not in frozen
    assert development["decision_identity"]["captain"] == 15
    assert development["residual_history_folds"] == len(history)
    assert development["measure_seconds"] >= 0.0


def test_a_2025_26_decision_is_measurable_only_through_a_development_handoff() -> None:
    fold_id = f"{LOCKED}-gw02"
    rows = _component_rows((*_history_before(fold_id, "2024-25"), fold_id))
    prepared, result = _frozen_decision(fold_id)
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())

    with pytest.raises(ScenarioValidationError, match="locked holdout"):
        _measure_fold(
            _handoff(rows, development=False), prepared, result, 40.0, selected, settings, None
        )

    reading, record = _measure_fold(
        _handoff(rows, development=True),
        prepared,
        result,
        40.0,
        selected,
        settings,
        ConditionalResidualConfig(fraction=0.25, minimum_rows=4),
        development=True,
    )

    assert reading.fold_id == fold_id
    assert record["sampler_contract_version"] == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    assert record["solver_status"] == "OPTIMAL"
    assert 0.0 <= record["probability_integral_transform"] <= 1.0


# --- decision folds ------------------------------------------------------------------------


def test_prepare_folds_admits_a_development_handoff_only_when_the_caller_names_it() -> None:
    rows = _component_rows(("2021-22-gw11",))

    with pytest.raises(EvaluationValidationError, match="contract mismatch"):
        prepare_phase_c_component_folds(_handoff(rows, development=True), [])
    with pytest.raises(EvaluationValidationError, match="contract mismatch"):
        prepare_phase_c_component_folds(
            _handoff(rows, development=False),
            [],
            development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        )
    # Past the contract guard, the next refusal is the ordinary control-order check.
    with pytest.raises(EvaluationValidationError, match="at least one EvaluationFold"):
        prepare_phase_c_component_folds(
            _handoff(rows, development=True),
            [],
            development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        )


# --- runner arguments and binding ---------------------------------------------------------


def _arguments(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "phase_c_contract": "v1",
        "fidelity": Path("fidelity.json"),
        "expected_table_sha256": None,
        "expected_roster_sha256": None,
        "expected_manifest_sha256": None,
        "folds": None,
        "json_output": Path("out.json"),
        "table": Path("t.csv"),
        "roster": Path("r.csv"),
        "manifest": Path("m.json"),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _development_arguments(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "phase_c_contract": "development_v2",
        "fidelity": None,
        "expected_table_sha256": TABLE,
        "expected_roster_sha256": ROSTER,
        "expected_manifest_sha256": MANIFEST,
    }
    fields.update(overrides)
    return _arguments(**fields)


def test_the_v1_contract_is_the_default_and_still_needs_its_fidelity_artifact() -> None:
    assert _development_from_arguments(_arguments()) is None
    with pytest.raises(BindingCalibrationError, match="--fidelity is required"):
        _development_from_arguments(_arguments(fidelity=None))
    with pytest.raises(BindingCalibrationError, match="development_v2 only"):
        _development_from_arguments(_arguments(expected_table_sha256=TABLE))
    with pytest.raises(BindingCalibrationError, match="development_v2 only"):
        _development_from_arguments(_arguments(folds="2024-25-gw02"))


def test_the_development_contract_pins_the_reference_and_refuses_the_binding_paths() -> None:
    pinned = _development_from_arguments(_development_arguments())
    assert pinned == DevelopmentInputs(TABLE, ROSTER, MANIFEST, None)

    with pytest.raises(BindingCalibrationError, match="64-hex"):
        _development_from_arguments(_development_arguments(expected_roster_sha256=None))
    with pytest.raises(BindingCalibrationError, match="64-hex"):
        _development_from_arguments(_development_arguments(expected_table_sha256="abc"))
    assert _development_from_arguments(
        _development_arguments(fidelity=Path("fidelity.json"))
    ) == DevelopmentInputs(TABLE, ROSTER, MANIFEST, None, Path("fidelity.json"))
    with pytest.raises(BindingCalibrationError, match="binding artifact path"):
        _development_from_arguments(_development_arguments(json_output=DEFAULT_OUTPUT))

    pilot = _development_from_arguments(
        _development_arguments(folds="2023-24-gw02, 2024-25-gw02,2025-26-gw02")
    )
    assert pilot is not None
    assert pilot.folds == ("2023-24-gw02", "2024-25-gw02", "2025-26-gw02")
    with pytest.raises(BindingCalibrationError, match="distinct"):
        _development_from_arguments(_development_arguments(folds="2024-25-gw02,2024-25-gw02"))


def test_read_handoff_refuses_anything_but_the_pinned_equal_weight_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _component_rows(("2021-22-gw11",))
    calls: list[dict[str, object]] = []
    served: dict[str, PhaseCComponentHandoff] = {}

    def fake_reader(table: Path, roster: Path, manifest: Path, **kwargs: object) -> object:
        calls.append(dict(kwargs))
        return served["handoff"]

    monkeypatch.setattr(runner, "read_phase_c_component_handoff", fake_reader)
    pinned = DevelopmentInputs(TABLE, ROSTER, MANIFEST, None)

    served["handoff"] = _handoff(rows, development=True)
    assert _read_handoff(_development_arguments(), pinned) is served["handoff"]
    assert calls[-1] == {"development_contract": DEVELOPMENT_OOF_CONTRACT_VERSION}

    served["handoff"] = _handoff(rows, development=True, table="f" * 64)
    with pytest.raises(BindingCalibrationError, match="differ from the pinned"):
        _read_handoff(_development_arguments(), pinned)

    served["handoff"] = _handoff(
        rows,
        development=True,
        weighting=SEASON_HALF_LIFE_WEIGHTING,
        model_version=SEASON_WEIGHTED_MODEL_VERSION,
    )
    with pytest.raises(BindingCalibrationError, match="equal-weight A reference"):
        _read_handoff(_development_arguments(), pinned)

    served["handoff"] = _handoff(rows, development=False)
    assert _read_handoff(_arguments(), None) is served["handoff"]
    assert calls[-1] == {}


# --- population -----------------------------------------------------------------------------


def _v1_shaped_rows(extra_seasons: Sequence[str] = ()) -> tuple[pd.DataFrame, tuple[str, ...]]:
    fold_ids = (
        *(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2022-23-gw{gameweek:02d}" for gameweek in range(2, 39) if gameweek != 7),
        *(f"2023-24-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2024-25-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"{season}-gw{gameweek:02d}" for season in extra_seasons for gameweek in range(2, 39)),
    )
    rows = _component_rows(fold_ids)
    # The first fold has no fitted model: every row is direct control, so it contributes no
    # residual, exactly like the archive's 2021-22-gw02.
    first = rows["fold_id"].eq(fold_ids[0])
    rows.loc[first, "composition_route"] = DIRECT_CONTROL_ROUTE
    rows.loc[first, ["appearance_probability", "raw_expected_points_if_appearance"]] = pd.NA
    return rows, fold_ids


def test_the_computed_population_reproduces_the_preregistered_burn_in() -> None:
    rows, fold_ids = _v1_shaped_rows()

    burn_in, eligible = _development_population(rows, fold_ids, min_history_folds=8)

    assert burn_in == HISTORY_BURN_IN_FOLDS
    assert eligible[0] == "2021-22-gw11"
    assert eligible[-1] == "2024-25-gw38"
    assert len(burn_in) + len(eligible) == len(fold_ids)


def test_the_development_season_extends_the_eligible_population() -> None:
    rows, fold_ids = _v1_shaped_rows((LOCKED,))

    burn_in, eligible = _development_population(rows, fold_ids, min_history_folds=8)

    assert burn_in == HISTORY_BURN_IN_FOLDS
    assert f"{LOCKED}-gw02" in eligible
    assert eligible[-1] == f"{LOCKED}-gw38"
    assert len(eligible) == len(fold_ids) - len(HISTORY_BURN_IN_FOLDS)


def test_repeated_fold_ids_are_refused_by_the_population_rule() -> None:
    rows, fold_ids = _v1_shaped_rows()
    with pytest.raises(BindingCalibrationError, match="repeat"):
        _development_population(rows, (*fold_ids, fold_ids[-1]), min_history_folds=8)


# --- observations, identity, contracts -----------------------------------------------------


def test_the_development_observation_reads_s1_s2_without_a_verdict() -> None:
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    rows = _component_rows((*history, fold_id))
    prepared, result = _frozen_decision(fold_id)
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())
    handoff = _handoff(rows, development=True)

    low, low_record = _measure_fold(
        handoff, prepared, result, 5.0, selected, settings, None, development=True
    )
    high, high_record = _measure_fold(
        handoff, prepared, result, 95.0, selected, settings, None, development=True
    )

    assert _development_observation([]) is None
    observation = _development_observation([low, high])
    assert observation is not None
    assert observation["fold_count"] == 2
    expected_pit = (
        low_record["probability_integral_transform"] + high_record["probability_integral_transform"]
    ) / 2
    assert observation["mean_probability_integral_transform"] == pytest.approx(expected_pit)
    assert observation["realized_below_lower_quantile_count"] == 1
    assert observation["realized_below_lower_quantile_rate"] == pytest.approx(0.5)
    assert observation["s1_bounds"] == [0.43, 0.57]
    assert observation["s2_bounds"] == [0.04, 0.16]
    assert observation["tail_rate_within_s2_bounds"] is False
    assert "not a calibration verdict" in str(observation["note"])


def test_the_decision_identity_is_complete_and_order_independent() -> None:
    _, result = _frozen_decision("2021-22-gw11")
    identity = _decision_identity(result)

    completed = complete_optimization_decision(result)
    assert identity["squad"] == list(range(1, 16))
    assert identity["starting_xi"] == [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    assert identity["captain"] == 15
    # The completion the official scorer walks, not the optimizer's frame layout.
    assert identity["bench_order"] == [int(value) for value in completed.bench]
    assert identity["vice_captain"] == int(completed.vice_captain_id)  # type: ignore[call-overload]
    assert identity["vice_captain"] != identity["captain"]
    assert len(str(identity["sha256"])) == 64

    shuffled = OptimizationResult(
        solver_status=result.solver_status,
        selected_squad=result.selected_squad.iloc[::-1].reset_index(drop=True),
        starting_xi=result.starting_xi.iloc[::-1].reset_index(drop=True),
        bench=result.bench,
        captain=result.captain,
        total_cost_tenths=result.total_cost_tenths,
        projected_score=result.projected_score,
        objective_value=result.objective_value,
        diagnostics={},
    )
    assert _decision_identity(shuffled)["sha256"] == identity["sha256"]


def test_the_development_report_has_its_own_contract_and_the_fixed_solver_profile() -> None:
    pinned = DevelopmentInputs(TABLE, ROSTER, MANIFEST, None)
    assert len({REPORT_VERSION, CANDIDATE_REPORT_VERSION, DEVELOPMENT_REPORT_VERSION}) == 3
    assert _report_contract_version(None, pinned) == DEVELOPMENT_REPORT_VERSION
    assert (
        _report_contract_version(ConditionalResidualConfig(fraction=0.15, minimum_rows=30), pinned)
        == DEVELOPMENT_REPORT_VERSION
    )
    assert _report_contract_version(None) == REPORT_VERSION

    profile = _solver_profile()
    assert profile["solver_time_limit_seconds"] == 10.0
    assert profile["solver_deterministic_time_limit"] is None
    assert profile["deterministic_seed"] == 0
    assert profile["num_search_workers"] == 1


def test_the_candidate_block_names_the_report_it_belongs_to() -> None:
    sampler = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)
    binding = _candidate_record(sampler)
    development = _candidate_record(sampler, reference=DEVELOPMENT_REPORT_VERSION)

    assert binding is not None and development is not None
    assert binding["reference_contract_version"] == REPORT_VERSION
    assert development["reference_contract_version"] == DEVELOPMENT_REPORT_VERSION
    assert development["binding"] is False


def test_an_incomplete_readout_is_refused_by_the_observation() -> None:
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    prepared, result = _frozen_decision(fold_id)
    handoff = _handoff(_component_rows((*history, fold_id)), development=True)
    reading, _ = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        tuple(_squad_positions()),
        ScenarioConfig(scenario_count=64),
        None,
    )
    incomplete = SimpleNamespace(
        fold_id=fold_id,
        readout=SimpleNamespace(
            probability_integral_transform=None, realized_below_lower_quantile=None
        ),
    )

    with pytest.raises(BindingCalibrationError, match="incomplete readout"):
        _development_observation([reading, incomplete])  # type: ignore[list-item]


def test_a_frozen_draw_carries_no_development_key_and_a_development_draw_does() -> None:
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    rows = _component_rows((*history, fold_id))
    prepared, _ = _frozen_decision(fold_id)
    selected = tuple(_squad_positions())
    target = ScenarioTarget(season="2021-22", gameweek=11)
    settings = ScenarioConfig(scenario_count=16)

    draws = {}
    for label, development in (("frozen", False), ("development", True)):
        handoff = _handoff(rows, development=development)
        inputs, snapshot = _selected_component_inputs(handoff, prepared, selected)
        pool = paired_conditional_residuals(
            handoff.rows.loc[handoff.rows["fold_id"] < fold_id],
            target=target,
            min_history_folds=settings.min_history_folds,
        )
        draws[label] = sample_component_scenarios(inputs, snapshot, pool, target, settings)

    assert "development_contract" not in draws["frozen"].scenarios.diagnostics
    assert (
        draws["development"].scenarios.diagnostics["development_contract"]
        == DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    # The points matrices agree: only the identity differs, never the draw itself.
    assert draws["frozen"].scenarios.scenario_fingerprint == (
        draws["development"].scenarios.scenario_fingerprint
    )
    assert draws["frozen"].component_fingerprint != draws["development"].component_fingerprint


def test_the_residual_pool_for_a_2025_26_fold_uses_only_earlier_folds() -> None:
    earlier = (
        *_history_before("x", "2024-25"),
        f"{LOCKED}-gw02",
        f"{LOCKED}-gw03",
        f"{LOCKED}-gw04",
    )
    later = (f"{LOCKED}-gw05", f"{LOCKED}-gw06")
    rows = _component_rows((*earlier, *later))
    target = ScenarioTarget(season=LOCKED, gameweek=5)

    pool = paired_conditional_residuals(
        rows.loc[rows["fold_id"] < target.fold_id], target=target, min_history_folds=8
    )

    assert pool.history_fold_ids == tuple(sorted(earlier))
    with pytest.raises(ScenarioValidationError, match=r"own residual history|must precede"):
        paired_conditional_residuals(rows, target=target, min_history_folds=8)
    later_only = rows.loc[rows["fold_id"] != target.fold_id]
    with pytest.raises(ScenarioValidationError, match="must precede"):
        paired_conditional_residuals(later_only, target=target, min_history_folds=8)


def test_v1_argument_parsing_still_refuses_a_missing_fidelity_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["run", "--table", "t.csv", "--manifest", "m.json", "--roster", "r.csv"],
    )
    with pytest.raises(SystemExit) as raised:
        runner._parse_arguments()
    assert raised.value.code == 2


# --- the development measurement itself ------------------------------------------------------


def _prepared_folds(fold_ids: Sequence[str]) -> tuple[EvaluationFold, ...]:
    prepared, _ = _frozen_decision(fold_ids[0])
    return tuple(
        EvaluationFold(
            fold_id=fold_id,
            projections=prepared.projections,
            realized_points=prepared.realized_points,
        )
        for fold_id in fold_ids
    )


def _unsolved() -> OptimizationResult:
    empty = pd.DataFrame(
        {
            "player_id": pd.Series([], dtype="int64"),
            "name": pd.Series([], dtype="string"),
            "team_id": pd.Series([], dtype="string"),
            "position": pd.Series([], dtype="string"),
            "price_tenths": pd.Series([], dtype="int64"),
            "expected_points": pd.Series([], dtype="float64"),
        }
    )
    return OptimizationResult(
        solver_status=SolverStatus.UNKNOWN,
        selected_squad=empty,
        starting_xi=empty,
        bench=empty,
        captain=None,
        total_cost_tenths=None,
        projected_score=None,
        objective_value=None,
        diagnostics={},
    )


def _real_readings(fold_ids: Sequence[str]) -> dict[str, object]:
    """One genuine readout, reused per fold: the evaluator refuses anything else."""

    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    prepared, result = _frozen_decision(fold_id)
    # The frozen scenario count, because the evaluator refuses any other once it is asked to
    # read S1/S2 rather than abstain.
    base, _ = _measure_fold(
        _handoff(_component_rows((*history, fold_id)), development=True),
        prepared,
        result,
        40.0,
        tuple(_squad_positions()),
        ScenarioConfig(),
        None,
    )
    return {item: ComponentCalibrationFold(fold_id=item, readout=base.readout) for item in fold_ids}


def _patch_measurement(
    monkeypatch: pytest.MonkeyPatch,
    *,
    unsolved: Sequence[str] = (),
    unscored: Sequence[str] = (),
    readings: dict[str, object] | None = None,
) -> list[str]:
    """Stand in for the panel, the controls and the scorer; record which folds were solved."""

    _, solved_result = _frozen_decision("2021-22-gw11")
    solved: list[str] = []

    def fake_panel(archive_root: Path, seasons: Sequence[str] = ()) -> pd.DataFrame:
        return pd.DataFrame({"season": list(seasons)})

    def fake_controls(panel: pd.DataFrame, **kwargs: object) -> tuple[str, ...]:
        return ("controls",)

    def fake_prepare(
        handoff: PhaseCComponentHandoff, controls: object, *, development_contract: str | None
    ) -> tuple[EvaluationFold, ...]:
        assert development_contract == DEVELOPMENT_OOF_CONTRACT_VERSION
        return _prepared_folds(tuple(handoff.rows["fold_id"].drop_duplicates()))

    def fake_evaluate(candidates: Sequence[EvaluationFold], config: object) -> SimpleNamespace:
        folds = []
        for fold in candidates:
            solved.append(fold.fold_id)
            folds.append(
                SimpleNamespace(
                    fold_id=fold.fold_id,
                    optimization_result=_unsolved() if fold.fold_id in unsolved else solved_result,
                    realized_squad_points=None if fold.fold_id in unscored else 40.0,
                )
            )
        return SimpleNamespace(folds=folds)

    def fake_measure_fold(
        handoff: PhaseCComponentHandoff,
        prepared: EvaluationFold,
        result: OptimizationResult,
        realized: float,
        selected: Sequence[int],
        settings: ScenarioConfig,
        sampler: object,
        *,
        development: bool = False,
    ) -> tuple[object, dict[str, object]]:
        assert development is True
        if readings is not None:
            return readings[prepared.fold_id], {"fold_id": prepared.fold_id}
        reading = SimpleNamespace(
            fold_id=prepared.fold_id,
            readout=SimpleNamespace(
                probability_integral_transform=0.5, realized_below_lower_quantile=False
            ),
        )
        return reading, {"fold_id": prepared.fold_id}

    monkeypatch.setattr(runner, "_load_development_panel", fake_panel)
    monkeypatch.setattr(runner, "build_walk_forward_folds", fake_controls)
    monkeypatch.setattr(runner, "prepare_phase_c_component_folds", fake_prepare)
    monkeypatch.setattr(runner, "evaluate_prepared_folds", fake_evaluate)
    monkeypatch.setattr(runner, "_measure_fold", fake_measure_fold)
    return solved


def test_a_pilot_solves_only_the_requested_folds_and_lists_every_abstention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, fold_ids = _v1_shaped_rows((LOCKED,))
    direct = "2024-25-gw02"
    picked = rows["fold_id"].eq(direct) & rows["player_id"].eq(1)
    rows.loc[picked, "composition_route"] = DIRECT_CONTROL_ROUTE
    handoff = _handoff(rows, development=True)
    solved = _patch_measurement(
        monkeypatch, unsolved=(f"{LOCKED}-gw02",), unscored=("2023-24-gw03",)
    )
    requested = ("2023-24-gw02", "2023-24-gw03", direct, f"{LOCKED}-gw02")
    sampler = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)

    measured, panel_rows = _measure_development(
        SimpleNamespace(archive_root=Path(".")),
        handoff,
        sampler,
        DevelopmentInputs(TABLE, ROSTER, MANIFEST, requested),
    )

    population = measured["population"]
    assert solved == list(requested)
    assert population["evaluated_fold_ids"] == list(requested)
    assert population["history_burn_in_fold_ids"] == list(HISTORY_BURN_IN_FOLDS)
    assert population["history_eligible_fold_count"] == len(fold_ids) - len(HISTORY_BURN_IN_FOLDS)
    assert population["direct_control_abstention_fold_ids"] == [direct]
    assert population["unsolved_fold_ids"] == [f"{LOCKED}-gw02"]
    assert population["unscored_fold_ids"] == ["2023-24-gw03"]
    assert population["measured_fold_ids"] == ["2023-24-gw02"]
    assert population["history_seasons"] == [
        "2020-21",
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
        LOCKED,
    ]
    assert measured["verdict"] is None
    assert "pilot" in str(measured["verdict_note"])
    assert measured["source"]["phase_c_contract"] == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert measured["source"]["pinned_by_arguments"] is True
    assert measured["candidate"]["reference_contract_version"] == DEVELOPMENT_REPORT_VERSION
    assert measured["development_observation"]["fold_count"] == 1
    assert panel_rows == 6


def test_a_pilot_refuses_unknown_and_burn_in_folds(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, _ = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    _patch_measurement(monkeypatch)

    with pytest.raises(BindingCalibrationError, match="outside the handoff"):
        _measure_development(
            SimpleNamespace(archive_root=Path(".")),
            handoff,
            None,
            DevelopmentInputs(TABLE, ROSTER, MANIFEST, ("2027-28-gw02",)),
        )
    with pytest.raises(BindingCalibrationError, match="burn-in"):
        _measure_development(
            SimpleNamespace(archive_root=Path(".")),
            handoff,
            None,
            DevelopmentInputs(TABLE, ROSTER, MANIFEST, ("2021-22-gw05",)),
        )


def test_a_full_development_run_abstains_by_protocol_at_the_minimum_fold_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, _ = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    fold_id = "2021-22-gw11"
    history = tuple(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 11))
    prepared, result = _frozen_decision(fold_id)
    base, _ = _measure_fold(
        _handoff(_component_rows((*history, fold_id)), development=True),
        prepared,
        result,
        40.0,
        tuple(_squad_positions()),
        ScenarioConfig(scenario_count=64),
        None,
    )
    requested = tuple(f"2023-24-gw{gameweek:02d}" for gameweek in range(2, 32))
    readings = {
        item: ComponentCalibrationFold(fold_id=item, readout=base.readout) for item in requested
    }
    _patch_measurement(monkeypatch, readings=readings)

    measured, _ = _measure_development(
        SimpleNamespace(archive_root=Path(".")),
        handoff,
        None,
        DevelopmentInputs(TABLE, ROSTER, MANIFEST, requested),
    )

    verdict = measured["verdict"]
    assert verdict is not None
    assert verdict["status"] == "abstained"
    assert verdict["abstention_reason"] == "sampler_fidelity_not_verified"
    assert verdict["fold_count"] == 30
    assert "abstains by protocol" in str(measured["verdict_note"])
    assert measured["development_observation"]["fold_count"] == 30


def test_the_development_document_is_flagged_not_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "development.json"
    arguments = SimpleNamespace(
        phase_c_contract="development_v2",
        fidelity=None,
        expected_table_sha256=TABLE,
        expected_roster_sha256=ROSTER,
        expected_manifest_sha256=MANIFEST,
        folds=None,
        json_output=output,
        conditional_residual_fraction=0.15,
        conditional_residual_minimum_rows=30,
        table=Path("t.csv"),
        roster=Path("r.csv"),
        manifest=Path("m.json"),
        archive_root=Path("."),
    )
    measured = {
        "source": {"phase_c_contract": DEVELOPMENT_OOF_CONTRACT_VERSION},
        "config": {},
        "solver_profile": {},
        "candidate": {"binding": False},
        "sampler_contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
        "population": {
            "history_seasons": ["2020-21", "2021-22", "2022-23", "2023-24", "2024-25", LOCKED],
            "measured_fold_ids": ["2023-24-gw02"],
        },
        "folds": [],
        "development_observation": None,
        "verdict": None,
        "verdict_note": "pilot",
    }

    def fake_metadata(**kwargs: object) -> dict[str, object]:
        return {
            "created_utc": "2026-09-06T00:00:00+00:00",
            "provenance": {
                "working_tree_dirty": False,
                "repository_commit": "0" * 40,
                "history_seasons": list(kwargs.get("history_seasons", ())),  # type: ignore[arg-type]
            },
            "environment": {},
        }

    monkeypatch.setattr(runner, "_parse_arguments", lambda: arguments)
    monkeypatch.setattr(runner, "artifact_metadata", fake_metadata)
    monkeypatch.setattr(runner, "_measure", lambda received: (measured, 10))

    assert main() == 0
    document = json.loads(output.read_text(encoding="utf-8"))
    assert document["contract_version"] == DEVELOPMENT_REPORT_VERSION
    assert document["binding"] is False
    assert document["development_only"] is True
    assert document["locked_holdout_accessed"] is True
    assert document["development_method"] == "docs/phase_d_v2_development_method.md"
    assert document["provenance"]["history_seasons"][-1] == LOCKED


# --- the development fidelity record -------------------------------------------------------

FIDELITY_FOLDS = tuple(f"{LOCKED}-gw{gameweek:02d}" for gameweek in (1, 2, 3))
FIDELITY_CONFIG = ScenarioConfig(scenario_count=16, deterministic_seed=0, min_history_folds=2)
FIDELITY_SAMPLER = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)


def _fidelity_manifest(**overrides: object) -> dict[str, object]:
    manifest: dict[str, object] = {
        "contract_version": DEVELOPMENT_OOF_CONTRACT_VERSION,
        "development_only": True,
        "locked_holdout_read": True,
        "development_seasons": [LOCKED],
        "weighting": {"label": EQUAL_WEIGHTING, "model_version": COMPONENT_MODEL_VERSION},
        "model_version": COMPONENT_MODEL_VERSION,
        "feature_contract_version": "features-v1",
        "target_contract_version": "targets-v1",
        "dataset_contract_version": "dataset-v1",
        "table_sha256": TABLE,
        "roster_sha256": ROSTER,
        "repository_commit": "d" * 40,
    }
    manifest.update(overrides)
    return manifest


def _fidelity_roster(fold_ids: Sequence[str]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold_id in fold_ids:
        for player_id, position in _squad_positions().items():
            records.append(
                {
                    "fold_id": fold_id,
                    "player_id": player_id,
                    "name": f"Player {player_id}",
                    "team_id": f"T{(player_id - 1) // 3}",
                    "position": position,
                    "price_tenths": 50,
                }
            )
    return pd.DataFrame(records)


def _fidelity_document(
    *,
    manifest: dict[str, object] | None = None,
    sampler: ConditionalResidualConfig | None = FIDELITY_SAMPLER,
) -> dict[str, object]:
    """One real record, produced by the producer's own code so the two cannot drift apart."""

    rows = _component_rows(FIDELITY_FOLDS)
    rows["control_expected_points"] = (
        rows["appearance_probability"] * rows["raw_expected_points_if_appearance"]
    )
    document = measure_fidelity(
        rows,
        _fidelity_roster(FIDELITY_FOLDS),
        _fidelity_manifest() if manifest is None else manifest,
        config=FIDELITY_CONFIG,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        conditional_residuals=sampler,
    )
    document["generated_at_utc"] = "2026-09-07T00:00:00+00:00"
    document["provenance"] = provenance_block(
        _fidelity_manifest() if manifest is None else manifest,
        revision="a" * 40,
        dirty=False,
        files={
            "oof_table": ("table.csv", TABLE),
            "roster": ("roster.csv", ROSTER),
            "manifest": ("manifest.json", MANIFEST),
        },
        development=True,
    )
    return document


def _write_fidelity(tmp_path: Path, document: dict[str, object]) -> Path:
    destination = tmp_path / "fidelity.json"
    destination.write_text(json.dumps(document), encoding="utf-8")
    return destination


def _fidelity_handoff() -> PhaseCComponentHandoff:
    return _handoff(_component_rows(FIDELITY_FOLDS), development=True)


def _load(path: Path, **overrides: object) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    arguments: dict[str, object] = {
        "handoff": _fidelity_handoff(),
        "settings": FIDELITY_CONFIG,
        "candidate_sampler": FIDELITY_SAMPLER,
    }
    arguments.update(overrides)
    return _load_verified_development_fidelity(
        path,
        arguments.pop("handoff"),  # type: ignore[arg-type]
        **arguments,  # type: ignore[arg-type]
    )


def test_the_record_the_producer_writes_is_the_one_the_consumer_accepts(tmp_path: Path) -> None:
    """Writer and reader are checked against each other, not against a hand-built fixture."""

    path = _write_fidelity(tmp_path, _fidelity_document())

    digest, measured, excluded = _load(path)

    assert len(digest) == 64
    # The first two folds have too little history for the pool; the third is measured.
    assert measured == (FIDELITY_FOLDS[-1],)
    assert excluded == FIDELITY_FOLDS[:2]


def _mutate(document: dict[str, object], path: str, value: object) -> dict[str, object]:
    """Return a copy of ``document`` with one dotted path replaced or, for None, removed."""

    import copy

    mutated = copy.deepcopy(document)
    head, _, tail = path.rpartition(".")
    target: object = mutated
    for part in head.split(".") if head else []:
        assert isinstance(target, dict)
        target = target[part]
    assert isinstance(target, dict)
    if value is None:
        target.pop(tail, None)
    else:
        target[tail] = value
    return mutated


@pytest.mark.parametrize(
    ("path_", "value", "match"),
    [
        ("contract_version", "phase_d_component_fidelity_v1", "fidelity record"),
        ("development_only", None, "diagnostic-only"),
        ("promotes_anything", True, "diagnostic-only"),
        ("phase_c_contract", "phase_c_component_oof_v1", "different Phase C contract"),
        ("observation_unit", "squad_decision", "observation unit"),
        ("config.scenario_count", 999, "different scenario configuration"),
        ("sampler.contract_version", "component_scenario_foundation_v1", "different sampler"),
        ("sampler.conditional_residual_fraction", 0.25, "different sampler"),
        ("provenance.working_tree_dirty", True, "does not describe this Phase C handoff"),
        ("provenance.model_version", "other-model", "does not describe this Phase C handoff"),
        ("provenance.phase_c_weighting", "season_half_life_0.5_v1", "does not describe this"),
        ("provenance.oof_table_sha256", "9" * 64, "does not describe this Phase C handoff"),
        ("provenance.manifest_sha256", "9" * 64, "does not describe this Phase C handoff"),
        (
            "provenance.phase_c_producer_repository_commit",
            "9" * 40,
            "does not describe this Phase C handoff",
        ),
        ("provenance.manifest_locked_holdout_read", False, "does not describe this"),
        ("population.fold_count_measured", 99, "contradict its population"),
        ("population.fold_count_total", 99, "contradict its population"),
        ("population.locked_holdout_season", "2024-25", "contradict its population"),
        ("pooled", {}, "pooled is missing"),
        ("fold_summary", {}, "fold_summary is missing"),
    ],
)
def test_a_record_that_does_not_describe_this_run_is_refused(
    tmp_path: Path, path_: str, value: object, match: str
) -> None:
    path = _write_fidelity(tmp_path, _mutate(_fidelity_document(), path_, value))

    with pytest.raises(BindingCalibrationError, match=match):
        _load(path)


def test_a_record_naming_a_fold_outside_the_handoff_is_refused(tmp_path: Path) -> None:
    document = _fidelity_document()
    population = document["population"]
    assert isinstance(population, dict)
    stranger = "2019-20-gw05"
    population["measured_fold_ids"] = [stranger]
    folds = document["folds"]
    assert isinstance(folds, list) and len(folds) == 1
    folds[0]["fold_id"] = stranger

    with pytest.raises(BindingCalibrationError, match="outside this handoff"):
        _load(_write_fidelity(tmp_path, document))


def test_the_frozen_sampler_needs_a_record_measured_on_the_frozen_sampler(
    tmp_path: Path,
) -> None:
    foundation = _write_fidelity(tmp_path, _fidelity_document(sampler=None))

    assert _sampler_record(None)["contract_version"] == "component_scenario_foundation_v1"
    with pytest.raises(BindingCalibrationError, match="different sampler"):
        _load(foundation)
    digest, measured, _ = _load(foundation, candidate_sampler=None)
    assert measured == (FIDELITY_FOLDS[-1],)
    assert len(digest) == 64


# --- what a verified record changes in the run ----------------------------------------------


def _patch_fidelity(
    monkeypatch: pytest.MonkeyPatch, measured: Sequence[str], excluded: Sequence[str]
) -> None:
    monkeypatch.setattr(
        runner,
        "_load_verified_development_fidelity",
        lambda path, handoff, *, settings, candidate_sampler: (
            "f" * 64,
            tuple(measured),
            tuple(excluded),
        ),
    )


def test_a_verified_record_turns_the_abstention_into_an_evaluated_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows, fold_ids = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    burn_in, eligible = _development_population(rows, fold_ids, min_history_folds=8)
    requested = eligible[:30]
    _patch_measurement(monkeypatch, readings=_real_readings(requested))
    _patch_fidelity(monkeypatch, eligible, burn_in)

    measured, _ = _measure_development(
        SimpleNamespace(archive_root=Path(".")),
        handoff,
        FIDELITY_SAMPLER,
        DevelopmentInputs(TABLE, ROSTER, MANIFEST, requested, Path("fidelity.json")),
    )

    verdict = measured["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["status"] != "abstained"
    assert verdict["abstention_reason"] is None
    assert measured["sampler_fidelity_verified"] is True
    assert measured["source"]["fidelity_artifact_sha256"] == "f" * 64
    assert measured["source"]["fidelity_contract_version"] == DEVELOPMENT_FIDELITY_VERSION
    assert measured["source"]["fidelity_measured_fold_count"] == len(eligible)
    assert "verified development fidelity record" in str(measured["verdict_note"])


def test_without_a_record_the_run_keeps_abstaining(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, fold_ids = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    _, eligible = _development_population(rows, fold_ids, min_history_folds=8)
    requested = eligible[:30]
    _patch_measurement(monkeypatch, readings=_real_readings(requested))

    measured, _ = _measure_development(
        SimpleNamespace(archive_root=Path(".")),
        handoff,
        FIDELITY_SAMPLER,
        DevelopmentInputs(TABLE, ROSTER, MANIFEST, requested, None),
    )

    verdict = measured["verdict"]
    assert isinstance(verdict, dict)
    assert verdict["status"] == "abstained"
    assert verdict["abstention_reason"] == "sampler_fidelity_not_verified"
    assert measured["sampler_fidelity_verified"] is False
    assert measured["source"]["fidelity_artifact_sha256"] is None


def test_a_record_that_disagrees_on_eligibility_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two implementations of 'enough history' are compared, not assumed to agree."""

    rows, fold_ids = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    burn_in, eligible = _development_population(rows, fold_ids, min_history_folds=8)
    _patch_measurement(monkeypatch)
    _patch_fidelity(monkeypatch, eligible[1:], burn_in)

    with pytest.raises(BindingCalibrationError, match="disagree on which folds"):
        _measure_development(
            SimpleNamespace(archive_root=Path(".")),
            handoff,
            FIDELITY_SAMPLER,
            DevelopmentInputs(TABLE, ROSTER, MANIFEST, eligible[:2], Path("fidelity.json")),
        )


def test_a_pilot_with_a_verified_record_still_produces_no_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fidelity answers 'was the sampler measured', never 'are there enough folds'."""

    rows, fold_ids = _v1_shaped_rows((LOCKED,))
    handoff = _handoff(rows, development=True)
    burn_in, eligible = _development_population(rows, fold_ids, min_history_folds=8)
    _patch_measurement(monkeypatch)
    _patch_fidelity(monkeypatch, eligible, burn_in)

    measured, _ = _measure_development(
        SimpleNamespace(archive_root=Path(".")),
        handoff,
        FIDELITY_SAMPLER,
        DevelopmentInputs(TABLE, ROSTER, MANIFEST, eligible[:3], Path("fidelity.json")),
    )

    assert measured["verdict"] is None
    assert measured["sampler_fidelity_verified"] is True
    assert "pilot" in str(measured["verdict_note"])
