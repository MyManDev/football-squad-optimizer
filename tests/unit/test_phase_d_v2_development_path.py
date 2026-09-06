"""Tests for the Phase D v2 development binding to the Phase C v2 equal-weight reference.

The v1 binding path must be untouched; the development path must be chosen by name, bound
to the pinned A artifacts, refuse the season-weighted B arm and any digest drift, compute its
population from the handoff under the preregistered rule, admit a 2025-26 decision only
through a development handoff, and carry the decision identity a repeat can be compared to.
"""

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from scripts import run_component_squad_calibration as runner
from scripts.run_component_squad_calibration import (
    CANDIDATE_REPORT_VERSION,
    DEFAULT_OUTPUT,
    DEVELOPMENT_REPORT_VERSION,
    HISTORY_BURN_IN_FOLDS,
    REPORT_VERSION,
    BindingCalibrationError,
    DevelopmentInputs,
    _decision_identity,
    _development_from_arguments,
    _development_observation,
    _development_population,
    _measure_fold,
    _read_handoff,
    _report_contract_version,
    _solver_profile,
)

from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationFold,
    EvaluationValidationError,
    prepare_phase_c_component_folds,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHTED_MODEL_VERSION,
)
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ComponentScenarioProvenance,
    ConditionalResidualConfig,
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
    with pytest.raises(BindingCalibrationError, match="Drop --fidelity"):
        _development_from_arguments(_development_arguments(fidelity=Path("fidelity.json")))
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

    assert identity["squad"] == list(range(1, 16))
    assert identity["starting_xi"] == [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    assert identity["captain"] == 15
    assert identity["bench_order"] == [2, 6, 7, 12]
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
