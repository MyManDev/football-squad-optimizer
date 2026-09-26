"""Compatibility and deterministic evidence across the shared-layer extraction."""

import ast
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

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
from squadopt.optimization import config as optimizer_config
from squadopt.optimization import validation
from squadopt.optimization.coefficients import objective_coefficient_fingerprint
from squadopt.optimization.coefficients import sort_players_by_id as legacy_sort


def test_legacy_imports_reexport_the_shared_objects() -> None:
    assert optimizer_config.Position is schema.Position is Position
    assert optimizer_config.POSITIONS is schema.POSITIONS is POSITIONS
    assert validation.REQUIRED_COLUMNS is schema.PROJECTION_REQUIRED_COLUMNS is REQUIRED_COLUMNS
    assert legacy_sort is sort_players_by_id
    assert PromotionPolicy is promotion.PromotionPolicy
    assert ExperimentError is promotion.ExperimentError
    assert ExperimentConfigurationError is promotion.ExperimentConfigurationError


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
    assert issubclass(promotion.ExperimentExecutionError, ExperimentError)
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


# The 2026-09-10 one-release re-exports, removed on 2026-09-26 once site releases had shipped
# (docs/architecture/dependency_rules.md, rule 2). Each old module maps to the names it no
# longer serves; the names live in `data`, `contracts`, `evaluation` and `application` now.
_REMOVED_RE_EXPORTS: dict[str, frozenset[str]] = {
    "squadopt.backtest.export_precision": frozenset(
        {"EXPORT_LINE_TERMINATOR", "write_export_table"}
    ),
    "squadopt.bayesopt.models": frozenset(
        {
            "BayesianFactor",
            "BayesianOptimizationConfigurationError",
            "BayesianOptimizationError",
            "FactorKind",
        }
    ),
    "squadopt.experiments.config": frozenset(
        {
            "ExperimentConfigurationError",
            "ExperimentError",
            "ExperimentExecutionError",
            "PromotionPolicy",
        }
    ),
    "squadopt.experiments.statistics": frozenset(
        {
            "_bootstrap_seed",
            "_percentile",
            "season_aware_moving_block_indices",
            "season_aware_moving_block_interval",
        }
    ),
    "squadopt.platform.capture_context": frozenset(
        {"CapturePicksProvider", "capture_element_codes"}
    ),
    "squadopt.preflight.validator": frozenset({"compute_table_sha256"}),
}
_REMOVED_MODULES = ("squadopt.platform._long_paths",)
_REPOSITORY = Path(__file__).resolve().parents[2]


def _module_file(module: str) -> Path:
    return _REPOSITORY / "src" / Path(*module.split(".")).with_suffix(".py")


def test_the_removed_re_exports_are_not_declared_again() -> None:
    for module in _REMOVED_MODULES:
        assert not _module_file(module).exists(), module
    for module, names in _REMOVED_RE_EXPORTS.items():
        source = _module_file(module).read_text(encoding="utf-8")
        assert "Compatibility re-export" not in source, module
        assert "for one release" not in source, module
        assert not names & _declared_exports(ast.parse(source)), module


def _declared_exports(tree: ast.Module) -> set[str]:
    """Names a module re-exports explicitly: `import x as x` aliases and `__all__` entries."""
    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            declared |= {alias.name for alias in node.names if alias.asname == alias.name}
        elif isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
                declared |= {
                    item.value
                    for item in ast.walk(node.value)
                    if isinstance(item, ast.Constant) and isinstance(item.value, str)
                }
    return declared


def test_nothing_imports_a_moved_name_from_its_old_module() -> None:
    old_paths = {*_REMOVED_RE_EXPORTS, *_REMOVED_MODULES}
    found: list[str] = []
    for root in ("src", "tests", "scripts"):
        for path in sorted((_REPOSITORY / root).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            if not any(module in source for module in old_paths):
                continue
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.ImportFrom) or node.module is None:
                    continue
                banned = _REMOVED_RE_EXPORTS.get(node.module, frozenset())
                names = {alias.name for alias in node.names}
                if node.module in _REMOVED_MODULES or names & banned:
                    found.append(f"{path.relative_to(_REPOSITORY)}:{node.lineno}")

    assert found == []
