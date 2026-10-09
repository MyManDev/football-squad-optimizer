"""Independent invented likelihood, score-chain and interval survival oracles."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any

import numpy as np
import pytest
from scipy.linalg import expm
from scipy.stats import poisson, skellam

import squadopt.prediction.football_score_state as module
from squadopt.features.football_score_state_inputs import (
    CLOCK_VERSION,
    FPLCredit,
    ObservedPlayerExposure,
    PhysicalGoal,
    PhysicalPeriod,
    ScoreFixture,
    ScorePlayer,
    TrainingScoreFixture,
    score_input_digest,
)
from squadopt.prediction.football_score_state import (
    FEATURE_NAMES,
    MODEL_VERSION,
    ScoreStateModel,
    ScoreTrainingExample,
    _Process,
    objective_gradient,
    training_design,
)

CUTOFF = "2026-10-09T00:00:00Z"


def clock(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def player(code: int, club: int, horizon: float = 96, *, four: bool = False) -> ScorePlayer:
    if four:
        return ScorePlayer(
            code,
            club,
            "DEF",
            (0, 0, 0, 1),
            (0, 15, 75, 90),
            (0, 0, 0, 0),
            (0, 16, 80, horizon),
            ("not_playing", "normal_substitution", "normal_substitution", "full_time"),
            "four_bins",
        )
    return ScorePlayer(
        code,
        club,
        "DEF",
        (0, 0, 0, 1, 0, 0, 0),
        (0, 15, 75, 90, 15, 75, 90),
        (0, 0, 0, 0, horizon - 16, horizon - 80, horizon - 90),
        (0, 16, 80, horizon, horizon, horizon, horizon),
        (
            "not_playing",
            "normal_substitution",
            "normal_substitution",
            "full_time",
            "full_time",
            "full_time",
            "full_time",
        ),
    )


def fixture(
    index: int = 0,
    *,
    target: bool = False,
    home: float = 1.5,
    away: float = 0.9,
    four: bool = False,
) -> ScoreFixture:
    kickoff = (
        datetime(2026, 10, 11, 12, tzinfo=UTC)
        if target
        else datetime(2024, 9, 1, 12, tzinfo=UTC) + timedelta(weeks=index)
    )
    decision = kickoff - timedelta(days=1)
    return ScoreFixture(
        "2026-27" if target else "2024-25",
        6 if target else index + 1,
        index + 1,
        clock(decision),
        clock(kickoff - timedelta(hours=6)),
        clock(kickoff),
        1,
        2,
        home,
        away,
        96.0,
        CLOCK_VERSION,
        tuple(player(code, 1 if code <= 2 else 2, four=four) for code in range(1, 5)),
        "a" * 64,
        "football_team_share_v1" if four else "football_joint_role_minutes_v1",
        "prospective" if target else "out_of_fold",
        clock(decision - timedelta(hours=1)),
        "synthetic-native-only",
        "b" * 64,
        "synthetic-complete-paired",
        "synthetic-frozen-calendar",
    )


def observation(
    index: int = 0,
    *,
    sequence: tuple[tuple[float, int], ...] = ((10, 1), (30, 1), (70, 1)),
    actual: float = 96,
) -> TrainingScoreFixture:
    source = fixture(index, home=1, away=1)
    first = actual / 2
    goals = tuple(
        PhysicalGoal(
            f"goal-{index}-{ordinal}",
            elapsed,
            1 if elapsed <= first else 2,
            elapsed if elapsed <= first else elapsed - first,
            club,
            club,
            1 if club == 1 else 3,
            False,
            ordinal,
        )
        for ordinal, (elapsed, club) in enumerate(sequence, 1)
    )
    exposures = tuple(
        ObservedPlayerExposure(
            item.player_code,
            item.club_code,
            0,
            actual,
            90 if actual >= 90 else int(actual),
            1,
            "full_time",
        )
        for item in source.players
    )
    return TrainingScoreFixture(
        source,
        goals,
        (PhysicalPeriod(1, first), PhysicalPeriod(2, actual - first)),
        actual,
        sum(club == 1 for _, club in sequence),
        sum(club == 2 for _, club in sequence),
        tuple(
            FPLCredit(
                goal.event_id, goal.scorer_player_code, 2 if goal.beneficiary_club_code == 1 else 4
            )
            for goal in goals
        ),
        exposures,
        clock(datetime.fromisoformat(source.kickoff.replace("Z", "+00:00")) + timedelta(hours=4)),
        f"{index + 1:064x}",
    )


def fit(rows: tuple[TrainingScoreFixture, ...] | None = None, **options: Any) -> ScoreStateModel:
    return ScoreStateModel().fit(
        rows or tuple(observation(index) for index in range(12)),
        cutoff=CUTOFF,
        target_season="2026-27",
        target_gameweeks=(6, 7),
        allowed_seasons=("2024-25",),
        **options,
    )


@pytest.fixture(scope="module")
def learned() -> ScoreStateModel:
    return fit()


def test_predictable_state_is_logged_before_the_goal() -> None:
    design = training_design(observation(sequence=((10, 1), (20, 1), (30, 2))))
    assert design.event_features[0] == (0, 0, 0, 0, 0, 0)
    assert design.event_features[1] == (1, 0, 0, 0, 0, 0)
    assert design.event_features[2] == (0, 1, 0, 0, 0, 0)
    assert len(design.event_features) == 3


def test_event_at_forecast_third_uses_new_phase() -> None:
    design = training_design(observation(sequence=((10, 1), (32, 1), (64, 2))))
    assert design.event_features == ((0, 0, 0, 0, 0, 0), (0, 0, 1, 0, 0, 0), (0, 0, 0, 0, 0, 1))


def test_actual_settlement_duration_does_not_replace_forecast_clock() -> None:
    row = observation(sequence=((10, 1),), actual=104)
    design = training_design(row)
    assert math.fsum(design.exposure_masses) == pytest.approx(2 * 104 / 96)
    assert row.input.forecast_duration == 96
    last_features = design.exposure_features[-2:]
    assert last_features == ((0, 0, 0, 0, 1, 0), (0, 0, 0, 0, 0, 1))


def test_objective_and_gradient_match_direct_history_oracle() -> None:
    row = observation(sequence=((10, 1), (20, 2), (40, 2), (80, 1)))
    coefficients = np.asarray([0.1, -0.3, 0.4, -0.1, 0.2, -0.2])
    loss, gradient = objective_gradient(coefficients, (training_design(row),), 0.7)
    points = sorted({0.0, 32.0, 64.0, row.actual_duration, *(goal.elapsed for goal in row.goals)})
    expected = 0.35 * float(coefficients @ coefficients)
    counts = {1: 0, 2: 0}
    for left, right in pairwise(points):
        for goal in row.goals:
            if goal.elapsed == left:
                counts[goal.beneficiary_club_code] += 1
        phase = min(2, int(3 * ((left + right) / 2) / 96))
        for club in (1, 2):
            difference = counts[club] - counts[3 - club]
            multiplier = (
                1 if difference == 0 else math.exp(coefficients[phase * 2 + (difference < 0)])
            )
            expected += (right - left) * multiplier / 96
    counts = {1: 0, 2: 0}
    for goal in row.goals:
        club = goal.beneficiary_club_code
        difference = counts[club] - counts[3 - club]
        phase = min(2, int(3 * goal.elapsed / 96))
        expected -= math.log(1 / 96) + (
            0 if difference == 0 else coefficients[phase * 2 + (difference < 0)]
        )
        counts[club] += 1
    assert loss == pytest.approx(expected, abs=1e-12)
    epsilon = 1e-6
    independent = []
    for index in range(6):
        direction = np.zeros(6)
        direction[index] = epsilon
        plus = objective_gradient(coefficients + direction, (training_design(row),), 0.7)[0]
        minus = objective_gradient(coefficients - direction, (training_design(row),), 0.7)[0]
        independent.append((plus - minus) / (2 * epsilon))
    np.testing.assert_allclose(gradient, independent, atol=2e-8, rtol=1e-7)


def test_empty_score_example_preserves_native_exposure_likelihood() -> None:
    example = training_design(observation(sequence=()))
    loss, gradient = objective_gradient(np.zeros(6), (example,), 1)
    assert loss == pytest.approx(2)
    assert not np.any(gradient)


def test_independent_minimal_design_exact_gradient() -> None:
    example = ScoreTrainingExample(
        (2.0,), ((1.0, 0, 0, 0, 0, 0),), (math.log(0.5),), ((1.0, 0, 0, 0, 0, 0),)
    )
    values = np.asarray([0.3, 0, 0, 0, 0, 0])
    loss, gradient = objective_gradient(values, (example,), 0.4)
    assert loss == pytest.approx(2 * math.exp(0.3) - 0.3 - math.log(0.5) + 0.2 * 0.3**2)
    assert gradient[0] == pytest.approx(2 * math.exp(0.3) - 1 + 0.4 * 0.3)


def test_zero_process_matches_independent_poisson_difference_and_survival(
    learned: ScoreStateModel,
) -> None:
    source = fixture(target=True)
    result = learned.predict(source, zero_coefficients=True)
    assert result.home_physical_goals == pytest.approx(
        source.native_home_goals, abs=result.goal_moment_error_bound
    )
    assert result.away_physical_goals == pytest.approx(
        source.native_away_goals, abs=result.goal_moment_error_bound
    )
    expected = skellam.pmf(
        result.difference_states, source.native_home_goals, source.native_away_goals
    )
    np.testing.assert_allclose(
        result.difference_probabilities, expected, atol=result.mass_error_bound, rtol=0
    )
    for row, original in zip(result.player_survival, source.players, strict=True):
        opposing = source.native_away_goals if row.club_code == 1 else source.native_home_goals
        for index in range(1, 7):
            expected_cs = math.exp(
                -opposing
                * (original.physical_off[index] - original.physical_on[index])
                / source.forecast_duration
            )
            assert row.survival[index] == pytest.approx(expected_cs, abs=result.mass_error_bound)
        assert row.survival[0] == 0
    assert math.fsum(result.difference_probabilities) + result.overflow_mass == pytest.approx(
        1, abs=2e-15
    )
    assert result.input_sha256 == score_input_digest(source)


def test_four_bin_native_source_uses_supplied_shape(learned: ScoreStateModel) -> None:
    result = learned.predict(fixture(target=True, four=True), zero_coefficients=True)
    assert all(len(row.survival) == 4 for row in result.player_survival)


def test_learned_effect_is_invented_and_differs_from_zero_process(learned: ScoreStateModel) -> None:
    assert learned.metadata.coefficients[0] > 0
    assert learned.metadata.coefficients[1] < 0
    result = learned.predict(fixture(target=True))
    zero = learned.predict(fixture(target=True), zero_coefficients=True)
    assert abs(result.home_physical_goals - zero.home_physical_goals) > 0.1
    assert result.model_sha256 == zero.model_sha256
    assert result.zero_coefficients is False and zero.zero_coefficients is True


def dense_oracle(
    source: ScoreFixture, coefficients: np.ndarray, radius: int
) -> tuple[np.ndarray, float, float]:
    states = np.arange(-radius, radius + 1)
    count = len(states)
    values = np.zeros(count + 2)
    values[radius] = 1
    for phase in range(3):
        matrix = np.zeros((count + 2, count + 2))
        for column, difference in enumerate(states):
            h_factor = (
                1 if difference == 0 else math.exp(coefficients[2 * phase + (difference < 0)])
            )
            a_factor = (
                1 if difference == 0 else math.exp(coefficients[2 * phase + (difference > 0)])
            )
            home = source.native_home_goals / source.forecast_duration * h_factor
            away = source.native_away_goals / source.forecast_duration * a_factor
            matrix[column, column] = -(home + away)
            if column < count - 1:
                matrix[column + 1, column] = home
            if column > 0:
                matrix[column - 1, column] = away
            matrix[count, column] = home
            matrix[count + 1, column] = away
        values = expm(matrix * source.forecast_duration / 3) @ values
    return values[:count], values[count], values[count + 1]


def test_sparse_full_difference_process_matches_independent_dense_matrix() -> None:
    source = fixture(target=True, home=0.7, away=0.4)
    coefficients = np.asarray([0.6, -0.4, 0.1, 0.3, -0.2, 0.5])
    process = _Process(source, coefficients, 1e-11, 256)
    home, away = process.goals()
    probabilities, expected_home, expected_away = dense_oracle(source, coefficients, process.radius)
    np.testing.assert_allclose(process.entry(96), probabilities, atol=process.mass_bound, rtol=0)
    assert home == pytest.approx(expected_home, abs=process.moment_bound)
    assert away == pytest.approx(expected_away, abs=process.moment_bound)


def test_home_away_reversal_reverses_full_difference_distribution(learned: ScoreStateModel) -> None:
    source = fixture(target=True)
    reversed_fixture = replace(
        source,
        home_club_code=2,
        away_club_code=1,
        native_home_goals=source.native_away_goals,
        native_away_goals=source.native_home_goals,
    )
    original = learned.predict(source)
    reverse = learned.predict(reversed_fixture)
    assert original.home_physical_goals == pytest.approx(reverse.away_physical_goals, abs=1e-11)
    assert original.away_physical_goals == pytest.approx(reverse.home_physical_goals, abs=1e-11)
    np.testing.assert_allclose(
        original.difference_probabilities,
        reverse.difference_probabilities[::-1],
        atol=1e-11,
        rtol=0,
    )
    for first, second in zip(original.player_survival, reverse.player_survival, strict=True):
        np.testing.assert_allclose(first.survival, second.survival, atol=1e-11, rtol=0)


def test_stoppage_interval_is_physical_and_cannot_be_credited_minute_shortcut(
    learned: ScoreStateModel,
) -> None:
    source = fixture(target=True)
    changed = replace(source.players[0], physical_off=(0, 16, 92, 96, 96, 96, 96))
    result = learned.predict(
        replace(source, players=(changed, *source.players[1:])), zero_coefficients=True
    )
    survival = result.player_survival[0].survival[2]
    assert survival == pytest.approx(math.exp(-0.9 * 92 / 96), abs=1e-11)
    assert abs(survival - math.exp(-0.9 * 75 / 90)) > 0.01


def test_goals_after_normal_exit_do_not_break_clean_sheet() -> None:
    source = fixture(target=True)
    process = _Process(source, np.asarray([0.3, -0.3, 0.6, -0.2, 0.8, -0.6]), 1e-11, 256)
    process.goals()
    early = process.survival(1, 0, 64)
    full = process.survival(1, 0, 96)
    assert early > full + 0.05


def test_interval_survival_keeps_score_history_before_cameo() -> None:
    source = fixture(target=True)
    coefficients = np.asarray([1.0, -0.7] * 3)
    process = _Process(source, coefficients, 1e-11, 256)
    process.goals()
    actual = process.survival(1, 60, 96)
    fresh = _Process(replace(source, forecast_duration=36), coefficients, 1e-11, 256)
    fresh.goals()
    wrong = fresh.survival(1, 0, 36)
    count = 2 * process.radius + 1
    full = np.zeros((count, count))
    killed = np.zeros((count, count))
    initial = np.zeros(count)
    initial[process.radius] = 1
    for column, difference in enumerate(range(-process.radius, process.radius + 1)):
        home = (
            source.native_home_goals
            / 96
            * (1 if difference == 0 else math.exp(1 if difference > 0 else -0.7))
        )
        away = (
            source.native_away_goals
            / 96
            * (1 if difference == 0 else math.exp(1 if difference < 0 else -0.7))
        )
        full[column, column] = killed[column, column] = -(home + away)
        if column < count - 1:
            full[column + 1, column] = killed[column + 1, column] = home
        if column > 0:
            full[column - 1, column] = away
    independent = float((expm(killed * 36) @ expm(full * 60) @ initial).sum())
    assert actual == pytest.approx(independent, abs=process.mass_bound)
    assert abs(actual - wrong) > 0.1
    assert abs(actual - math.exp(-source.native_away_goals * 36 / 96)) > 0.001


def test_interval_cache_is_shared_by_players(learned: ScoreStateModel) -> None:
    source = fixture(target=True)
    source = replace(
        source,
        players=tuple(
            replace(source.players[index % 4], player_code=index + 1) for index in range(66)
        ),
    )
    result = learned.predict(source)
    assert len(result.player_survival) == 66
    assert result.unique_intervals == 12
    assert result.matrix_exponentials < 50


def test_structural_zero_goal_intensity_is_never_created(learned: ScoreStateModel) -> None:
    source = fixture(target=True, home=0, away=1.2)
    result = learned.predict(source)
    assert result.home_physical_goals == 0
    assert all(
        row.survival[3] == pytest.approx(1, abs=result.mass_error_bound)
        for row in result.player_survival
        if row.club_code == 2
    )


def test_both_zero_goal_endpoints_are_exact(learned: ScoreStateModel) -> None:
    result = learned.predict(fixture(target=True, home=0, away=0))
    assert result.home_physical_goals == result.away_physical_goals == 0
    assert result.overflow_mass == 0
    assert result.difference_probabilities == (0, 1, 0)
    assert all(row.survival[3] == 1 for row in result.player_survival)


def test_tail_bound_dominates_true_poisson_mass_and_moment() -> None:
    for mean in (0.1, 2.0, 10.0):
        radius, mass, moment = module._radius(mean, 1e-11, 256)
        assert poisson.sf(radius, mean) <= mass
        assert mean * poisson.sf(radius - 1, mean) <= moment
        assert mass <= 1e-11 and moment <= 1e-11


def test_tail_is_never_silently_normalized() -> None:
    source = fixture(target=True, home=2.5, away=1.7)
    process = _Process(source, np.zeros(6), 1e-6, 256)
    process.goals()
    retained = float(process.entry(96).sum())
    assert retained < 1
    assert 0 <= 1 - retained <= process.mass_bound


def test_insufficient_grid_refuses_even_with_valid_inputs() -> None:
    with pytest.raises(ValueError, match=r"grid.*tail"):
        _Process(fixture(target=True, home=10, away=10), np.zeros(6), 1e-11, 2)


def test_global_causal_headers_precede_any_label_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = replace(observation(1), input=replace(fixture(1), season="2025-26"))

    def labels(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("labels must remain unread")

    monkeypatch.setattr(module, "validate_training_score_fixture", labels)
    with pytest.raises(ValueError, match="causal"):
        fit((observation(), forbidden))


@pytest.mark.parametrize(
    "season,gw", [("2026-27", 6), ("2026-27", 8), ("2027-28", 1), ("2025-26", 1)]
)
def test_target_future_and_protected_headers_refuse_before_goals(season: str, gw: int) -> None:
    row = replace(observation(), input=replace(fixture(), season=season, gameweek=gw), goals=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="causal"):
        fit((row,))


def test_historical_gameweek_requires_one_original_decision_clock() -> None:
    first = observation()
    second = replace(observation(1), input=replace(fixture(1), gameweek=1))
    with pytest.raises(ValueError, match="one original decision"):
        fit((first, second))


def test_equivalent_aware_original_clocks_are_accepted() -> None:
    first = observation()
    source = replace(first.input, fixture_id=999, decision_at="2024-08-31T13:00:00+01:00")
    second = replace(first, input=source, outcome_sha256="c" * 64)
    result = fit((first, second))
    assert result.metadata.cutoff == CUTOFF


def test_historical_native_zero_goal_support_refuses() -> None:
    row = observation()
    row = replace(row, input=replace(row.input, native_home_goals=0))
    with pytest.raises(ValueError, match="no native intensity"):
        fit((row,))


def test_failed_refit_leaves_original_model_and_receipts_atomic(learned: ScoreStateModel) -> None:
    before = learned.metadata_json
    prediction = learned.predict(fixture(target=True))
    with pytest.raises(ValueError):
        learned.fit(
            (observation(),),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweeks=(6,),
            allowed_seasons=("2024-25",),
            max_iterations=1,
        )
    assert learned.metadata_json == before
    assert learned.predict(fixture(target=True)) == prediction


def test_optimizer_failure_does_not_publish_partial_fit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "minimize",
        lambda *args, **kwargs: type("Failed", (), {"success": False, "x": np.zeros(6)})(),
    )
    model = ScoreStateModel()
    with pytest.raises(ValueError, match="optimizer"):
        model.fit(
            (observation(),),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweeks=(6,),
            allowed_seasons=("2024-25",),
        )
    with pytest.raises(ValueError, match="not been fitted"):
        _ = model.metadata


def test_fitted_parameters_and_metadata_are_immutable(learned: ScoreStateModel) -> None:
    fitted = learned._fitted
    assert fitted is not None
    with pytest.raises(ValueError):
        fitted.coefficients.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        learned.metadata.cutoff = "wrong"  # type: ignore[misc]
    encoded = learned.metadata_json
    assert hashlib.sha256(encoded.encode()).hexdigest() == learned.model_sha256
    assert json.loads(encoded)["feature_names"] == list(FEATURE_NAMES)
    assert learned.metadata.model_version == MODEL_VERSION


def test_training_receipt_binds_full_typed_outcome_and_projection() -> None:
    row = observation()
    model = fit((row,))
    receipt = model.metadata.training_receipts[0]
    from dataclasses import asdict

    record = json.dumps(asdict(row), sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert receipt == (
        score_input_digest(row.input),
        row.outcome_sha256,
        row.settled_at,
        hashlib.sha256(record.encode()).hexdigest(),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("cutoff", "2026-10-08T00:00:00Z"),
        ("target_gameweeks", (8,)),
        ("numerical_tolerance", 1e-6),
        ("model_version", "wrong"),
        ("coefficients", (0.0,) * 6),
    ],
)
def test_internal_metadata_replacement_refuses(field: str, value: Any) -> None:
    model = fit((observation(),))
    fitted = model._fitted
    assert fitted is not None
    model._fitted = replace(fitted, metadata=replace(fitted.metadata, **{field: value}))
    with pytest.raises(ValueError, match="receipt mismatch"):
        model.predict(fixture(target=True))


def test_internal_coefficient_replacement_refuses() -> None:
    model = fit((observation(),))
    assert model._fitted is not None
    model._fitted = replace(model._fitted, coefficients=np.zeros(6))
    with pytest.raises(ValueError, match="receipt mismatch"):
        model.predict(fixture(target=True), zero_coefficients=True)


@pytest.mark.parametrize("gameweeks", [(), (0,), (39,), (True,), (7, 6), (6, 6)])
def test_bad_target_inventory_refuses(gameweeks: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="target gameweeks"):
        ScoreStateModel().fit(
            (observation(),),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweeks=gameweeks,
            allowed_seasons=("2024-25",),
        )


@pytest.mark.parametrize(
    "options",
    [
        {"l2": True},
        {"l2": -1},
        {"l2": float("nan")},
        {"max_iterations": True},
        {"max_iterations": 0},
        {"max_iterations": 1001},
    ],
)
def test_bad_optimizer_configuration_refuses(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        fit((observation(),), **options)


@pytest.mark.parametrize(
    "options",
    [
        {"numerical_tolerance": True},
        {"numerical_tolerance": 0},
        {"numerical_tolerance": float("nan")},
        {"max_difference": True},
        {"max_difference": 0},
        {"max_difference": 513},
    ],
)
def test_bad_numeric_configuration_refuses(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        ScoreStateModel(**options)


def test_prediction_before_fit_target_or_clock_refuses(learned: ScoreStateModel) -> None:
    with pytest.raises(ValueError, match="not been fitted"):
        ScoreStateModel().predict(fixture(target=True))
    with pytest.raises(ValueError, match="target"):
        learned.predict(replace(fixture(target=True), gameweek=5))
    source = fixture(target=True)
    source = replace(
        source, decision_at="2026-10-08T00:00:00Z", native_basis_fit_cutoff="2026-10-07T00:00:00Z"
    )
    with pytest.raises(ValueError, match="decision"):
        learned.predict(source)
