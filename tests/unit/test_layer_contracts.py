"""Compatibility and deterministic evidence across the shared-layer extraction."""

from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

import squadopt
from squadopt import OptimizationConfig
from squadopt.backtest.production_benchmark import ProductionBenchmarkConfig
from squadopt.contracts import POSITIONS, REQUIRED_COLUMNS, Position, sort_players_by_id
from squadopt.data import schema
from squadopt.evaluation import promotion, statistics
from squadopt.experiments import (
    ExperimentConfigurationError,
    ExperimentError,
    PromotionPolicy,
    ScreeningExperimentConfig,
)
from squadopt.experiments import config as experiment_config
from squadopt.experiments import statistics as experiment_statistics
from squadopt.optimization import config as optimizer_config
from squadopt.optimization import validation
from squadopt.optimization.coefficients import objective_coefficient_fingerprint
from squadopt.optimization.coefficients import sort_players_by_id as legacy_sort


def test_legacy_imports_reexport_the_shared_objects() -> None:
    assert optimizer_config.Position is schema.Position is Position
    assert optimizer_config.POSITIONS is schema.POSITIONS is POSITIONS
    assert validation.REQUIRED_COLUMNS is schema.PROJECTION_REQUIRED_COLUMNS is REQUIRED_COLUMNS
    assert legacy_sort is sort_players_by_id
    assert experiment_config.PromotionPolicy is PromotionPolicy is promotion.PromotionPolicy
    assert ExperimentError is promotion.ExperimentError
    assert ExperimentConfigurationError is promotion.ExperimentConfigurationError
    assert experiment_statistics._percentile is statistics._percentile
    assert experiment_statistics._bootstrap_seed is statistics._bootstrap_seed
    assert (
        experiment_statistics.season_aware_moving_block_indices
        is statistics.season_aware_moving_block_indices
    )
    assert (
        experiment_statistics.season_aware_moving_block_interval
        is statistics.season_aware_moving_block_interval
    )


@pytest.mark.parametrize(
    ("ids", "ordered"),
    [([10, 2, 1], [1, 2, 10]), (["10", "2", "1"], ["1", "10", "2"]), ([], [])],
)
def test_canonical_order_preserves_identifier_semantics_and_independent_copy(
    ids: list[int] | list[str], ordered: list[int] | list[str]
) -> None:
    players = pd.DataFrame({"player_id": ids, "name": ["a", "b", "c"][: len(ids)]})
    original = players.copy(deep=True)

    result = sort_players_by_id(players)

    assert result.player_id.tolist() == ordered
    assert result.index.tolist() == list(range(len(ids)))
    assert_frame_equal(players, original)
    if ids:
        result.loc[0, "name"] = "changed"
        assert_frame_equal(players, original)


def test_seeded_bootstrap_preserves_pre_extraction_sequence_and_interval() -> None:
    policy = PromotionPolicy(bootstrap_resamples=8, moving_block_length=2, deterministic_seed=11)
    differences = [("s2", 10.0), ("s1", 1.0), ("s2", 30.0), ("s1", 3.0), ("s1", 5.0)]

    indices = list(
        statistics.season_aware_moving_block_indices(
            [season for season, _ in differences], policy=policy, candidate_id="compat-\u03b1"
        )
    )

    assert indices == [
        (1, 3, 3, 0, 2),
        (1, 3, 1, 0, 2),
        (3, 4, 1, 0, 2),
        (3, 4, 3, 0, 2),
        (1, 3, 3, 0, 2),
        (1, 3, 3, 0, 2),
        (1, 3, 3, 0, 2),
        (1, 3, 1, 0, 2),
    ]
    assert statistics.season_aware_moving_block_interval(
        differences, policy=policy, candidate_id="compat-\u03b1"
    ) == (9.0, 10.059999999999999)


def test_shared_policy_errors_remain_catchable_by_legacy_hierarchy() -> None:
    with pytest.raises(ExperimentError) as caught:
        promotion.PromotionPolicy(moving_block_length=0)

    assert type(caught.value) is ExperimentConfigurationError
    assert str(caught.value) == "moving_block_length must be at least 1."
    assert issubclass(experiment_config.ExperimentExecutionError, ExperimentError)
    assert issubclass(experiment_config.FrozenCandidateError, ExperimentError)


def test_projection_and_policy_fingerprints_preserve_pre_extraction_values() -> None:
    players = pd.DataFrame(
        {
            "player_id": [10, 2, 1],
            "team_id": [2, 1, 3],
            "position": ["FWD", "GK", "MID"],
            "price_tenths": [75, 45, 82],
            "expected_points": [1.2345, 0.5, 6.7777],
        }
    )

    assert objective_coefficient_fingerprint(players, OptimizationConfig()) == (
        "5c6cd6a2eca6097d037a6f078ddac72ade879fd1c9a11db5a8bd972ebd5b4df8"
    )
    assert ScreeningExperimentConfig().configuration_fingerprint == (
        "1072c1829995473eb89a8a74c8cf61bb80151d410c0f3e5c8ebada2fa1c4e98d"
    )
    assert ProductionBenchmarkConfig().configuration_fingerprint == (
        "34a94f823b0fa2ef485199d7a9325a16aa607316fd57cc12904e882c4f420641"
    )


def test_the_data_layer_imports_no_network_or_vendor_sdk() -> None:
    """The rule `lint-imports` cannot see, because it does not look outside the package.

    `include_external_packages = false` in the import contract, so the three contracts check
    how `squadopt` modules import each other and say nothing about what any of them imports
    from outside. That leaves the architecture's own rule — vendor and cloud SDKs stay
    outside the research engine (`docs/architecture/backend.md`,
    `docs/architecture/platform_runtime.md`) — with no gate at all, which is how the model
    call came to sit in `squadopt.data`, the bottom layer, while the club-page reader beside
    it sat correctly in `squadopt.platform`.

    Read as source text rather than by importing: an adapter that defers its SDK import into
    a constructor — which this repository's does, so a missing optional install is a typed
    domain error rather than a crash at import time — is invisible to any check that only
    looks at module attributes.
    """

    network_libraries = ("anthropic", "httpx", "httpx2", "requests", "urllib.request", "aiohttp")
    data_root = Path(squadopt.__file__).resolve().parent / "data"
    offenders: list[str] = []

    for module in sorted(data_root.rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        for line in source.splitlines():
            statement = line.strip()
            if not statement.startswith(("import ", "from ")):
                continue
            for library in network_libraries:
                if statement.startswith(f"import {library}") or statement.startswith(
                    f"from {library}"
                ):
                    offenders.append(f"{module.name}: {statement}")

    assert offenders == [], (
        "The data layer is the bottom of the engine and is meant to be source-independent; "
        f"these lines reach a network library from inside it: {offenders}. An adapter that "
        "speaks to something outside this process belongs in squadopt.platform, beside "
        "club_news_fetch and club_news_model."
    )
