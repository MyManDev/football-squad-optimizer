"""Shared pytest fixtures."""

import pandas as pd
import pytest

from squadopt import OptimizationConfig, OptimizationResult, optimize_squad
from tests.fixtures.synthetic_players import (
    make_baseline_players,
    make_known_optimum_players,
    make_tied_players,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/integration as ``integration``.

    ``slow`` is applied by hand to the solver-heavy tests; the fast suite is
    ``pytest -m "not slow"``, the full suite is plain ``pytest``.
    """

    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def baseline_players() -> pd.DataFrame:
    return make_baseline_players()


@pytest.fixture(scope="session")
def baseline_result() -> OptimizationResult:
    return optimize_squad(make_baseline_players(), OptimizationConfig())


@pytest.fixture
def small_config() -> OptimizationConfig:
    return OptimizationConfig(
        budget_tenths=200,
        squad_size=4,
        squad_position_limits={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
        starting_size=3,
        starting_position_min={"GK": 1, "DEF": 0, "MID": 0, "FWD": 1},
        starting_position_max={"GK": 1, "DEF": 1, "MID": 1, "FWD": 1},
        max_players_per_team=4,
    )


@pytest.fixture
def known_optimum_players() -> pd.DataFrame:
    return make_known_optimum_players()


@pytest.fixture
def tied_players() -> pd.DataFrame:
    return make_tied_players()
