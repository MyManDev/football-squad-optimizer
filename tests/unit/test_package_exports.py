"""The public root API remains available without eagerly loading its providers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def fresh_python(program: str) -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_root_import_and_discovery_do_not_load_export_providers() -> None:
    fresh_python("""
import sys
import squadopt
assert set(squadopt.__all__) <= set(dir(squadopt))
assert squadopt.__version__
assert squadopt.DISTRIBUTION_NAME == 'football-squad-optimizer'
assert {name for name in sys.modules if name.startswith('squadopt.')} == set()
assert not hasattr(squadopt, 'not_a_public_export')
try:
    squadopt.not_a_public_export
except AttributeError as error:
    assert 'not_a_public_export' in str(error)
else:
    raise AssertionError('Unknown names must raise AttributeError')
""")


def test_named_and_star_imports_preserve_all_public_objects() -> None:
    fresh_python("""
import importlib
import squadopt
from squadopt import OptimizationConfig, optimize_squad_from_csv
providers = {
    'squadopt.evaluation': (
        'EvaluationConfig', 'EvaluationError', 'EvaluationFold', 'EvaluationResult',
        'EvaluationSummary', 'EvaluationValidationError', 'FoldEvaluationResult',
        'FrozenSquadDecision', 'RealizedSquadScore', 'ScoringBasis', 'ScoringPolicy',
        'complete_optimization_decision', 'evaluate_prepared_folds',
        'score_frozen_squad_decision', 'score_realized_squad_points',
    ),
    'squadopt.integration': ('optimize_squad_from_csv',),
    'squadopt.optimization': (
        'InsufficientPlayerPoolError', 'InvalidConfigurationError', 'InvalidPlayerDataError',
        'OptimizationConfig', 'OptimizationResult', 'OptimizationValidationError',
        'SolverExecutionError', 'SolverStatus', 'SquadOptimizationError', 'optimize_squad',
    ),
}
namespace = {}
exec('from squadopt import *', namespace)
expected = {'DISTRIBUTION_NAME', '__version__'}
for module_name, names in providers.items():
    module = importlib.import_module(module_name)
    expected.update(names)
    for name in names:
        original = getattr(module, name)
        assert namespace[name] is original, name
        assert getattr(squadopt, name) is original, name
        assert squadopt.__dict__[name] is original, name
assert set(squadopt.__all__) == expected
assert set(namespace) - {'__builtins__'} == expected
assert OptimizationConfig is squadopt.OptimizationConfig
assert optimize_squad_from_csv is squadopt.optimize_squad_from_csv
""")


def test_submodule_import_does_not_eagerly_resolve_root_exports() -> None:
    fresh_python("""
import squadopt
import squadopt.platform.advice_worker
assert 'optimize_squad_from_csv' not in squadopt.__dict__
assert 'EvaluationConfig' not in squadopt.__dict__
""")
