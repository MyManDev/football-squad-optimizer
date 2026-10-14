"""Every path into `docs/contracts` comes from one resolver.

The schemas under `docs/contracts` are documents of the repository, not files of the installed
package: a module that builds `Path("docs") / "contracts" / ...` reaches them only when the
working directory is a checkout. Until 2026-10-13, 8 modules built such a path, 2 in
`application` and 6 in `platform`, each to name a schema as the default target of the function
that writes it or as a constant the tests read; none reads the schema when it runs. ADR 0011
(decision 6) puts the folder in one place, `squadopt.contracts.schema_paths`: its
`contract_schema_path` answers the same relative path those modules built, so every write
default and every test read is unchanged, and it refuses a name that is not `<name>_v<N>`.
Seven modules now take their path from it. `platform.history_documents` still builds its own
in `write_history_schema`, and leaves `ALLOWLIST` when #969, which edits that module, has
merged; under the ratchet rule of ADR 0010 (Decision 4), `ALLOWLIST` may only shrink.

Three checks hold this. Each `*_SCHEMA_PATH` constant is pinned to the literal it was before
the resolver, so a change to the resolver that moved a schema fails here before a schema
equality test reads the wrong file. The scan reads every Python file under `src/squadopt` and
reports a module when one expression names the `docs` folder followed by `contracts`: a string
such as `"docs/contracts/x.json"`, a chain such as `Path("docs") / "contracts" / name`, or the
arguments of `Path`, `PurePath`, `joinpath` or `os.path.join`; docstrings and comments are prose,
not paths, and are not read. Only the resolver and the allowlist may name the folder. And every
path a pinned constant holds is a file git tracks.
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

from squadopt.contracts.schema_paths import CONTRACT_SCHEMA_DIRECTORY, contract_schema_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PACKAGE = SOURCE_ROOT / "squadopt"

#: The one module that names the folder, by ADR 0011 (decision 6).
RESOLVER = "squadopt.contracts.schema_paths"

#: The calls whose arguments are joined into one path.
PATH_CALLS = frozenset({"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "joinpath", "join"})

#: The remedy and phase of an entry, as ARCHITECTURE.md's known violations write them.
TAKES_THE_PATH_FROM_THE_RESOLVER = (
    "write_history_schema takes its path from contract_schema_path once #969, which edits the "
    "module, has merged; Phase 3"
)

#: Every module under `src/squadopt` other than the resolver that names a path into
#: `docs/contracts` on 2026-10-13, with its remedy and phase: one, in `platform`. **It may only
#: shrink.** If the scan reports a module that is not here, take the path from the resolver; do
#: not add the module.
ALLOWLIST: dict[str, str] = {
    "squadopt.platform.history_documents": TAKES_THE_PATH_FROM_THE_RESOLVER,
}

#: Each `*_SCHEMA_PATH` constant and the literal it was before the resolver.
FORMER_LITERALS: dict[tuple[str, str], Path] = {
    ("squadopt.application.chip_forecast", "CHIP_FORECAST_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "chip_forecast_v1.schema.json"
    ),
    ("squadopt.application.contract", "UI_VIEW_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "ui_view_v1.schema.json"
    ),
    ("squadopt.platform.advice_documents", "ADVICE_READ_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "advice_read_v1.schema.json"
    ),
    ("squadopt.platform.advice_documents", "LEAGUE_CAPABILITIES_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "league_capabilities_v1.schema.json"
    ),
    ("squadopt.platform.advice_documents", "LEAGUE_STATE_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "league_state_v1.schema.json"
    ),
    ("squadopt.platform.api_contract", "BACKEND_API_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "backend_api_v1.schema.json"
    ),
    ("squadopt.platform.artifacts", "ARTIFACT_RECORD_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "artifact_record_v1.schema.json"
    ),
    ("squadopt.platform.jobs_contract", "BACKEND_JOBS_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "backend_jobs_v1.schema.json"
    ),
    ("squadopt.platform.manifest", "RUN_MANIFEST_SCHEMA_PATH"): (
        Path("docs") / "contracts" / "run_manifest_v1.schema.json"
    ),
}

#: The path `write_history_schema` builds itself today, so the swap to the resolver is a
#: no-op when #969 has merged.
HISTORY_SCHEMA_LITERAL = Path("docs/contracts/weekly_suggestion_history_v1.schema.json")

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


def _schema_path_constants() -> set[tuple[str, str]]:
    """Every module-level name ending in `_SCHEMA_PATH` that a module under `src/squadopt`
    assigns, as (module, name)."""

    found: set[tuple[str, str]] = set()
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for statement in tree.body:
            targets: list[ast.expr] = []
            if isinstance(statement, ast.Assign):
                targets = statement.targets
            elif isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith("_SCHEMA_PATH"):
                    found.add((_module_name(path), target.id))
    return found


def _tracked_contract_files() -> set[Path]:
    """Every file git tracks under `docs/contracts`, relative to the repository root."""

    listing = subprocess.run(
        ["git", "ls-files", "-z", "--", "docs/contracts"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {Path(entry) for entry in listing.stdout.split("\0") if entry}


def test_the_resolver_answers_the_relative_path_the_modules_built() -> None:
    directory = CONTRACT_SCHEMA_DIRECTORY

    assert directory == Path("docs") / "contracts"
    assert not directory.is_absolute()

    path = contract_schema_path("ui_view_v1")

    assert path == Path("docs") / "contracts" / "ui_view_v1.schema.json"
    assert path.parts == ("docs", "contracts", "ui_view_v1.schema.json")
    assert not path.is_absolute()
    assert contract_schema_path("weekly_suggestion_history_v1") == HISTORY_SCHEMA_LITERAL


@pytest.mark.parametrize(
    "contract_version",
    [
        "ui_view",
        "ui_view_v",
        "ui_view_v0",
        "ui_view_v01",
        "ui_view_V1",
        "UI_VIEW_V1",
        "ui-view_v1",
        "ui view_v1",
        "_v1",
        "1_view_v1",
        "ui_view_v1.schema.json",
        "ui_view_v1/",
        "../ui_view_v1",
        "docs/contracts/ui_view_v1",
        " ui_view_v1",
        "ui_view_v1\n",
        "",
    ],
)
def test_the_resolver_refuses_a_name_that_is_not_name_v_n(contract_version: str) -> None:
    with pytest.raises(ValueError, match="<name>_v<N>"):
        contract_schema_path(contract_version)


@pytest.mark.parametrize(
    ("module", "name", "literal"),
    [(module, name, literal) for (module, name), literal in FORMER_LITERALS.items()],
    ids=[f"{module}.{name}" for module, name in FORMER_LITERALS],
)
def test_each_schema_path_constant_is_its_former_literal(
    module: str, name: str, literal: Path
) -> None:
    value = getattr(importlib.import_module(module), name)

    assert isinstance(value, Path)
    assert value == literal
    assert value.parts == literal.parts
    assert str(value) == str(literal)


def test_every_schema_path_constant_is_pinned() -> None:
    assert _schema_path_constants() == set(FORMER_LITERALS), (
        "a *_SCHEMA_PATH constant is not pinned to its literal, or a pin names no constant"
    )


def test_every_pinned_path_is_a_committed_file() -> None:
    tracked = _tracked_contract_files()

    assert (REPOSITORY_ROOT / CONTRACT_SCHEMA_DIRECTORY / "README.md") in {
        REPOSITORY_ROOT / path for path in tracked
    }
    for literal in [*FORMER_LITERALS.values(), HISTORY_SCHEMA_LITERAL]:
        assert (REPOSITORY_ROOT / literal).is_file(), literal
        assert literal in tracked, f"{literal} is not tracked by git"


def test_only_the_resolver_and_the_allowlist_name_a_path_into_docs_contracts() -> None:
    found = _modules()

    assert RESOLVER in found, "the resolver is the one place that names the folder"
    assert {
        module: lines
        for module, lines in found.items()
        if module != RESOLVER and module not in ALLOWLIST
    } == {}, "a module names a path into docs/contracts: take it from contract_schema_path"
    assert sorted(module for module in ALLOWLIST if module not in found) == [], (
        "this module no longer names docs/contracts: delete its entry from ALLOWLIST"
    )
    assert len(found) == 1 + len(ALLOWLIST)


def test_the_allowlist_only_shrinks() -> None:
    assert set(ALLOWLIST) <= {"squadopt.platform.history_documents"}
    assert set(ALLOWLIST.values()) <= {TAKES_THE_PATH_FROM_THE_RESOLVER}


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
