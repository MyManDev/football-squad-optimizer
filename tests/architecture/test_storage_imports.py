"""The storage contract cannot be passed through the `squadopt.data` package root.

The import-linter contract "The decision core imports no storage or source module" forbids the
storage and source modules of `data` by name and allows indirect imports. `data/__init__.py`
re-exports names from `adapters`, `loaders`, `pipeline` and `snapshots`, so a statement such as
`from squadopt.data import load_csv` imports only the package root: import-linter records an
import of `squadopt.data`, reaches the storage modules indirectly, and keeps the contract. This
test closes that route for the contract's sources. Each of them imports a `data` module by its
own name, never the package root, so the contract sees what it imports.

The scan reads every Python file of every source package, including imports inside functions.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
DATA = SOURCE_ROOT / "squadopt" / "data"
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"

STORAGE_CONTRACT = "The decision core imports no storage or source module"
DATA_ROOT = "squadopt.data"


def _sources() -> list[str]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (contract,) = [
        contract
        for contract in document["tool"]["importlinter"]["contracts"]
        if contract["name"] == STORAGE_CONTRACT
    ]
    sources: list[str] = contract["source_modules"]
    return sources


def _is_data_submodule(name: str) -> bool:
    return (DATA / f"{name}.py").is_file() or (DATA / name / "__init__.py").is_file()


def _root_imports(text: str, package: list[str]) -> list[str]:
    """Every statement in `text` that imports the `data` package root.

    `package` is the dotted package the module sits in, as parts, which is where a relative
    import starts from.
    """

    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found.extend(
                (node.lineno, f"import {alias.name}")
                for alias in node.names
                if alias.name == DATA_ROOT
            )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - node.level + 1]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module == "squadopt":
                names = [alias.name for alias in node.names if alias.name == "data"]
            elif module == DATA_ROOT:
                names = [alias.name for alias in node.names if not _is_data_submodule(alias.name)]
            else:
                names = []
            found.extend((node.lineno, f"from {module} import {name}") for name in names)
    return [f"line {line}: {statement}" for line, statement in sorted(found)]


def _files(source: str) -> list[Path]:
    location = SOURCE_ROOT / Path(*source.split("."))
    if location.is_dir():
        return sorted(location.rglob("*.py"))
    return [location.with_suffix(".py")]


def test_every_source_of_the_storage_contract_is_a_module_under_src() -> None:
    sources = _sources()

    assert sources
    assert [
        source for source in sources if not all(path.is_file() for path in _files(source))
    ] == []


def test_no_source_of_the_storage_contract_imports_the_data_package_root() -> None:
    offending: dict[str, list[str]] = {}
    for source in _sources():
        for path in _files(source):
            package = list(path.relative_to(SOURCE_ROOT).parts[:-1])
            found = _root_imports(path.read_text(encoding="utf-8"), package)
            if found:
                offending[path.relative_to(REPOSITORY_ROOT).as_posix()] = found

    assert offending == {}, (
        "import the `data` module by its own name (for example `squadopt.data.schema`), so the "
        f"storage contract can see it: {offending}"
    )


def test_the_scan_finds_each_form_of_a_root_import() -> None:
    text = "\n".join(
        [
            "import squadopt.data",
            "import squadopt.data.schema",
            "from squadopt import data",
            "from squadopt.data import load_csv, schema",
            "from squadopt.data.schema import POSITIONS",
            "def late():",
            "    from ..data import build_snapshot_id",
            "    from . import scoring",
        ]
    )

    assert _root_imports(text, ["squadopt", "evaluation"]) == [
        "line 1: import squadopt.data",
        "line 3: from squadopt import data",
        "line 4: from squadopt.data import load_csv",
        "line 7: from squadopt.data import build_snapshot_id",
    ]
