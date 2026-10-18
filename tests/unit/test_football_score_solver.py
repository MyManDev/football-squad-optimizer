"""Independent bounded optima and failure-atomic solver fallback contracts."""

from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from tests.unit.test_football_score_replay import fit as replay_fit
from tests.unit.test_football_score_replay import replay
from tests.unit.test_football_score_state import CUTOFF, fit, fixture, observation

import squadopt.prediction.football_score_state as module
from squadopt.prediction.football_score_state import (
    ScoreSolvedMetadata,
    ScoreSolvedReplayMetadata,
    ScoreStateModel,
    ScoreTrainingExample,
    _projected_gradient,
    _separable_solution,
    objective_gradient,
    training_design,
)

UNIT = tuple(tuple(float(i == j) for i in range(6)) for j in range(6))
ZERO = (0.0,) * 6


def example(
    masses: tuple[float, ...] = (2, 4, 0, 0, 1, 1),
    counts: tuple[int, ...] = (4, 1, 2, 0, 0, 1000),
) -> ScoreTrainingExample:
    events = tuple(vector for vector, count in zip(UNIT, counts, strict=True) for _ in range(count))
    return ScoreTrainingExample(masses, UNIT, (math.log(0.25),) * len(events), events)


def abnormal(**changes: Any) -> SimpleNamespace:
    values = dict(success=False, status=2, nit=7, x=np.zeros(6))
    values.update(changes)
    return SimpleNamespace(**values)


def force(monkeypatch: pytest.MonkeyPatch, result: SimpleNamespace) -> None:
    monkeypatch.setattr(module, "minimize", lambda *args, **kwargs: result)


def test_unpenalized_analytic_optima_include_both_bounds_and_flat_tie() -> None:
    row = example()
    coefficients, iterations = _separable_solution((row,), 0)
    expected = (math.log(2), -math.log(4), 6, 0, -6, 6)
    assert coefficients == pytest.approx(expected, abs=2e-15)
    _, gradient = objective_gradient(coefficients, (row,), 0)
    assert _projected_gradient(coefficients, gradient) < 1e-12
    assert abs(gradient[5]) > 500  # A correct active bound can have a large raw gradient.
    assert iterations[2:] == (0, 0, 0, 0)
    assert all(0 <= count <= 128 for count in iterations)


@pytest.mark.parametrize("l2", [0.1, 1, 10])
def test_ridge_optimum_matches_independent_dense_loss_and_feasible_perturbations(l2: float) -> None:
    masses = (2.0, 4.0, 0.0, 0.0, 1.0, 1.0)
    counts = (4, 1, 2, 0, 0, 1000)
    row = example(masses, counts)
    beta, _ = _separable_solution((row,), l2)

    def independent_loss(values: np.ndarray) -> float:
        return sum(
            mass * math.exp(value) - count * value + l2 * value * value / 2
            for value, mass, count in zip(values, masses, counts, strict=True)
        ) - sum(counts) * math.log(0.25)

    loss, gradient = objective_gradient(beta, (row,), l2)
    assert loss == pytest.approx(independent_loss(beta), abs=1e-10)
    assert _projected_gradient(beta, gradient) < 1e-12
    for coordinate in range(6):
        for step in (-0.01, 0.01):
            candidate = beta.copy()
            candidate[coordinate] += step
            if abs(candidate[coordinate]) <= 6:
                assert independent_loss(candidate) >= independent_loss(beta) - 1e-10


@pytest.mark.parametrize("l2", [0, 1])
def test_zero_feature_constants_and_empty_examples_do_not_change_optimum(l2: float) -> None:
    row = example()
    constant = ScoreTrainingExample((3,), (ZERO,), (math.log(0.2),), (ZERO,))
    empty = ScoreTrainingExample((), (), (), ())
    expected, _ = _separable_solution((row,), l2)
    result, _ = _separable_solution((row, constant, empty), l2)
    assert np.array_equal(result, expected)
    zero, _ = _separable_solution((empty,), l2)
    assert np.array_equal(zero, np.zeros(6))


@pytest.mark.parametrize("l2", [True, -1, float("inf"), float("nan"), "1"])
def test_invalid_penalty_refuses(l2: Any) -> None:
    with pytest.raises(ValueError, match="l2"):
        _separable_solution((example(),), l2)


@pytest.mark.parametrize(
    "changes",
    [
        {"exposure_masses": (1,)},
        {"event_log_offsets": ()},
        {"exposure_masses": (True, 1, 1, 1, 1, 1)},
        {"exposure_masses": (-1, 1, 1, 1, 1, 1)},
        {"exposure_masses": (float("nan"), 1, 1, 1, 1, 1)},
        {"exposure_masses": (float("inf"), 1, 1, 1, 1, 1)},
        {"exposure_features": ((0, 0, 0, 0, 0),) * 6},
        {"exposure_features": ((1, 1, 0, 0, 0, 0),) * 6},
        {"exposure_features": ((0.5, 0, 0, 0, 0, 0),) * 6},
        {"exposure_features": ((-1, 0, 0, 0, 0, 0),) * 6},
        {"exposure_features": ((True, 0, 0, 0, 0, 0),) * 6},
        {"exposure_features": ((float("nan"), 0, 0, 0, 0, 0),) * 6},
    ],
)
def test_invalid_or_nonseparable_design_refuses(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="design"):
        _separable_solution((replace(example(), **changes),), 1)


def test_nonfinite_event_offset_and_exposure_overflow_refuse() -> None:
    with pytest.raises(ValueError, match="design"):
        _separable_solution((ScoreTrainingExample((), (), (float("inf"),), (ZERO,)),), 1)
    overflowing = ScoreTrainingExample((1e308, 1e308), (UNIT[0], UNIT[0]), (), ())
    with pytest.raises(ValueError, match="finite support"):
        _separable_solution((overflowing,), 1)


def test_status_two_fallback_has_an_independently_certified_immutable_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force(monkeypatch, abnormal())
    row = observation(sequence=((10, 1), (20, 1), (70, 2)))
    model = fit((row,))
    assert type(model.metadata) is ScoreSolvedMetadata
    receipt = model.metadata.solver_receipt
    assert receipt.original_status == 2
    assert receipt.original_iterations == model.metadata.optimizer_iterations == 7
    assert receipt.projected_gradient_max_abs <= 1e-8
    assert receipt.kkt_tolerance == 1e-8
    design = training_design(row)
    beta = np.asarray(model.metadata.coefficients)
    loss, gradient = objective_gradient(beta, (design,), model.metadata.l2)
    assert loss == model.metadata.objective
    assert _projected_gradient(beta, gradient) == receipt.projected_gradient_max_abs
    assert model.predict(fixture(target=True)).model_sha256 == model.model_sha256
    assert json.loads(model.metadata_json)["solver_receipt"]["original_status"] == 2
    with pytest.raises(FrozenInstanceError):
        receipt.original_status = 0  # type: ignore[misc]


def test_replay_fallback_preserves_typed_source_receipts_and_explicit_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force(monkeypatch, abnormal())
    row = replay(released=True)
    model = replay_fit((row,), allowed_seasons=("2025-26",), allow_released_2025_26=True)
    assert type(model.metadata) is ScoreSolvedReplayMetadata
    assert model.metadata.allow_released_2025_26 is True
    assert model.metadata.replay_receipts[0][1] == row.basis.provenance
    assert model.metadata.replay_receipts[0][1].revision == row.basis.provenance.revision
    encoded = json.loads(model.metadata_json)
    assert encoded["replay_receipts"][0][1]["revision"] == row.basis.provenance.revision
    assert encoded["solver_receipt"]["method"] == "separable_bounded_derivative_bisection_v1"


@pytest.mark.parametrize(
    "changes",
    [
        {"status": 1},
        {"status": True},
        {"status": None},
        {"status": 3},
        {"success": True, "status": None},
        {"success": True, "status": True},
        {"success": True, "status": 1},
        {"success": True, "status": 2},
        {"nit": None},
        {"nit": True},
        {"nit": -1},
        {"nit": 1000},
        {"nit": 1001},
        {"success": "false"},
        {"x": np.zeros((1, 6))},
        {"x": np.zeros(5)},
        {"x": np.full(6, float("nan"))},
        {"x": np.full(6, float("inf"))},
        {"x": np.full(6, 6.1)},
        {"x": np.full(6, True)},
        {"x": np.full(6, "0")},
        {"x": np.full(6, 1j)},
        {"x": np.full(6, None)},
    ],
)
def test_invalid_optimizer_results_do_not_publish_or_replace_a_fit(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, Any]
) -> None:
    model = fit((observation(),))
    before = model.metadata_json
    force(monkeypatch, abnormal(**changes))
    for target in (model, ScoreStateModel()):
        with pytest.raises(ValueError, match="optimizer"):
            target.fit(
                (observation(),),
                cutoff=CUTOFF,
                target_season="2026-27",
                target_gameweeks=(6, 7),
                allowed_seasons=("2024-25",),
            )
    assert model.metadata_json == before


def test_original_objective_certificate_failure_does_not_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    force(monkeypatch, abnormal())
    monkeypatch.setattr(module, "_separable_solution", lambda *args: (np.zeros(6), (1,) * 6))
    with pytest.raises(ValueError, match="original objective KKT"):
        fit((observation(),))


def test_successful_optimizer_path_never_runs_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    before = fit((observation(),)).metadata_json

    def forbidden(*args: Any) -> None:
        raise AssertionError("successful legacy fit must not run the coordinate solver")

    monkeypatch.setattr(module, "_separable_solution", forbidden)
    after = fit((observation(),)).metadata_json
    assert before == after
    assert "solver_receipt" not in json.loads(after)
