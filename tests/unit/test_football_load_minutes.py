"""Invented workload histories and independent whole-week likelihood oracles."""

from __future__ import annotations

import hashlib
import itertools
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest

from squadopt.data.errors import DataError
from squadopt.features.football_load_inputs import (
    LOAD_FEATURE_NAMES,
    NATIVE_BASIS_VERSION,
    LoadFixture,
    LoadWeek,
    TrainingLoadWeek,
    load_input_digest,
    native_joint_law_digest,
)
from squadopt.prediction import football_load_minutes as load_model
from squadopt.prediction.football_load_minutes import (
    LoadMinutesModel,
    LoadTrainingExample,
    objective_gradient,
)


def _clock(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _week(
    *,
    player: int = 1,
    training: bool = False,
    fixtures: int = 2,
    cup: float = 0.0,
    gap: float = 48.0,
    gameweek: int = 6,
    joint: tuple[float, ...] | None = None,
) -> LoadWeek:
    decision = datetime(2024 if training else 2026, 9, 2, tzinfo=UTC)
    native = (0.30, 0.05, 0.10, 0.35, 0.10, 0.05, 0.05)
    states = tuple(itertools.product(range(7), repeat=fixtures))
    probabilities = tuple(math.prod(native[index] for index in state) for state in states)
    if joint is not None:
        probabilities = joint
    marginals = tuple(
        tuple(
            math.fsum(
                p
                for state, p in zip(states, probabilities, strict=True)
                if state[index] == state_bin
            )
            for state_bin in range(7)
        )
        for index in range(fixtures)
    )
    values: list[float | None] = []
    for name in LOAD_FEATURE_NAMES:
        if name.startswith("fixture_"):
            index = int(name.split("_")[1])
            values.append(None if index > fixtures else gap if "gap_hours" in name else 0.0)
        elif "travel" in name:
            values.append(None)
        elif name.startswith("non_pl_physical_minutes_"):
            values.append(cup)
        else:
            values.append(0.0)
    native_fixtures = tuple(
        LoadFixture(
            fixture_id=index + 1,
            kickoff=_clock(decision + timedelta(hours=2 + index * gap)),
            club_code=1,
            opponent_code=index + 2,
            is_home=index % 2,
            probabilities=marginals[index],
            minutes=(0.0, 30.0, 70.0, 90.0, 20.0, 65.0, 90.0),
        )
        for index in range(fixtures)
    )
    return LoadWeek(
        season="2024-25" if training else "2026-27",
        gameweek=gameweek,
        player_code=player,
        decision_at=_clock(decision),
        deadline_at=_clock(decision + timedelta(hours=1)),
        position="DEF",
        fixtures=native_fixtures,
        native_joint_states=states,
        native_joint_probabilities=probabilities,
        native_basis_sha256="a" * 64,
        native_basis_kind="out_of_fold" if training else "prospective",
        native_basis_fit_cutoff=_clock(decision - timedelta(days=40)),
        native_basis_evidence_ref="synthetic-only/native",
        source_sha256="b" * 64,
        features=tuple(values),
        feature_names=tuple(LOAD_FEATURE_NAMES),
        native_basis_version=NATIVE_BASIS_VERSION,
        interval_start_at=_clock(decision - timedelta(days=28)),
        interval_end_at=_clock(decision),
        competition_ids=("PL", "CUP"),
        coverage_evidence_ref="synthetic-only/coverage",
        mapping_evidence_ref="synthetic-only/mapping",
        calendar_complete=True,
        covered_gameweeks=(gameweek,),
        calendar_evidence_ref="synthetic-only/calendar",
        native_model_version="football_components_v1",
        native_joint_law_sha256=native_joint_law_digest(native_fixtures, states, probabilities),
    )


def _training(*, fixtures: int = 2) -> tuple[TrainingLoadWeek, ...]:
    rows = []
    for index in range(24):
        cup = 120.0 if index >= 12 else 0.0
        observed = (0 if index % 3 else 4) if cup else (3 if index % 3 else 2)
        week = _week(player=index + 1, training=True, fixtures=fixtures, cup=cup)
        rows.append(
            TrainingLoadWeek(
                input=week,
                observed_states=(observed,) * fixtures,
                settled_at=_clock(datetime(2024, 9, 10, tzinfo=UTC)),
                outcome_sha256=f"{index + 1:064x}",
            )
        )
    return tuple(rows)


def _fit(rows: tuple[TrainingLoadWeek, ...] | None = None, **kwargs: Any) -> LoadMinutesModel:
    return LoadMinutesModel().fit(
        _training() if rows is None else rows,
        cutoff="2026-09-01T00:00:00Z",
        target_season="2026-27",
        target_gameweeks=(6, 7),
        **kwargs,
    )


@pytest.fixture(scope="module")
def fitted() -> LoadMinutesModel:
    return _fit()


def test_likelihood_and_gradient_match_independent_enumeration() -> None:
    native = np.asarray([0.2, 0.3, 0.0, 0.5])
    matrix = np.asarray([[0.0, 0.0], [1.0, 2.0], [7.0, 8.0], [1.0, -1.0]])
    theta = np.asarray([0.25, -0.3])
    examples = [LoadTrainingExample(matrix, native, 1)]
    actual, gradient = objective_gradient(theta, examples, 0.4)
    weights = [
        float(p) * math.exp(float(row @ theta)) for p, row in zip(native, matrix, strict=True)
    ]
    probability = weights[1] / math.fsum(weights)
    assert actual == pytest.approx(-math.log(probability) + 0.2 * float(theta @ theta), abs=1e-14)
    for index in range(2):
        perturb = np.zeros(2)
        perturb[index] = 1e-6
        upper = objective_gradient(theta + perturb, examples, 0.4)[0]
        lower = objective_gradient(theta - perturb, examples, 0.4)[0]
        assert gradient[index] == pytest.approx((upper - lower) / 2e-6, abs=2e-9)


def test_learned_cup_exposure_changes_appearance_and_role(fitted: LoadMinutesModel) -> None:
    rested = fitted.predict(_week(cup=0))
    loaded = fitted.predict(_week(cup=120))
    assert rested.weekly_appearance > loaded.weekly_appearance + 0.15
    assert rested.fixture_probabilities[0][3] > loaded.fixture_probabilities[0][3] + 0.15
    assert loaded.fixture_probabilities[0][4] > rested.fixture_probabilities[0][4]


def test_prediction_matches_independent_published_coefficient_oracle(
    fitted: LoadMinutesModel,
) -> None:
    week = _week(cup=120)
    result = fitted.predict(week)
    metadata = fitted.metadata
    features = dict(zip(week.feature_names, week.features, strict=True))
    transforms = dict(
        zip(metadata.feature_names, zip(metadata.means, metadata.scales, strict=True), strict=True)
    )
    names = metadata.design_names
    logits = []
    for state, native in zip(result.states, week.native_joint_probabilities, strict=True):
        terms = []
        for name, coefficient in zip(names, metadata.coefficients, strict=True):
            response, feature = name.split(":", 1)
            if response == "weekly_appearance":
                multiplier = float(any(state))
            else:
                multiplier = float(state.count(load_model._BINS.index(response) + 1))
            if feature == "intercept":
                value = multiplier
            elif feature.startswith("position_"):
                value = multiplier * float(week.position == feature.removeprefix("position_"))
            elif feature.startswith("target_"):
                missing = feature.endswith("_missing")
                suffix = feature.removeprefix("target_").removesuffix("_missing")
                value = 0.0
                for index, state_bin in enumerate(state):
                    if state_bin == load_model._BINS.index(response) + 1:
                        raw = features[f"fixture_{index + 1}_" + suffix]
                        mean, scale = transforms[f"fixture_{index + 1}_" + suffix]
                        value += (
                            float(raw is None)
                            if missing
                            else 0
                            if raw is None
                            else (raw - mean) / scale
                        )
            elif feature in (
                "prior_week_minutes90",
                "prior_fixture_gap_scaled",
                "prior_minutes90_x_gap_scaled",
            ):
                value = 0.0
                prior = 0.0
                for index, state_bin in enumerate(state):
                    if index and state_bin == load_model._BINS.index(response) + 1:
                        gap = (48.0 - metadata.gap_mean_hours) / metadata.gap_scale_hours
                        value += (
                            prior
                            if feature == "prior_week_minutes90"
                            else gap
                            if feature == "prior_fixture_gap_scaled"
                            else prior * gap
                        )
                    prior += week.fixtures[index].minutes[state_bin] / 90
            else:
                missing = feature.endswith("_missing")
                base = feature.removesuffix("_missing")
                raw = features[base]
                mean, scale = transforms[base]
                value = multiplier * (
                    float(raw is None) if missing else 0 if raw is None else (raw - mean) / scale
                )
            terms.append(coefficient * value)
        logits.append(math.log(native) + math.fsum(terms) if native else -math.inf)
    maximum = max(logits)
    weights = [math.exp(logit - maximum) for logit in logits]
    expected = tuple(weight / math.fsum(weights) for weight in weights)
    assert result.probabilities == pytest.approx(expected, abs=2e-15)


def test_zero_coefficients_preserve_dependent_native_joint_law(fitted: LoadMinutesModel) -> None:
    states = tuple(itertools.product(range(7), repeat=2))
    probabilities = tuple(
        0.4 if state == (0, 0) else 0.6 if state == (3, 3) else 0 for state in states
    )
    week = _week(joint=probabilities)
    result = fitted.predict(week, zero_coefficients=True)
    assert result.probabilities == probabilities
    assert result.weekly_appearance == 0.6
    assert result.fixture_probabilities == ((0.4, 0, 0, 0.6, 0, 0, 0),) * 2
    assert result.weekly_appearance != 1 - result.fixture_probabilities[0][0] ** 2


def test_learning_never_creates_structural_native_support(fitted: LoadMinutesModel) -> None:
    states = tuple(itertools.product(range(7), repeat=2))
    probabilities = tuple(
        0.4 if state == (0, 0) else 0.6 if state == (3, 3) else 0 for state in states
    )
    result = fitted.predict(_week(joint=probabilities))
    assert all(
        p == 0
        for state, p in zip(result.states, result.probabilities, strict=True)
        if state not in ((0, 0), (3, 3))
    )
    assert math.fsum(result.probabilities) == pytest.approx(1, abs=1e-15)


def test_blank_gameweek_and_deterministic_support_are_valid() -> None:
    blank = _week(training=True, fixtures=0)
    row = TrainingLoadWeek(blank, (), "2024-09-10T00:00:00Z", "c" * 64)
    model = _fit((row,))
    result = model.predict(_week(fixtures=0))
    assert result.states == ((),)
    assert result.probabilities == (1.0,)
    assert result.weekly_appearance == 0
    assert result.fixture_probabilities == ()


@pytest.mark.parametrize("fixtures", [1, 2, 3])
def test_full_bounded_calendar_and_marginal_closure(fixtures: int) -> None:
    model = _fit(_training(fixtures=fixtures))
    result = model.predict(_week(fixtures=fixtures))
    assert len(result.states) == 7**fixtures
    assert math.fsum(result.probabilities) == pytest.approx(1, abs=1e-15)
    for index, marginal in enumerate(result.fixture_probabilities):
        expected = tuple(
            math.fsum(
                p
                for state, p in zip(result.states, result.probabilities, strict=True)
                if state[index] == state_bin
            )
            for state_bin in range(7)
        )
        assert marginal == expected


def test_train_only_scalers_and_source_receipts(fitted: LoadMinutesModel) -> None:
    before = fitted.metadata_json
    fitted.predict(_week(cup=900))
    assert fitted.metadata_json == before
    feature_index = fitted.metadata.feature_names.index("non_pl_physical_minutes_7d")
    assert fitted.metadata.means[feature_index] == 60
    assert fitted.metadata.scales[feature_index] == 60
    payload = json.loads(before)
    assert payload["eligibility_policy"] == "not_applied_by_model"
    assert fitted.metadata.model_sha256 == hashlib.sha256(before.encode()).hexdigest()
    assert fitted.metadata.training_input_sha256 == tuple(
        load_input_digest(row.input) for row in _training()
    )


def test_missing_values_are_explicit_and_untrained_observation_refuses(
    fitted: LoadMinutesModel,
) -> None:
    week = _week()
    index = week.feature_names.index("actual_travel_distance_km")
    values = list(week.features)
    values[index] = 0.0
    with pytest.raises(ValueError, match="no training support"):
        fitted.predict(replace(week, features=tuple(values)))
    assert fitted.metadata.known_counts[index] == 0
    assert "actual_travel_distance_km_missing" in " ".join(fitted.metadata.design_names)


def test_metadata_and_parameters_are_immutable(fitted: LoadMinutesModel) -> None:
    with pytest.raises(FrozenInstanceError):
        fitted.metadata.cutoff = "changed"  # type: ignore[misc]
    state = fitted._fitted
    assert state is not None
    with pytest.raises(ValueError):
        state.coefficients[0] = 1
    with pytest.raises(ValueError):
        state.coefficients.setflags(write=True)


@pytest.mark.parametrize(
    "field", ["means", "scales", "known_counts", "names", "gap_mean", "gap_scale"]
)
def test_internal_transform_replacement_refuses(field: str) -> None:
    model = _fit()
    fitted = model._fitted
    assert fitted is not None
    value = getattr(fitted.transform, field)
    changed = (
        ("changed", *value[1:])
        if field == "names"
        else (value[0] + 1, *value[1:])
        if isinstance(value, tuple)
        else value + 1
    )
    model._fitted = replace(fitted, transform=replace(fitted.transform, **{field: changed}))
    with pytest.raises(ValueError, match="receipt"):
        model.predict(_week(), zero_coefficients=True)


@pytest.mark.parametrize(
    "field,value",
    [
        ("cutoff", "2026-08-01T00:00:00Z"),
        ("target_gameweeks", (6, 7, 8)),
        ("model_version", "changed"),
        ("feature_version", "changed"),
        ("design_names", ("changed",)),
    ],
)
def test_internal_metadata_replacement_refuses(field: str, value: Any) -> None:
    model = _fit()
    fitted = model._fitted
    assert fitted is not None
    model._fitted = replace(fitted, metadata=replace(fitted.metadata, **{field: value}))
    with pytest.raises(ValueError, match="receipt"):
        model.predict(_week())


def test_packed_objective_equals_dense_algebra_and_uses_less_storage(
    fitted: LoadMinutesModel,
) -> None:
    state = fitted._fitted
    assert state is not None
    week = _week(fixtures=2)
    context, counts, trailing, names = load_model._packed_design(week, state.transform)
    dense = np.concatenate(
        [np.einsum("ij,k->ijk", counts, context).reshape(len(counts), -1), trailing], axis=1
    )
    native = np.asarray(week.native_joint_probabilities)
    observed = week.native_joint_states.index((3, 4))
    theta = np.asarray(fitted.metadata.coefficients)
    packed = load_model._PackedExample(context, counts, trailing, native, observed)
    expected = objective_gradient(theta, [LoadTrainingExample(dense, native, observed)], 0.8)
    actual = load_model._packed_objective_gradient(theta, [packed], 0.8)
    assert names == fitted.metadata.design_names
    assert actual[0] == pytest.approx(expected[0], abs=1e-13)
    assert actual[1] == pytest.approx(expected[1], abs=1e-13)
    assert context.nbytes + counts.nbytes + trailing.nbytes < dense.nbytes / 8


def test_ordered_state_minutes_and_kickoff_gap_cross_later_role(fitted: LoadMinutesModel) -> None:
    state = fitted._fitted
    assert state is not None
    week = _week(gap=72)
    context, counts, trailing, names = load_model._packed_design(week, state.transform)
    start = week.native_joint_states.index((3, 4))
    cameo = week.native_joint_states.index((4, 3))
    absent = week.native_joint_states.index((0, 4))
    offset = 7 * len(context)
    column = names.index("cameo_short:prior_week_minutes90") - offset
    assert trailing[start, column] == 1
    assert trailing[cameo, column] == 0
    assert trailing[absent, column] == 0
    gap = (72 - fitted.metadata.gap_mean_hours) / fitted.metadata.gap_scale_hours
    interaction = names.index("cameo_short:prior_minutes90_x_gap_scaled") - offset
    assert trailing[start, interaction] == gap
    first_only = week.native_joint_states.index((4, 0))
    assert trailing[first_only, column] == 0
    assert counts[start, 0] == 1


def test_near_unit_mass_is_normalized_once_with_original_digest(fitted: LoadMinutesModel) -> None:
    week = _week()
    scale = 1 + 5e-13
    changed = replace(
        week,
        native_joint_probabilities=tuple(p * scale for p in week.native_joint_probabilities),
        fixtures=tuple(
            replace(fixture, probabilities=tuple(p * scale for p in fixture.probabilities))
            for fixture in week.fixtures
        ),
    )
    changed = replace(
        changed,
        native_joint_law_sha256=native_joint_law_digest(
            changed.fixtures,
            changed.native_joint_states,
            changed.native_joint_probabilities,
        ),
    )
    result = fitted.predict(changed, zero_coefficients=True)
    assert math.fsum(changed.native_joint_probabilities) > 1
    assert math.fsum(result.probabilities) == pytest.approx(1, abs=1e-15)
    assert result.probabilities == pytest.approx(week.native_joint_probabilities, abs=2e-16)
    assert result.input_sha256 == load_input_digest(changed)
    assert result.input_sha256 != load_input_digest(week)


def test_failed_refit_does_not_replace_fitted_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _fit()
    before = model.predict(_week())
    receipt = model.metadata_json
    monkeypatch.setattr(
        load_model,
        "minimize",
        lambda *args, **kwargs: SimpleNamespace(
            success=False, x=np.zeros(len(model.metadata.coefficients))
        ),
    )
    with pytest.raises(ValueError, match="did not converge"):
        model.fit(
            _training(),
            cutoff="2026-09-01T00:00:00Z",
            target_season="2026-27",
            target_gameweeks=(6, 7),
        )
    assert model.metadata_json == receipt
    assert model.predict(_week()) == before


def test_global_causal_header_preflight_precedes_observed_labels() -> None:
    class Unreadable:
        def __iter__(self) -> Any:
            raise AssertionError("observed label was read")

    first = replace(_training()[0], observed_states=cast(Any, Unreadable()))
    later = replace(_training()[1], input=_week(player=99, training=False, gameweek=6))
    with pytest.raises(ValueError, match="outside the causal"):
        _fit((first, later))


def test_historical_gameweek_requires_one_decision_clock() -> None:
    rows = _training()
    second = replace(
        rows[1].input,
        decision_at="2024-09-02T00:01:00Z",
        interval_end_at="2024-09-02T00:01:00Z",
        interval_start_at="2024-08-05T00:01:00Z",
    )
    with pytest.raises(ValueError, match="one original decision"):
        _fit((rows[0], replace(rows[1], input=second)))


def test_observed_state_without_native_support_refuses() -> None:
    states = tuple(itertools.product(range(7), repeat=2))
    probabilities = tuple(float(state == (0, 0)) for state in states)
    row = replace(_training()[0], input=_week(training=True, joint=probabilities))
    with pytest.raises(ValueError, match="native support"):
        _fit((row,))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"l2": True},
        {"l2": -1},
        {"l2": math.nan},
        {"max_iterations": True},
        {"max_iterations": 0},
        {"max_iterations": 1001},
    ],
)
def test_fit_resource_parameters_refuse_invalid_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        _fit(**kwargs)


@pytest.mark.parametrize(
    "season,gameweeks",
    [
        ("2025-26", (6,)),
        ("2026-28", (6,)),
        ("2026-27", (0,)),
        ("2026-27", (39,)),
        ("2026-27", (True,)),
        ("2026-27", (7, 6)),
        ("2026-27", ()),
    ],
)
def test_target_scope_refuses_invalid_or_protected_values(
    season: str, gameweeks: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError):
        LoadMinutesModel().fit(
            _training(),
            cutoff="2026-09-01T00:00:00Z",
            target_season=season,
            target_gameweeks=gameweeks,
        )


@pytest.mark.parametrize(
    "change", [{"season": "2025-26"}, {"gameweek": 8}, {"decision_at": "2026-08-31T00:00:00Z"}]
)
def test_prediction_target_clock_refusal(fitted: LoadMinutesModel, change: dict[str, Any]) -> None:
    with pytest.raises((ValueError, DataError)):
        fitted.predict(replace(_week(), **change))


def test_not_fitted_public_metadata_and_predict_refuse() -> None:
    model = LoadMinutesModel()
    with pytest.raises(ValueError, match="not fitted"):
        _ = model.metadata
    with pytest.raises(ValueError, match="not fitted"):
        _ = model.metadata_json
    with pytest.raises(ValueError, match="not fitted"):
        model.predict(_week())


def test_underflow_refuses_instead_of_erasing_supported_states(fitted: LoadMinutesModel) -> None:
    with pytest.raises(ValueError, match="underflow"):
        fitted.predict(_week(cup=1e300))


def test_duplicate_training_player_week_refuses() -> None:
    row = _training()[0]
    with pytest.raises(ValueError, match="duplicate"):
        _fit((row, row))


def test_settled_training_at_cutoff_refuses() -> None:
    row = replace(_training()[0], settled_at="2026-09-01T00:00:00Z")
    with pytest.raises(DataError, match="strictly before"):
        _fit((row,))


def test_target_future_training_refuses_before_labels() -> None:
    row = replace(_training()[0], input=replace(_week(training=True), season="2027-28"))
    with pytest.raises(ValueError, match="causal"):
        _fit((row,))


def test_flag_feature_is_not_an_allowed_workload_input(fitted: LoadMinutesModel) -> None:
    week = _week()
    changed = replace(week, feature_names=(*week.feature_names[:-1], "fpl_flag75"))
    with pytest.raises(DataError, match="feature inventory"):
        fitted.predict(changed)
    assert all("flag" not in name for name in fitted.metadata.feature_names)


def test_full_duration_states_allow_120_physical_proxy_minutes(fitted: LoadMinutesModel) -> None:
    week = _week()
    fixtures = tuple(
        replace(fixture, minutes=(*fixture.minutes[:3], 120.0, *fixture.minutes[4:6], 120.0))
        for fixture in week.fixtures
    )
    changed = replace(
        week,
        fixtures=fixtures,
        native_joint_law_sha256=native_joint_law_digest(
            fixtures, week.native_joint_states, week.native_joint_probabilities
        ),
    )
    result = fitted.predict(changed, zero_coefficients=True)
    assert result.probabilities == pytest.approx(week.native_joint_probabilities, abs=1e-15)


def test_zero_switch_must_be_boolean(fitted: LoadMinutesModel) -> None:
    with pytest.raises(ValueError, match="Boolean"):
        fitted.predict(_week(), zero_coefficients=cast(Any, 1))


def test_equivalent_offset_clocks_preserve_forecast_and_original_digest(
    fitted: LoadMinutesModel,
) -> None:
    week = _week()
    offset = timezone(timedelta(hours=3))
    fixtures = tuple(
        replace(
            fixture, kickoff=datetime.fromisoformat(fixture.kickoff).astimezone(offset).isoformat()
        )
        for fixture in week.fixtures
    )
    changed = replace(
        week,
        fixtures=fixtures,
        decision_at="2026-09-02T03:00:00+03:00",
        native_joint_law_sha256=native_joint_law_digest(
            fixtures, week.native_joint_states, week.native_joint_probabilities
        ),
    )
    actual = fitted.predict(changed)
    expected = fitted.predict(week)
    assert actual.probabilities == expected.probabilities
    assert actual.input_sha256 != expected.input_sha256
    assert actual.input_sha256 == load_input_digest(changed)


def test_common_historical_clock_compares_instant_and_fit_cutoff_is_canonical() -> None:
    rows = _training()
    second = replace(rows[1], input=replace(rows[1].input, decision_at="2024-09-02T01:00:00+01:00"))
    model = LoadMinutesModel().fit(
        (rows[0], second),
        cutoff="2026-09-01T03:00:00+03:00",
        target_season="2026-27",
        target_gameweeks=(6, 7),
    )
    assert model.metadata.cutoff == "2026-09-01T00:00:00Z"


def test_naive_clock_is_not_interpreted_as_local_time(fitted: LoadMinutesModel) -> None:
    with pytest.raises(DataError, match="UTC offset"):
        fitted.predict(replace(_week(), decision_at="2026-09-02T00:00:00"))


def test_unknown_load_mask_is_learned_separately_from_known_zero() -> None:
    index = tuple(LOAD_FEATURE_NAMES).index("player_physical_minutes_7d")
    rows = []
    for player in range(1, 13):
        week = _week(training=True, player=player)
        values = list(week.features)
        unknown = player > 6
        values[index] = None if unknown else 0.0
        rows.append(
            TrainingLoadWeek(
                replace(week, features=tuple(values)),
                (0, 0) if unknown else (3, 3),
                "2024-09-10T00:00:00Z",
                f"{player:064x}",
            )
        )
    model = _fit(tuple(rows))
    known = _week()
    values = list(known.features)
    values[index] = None
    unknown_week = replace(known, features=tuple(values))
    assert (
        model.predict(known).weekly_appearance > model.predict(unknown_week).weekly_appearance + 0.2
    )
    fitted = model._fitted
    assert fitted is not None
    known_context = load_model._context(known, fitted.transform)
    unknown_context = load_model._context(unknown_week, fitted.transform)
    mask = known_context[1].index("player_physical_minutes_7d_missing")
    value = known_context[1].index("player_physical_minutes_7d")
    assert known_context[0][mask] == 0
    assert unknown_context[0][mask] == 1
    assert known_context[0][value] == unknown_context[0][value] == 0
