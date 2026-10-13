"""No new module of the package names a path into `docs/contracts`.

The schemas under `docs/contracts` are documents of the repository, not files of the installed
package: a module that builds `Path("docs") / "contracts" / ...` reaches them only when the
working directory is a checkout. Today 8 modules do, 2 in `application` and 6 in `platform`,
each to name a schema as the default target of the function that writes it, as the target of
`write_history_schema`, or as a constant the tests read. None reads the schema when it runs;
`docs/contracts/README.md` lists each schema with its producer. Under the ratchet rule of ADR
0010 (Decision 4), `ALLOWLIST` holds exactly those modules, each with its remedy and phase, and
may only shrink.

The scan reads every Python file under `src/squadopt` and reports a module when one expression
names the `docs` folder followed by `contracts`: a string such as `"docs/contracts/x.json"`, a
chain such as `Path("docs") / "contracts" / name`, or the arguments of `Path`, `PurePath`,
`joinpath` or `os.path.join`. Docstrings and comments are prose, not paths, and are not read.
"""

from __future__ import annotations

import ast
import re
from itertools import pairwise
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE = SOURCE_ROOT / "squadopt"

#: The calls whose arguments are joined into one path.
PATH_CALLS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "joinpath", "join"})

#: The remedy and phase of an entry, as ARCHITECTURE.md's known violations write them.
CALLER_PASSES_THE_PATH = (
    "The script or test that writes or compares the schema passes its path, so the module keeps "
    "the schema function and names no repository folder; Phase 3"
)

#: Every module under `src/squadopt` that names a path into `docs/contracts` on 2026-10-13,
#: with its remedy and phase: 8 modules, 2 in `application` and 6 in `platform`. **It may only
#: shrink.** If this test fails because a module is new, take the path from the caller; do not
#: add it here.
ALLOWLIST: dict[str, str] = dict.fromkeys(
    (
        "squadopt.application.chip_forecast",
        "squadopt.application.contract",
        "squadopt.platform.advice_documents",
        "squadopt.platform.api_contract",
        "squadopt.platform.artifacts",
        "squadopt.platform.history_documents",
        "squadopt.platform.jobs_contract",
        "squadopt.platform.manifest",
    ),
    CALLER_PASSES_THE_PATH,
)

#: A separator between path parts that do not join, such as the result of another call.
_GAP = ""


def _docstrings(tree: ast.Module) -> set[int]:
    """The ids of every string that stands alone as a statement: docstrings and the
    attribute docstrings that follow an assignment."""

    found: set[int] = set()
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            statements = getattr(node, field, None)
            if not isinstance(statements, list):
                continue
            for statement in statements:
                if (
                    isinstance(statement, ast.Expr)
                    and isinstance(statement.value, ast.Constant)
                    and isinstance(statement.value.value, str)
                ):
                    found.add(id(statement.value))
    return found


def _parts(node: ast.AST, prose: set[int]) -> list[str]:
    """The path parts an expression names, in order, with `_GAP` where they cannot join."""

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [_GAP] if id(node) in prose else re.split(r"[\\/]", node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [*_parts(node.left, prose), *_parts(node.right, prose)]
    if isinstance(node, ast.JoinedStr):
        return [
            part
            for value in node.values
            for part in (_parts(value, prose) if isinstance(value, ast.Constant) else [_GAP])
        ]
    if isinstance(node, ast.Call):
        function = node.func
        start = [_GAP]
        if isinstance(function, ast.Name):
            name = function.id
        elif isinstance(function, ast.Attribute):
            name = function.attr
            if name == "joinpath":
                start = _parts(function.value, prose)
        else:
            name = ""
        if name not in PATH_CALLS:
            return [_GAP]
        return [*start, *(part for argument in node.args for part in _parts(argument, prose))]
    return [_GAP]


def _names_contract_path(text: str) -> list[int]:
    """The lines of `text` where an expression names `docs` followed by `contracts`."""

    tree = ast.parse(text)
    prose = _docstrings(tree)
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant | ast.BinOp | ast.JoinedStr | ast.Call):
            parts = _parts(node, prose)
            if any((first, second) == ("docs", "contracts") for first, second in pairwise(parts)):
                lines.add(node.lineno)
    return sorted(lines)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _modules() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        lines = _names_contract_path(path.read_text(encoding="utf-8"))
        if lines:
            found[_module_name(path)] = lines
    return found


def test_only_the_allowlisted_modules_name_a_path_into_docs_contracts() -> None:
    found = _modules()

    assert {module: lines for module, lines in found.items() if module not in ALLOWLIST} == {}, (
        "a module names a path into docs/contracts: take the path from the caller; the "
        "allowlist does not grow"
    )
    assert sorted(module for module in ALLOWLIST if module not in found) == [], (
        "this module no longer names docs/contracts: delete its entry from ALLOWLIST"
    )


def test_the_allowlist_is_two_application_and_six_platform_modules() -> None:
    packages = [module.split(".")[1] for module in ALLOWLIST]

    assert (packages.count("application"), packages.count("platform")) == (2, 6)
    assert len(ALLOWLIST) == len(packages)
    assert set(ALLOWLIST.values()) == {CALLER_PASSES_THE_PATH}


def test_the_scan_finds_each_way_of_naming_the_folder() -> None:
    text = "\n".join(
        [
            '"""A module that writes docs/contracts/x.json, as prose."""',
            'A = Path("docs") / "contracts" / "a.schema.json"',
            'B = Path("docs/contracts/b.schema.json")',
            'C = ROOT.joinpath("docs", "contracts", "c.json")',
            'D = os.path.join("docs", "contracts", "d.json")',
            'E = Path("docs") / "records" / "contracts.json"',
            'F = f"docs/contracts/{name}.json"',
            'G = load("docs") / "contracts"',
            "def write():",
            '    """Writes the schema to docs/contracts."""',
            '    return Path("docs", "contracts")',
        ]
    )

    assert _names_contract_path(text) == [2, 3, 4, 5, 7, 11]
