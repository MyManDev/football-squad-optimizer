"""The general design generators and the one objective shape they feed."""

import pytest

from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    enumerate_candidates,
)
from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.experiments.design import (
    DesignKind,
    ExperimentDesign,
    StrategyObjective,
)


def _factors() -> tuple[BayesianFactor, ...]:
    return (
        BayesianFactor(name="overlap_floor", lower_bound=5, upper_bound=11, step=2, kind="integer"),
        BayesianFactor(name="hit_cap", lower_bound=0, upper_bound=2, step=1, kind="integer"),
        BayesianFactor(name="discount", lower_bound=0.8, upper_bound=1.0, step=0.1),
    )


def _two_level_factors(count: int) -> tuple[BayesianFactor, ...]:
    return tuple(
        BayesianFactor(name=f"factor_{index}", lower_bound=0, upper_bound=1, step=1, kind="integer")
        for index in range(count)
    )


# --- designs -----------------------------------------------------------------------


def test_full_factorial_matches_the_optimizer_enumeration() -> None:
    """One grid, one enumeration: the design and the search agree on the space."""

    factors = _factors()
    design = ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=factors)
    config = BayesianOptimizationConfig(factors=factors, initial_design_size=2, evaluation_budget=4)
    assert [c.candidate_id for c in design.candidates()] == [
        c.candidate_id for c in enumerate_candidates(config)
    ]
    assert len(design.candidates()) == 4 * 3 * 3


def test_fractional_factorial_halves_the_grid_and_keeps_balance() -> None:
    factors = _two_level_factors(4)
    design = ExperimentDesign(
        kind=DesignKind.FRACTIONAL_FACTORIAL,
        factors=factors,
        fraction_generators=(("factor_3", ("factor_0", "factor_1", "factor_2")),),
    )
    candidates = design.candidates()
    assert len(candidates) == 8  # 2^(4-1)
    for factor in factors:
        highs = sum(1 for c in candidates if c.values[factor.name] == 1)
        assert highs == 4  # every column balanced
    # The generated column is the declared product, run for run.
    for candidate in candidates:
        signs = [2 * int(str(candidate.values[f"factor_{i}"])) - 1 for i in range(4)]
        assert signs[3] == signs[0] * signs[1] * signs[2]


def test_fractional_generators_are_validated() -> None:
    factors = _two_level_factors(3)
    with pytest.raises(ExperimentConfigurationError, match="fraction_generators"):
        ExperimentDesign(kind=DesignKind.FRACTIONAL_FACTORIAL, factors=factors).candidates()
    with pytest.raises(ExperimentConfigurationError, match="unknown factor"):
        ExperimentDesign(
            kind=DesignKind.FRACTIONAL_FACTORIAL,
            factors=factors,
            fraction_generators=(("missing", ("factor_0",)),),
        ).candidates()


def test_plackett_burman_is_orthogonal_and_sized_by_the_factor_count() -> None:
    factors = _two_level_factors(7)
    design = ExperimentDesign(kind=DesignKind.PLACKETT_BURMAN, factors=factors)
    candidates = design.candidates()
    assert len(candidates) == 8  # seven factors fit the eight-run construction
    columns = [[2 * int(str(c.values[factor.name])) - 1 for c in candidates] for factor in factors]
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            dot = sum(a * b for a, b in zip(columns[i], columns[j], strict=True))
            assert dot == 0  # any two columns orthogonal


def test_plackett_burman_beyond_its_table_is_refused() -> None:
    with pytest.raises(ExperimentConfigurationError, match="at most"):
        ExperimentDesign(
            kind=DesignKind.PLACKETT_BURMAN, factors=_two_level_factors(20)
        ).candidates()


def test_sampling_designs_are_seeded_on_grid_and_deduplicated() -> None:
    factors = _factors()
    for kind in (DesignKind.LATIN_HYPERCUBE, DesignKind.SOBOL):
        first = ExperimentDesign(kind=kind, factors=factors, size=16, seed=7)
        second = ExperimentDesign(kind=kind, factors=factors, size=16, seed=7)
        third = ExperimentDesign(kind=kind, factors=factors, size=16, seed=8)
        ids = [c.candidate_id for c in first.candidates()]
        assert ids == [c.candidate_id for c in second.candidates()]  # seed reproduces
        assert ids != [c.candidate_id for c in third.candidates()]  # seed matters
        assert len(set(ids)) == len(ids)  # unique cells only
        grid = {factor.name: set(factor.levels) for factor in factors}
        for candidate in first.candidates():
            for name, value in candidate.values.items():
                assert value in grid[name]  # snapped onto the declared grid, exactly


def test_sampling_designs_need_a_size() -> None:
    with pytest.raises(ExperimentConfigurationError, match="size"):
        ExperimentDesign(kind=DesignKind.LATIN_HYPERCUBE, factors=_factors())


def test_design_fingerprint_is_stable_and_sensitive() -> None:
    factors = _factors()
    baseline = ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=factors)
    assert (
        baseline.design_fingerprint
        == ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=factors).design_fingerprint
    )
    assert (
        baseline.design_fingerprint
        != ExperimentDesign(
            kind=DesignKind.LATIN_HYPERCUBE, factors=factors, size=4
        ).design_fingerprint
    )


# --- the objective shape ------------------------------------------------------------


def test_the_objective_is_the_fold_mean_and_keeps_the_folds() -> None:
    factors = _factors()
    calls: list[str] = []

    def evaluate(candidate: BayesianCandidate) -> tuple[float, ...]:
        calls.append(candidate.candidate_id)
        return (10.0, 20.0, 30.0)

    objective = StrategyObjective(
        strategy_slug="ortak-koru",
        factors=factors,
        population_id="dev-2021-2024-h1",
        evaluate_folds=evaluate,
    )
    candidate = ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=factors).candidates()[0]
    assert objective.fold_values(candidate) == (10.0, 20.0, 30.0)
    assert objective(candidate) == 20.0
    assert calls  # the evaluator, not a cache, produced the numbers


def test_the_searched_space_must_be_the_declared_space() -> None:
    objective = StrategyObjective(
        strategy_slug="ortak-koru",
        factors=_factors(),
        population_id="dev",
        evaluate_folds=lambda candidate: (1.0,),
    )
    stray = BayesianCandidate({"overlap_floor": 5, "hit_cap": 0, "surprise": 1})
    with pytest.raises(ExperimentExecutionError, match="declared space"):
        objective(stray)


def test_an_empty_or_non_finite_fold_vector_is_refused() -> None:
    factors = _factors()
    candidate = ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=factors).candidates()[0]
    empty = StrategyObjective(
        strategy_slug="s", factors=factors, population_id="p", evaluate_folds=lambda c: ()
    )
    with pytest.raises(ExperimentExecutionError, match="no folds"):
        empty(candidate)
    bad = StrategyObjective(
        strategy_slug="s",
        factors=factors,
        population_id="p",
        evaluate_folds=lambda c: (1.0, float("nan")),
    )
    with pytest.raises(ExperimentExecutionError, match="non-finite"):
        bad(candidate)


def test_the_objective_fingerprint_exists_before_any_evaluation() -> None:
    factors = _factors()
    objective = StrategyObjective(
        strategy_slug="fark-yarat",
        factors=factors,
        population_id="dev-h3",
        evaluate_folds=lambda c: (0.0,),
    )
    again = StrategyObjective(
        strategy_slug="fark-yarat",
        factors=factors,
        population_id="dev-h3",
        evaluate_folds=lambda c: (99.0,),  # a different evaluator, same declaration
    )
    assert objective.objective_fingerprint == again.objective_fingerprint
    other = StrategyObjective(
        strategy_slug="fark-yarat",
        factors=factors,
        population_id="dev-h1",
        evaluate_folds=lambda c: (0.0,),
    )
    assert objective.objective_fingerprint != other.objective_fingerprint
