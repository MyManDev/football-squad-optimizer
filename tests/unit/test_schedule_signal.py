"""The schedule signal study: fitting, walking forward, and the gate that judges it.

Synthetic windows only — the archive is not available everywhere the tests run, and the
point of these tests is the machinery, not the football.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError
from squadopt.experiments.schedule_signal import (
    CALENDAR_RULE,
    DIFFICULTY_RULES,
    FLAT_RULE,
    RULES,
    Comparison,
    RuleResult,
    RuleSeasonResult,
    ScheduleSignalConfig,
    WindowDecision,
    _best_single_transfer,
    _normalized_ease,
    compare_rules,
    evaluate_rules,
    fit_rule,
    gate_verdict,
    predict_rule,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")


def _windows(
    season: str, *, difficulty_slope: float, count: int = 80, seed: int = 0
) -> pd.DataFrame:
    """A season whose realized points follow the calendar and, optionally, the difficulty."""

    generator = np.random.default_rng(seed)
    rate = np.linspace(0.5, 8.0, count)
    # Drawn rather than tiled: a fixture count that lined up with the position cycle would
    # be absorbed by the per-position fit, and every rule would look identical.
    fixture_count = generator.choice([4.0, 5.0, 5.0, 6.0], size=count)
    ease = generator.uniform(0.05, 0.95, size=count)
    ease_sum = ease * fixture_count
    realized = rate * fixture_count * (1.0 + difficulty_slope * (ease - 0.5))
    return pd.DataFrame(
        {
            "season": season,
            "origin_gameweek": [6 + 5 * (index % 3) for index in range(count)],
            "player_id": [index + 1 for index in range(count)],
            "name": [f"Player {index}" for index in range(count)],
            "team_id": [f"Club {index % 6}" for index in range(count)],
            "position": [POSITIONS[index % 4] for index in range(count)],
            "price_tenths": np.linspace(40, 130, count).astype(int),
            "prior_points": rate * 5.0,
            "prior_minutes": 450,
            "rate": rate,
            "fixture_count": fixture_count,
            "published_ease_sum": ease_sum,
            "carried_ease_sum": ease_sum,
            "realized_points": realized + generator.normal(0.0, 0.05, count),
            "window_length": 5.0,
        }
    )


def _population(difficulty_slope: float) -> pd.DataFrame:
    return pd.concat(
        [
            _windows(season, difficulty_slope=difficulty_slope, seed=index)
            for index, season in enumerate(("2020-21", "2021-22", "2022-23", "2023-24"))
        ],
        ignore_index=True,
    )


def _config(**overrides: object) -> ScheduleSignalConfig:
    settings = {
        "seasons": ("2020-21", "2021-22", "2022-23", "2023-24"),
        "evaluated_seasons": ("2022-23", "2023-24"),
        "origin_gameweeks": (6, 11, 16),
        "bootstrap_resamples": 200,
        "minimum_training_rows": 10,
    }
    settings.update(overrides)
    return ScheduleSignalConfig(**settings)  # type: ignore[arg-type]


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        ScheduleSignalConfig(seasons=("2024-25", "2025-26"), evaluated_seasons=("2024-25",))
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        ScheduleSignalConfig(evaluated_seasons=("2025-26",))


def test_an_origin_must_leave_a_full_form_window_behind_it() -> None:
    with pytest.raises(ExperimentConfigurationError, match="form window"):
        ScheduleSignalConfig(origin_gameweeks=(3, 11), form_window=5)


def test_normalized_ease_inverts_strength_and_stays_bounded() -> None:
    ease = _normalized_ease(pd.Series([10.0, 20.0, 30.0]))
    assert list(ease) == [1.0, 0.5, 0.0]
    flat = _normalized_ease(pd.Series([7.0, 7.0]))
    assert list(flat) == [0.5, 0.5]


def test_every_rule_is_fitted_including_the_ones_without_an_ease_column() -> None:
    rows = _population(difficulty_slope=0.0)
    for rule in RULES:
        coefficients = fit_rule(rows, rule)
        assert set(coefficients) == set(POSITIONS)
        expected = 1 if rule in (FLAT_RULE, CALENDAR_RULE) else 2
        for values in coefficients.values():
            assert len(values) == expected


def test_the_calendar_rule_recovers_the_generating_relationship() -> None:
    rows = _population(difficulty_slope=0.0)
    coefficients = fit_rule(rows, CALENDAR_RULE)
    for values in coefficients.values():
        assert values[0] == pytest.approx(1.0, abs=0.02)
    prediction = predict_rule(rows, CALENDAR_RULE, coefficients)
    assert np.abs(prediction - rows["realized_points"].to_numpy()).mean() < 0.1


def test_predictions_are_never_negative() -> None:
    rows = _population(difficulty_slope=0.0)
    coefficients = {position: (-5.0, -5.0) for position in POSITIONS}
    prediction = predict_rule(rows, "C_published_difficulty", coefficients)
    assert (prediction >= 0.0).all()


def test_the_difficulty_rule_wins_when_difficulty_drives_the_outcome() -> None:
    rows = _population(difficulty_slope=0.8)
    config = _config()
    results, errors = evaluate_rules(rows, config)
    comparison = compare_rules(
        results, errors, rule="C_published_difficulty", reference=CALENDAR_RULE, config=config
    )
    assert comparison.error_improvement > 0.0
    assert comparison.interval_excludes_zero
    assert comparison.sign_consistent


def test_the_difficulty_rule_does_not_win_when_difficulty_is_inert() -> None:
    rows = _population(difficulty_slope=0.0)
    config = _config()
    results, errors = evaluate_rules(rows, config)
    comparison = compare_rules(
        results, errors, rule="C_published_difficulty", reference=CALENDAR_RULE, config=config
    )
    assert abs(comparison.error_improvement) < 0.05
    assert not comparison.interval_excludes_zero


def test_the_calendar_beats_the_flat_rule_when_fixture_counts_vary() -> None:
    rows = _population(difficulty_slope=0.0)
    config = _config()
    results, errors = evaluate_rules(rows, config)
    comparison = compare_rules(
        results, errors, rule=CALENDAR_RULE, reference=FLAT_RULE, config=config
    )
    assert comparison.error_improvement > 0.0
    assert comparison.sign_consistent


def test_walking_forward_never_fits_on_the_judged_season() -> None:
    """A season poisoned only in its own rows cannot improve the fit that judges it."""

    rows = _population(difficulty_slope=0.5)
    poisoned = rows.copy()
    judged = poisoned["season"] == "2023-24"
    poisoned.loc[judged, "published_ease_sum"] = 0.0
    config = _config(evaluated_seasons=("2022-23",))
    clean_results, _ = evaluate_rules(rows, config)
    poisoned_results, _ = evaluate_rules(poisoned, config)
    clean = {result.rule: result.pooled_mean_absolute_error for result in clean_results}
    dirty = {result.rule: result.pooled_mean_absolute_error for result in poisoned_results}
    assert clean == dirty


def _comparison(**overrides: object) -> Comparison:
    settings: dict[str, object] = {
        "rule": "C_published_difficulty",
        "reference": CALENDAR_RULE,
        "rows": 100,
        "error_improvement": 0.2,
        "error_interval": (0.1, 0.3),
        "per_season_error_improvement": {"2022-23": 0.2, "2023-24": 0.2},
        "rank_improvement": 0.01,
        "per_season_rank_improvement": {"2022-23": 0.01, "2023-24": 0.01},
    }
    settings.update(overrides)
    return Comparison(**settings)  # type: ignore[arg-type]


def _decision(**overrides: object) -> WindowDecision:
    settings: dict[str, object] = {
        "season": "2022-23",
        "origin_gameweek": 6,
        "rule": "C_published_difficulty",
        "reference": CALENDAR_RULE,
        "rule_realized_points": 60.0,
        "reference_realized_points": 55.0,
        "changed_starters": 2,
        "transfer_realized_gain": 6.0,
        "transfer_net_gain": 2.0,
        "rule_proposes_transfer": True,
    }
    settings.update(overrides)
    return WindowDecision(**settings)  # type: ignore[arg-type]


def test_the_gate_passes_only_when_all_four_conditions_hold() -> None:
    verdict = gate_verdict(_comparison(), [_decision()])
    assert verdict["passes"] is True
    assert verdict["interval_excludes_zero"] is True
    assert verdict["decision_passes"] is True


def test_an_interval_touching_zero_fails_the_gate() -> None:
    verdict = gate_verdict(_comparison(error_interval=(-0.1, 0.3)), [_decision()])
    assert verdict["interval_excludes_zero"] is False
    assert verdict["passes"] is False


def test_one_season_of_the_wrong_sign_fails_the_gate() -> None:
    comparison = _comparison(
        per_season_error_improvement={"2022-23": -0.1, "2023-24": 0.5},
    )
    verdict = gate_verdict(comparison, [_decision()])
    assert verdict["sign_consistent"] is False
    assert verdict["passes"] is False


def test_a_transfer_that_does_not_repay_its_cost_fails_the_gate() -> None:
    losing = _decision(transfer_realized_gain=1.0, transfer_net_gain=-3.0)
    verdict = gate_verdict(_comparison(), [losing])
    assert verdict["decision_passes"] is False
    assert verdict["passes"] is False


def test_a_worse_ordering_in_both_seasons_fails_the_gate() -> None:
    comparison = _comparison(
        rank_improvement=-0.02,
        per_season_rank_improvement={"2022-23": -0.02, "2023-24": -0.02},
    )
    verdict = gate_verdict(comparison, [_decision()])
    assert verdict["ordering_not_worse"] is False
    assert verdict["passes"] is False


def test_the_gate_needs_at_least_one_decision() -> None:
    verdict = gate_verdict(_comparison(), [])
    assert verdict["decision_passes"] is False
    assert verdict["passes"] is False


def test_the_best_transfer_respects_price_and_club_limits() -> None:
    block = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5],
            "team_id": ["A", "A", "A", "B", "B"],
            "position": ["MID", "MID", "MID", "MID", "MID"],
            "price_tenths": [60, 60, 60, 200, 55],
        }
    )
    # Player 4 projects best but costs more than the outgoing player can fund; player 5 is
    # affordable and is the move the rule should propose.
    prediction = np.array([1.0, 1.0, 1.0, 99.0, 5.0])
    swap = _best_single_transfer(block, prediction, [1, 2, 3], club_limit=3)
    assert swap is not None
    assert swap[1] == 5


def test_a_full_club_blocks_a_swap_that_would_exceed_the_limit() -> None:
    block = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "team_id": ["A", "A", "A", "A"],
            "position": ["MID", "MID", "MID", "MID"],
            "price_tenths": [60, 60, 60, 50],
        }
    )
    prediction = np.array([1.0, 1.0, 1.0, 9.0])
    # Swapping into a fourth player from club A is legal only because one leaves it, so the
    # limit permits this move; raising the held count without a departure would not.
    swap = _best_single_transfer(block, prediction, [1, 2, 3], club_limit=3)
    assert swap is not None
    assert swap[1] == 4
    assert _best_single_transfer(block, prediction, [1, 2, 3], club_limit=2) is None


def test_no_transfer_is_proposed_when_nothing_projects_better() -> None:
    block = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "team_id": ["A", "A", "A", "B"],
            "position": ["MID", "MID", "MID", "MID"],
            "price_tenths": [60, 60, 60, 60],
        }
    )
    prediction = np.array([5.0, 5.0, 5.0, 1.0])
    assert _best_single_transfer(block, prediction, [1, 2, 3], club_limit=3) is None


def test_rule_results_carry_every_judged_season() -> None:
    rows = _population(difficulty_slope=0.4)
    config = _config()
    results, _ = evaluate_rules(rows, config)
    assert {result.rule for result in results} == set(RULES)
    for result in results:
        assert [season.season for season in result.seasons] == list(config.evaluated_seasons)
        assert isinstance(result.seasons[0], RuleSeasonResult)
        assert isinstance(result, RuleResult)


def test_every_difficulty_rule_is_compared_against_the_calendar() -> None:
    assert set(DIFFICULTY_RULES) <= set(RULES)
    assert FLAT_RULE in RULES and CALENDAR_RULE in RULES
    assert all(RULES[rule] is not None for rule in DIFFICULTY_RULES)
