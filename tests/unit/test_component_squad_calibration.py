"""Tests for the preregistered Phase D S1/S2 aggregation."""

from dataclasses import replace

import pytest

from squadopt.experiments import (
    ComponentCalibrationFold,
    ComponentSquadCalibrationError,
    evaluate_component_squad_calibration,
)
from squadopt.scenarios import ComponentDecisionDistributionReadout


def _fold_ids(count: int = 30) -> tuple[str, ...]:
    return tuple(
        f"{season_start}-{str(season_start + 1)[-2:]}-gw{index % 38 + 1:02d}"
        for index in range(count)
        for season_start in (2021 + index // 38,)
    )


def _readout(*, pit: float = 0.5, below: bool = False) -> ComponentDecisionDistributionReadout:
    return ComponentDecisionDistributionReadout(
        scenario_count=1_000,
        mean_score=50.0,
        score_standard_deviation=10.0,
        lower_quantile_probability=0.10,
        lower_quantile_score=37.0,
        realized_score=30.0 if below else 48.0,
        probability_integral_transform=pit,
        realized_below_lower_quantile=below,
        scenario_fingerprint="a" * 64,
        component_fingerprint="b" * 64,
        decision_scoring_contract_version="component_decision_scoring_v1",
    )


def _folds(
    *,
    count: int = 30,
    pit: float = 0.5,
    lower_tail_count: int = 3,
) -> tuple[ComponentCalibrationFold, ...]:
    return tuple(
        ComponentCalibrationFold(
            fold_id=fold_id,
            readout=_readout(pit=pit, below=index < lower_tail_count),
        )
        for index, fold_id in enumerate(_fold_ids(count))
    )


def test_aggregates_the_hand_calculated_s1_and_s2_readings() -> None:
    folds = _folds()

    result = evaluate_component_squad_calibration(
        folds,
        expected_fold_ids=_fold_ids(),
        sampler_fidelity_verified=True,
    )

    assert result.status == "calibrated_internal"
    assert result.fold_count == 30
    assert result.mean_probability_integral_transform == 0.5
    assert result.realized_below_lower_quantile_count == 3
    assert result.realized_below_lower_quantile_rate == 0.1
    assert result.s1_passes is True
    assert result.s2_passes is True
    assert result.abstention_reason is None


@pytest.mark.parametrize(
    ("pit", "lower_tail_count"),
    [(0.43, 4), (0.57, 16)],
)
def test_gate_bounds_are_inclusive(pit: float, lower_tail_count: int) -> None:
    folds = _folds(count=100, pit=pit, lower_tail_count=lower_tail_count)

    result = evaluate_component_squad_calibration(
        folds,
        expected_fold_ids=_fold_ids(100),
        sampler_fidelity_verified=True,
    )

    assert result.status == "calibrated_internal"


def test_a_measured_gate_failure_is_recorded_without_moving_the_bounds() -> None:
    folds = _folds(pit=0.7, lower_tail_count=3)

    result = evaluate_component_squad_calibration(
        folds,
        expected_fold_ids=_fold_ids(),
        sampler_fidelity_verified=True,
    )

    assert result.status == "failed"
    assert result.s1_passes is False
    assert result.s2_passes is True


def test_missing_sampler_fidelity_abstains_without_publishing_gate_values() -> None:
    result = evaluate_component_squad_calibration(
        _folds(),
        expected_fold_ids=_fold_ids(),
        sampler_fidelity_verified=False,
    )

    assert result.status == "abstained"
    assert result.mean_probability_integral_transform is None
    assert result.realized_below_lower_quantile_rate is None
    assert result.abstention_reason == "sampler_fidelity_not_verified"


def test_a_population_mismatch_abstains_instead_of_changing_the_denominator() -> None:
    result = evaluate_component_squad_calibration(
        _folds()[:-1],
        expected_fold_ids=_fold_ids(),
        sampler_fidelity_verified=True,
    )

    assert result.status == "abstained"
    assert "population_mismatch" in str(result.abstention_reason)
    assert "2021-22-gw30" in str(result.abstention_reason)


def test_an_incomplete_observation_abstains_instead_of_becoming_zero() -> None:
    folds = list(_folds())
    folds[4] = replace(
        folds[4],
        readout=replace(
            folds[4].readout,
            realized_score=None,
            probability_integral_transform=None,
            realized_below_lower_quantile=None,
        ),
    )

    result = evaluate_component_squad_calibration(
        folds,
        expected_fold_ids=_fold_ids(),
        sampler_fidelity_verified=True,
    )

    assert result.status == "abstained"
    assert result.abstention_reason == "incomplete_readout: 2021-22-gw05"


def test_duplicate_fold_identifiers_are_rejected() -> None:
    folds = list(_folds())
    folds[-1] = folds[0]

    with pytest.raises(ComponentSquadCalibrationError, match="duplicate"):
        evaluate_component_squad_calibration(
            folds,
            expected_fold_ids=_fold_ids(),
            sampler_fidelity_verified=True,
        )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"scenario_count": 999}, "scenario_count"),
        ({"realized_below_lower_quantile": False}, "disagrees"),
    ],
)
def test_a_readout_that_contradicts_the_frozen_protocol_is_rejected(
    change: dict[str, object], message: str
) -> None:
    folds = list(_folds())
    folds[0] = replace(folds[0], readout=replace(folds[0].readout, **change))

    with pytest.raises(ComponentSquadCalibrationError, match=message):
        evaluate_component_squad_calibration(
            folds,
            expected_fold_ids=_fold_ids(),
            sampler_fidelity_verified=True,
        )


@pytest.mark.parametrize("pit", [-0.01, 1.01, float("nan")])
def test_invalid_pit_values_are_rejected(pit: float) -> None:
    folds = list(_folds())
    folds[0] = replace(
        folds[0], readout=replace(folds[0].readout, probability_integral_transform=pit)
    )

    with pytest.raises(ComponentSquadCalibrationError, match="PIT"):
        evaluate_component_squad_calibration(
            folds,
            expected_fold_ids=_fold_ids(),
            sampler_fidelity_verified=True,
        )
