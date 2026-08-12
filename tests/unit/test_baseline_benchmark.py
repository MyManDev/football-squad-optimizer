"""Tests for the frozen historical baseline benchmark contract."""

import pytest
from tests.fixtures.synthetic_gameweeks import GAMEWEEK_COUNT, SEASON, make_two_season_gameweeks

from squadopt.backtest import (
    BASELINE_BENCHMARK_CONTRACT_VERSION,
    BacktestConfigurationError,
    BaselineBenchmarkConfig,
    run_baseline_benchmark,
)
from squadopt.prediction import FEATURE_GENERATION_CONTRACT_VERSION


def test_the_benchmark_runs_the_requested_holdout_season() -> None:
    result = run_baseline_benchmark(
        make_two_season_gameweeks(),
        BaselineBenchmarkConfig(seasons=(SEASON,)),
    )

    assert result.summary.attempted_folds == GAMEWEEK_COUNT - 1
    assert result.summary.feasibility_rate == 1.0
    assert {fold.metadata["season"] for fold in result.folds} == {SEASON}


def test_opening_gameweeks_cannot_be_mixed_into_the_benchmark() -> None:
    with pytest.raises(BacktestConfigurationError, match="excludes opening gameweeks"):
        BaselineBenchmarkConfig(min_prior_gameweeks_in_season=0)


def test_the_run_records_factor_and_contract_provenance() -> None:
    result = run_baseline_benchmark(
        make_two_season_gameweeks(),
        BaselineBenchmarkConfig(
            seasons=(SEASON,),
            form_window=3,
            run_metadata={"dataset": "synthetic"},
        ),
    )
    metadata = result.config.run_metadata

    assert metadata["dataset"] == "synthetic"
    assert metadata["form_window"] == 3
    assert metadata["benchmark_contract_version"] == BASELINE_BENCHMARK_CONTRACT_VERSION
    assert metadata["feature_generation_contract_version"] == FEATURE_GENERATION_CONTRACT_VERSION


@pytest.mark.parametrize("seasons", [(), ("",), (SEASON, SEASON)])
def test_invalid_evaluation_seasons_are_rejected(seasons: tuple[str, ...]) -> None:
    with pytest.raises(BacktestConfigurationError, match="seasons"):
        BaselineBenchmarkConfig(seasons=seasons)


def test_non_text_evaluation_seasons_are_domain_errors() -> None:
    with pytest.raises(BacktestConfigurationError, match="entries must be strings"):
        BaselineBenchmarkConfig(seasons=(2025,))  # type: ignore[arg-type]


@pytest.mark.parametrize("window", [True, 0, 3.5, "5"])
def test_invalid_benchmark_form_windows_are_rejected_at_construction(window: object) -> None:
    with pytest.raises(BacktestConfigurationError, match="form_window"):
        BaselineBenchmarkConfig(form_window=window)  # type: ignore[arg-type]
