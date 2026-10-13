"""A package guide places every module of its package in exactly one family, and no module twice.

Seven packages under `src/squadopt` have a guide, a `README.md` beside their modules:
`platform`, `application`, `experiments`, `live`, `data`, `prediction` and `features`. Each
guide sorts its package's modules into families, and the package map, `src/squadopt/README.md`,
says that the guides place every module. Nothing kept that true: the next module added to a
package would have had no row, and the next module removed would have kept one. This test holds
each guide to the Python files of its package.

A guide writes its families in one of two forms, and the test reads both:

- a family heading followed by a table whose header is `| Module | What it does |`, with one
  module per row, its path relative to the package in the first cell (`advice.py`,
  `strategies/catalog.py`, `sources/__init__.py`);
- one table whose header is `| Family | Modules |`, with a family per row and its modules in
  the second cell as backticked names without `.py` (the `experiments` guide).

A module is every `.py` file under the package, at any depth, apart from `__pycache__`, and
`__init__.py` counts: a package root that re-exports names is a module a reader looks for. A
package directly under `src/squadopt` that has a `README.md` is held by this test, so a guide
written for another package is held from the day it lands.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest
from tests.architecture.test_markdown_links import _lines_outside_fences

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY_ROOT / "src" / "squadopt"

#: The packages whose guides place every module. A guide may be added; none of these may go.
GUIDED = ("platform", "application", "experiments", "live", "data", "prediction", "features")

MODULE_TABLE = "| Module | What it does |"
FAMILY_TABLE = "| Family | Modules |"

#: A backticked name in a table cell.
NAME = re.compile(r"`([^`]+)`")


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _placements(text: str) -> list[tuple[str, str]]:
    """Every module a guide places, as its family and its path relative to the package.

    The path loses `.py`, so both forms name a module the same way. A row of a module table
    whose first cell is not one backticked name is returned with that cell, so it is reported
    as naming no module rather than skipped.
    """

    placements: list[tuple[str, str]] = []
    heading = ""
    table: str | None = None
    rows_follow = False
    for _, line in _lines_outside_fences(text):
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            table = None
            continue
        if not line.startswith("|"):
            table = None
            continue
        if table is None:
            table = line.strip() if line.strip() in (MODULE_TABLE, FAMILY_TABLE) else ""
            rows_follow = False
            continue
        if not rows_follow:
            rows_follow = True  # The delimiter row under the header.
            continue
        cells = _cells(line)
        if table == MODULE_TABLE:
            name = re.fullmatch(r"`([^`]+)`", cells[0])
            placements.append((heading, (name.group(1) if name else cells[0]).removesuffix(".py")))
        elif table == FAMILY_TABLE:
            placements.extend(
                (cells[0], name.removesuffix(".py")) for name in NAME.findall(cells[1])
            )
    return placements


def _modules(package: str) -> list[str]:
    """Every module of a package, as its path relative to the package without `.py`."""

    root = PACKAGE / package
    return sorted(
        path.relative_to(root).with_suffix("").as_posix()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _guided() -> set[str]:
    """The packages directly under `src/squadopt` that have a guide."""

    return {
        entry.name
        for entry in PACKAGE.iterdir()
        if (entry / "__init__.py").is_file() and (entry / "README.md").is_file()
    }


def test_every_package_named_here_keeps_its_guide() -> None:
    assert set(GUIDED) <= _guided(), f"a package lost its guide: {sorted(set(GUIDED) - _guided())}"


@pytest.mark.parametrize("package", sorted(_guided() | set(GUIDED)))
def test_the_guide_places_every_module_of_its_package_once(package: str) -> None:
    guide = PACKAGE / package / "README.md"
    placements = _placements(guide.read_text(encoding="utf-8"))
    modules = _modules(package)
    placed = Counter(module for _, module in placements)

    # A guide whose tables this file cannot read would pass the checks below emptily.
    assert placements, f"{guide.relative_to(REPOSITORY_ROOT)} holds no table this test reads"

    missing = [module for module in modules if module not in placed]
    repeated = sorted(module for module, count in placed.items() if count > 1)
    ghosts = sorted(
        f"{family}: {module}" for family, module in placements if module not in set(modules)
    )
    where = guide.relative_to(REPOSITORY_ROOT).as_posix()
    assert not missing, "\n".join(
        [f"A module of squadopt.{package} has no row in {where}. Add it to its family:", *missing]
    )
    assert not repeated, "\n".join(
        [f"A module is placed in more than one family of {where}; keep one:", *repeated]
    )
    assert not ghosts, "\n".join(
        [f"A row of {where} names a module that is not in the package:", *ghosts]
    )


def test_both_forms_of_a_family_are_read() -> None:
    """The reading rule is exercised on a synthetic guide, so a drift in it is seen here."""

    guide = "\n".join(
        [
            "# `squadopt.example`",
            "| Process | Entry point |",
            "| --- | --- |",
            "| Weekly run | `python -m squadopt.platform.weekly_operations` |",
            "## Weekly run",
            "",
            "| Module | What it does |",
            "| --- | --- |",
            "| `weekly_operations.py` | The installed weekly entry point. |",
            "| `strategies/catalog.py` | The catalogue. |",
            "| notes | Not a backticked name. |",
            "",
            "### Club news",
            "| Module | What it does |",
            "| --- | --- |",
            "| `sources/__init__.py` | Re-exports. |",
            "```text",
            "| `inside_a_fence.py` | Not a row. |",
            "```",
            "## Ports declared here",
            "| Port | Module |",
            "| --- | --- |",
            "| `JobQueue` | `queue_contracts.py` |",
            "## Module families",
            "| Family | Modules |",
            "| --- | --- |",
            "| Benchmark V2 | `benchmark_v2`, `benchmark_v2_live` |",
            "| The package root | `__init__` |",
        ]
    )

    assert _placements(guide) == [
        ("Weekly run", "weekly_operations"),
        ("Weekly run", "strategies/catalog"),
        ("Weekly run", "notes"),
        ("Club news", "sources/__init__"),
        ("Benchmark V2", "benchmark_v2"),
        ("Benchmark V2", "benchmark_v2_live"),
        ("The package root", "__init__"),
    ]
