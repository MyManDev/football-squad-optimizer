"""The tuned-knob gate: declared before the run, fold-paired, immovable after."""

import pytest

from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
    PromotionPolicy,
)
from squadopt.experiments.strategy_gate import (
    StrategyDeclaration,
    run_strategy_gate,
)


def _declaration(**overrides: object) -> StrategyDeclaration:
    fields: dict[str, object] = {
        "declaration_id": "chip-holding-2026-01",
        "strategy_slug": "cip-yerlesimi",
        "knob_values": {"wildcard_holding": 20.0},
        "baseline_knob_values": {"wildcard_holding": 15.0},
        "objective_fingerprint": "a" * 64,
        "design_fingerprint": "b" * 64,
        "population_id": "dev-2021-2024-h1",
        "change_summary": "BO's wildcard holding candidate against the shipped constant.",
    }
    fields.update(overrides)
    return StrategyDeclaration(**fields)  # type: ignore[arg-type]


def _folds(
    seasons: tuple[str, ...], per_season: int, base: float, lift: float
) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    tuned: list[tuple[str, float]] = []
    baseline: list[tuple[str, float]] = []
    for season_index, season in enumerate(seasons):
        for fold in range(per_season):
            value = base + season_index * 10.0 + fold * 0.25
            baseline.append((season, value))
            tuned.append((season, value + lift))
    return tuned, baseline


# --- the declaration ----------------------------------------------------------------


def test_the_declaration_validates_its_knobs() -> None:
    with pytest.raises(ExperimentConfigurationError, match="same knobs"):
        _declaration(baseline_knob_values={"another_knob": 1.0})
    with pytest.raises(ExperimentConfigurationError, match="nothing to gate"):
        _declaration(baseline_knob_values={"wildcard_holding": 20.0})
    with pytest.raises(ExperimentConfigurationError, match="finite"):
        _declaration(knob_values={"wildcard_holding": float("nan")})


def test_moving_a_threshold_is_visibly_a_new_declaration() -> None:
    """The fingerprint carries the gate: thresholds cannot drift silently."""

    original = _declaration()
    softened = _declaration(gate=PromotionPolicy(min_mean_improvement=0.1))
    assert original.declaration_fingerprint != softened.declaration_fingerprint
    assert original.declaration_fingerprint == _declaration().declaration_fingerprint


# --- the gate -----------------------------------------------------------------------


def test_a_real_lift_promotes_and_the_verdict_is_bound_to_the_declaration() -> None:
    declaration = _declaration()
    tuned, baseline = _folds(("2021-22", "2022-23"), per_season=12, base=50.0, lift=1.5)

    result = run_strategy_gate(declaration, tuned, baseline)

    assert result.promoted
    assert result.mean_improvement == pytest.approx(1.5)
    assert result.confidence_interval_lower > 0.0
    assert result.comparable_folds == 24
    assert result.declaration_fingerprint == declaration.declaration_fingerprint
    assert set(result.season_mean_improvements) == {"2021-22", "2022-23"}


def test_a_lift_below_the_declared_floor_fails_even_when_consistent() -> None:
    """0.2 points every fold: the interval excludes zero, the floor still refuses."""

    declaration = _declaration()  # floor is the default 0.5
    tuned, baseline = _folds(("2021-22",), per_season=20, base=50.0, lift=0.2)

    result = run_strategy_gate(declaration, tuned, baseline)

    assert result.passes_confidence_interval
    assert not result.passes_mean_improvement
    assert not result.promoted


def test_a_noisy_lift_fails_the_interval_even_when_the_mean_clears_the_floor() -> None:
    """Mean +0.5 made of swings the size of a season: the interval refuses it."""

    declaration = _declaration()
    swings = (21.0, 18.0, -19.0, -17.0, 16.0, 2.0, -14.0, -2.0, 1.0, -1.0)  # mean +0.5
    baseline = [("2021-22", 50.0 + index) for index in range(len(swings))]
    tuned = [
        (season, value + swing) for (season, value), swing in zip(baseline, swings, strict=True)
    ]

    result = run_strategy_gate(declaration, tuned, baseline)

    assert result.mean_improvement == pytest.approx(0.5)
    assert result.passes_mean_improvement
    assert not result.passes_confidence_interval
    assert not result.promoted


def test_broken_pairing_is_refused() -> None:
    declaration = _declaration()
    tuned, baseline = _folds(("2021-22", "2022-23"), per_season=3, base=50.0, lift=1.0)
    shuffled = list(reversed(baseline))
    with pytest.raises(ExperimentExecutionError, match="pairing broken"):
        run_strategy_gate(declaration, tuned, shuffled)
    with pytest.raises(ExperimentExecutionError, match="fold-paired"):
        run_strategy_gate(declaration, tuned, baseline[:-1])
    with pytest.raises(ExperimentExecutionError, match="fold-paired"):
        run_strategy_gate(declaration, [], [])
