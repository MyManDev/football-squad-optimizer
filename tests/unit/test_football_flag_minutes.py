"""Synthetic tests of categorical flags and the whole-week minute likelihood."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import FrozenInstanceError, replace
from typing import Any

import numpy as np
import pytest

from squadopt.features.football_flag_inputs import MinuteFixture, PlayerWeekInput, TrainingWeek
from squadopt.prediction.football_flag_minutes import (
    FEATURE_VERSION,
    MODEL_VERSION,
    FlagMinutesModel,
    conditional_objective_gradient,
    hurdle_objective_gradient,
)

FIT = "2026-09-10T00:00:00Z"
TARGET = "2026-10-09T00:00:00Z"
NATIVE = (0.3, 0.1, 0.1, 0.2, 0.1, 0.1, 0.1)
MINUTES = (0.0, 30.0, 75.0, 90.0, 15.0, 65.0, 90.0)


def _week(
    *,
    player: int = 1,
    label: int | None = 75,
    fixtures: int = 1,
    training: bool = False,
    probabilities: tuple[float, ...] = NATIVE,
) -> PlayerWeekInput:
    decision = "2026-09-01T00:00:00Z" if training else TARGET
    deadline = "2026-09-01T02:00:00Z" if training else "2026-10-09T02:00:00Z"
    dates = (
        ("2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z")
        if training
        else ("2026-10-10T00:00:00Z", "2026-10-11T00:00:00Z", "2026-10-12T00:00:00Z")
    )
    return PlayerWeekInput(
        season="2026-27",
        gameweek=2 if training else 6,
        player_code=player,
        decision_at=decision,
        deadline_at=deadline,
        position="DEF",
        status="d",
        label=label,
        news_state="unknown" if label is None else "flagged",
        news_age_hours=None if label is None else 4.0,
        capture_age_hours=1.0,
        history_covered=True,
        label_changed=False,
        fixtures=tuple(
            MinuteFixture(
                fixture=100 + f,
                kickoff=dates[f],
                club=1,
                opponent=2 + f,
                home=int(f % 2 == 0),
                probabilities=probabilities,
                minutes=MINUTES,
            )
            for f in range(fixtures)
        ),
        source_sha256="a" * 64,
        native_basis_sha256="b" * 64,
        native_basis_evidence_ref="synthetic-only",
        native_basis_kind="out_of_fold" if training else "prospective",
        native_basis_fit_cutoff="2026-08-31T00:00:00Z" if training else FIT,
        calendar_complete=True,
        covered_gameweeks=(2,) if training else (6,),
        calendar_evidence_ref="synthetic-only",
    )


def _row(week: PlayerWeekInput, observed: tuple[int, ...]) -> TrainingWeek:
    return TrainingWeek(
        input=week,
        observed_states=observed,
        settled_at="2026-09-05T00:00:00Z",
        outcome_sha256="c" * 64,
    )


def _training() -> tuple[TrainingWeek, ...]:
    rows = []
    player = 1
    for label, played in ((0, 2), (25, 3), (50, 4), (75, 10), (100, 11), (None, 6)):
        for index in range(12):
            cell = 3 if label in (75, 100) else 4
            rows.append(
                _row(
                    _week(player=player, label=label, training=True),
                    (cell if index < played else 0,),
                )
            )
            player += 1
    return tuple(rows)


@pytest.fixture(scope="module")
def model() -> FlagMinutesModel:
    return FlagMinutesModel(
        _training(), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6, 7)
    )


def _finite_difference(function: Any, coefficients: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    gradient = np.zeros_like(coefficients)
    for index in range(len(coefficients)):
        delta = np.zeros_like(coefficients)
        delta[index] = 1e-6
        gradient[index] = (
            function(coefficients + delta)[0] - function(coefficients - delta)[0]
        ) / 2e-6
    return gradient


def test_hurdle_gradient_and_independent_likelihood() -> None:
    theta = np.asarray([0.2, -0.4])
    x = np.asarray([[1.0, 2.0], [1.0, -1.0], [1.0, 0.5]])
    offsets = np.asarray([-0.8, 0.4, 1.2])
    labels = np.asarray([0.0, 1.0, 1.0])

    def function(values: np.ndarray[Any, Any]) -> Any:
        return hurdle_objective_gradient(values, x, offsets, labels, 0.7)

    value, gradient = function(theta)
    logits = offsets + x @ theta
    probability = 1 / (1 + np.exp(-logits))
    expected = -sum(
        y * math.log(p) + (1 - y) * math.log1p(-p) for p, y in zip(probability, labels, strict=True)
    )
    expected += 0.7 * float(theta @ theta) / 2
    assert value == pytest.approx(expected, abs=1e-12)
    assert gradient == pytest.approx(_finite_difference(function, theta), abs=1e-8)


def test_conditional_gradient_counts_one_whole_week_once() -> None:
    theta = np.asarray([0.4, -0.3])
    designs = (
        np.asarray([[1.0, 0.0], [0.0, 2.0], [2.0, 1.0]]),
        np.asarray([[0.2, 0.7], [1.0, -1.0]]),
    )
    baselines = (np.log(np.asarray([0.2, 0.3, 0.5])), np.log(np.asarray([0.7, 0.3])))
    labels = (2, 0)

    def function(values: np.ndarray[Any, Any]) -> Any:
        return conditional_objective_gradient(values, designs, baselines, labels, 0.5)

    value, gradient = function(theta)
    expected = 0.5 * float(theta @ theta) / 2
    for x, b, label in zip(designs, baselines, labels, strict=True):
        weights = np.exp(b + x @ theta)
        expected -= math.log(weights[label] / weights.sum())
    assert value == pytest.approx(expected, abs=1e-12)
    assert gradient == pytest.approx(_finite_difference(function, theta), abs=1e-8)


@pytest.mark.parametrize("fixtures", [1, 2, 3])
@pytest.mark.parametrize("label", [0, 25, 50, 75, 100, None])
def test_zero_coefficients_are_unflagged_native_product(
    model: FlagMinutesModel, fixtures: int, label: int | None
) -> None:
    prediction = model.predict(_week(label=label, fixtures=fixtures), zero_coefficients=True)
    states = tuple(itertools.product(range(7), repeat=fixtures))
    expected = tuple(math.prod(NATIVE[cell] for cell in state) for state in states)
    assert prediction.states == states
    assert prediction.probabilities == pytest.approx(expected, abs=1e-15)
    assert prediction.weekly_appearance == pytest.approx(1 - NATIVE[0] ** fixtures, abs=1e-15)
    assert prediction.fixture_probabilities == pytest.approx(
        np.tile(NATIVE, (fixtures, 1)), abs=1e-15
    )
    assert math.fsum(prediction.probabilities) == pytest.approx(1.0, abs=1e-15)


def test_categories_learn_distinct_appearance_and_positive_roles(model: FlagMinutesModel) -> None:
    predictions = {label: model.predict(_week(label=label)) for label in (0, 25, 50, 75, 100, None)}
    assert predictions[75].weekly_appearance > predictions[50].weekly_appearance
    assert predictions[50].weekly_appearance > predictions[0].weekly_appearance > 0
    assert predictions[75].weekly_appearance != pytest.approx(0.75)
    start75 = (
        math.fsum(predictions[75].fixture_probabilities[0][1:4]) / predictions[75].weekly_appearance
    )
    start25 = (
        math.fsum(predictions[25].fixture_probabilities[0][1:4]) / predictions[25].weekly_appearance
    )
    assert start75 > start25
    assert predictions[75].fixture_probabilities[0][3] > predictions[75].fixture_probabilities[0][1]
    assert predictions[25].fixture_probabilities[0][4] > predictions[25].fixture_probabilities[0][5]
    assert predictions[None].weekly_appearance != predictions[100].weekly_appearance


def test_double_week_has_one_hurdle_and_explicit_partial_participation(
    model: FlagMinutesModel,
) -> None:
    prediction = model.predict(_week(label=0, fixtures=2))
    assert prediction.weekly_appearance == pytest.approx(
        math.fsum(prediction.probabilities[1:]), abs=1e-15
    )
    assert prediction.probabilities[0] == 1 - prediction.weekly_appearance
    assert any(
        p > 0
        for state, p in zip(prediction.states, prediction.probabilities, strict=True)
        if state[0] == 0 and state[1] > 0
    )
    for fixture in range(2):
        assert 0 < 1 - prediction.fixture_probabilities[fixture][0] <= prediction.weekly_appearance
        for cell in range(7):
            independent = math.fsum(
                p
                for state, p in zip(prediction.states, prediction.probabilities, strict=True)
                if state[fixture] == cell
            )
            assert prediction.fixture_probabilities[fixture][cell] == independent


def test_blank_week_is_exact_zero_even_with_low_flag(model: FlagMinutesModel) -> None:
    prediction = model.predict(_week(label=0, fixtures=0))
    assert prediction.states == ((),)
    assert prediction.probabilities == (1.0,)
    assert prediction.weekly_appearance == 0
    assert prediction.fixture_probabilities == ()


def test_native_unsupported_cells_are_not_invented(model: FlagMinutesModel) -> None:
    probabilities = (0.3, 0.0, 0.0, 0.7, 0.0, 0.0, 0.0)
    prediction = model.predict(_week(probabilities=probabilities))
    assert prediction.fixture_probabilities[0][1:3] == (0.0, 0.0)
    assert prediction.fixture_probabilities[0][4:] == (0.0, 0.0, 0.0)
    assert prediction.fixture_probabilities[0][3] > 0


@pytest.mark.parametrize("probabilities", [(1.0, 0, 0, 0, 0, 0, 0), (0, 0, 0, 1.0, 0, 0, 0)])
def test_native_endpoints_refuse_without_epsilon(
    model: FlagMinutesModel, probabilities: tuple[float, ...]
) -> None:
    with pytest.raises(ValueError, match="interior"):
        model.predict(_week(probabilities=probabilities))


def test_observed_state_without_native_support_refuses() -> None:
    row = _row(_week(training=True, probabilities=(0.3, 0, 0, 0.7, 0, 0, 0)), (4,))
    with pytest.raises(ValueError, match="support"):
        FlagMinutesModel((row,), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,))


@pytest.mark.parametrize(
    "name,value",
    [
        ("l2", True),
        ("l2", -1),
        ("l2", float("nan")),
        ("l2", float("inf")),
        ("max_iterations", True),
        ("max_iterations", 0),
    ],
)
def test_invalid_fit_configuration_refuses(name: str, value: Any) -> None:
    kwargs = {name: value}
    with pytest.raises(ValueError):
        FlagMinutesModel(
            _training(), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,), **kwargs
        )


def test_nonconvergence_refuses() -> None:
    with pytest.raises(ValueError, match="converge"):
        FlagMinutesModel(
            _training(),
            fit_cutoff=FIT,
            target_season="2026-27",
            target_gameweeks=(6,),
            max_iterations=1,
        )


@pytest.mark.parametrize(
    "changed", [{"season": "2025-26"}, {"gameweek": 6}, {"gameweek": 9}, {"season": "2027-28"}]
)
def test_protected_target_future_headers_refuse_before_label_access(
    changed: dict[str, Any],
) -> None:
    class NoLabels:
        def __iter__(self) -> Any:
            raise AssertionError("Observed labels were accessed before global source preflight.")

    malformed = replace(_training()[0], observed_states=NoLabels())
    late = replace(_training()[1], input=replace(_training()[1].input, **changed))
    with pytest.raises(ValueError, match=r"Protected|target|future"):
        FlagMinutesModel(
            (malformed, late), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,)
        )


def test_historical_gameweek_requires_one_original_clock() -> None:
    rows = _training()
    altered = replace(rows[1], input=replace(rows[1].input, decision_at="2026-09-01T00:01:00Z"))
    with pytest.raises(ValueError, match="original decision clock"):
        FlagMinutesModel(
            (rows[0], altered), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,)
        )


def test_settlement_at_fit_cutoff_refuses() -> None:
    with pytest.raises(ValueError, match="settlement"):
        FlagMinutesModel(
            (replace(_training()[0], settled_at=FIT),),
            fit_cutoff=FIT,
            target_season="2026-27",
            target_gameweeks=(6,),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"gameweek": 8, "covered_gameweeks": (8,)},
        {"season": "2027-28"},
        {
            "decision_at": "2026-09-09T00:00:00Z",
            "deadline_at": "2026-09-09T02:00:00Z",
            "native_basis_fit_cutoff": "2026-08-31T00:00:00Z",
        },
    ],
)
def test_prediction_target_and_model_cutoff_binding(
    model: FlagMinutesModel, changes: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        model.predict(replace(_week(), **changes))


def test_metadata_and_parameters_are_immutable_and_content_bound(model: FlagMinutesModel) -> None:
    payload = json.loads(model.metadata_json)
    assert payload["model_version"] == MODEL_VERSION
    assert payload["feature_version"] == FEATURE_VERSION
    assert (
        payload["availability_application"] == "learned_weekly_hurdle_once_no_raw_label_multiplier"
    )
    assert payload["calibration"] == "not_empirically_verified"
    assert hashlib.sha256(model.metadata_json.encode()).hexdigest() == model.model_sha256
    assert len(payload["training_receipts"]) == len(_training())
    assert tuple(payload["hurdle_coefficients"]) == model.metadata.hurdle_coefficients
    with pytest.raises(FrozenInstanceError):
        model.metadata.cutoff = TARGET  # type: ignore[misc]
    for values in (
        model._fitted.beta,
        model._fitted.gamma,
        model._fitted.means,
        model._fitted.scales,
    ):
        with pytest.raises(ValueError):
            values.setflags(write=True)
        with pytest.raises(ValueError):
            values[0] = 100


def test_failed_refit_preserves_complete_previous_state(model: FlagMinutesModel) -> None:
    before = model.predict(_week())
    metadata = model.metadata
    with pytest.raises(ValueError):
        model.fit((), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,))
    assert model.metadata is metadata
    assert model.predict(_week()) == before


def test_failure_after_hurdle_fit_does_not_publish_partial_refit(
    model: FlagMinutesModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    import squadopt.prediction.football_flag_minutes as module

    before = model.predict(_week())
    metadata = model.metadata
    optimize = module._optimize
    calls = 0

    def interrupted(function: Any, size: int, max_iterations: int) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("Synthetic conditional fit failure.")
        return optimize(function, size, max_iterations)

    monkeypatch.setattr(module, "_optimize", interrupted)
    changed_rows = tuple(
        replace(
            row,
            input=replace(row.input, capture_age_hours=100.0 if any(row.observed_states) else 1.0),
        )
        for row in _training()
    )
    with pytest.raises(ValueError, match="Synthetic conditional"):
        model.fit(changed_rows, fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6, 7))
    assert calls == 2
    assert model.metadata is metadata
    assert model.predict(_week()) == before


def test_successful_refit_binds_new_labels_and_all_parameters() -> None:
    candidate = FlagMinutesModel(
        _training(), fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,)
    )
    original = candidate.predict(_week())
    rows = tuple(
        replace(row, observed_states=(4,), outcome_sha256="d" * 64)
        if row.input.label == 75 and any(row.observed_states)
        else row
        for row in _training()
    )
    assert (
        candidate.fit(rows, fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,))
        is candidate
    )
    updated = candidate.predict(_week())
    assert updated.model_sha256 != original.model_sha256
    assert updated.weekly_appearance == original.weekly_appearance
    assert updated.fixture_probabilities[0][4] > original.fixture_probabilities[0][4]
    assert json.loads(candidate.metadata_json)["conditional_coefficients"] == list(
        candidate.metadata.conditional_coefficients
    )


def test_source_receipt_change_changes_input_digest_without_changing_numerical_forecast(
    model: FlagMinutesModel,
) -> None:
    original = model.predict(_week())
    changed = model.predict(replace(_week(), source_sha256="d" * 64))
    assert original.input_sha256 != changed.input_sha256
    assert original.probabilities == changed.probabilities
    assert original.model_sha256 == changed.model_sha256


def test_unknown_label_change_is_separate_from_observed_false(model: FlagMinutesModel) -> None:
    from squadopt.prediction.football_flag_minutes import _design

    known = _design(_week(), model._fitted.means, model._fitted.scales)
    unknown = _design(
        replace(_week(), label_changed=None), model._fitted.means, model._fitted.scales
    )
    index = model.metadata.feature_names.index("missing:label_changed")
    assert known[index] == 0
    assert unknown[index] == 1
    assert (
        model.metadata.feature_names[model.metadata.feature_names.index("label_changed")]
        == "label_changed"
    )


@pytest.mark.parametrize(
    "season,weeks",
    [
        ("2026-25", (6,)),
        ("bad", (6,)),
        ("2026-27", (39,)),
        ("2026-27", (7, 6)),
        ("2026-27", (6, 6)),
    ],
)
def test_invalid_target_contract_refuses(season: str, weeks: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="target"):
        FlagMinutesModel(_training(), fit_cutoff=FIT, target_season=season, target_gameweeks=weeks)


def test_training_order_does_not_change_fitted_receipt_or_forecast(model: FlagMinutesModel) -> None:
    reordered = FlagMinutesModel(
        tuple(reversed(_training())),
        fit_cutoff=FIT,
        target_season="2026-27",
        target_gameweeks=(6, 7),
    )
    assert reordered.metadata_json == model.metadata_json
    assert reordered.predict(_week()) == model.predict(_week())


def test_extreme_learned_numeric_values_refuse_support_saturation() -> None:
    rows = tuple(
        replace(
            row,
            input=replace(row.input, capture_age_hours=100.0 if any(row.observed_states) else 1.0),
        )
        for row in _training()
    )
    model = FlagMinutesModel(rows, fit_cutoff=FIT, target_season="2026-27", target_gameweeks=(6,))
    index = model.metadata.feature_names.index("standardized:capture_age_hours")
    assert model.metadata.hurdle_coefficients[index] > 0
    with pytest.raises(ValueError, match=r"support|underflow"):
        model.predict(replace(_week(), capture_age_hours=1e100))


def test_positive_native_state_product_underflow_refuses(model: FlagMinutesModel) -> None:
    probabilities = (0.3, 1e-250, 0.0, 0.7, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="underflow"):
        model.predict(_week(probabilities=probabilities, fixtures=3))
