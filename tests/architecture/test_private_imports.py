"""A private name crosses a package boundary only where a shrinking allowlist says.

A single-underscore name is its module's own: a caller in another package that imports it
binds itself to a surface the owner never published, and a rename inside the owner breaks
that caller without any contract saying so. `planning` and both `scenarios` solvers did this
with the CP-SAT driver of `optimization.optimizer`, 19 names in three modules, until
ADR 0011 (decision 5) published the driver as `optimization.cpsat`. The 20 crossings that
remain are held here under the ratchet rule of ADR 0010 (Decision 4): `ALLOWLIST` holds
exactly today's crossings, each with its remedy, and may only shrink. The remedy is always the
same shape: the owning module publishes the name and keeps the private alias for one release
(dependency rule 2), and the caller imports the public one.

The scan reads every Python file under `src/squadopt`, imports inside functions included, and
reports each `from squadopt.<a>... import _name` whose importing module lives under a different
top-level package `squadopt.<b>`. A name is private when it starts with one underscore and not
two. A relative import is resolved against the importing module's package first. The scan sees
from-imports of names only: a private module name such as `squadopt.data._long_paths` is a
module, not a name, and `import squadopt.a` followed by an attribute access is not an import
statement.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE = "squadopt"

#: The remedy of an entry, as ARCHITECTURE.md's known violations write it.
EXPECTED_LINEUP = (
    "scenarios.expected_lineup publishes the inputs, the decision, prepare, score and the "
    "autosub multipliers, keeping the private aliases for one release; Phase 3, once the owner "
    "decides whether football_exact_lineup is product or laboratory"
)
FROZEN_DECISION = (
    "evaluation.scoring publishes validate_frozen_decision, keeping the private alias for one "
    "release; Phase 3"
)
CAPTURE_NAME = (
    "application.weekly_plan publishes require_capture_name, keeping the private alias for one "
    "release; Phase 3, in the lines of weekly_operations that pull request #969 leaves alone"
)
LABORATORY = (
    "Laboratory code reading a private surface of the product: it stays on the allowlist, and "
    "the entry leaves when the study retires or the owner publishes the name"
)

#: Every private name imported across a package boundary under `src/squadopt` on 2026-10-13,
#: as (importing module, imported module, name), with its remedy: 6 in the decision core, 1 in
#: `platform`, 13 in the laboratory. **It may only shrink.** If this test fails because a
#: crossing is new, publish the name in its owner; do not add it here.
ALLOWLIST: dict[tuple[str, str, str], str] = {
    ("squadopt.bayesopt.models", "squadopt.contracts.factors", "_integer"): LABORATORY,
    ("squadopt.experiments.football_components", "squadopt.prediction.football", "_fit"): (
        LABORATORY
    ),
    ("squadopt.experiments.football_components", "squadopt.prediction.football", "_matrix"): (
        LABORATORY
    ),
    ("squadopt.experiments.football_components", "squadopt.prediction.football", "_pipeline"): (
        LABORATORY
    ),
    (
        "squadopt.experiments.football_flag_experiment",
        "squadopt.live.minute_evidence",
        "_validate_components",
    ): LABORATORY,
    (
        "squadopt.experiments.football_load_experiment",
        "squadopt.live.minute_evidence",
        "_score_components",
    ): LABORATORY,
    (
        "squadopt.experiments.football_load_experiment",
        "squadopt.live.minute_evidence",
        "_validate_components",
    ): LABORATORY,
    ("squadopt.experiments.football_minutes", "squadopt.prediction.football", "_fit"): (LABORATORY),
    ("squadopt.experiments.football_minutes", "squadopt.prediction.football", "_matrix"): (
        LABORATORY
    ),
    ("squadopt.experiments.football_minutes", "squadopt.prediction.football", "_pipeline"): (
        LABORATORY
    ),
    (
        "squadopt.experiments.football_score_state_experiment",
        "squadopt.live.minute_evidence",
        "_validate_components",
    ): LABORATORY,
    (
        "squadopt.experiments.football_unit_experiment",
        "squadopt.live.minute_evidence",
        "_validate_components",
    ): LABORATORY,
    ("squadopt.experiments.phase_e_shadow", "squadopt.evaluation.statistics", "_percentile"): (
        LABORATORY
    ),
    (
        "squadopt.planning.football_exact_lineup",
        "squadopt.scenarios.expected_lineup",
        "_autosub_multipliers",
    ): EXPECTED_LINEUP,
    (
        "squadopt.planning.football_exact_lineup",
        "squadopt.scenarios.expected_lineup",
        "_Decision",
    ): (EXPECTED_LINEUP),
    ("squadopt.planning.football_exact_lineup", "squadopt.scenarios.expected_lineup", "_Inputs"): (
        EXPECTED_LINEUP
    ),
    ("squadopt.planning.football_exact_lineup", "squadopt.scenarios.expected_lineup", "_prepare"): (
        EXPECTED_LINEUP
    ),
    ("squadopt.planning.football_exact_lineup", "squadopt.scenarios.expected_lineup", "_score"): (
        EXPECTED_LINEUP
    ),
    (
        "squadopt.platform.weekly_operations",
        "squadopt.application.weekly_plan",
        "_require_capture_name",
    ): CAPTURE_NAME,
    (
        "squadopt.scenarios.expected_lineup",
        "squadopt.evaluation.scoring",
        "_validate_frozen_decision",
    ): FROZEN_DECISION,
}


def _is_private(name: str) -> bool:
    return name.startswith("_") and not name.startswith("__")


def _package_of(module: str) -> str:
    """The top-level package under `squadopt` of a dotted module name, or the root."""

    parts = module.split(".")
    return ".".join(parts[:2]) if len(parts) > 1 else parts[0]


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _absolute(module: str, node: ast.ImportFrom, *, is_package: bool) -> str:
    """The absolute dotted name an import-from statement in `module` names."""

    if node.level == 0:
        return node.module or ""
    base = module.split(".") if is_package else module.split(".")[:-1]
    base = base[: max(0, len(base) - (node.level - 1))]
    return ".".join([*base, node.module] if node.module else base)


def _private_crossings(
    module: str, text: str, *, is_package: bool = False
) -> list[tuple[str, str, int]]:
    """Each private name `module` imports from another package, with the line it is on."""

    package = _package_of(module)
    found: list[tuple[str, str, int]] = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom):
            continue
        imported = _absolute(module, node, is_package=is_package)
        if not imported.startswith(f"{PACKAGE}.") or _package_of(imported) == package:
            continue
        found.extend(
            (imported, alias.name, node.lineno) for alias in node.names if _is_private(alias.name)
        )
    return found


def _offending() -> dict[tuple[str, str, str], int]:
    offending: dict[tuple[str, str, str], int] = {}
    for path in sorted((SOURCE_ROOT / PACKAGE).rglob("*.py")):
        module = _module_name(path)
        crossings = _private_crossings(
            module, path.read_text(encoding="utf-8"), is_package=path.name == "__init__.py"
        )
        for imported, name, line in crossings:
            offending[(module, imported, name)] = line
    return offending


def test_private_names_cross_packages_exactly_where_the_allowlist_says() -> None:
    offending = _offending()

    assert {key: line for key, line in offending.items() if key not in ALLOWLIST} == {}, (
        "a private name is its module's own: publish it there and import the public name; "
        "the allowlist does not grow"
    )
    assert sorted(key for key in ALLOWLIST if key not in offending) == [], (
        "this private name is no longer imported across packages: delete its entry from ALLOWLIST"
    )


def test_no_private_name_of_the_optimization_package_crosses_a_boundary() -> None:
    assert [key for key in ALLOWLIST if _package_of(key[1]) == "squadopt.optimization"] == []


def test_every_entry_names_two_modules_under_src_and_a_known_remedy() -> None:
    for importer, imported, name in ALLOWLIST:
        assert _is_private(name), name
        assert _package_of(importer) != _package_of(imported), (importer, imported)
        for module in (importer, imported):
            location = SOURCE_ROOT / Path(*module.split("."))
            assert location.with_suffix(".py").is_file() or (location / "__init__.py").is_file(), (
                module
            )
    assert set(ALLOWLIST.values()) == {EXPECTED_LINEUP, FROZEN_DECISION, CAPTURE_NAME, LABORATORY}


def test_the_scan_reports_only_a_private_name_from_another_package() -> None:
    text = "\n".join(
        [
            "from squadopt.optimization.cpsat import solve as _solve",
            "from squadopt.optimization.optimizer import _solve, optimize_squad",
            "from squadopt.planning.models import _Hidden, __version__",
            "from squadopt.data._long_paths import addressable",
            "import squadopt.optimization.optimizer",
            "from .models import _OwnHidden",
            "from ..evaluation.scoring import _percentile",
            "def late():",
            "    from squadopt.evaluation.scoring import _validate_frozen_decision",
            "    return _validate_frozen_decision",
        ]
    )

    assert _private_crossings("squadopt.planning.optimizer", text) == [
        ("squadopt.optimization.optimizer", "_solve", 2),
        ("squadopt.evaluation.scoring", "_percentile", 7),
        ("squadopt.evaluation.scoring", "_validate_frozen_decision", 9),
    ]
    # A package file resolves `..` one level higher than a module of the same name would, so
    # the same text in `squadopt/planning/optimizer/__init__.py` names a sibling package.
    assert _private_crossings("squadopt.planning.optimizer", text, is_package=True) == [
        ("squadopt.optimization.optimizer", "_solve", 2),
        ("squadopt.evaluation.scoring", "_validate_frozen_decision", 9),
    ]
