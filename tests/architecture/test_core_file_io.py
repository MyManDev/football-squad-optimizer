"""The vocabulary, the decision core and prediction touch no file, apart from a shrinking list.

ADR 0010 puts `contracts` in the vocabulary ring (R1) and `optimization`, `planning`,
`scenarios`, `evaluation` and `prediction` in the domain ring (R2). Reading and writing files is
an adapter's job (R4). The contract "The decision core imports no OS or process module" refuses
`os`, `shutil` and `tempfile` in the first five packages, but a file is also reached through
`pathlib`, the `open` builtin and pandas, which no import contract can refuse. Today two modules
of `contracts` and one of `evaluation` do that, so this test states the rule with today's calls
as its allowlist, under the ratchet rule of ADR 0010 (Decision 4): `ALLOWLIST` holds exactly
today's violations, each with its remedy and phase, and may only shrink. `prediction` makes no
such call today, so it is held to the rule with no entry.

The scan reads every Python file of these packages and reports, for each function (written as
its qualified name, `<module>` for module level code), a call that touches the file system:

- the `open` builtin;
- a method named as a `pathlib.Path` method that touches the file system (`FILE_METHODS`), or
  as a pandas reader or writer (`PANDAS_IO`), whatever object it is called on;
- an `os` or `os.path` function that touches the file system (`OS_FILE_FUNCTIONS`), called
  through the module or imported from it;
- any import of `shutil` or `tempfile`.

A call is matched by its name, so names that strings and data frames share with `Path`
(`replace`, `rename`) are left out, and a function that reaches a file only through another
function is reported where the call is, not where it is used.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"

PACKAGES = (
    "squadopt.contracts",
    "squadopt.optimization",
    "squadopt.planning",
    "squadopt.scenarios",
    "squadopt.evaluation",
    "squadopt.prediction",
)

FILE_METHODS = frozenset(
    {
        "open",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rmdir",
        "touch",
        "iterdir",
        "glob",
        "rglob",
        "exists",
        "is_file",
        "is_dir",
        "stat",
    }
)
PANDAS_IO = frozenset(
    {
        "read_csv",
        "read_json",
        "read_parquet",
        "read_excel",
        "read_pickle",
        "to_csv",
        "to_parquet",
        "to_excel",
        "to_pickle",
    }
)
OS_FILE_FUNCTIONS = frozenset(
    {
        "open",
        "remove",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "makedirs",
        "rmdir",
        "removedirs",
        "listdir",
        "scandir",
        "walk",
        "stat",
        "lstat",
        "chmod",
        "link",
        "symlink",
        "truncate",
        "fsync",
        "exists",
        "lexists",
        "isfile",
        "isdir",
        "getsize",
        "getmtime",
    }
)
FILE_MODULES = frozenset({"shutil", "tempfile"})

#: The remedy and phase of an entry, as ARCHITECTURE.md's known violations write them.
LEAGUE_FILES = (
    "Move the file IO to an adapter, with a one-release re-export; Phase 3, after issue #981"
)
COMPONENT_HANDOFF = (
    "Move read_phase_c_component_handoff to an adapter, so evaluation receives the parsed "
    "tables; Phase 3"
)

#: Every function of these packages that touches the file system on 2026-10-13, with its
#: remedy and phase: 9 functions in 3 modules. **It may only shrink.** If this test fails
#: because a call is new, move the call to an adapter; do not add it here.
ALLOWLIST: dict[tuple[str, str], str] = {
    ("squadopt.contracts.league_list", "read_league_list"): LEAGUE_FILES,
    ("squadopt.contracts.league_tree", "device_plan_sha256"): LEAGUE_FILES,
    ("squadopt.contracts.league_tree", "read_league_directory"): LEAGUE_FILES,
    ("squadopt.contracts.league_tree", "write_league_directory"): LEAGUE_FILES,
    ("squadopt.contracts.league_tree", "legacy_tree_league_id"): LEAGUE_FILES,
    ("squadopt.evaluation.component_handoff", "_manifest"): COMPONENT_HANDOFF,
    ("squadopt.evaluation.component_handoff", "_sha256"): COMPONENT_HANDOFF,
    ("squadopt.evaluation.component_handoff", "_file_sha256"): COMPONENT_HANDOFF,
    ("squadopt.evaluation.component_handoff", "_read_csv"): COMPONENT_HANDOFF,
}


def _call_name(call: ast.Call) -> str | None:
    """What a call is reported as when it touches the file system, else None."""

    function = call.func
    if isinstance(function, ast.Name) and function.id == "open":
        return "open"
    if not isinstance(function, ast.Attribute):
        return None
    owner = ast.unparse(function.value)
    if owner in {"os", "os.path"}:
        return f"{owner}.{function.attr}" if function.attr in OS_FILE_FUNCTIONS else None
    if function.attr in FILE_METHODS | PANDAS_IO:
        return f"{owner}.{function.attr}"
    return None


def _import_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """What an import is reported as when it brings in file system access, else nothing."""

    if isinstance(node, ast.Import):
        return [
            f"import {alias.name}"
            for alias in node.names
            if alias.name.split(".")[0] in FILE_MODULES
        ]
    module = node.module or ""
    if node.level == 0 and module.split(".")[0] in FILE_MODULES:
        return [f"from {module} import {alias.name}" for alias in node.names]
    if node.level == 0 and module in {"os", "os.path"}:
        return [
            f"from {module} import {alias.name}"
            for alias in node.names
            if alias.name in OS_FILE_FUNCTIONS
        ]
    return []


def _file_access(text: str) -> dict[str, list[str]]:
    """Each function of `text` that touches the file system, with what it calls."""

    found: dict[str, list[str]] = {}

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = [*scope, child.name]
            names: list[str] = []
            line = 0
            if isinstance(child, ast.Call):
                name = _call_name(child)
                names, line = ([name] if name else []), child.lineno
            elif isinstance(child, ast.Import | ast.ImportFrom):
                names, line = _import_names(child), child.lineno
            if names:
                found.setdefault(".".join(scope) or "<module>", []).extend(
                    f"line {line}: {name}" for name in names
                )
            visit(child, inner)

    visit(ast.parse(text), [])
    return found


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _offending() -> dict[tuple[str, str], list[str]]:
    offending: dict[tuple[str, str], list[str]] = {}
    for package in PACKAGES:
        for path in sorted((SOURCE_ROOT / Path(*package.split("."))).rglob("*.py")):
            module = _module_name(path)
            for function, calls in _file_access(path.read_text(encoding="utf-8")).items():
                offending[(module, function)] = calls
    return offending


def test_every_package_named_here_is_under_src() -> None:
    assert [
        package
        for package in PACKAGES
        if not (SOURCE_ROOT / Path(*package.split(".")) / "__init__.py").is_file()
    ] == []


def test_the_core_touches_files_exactly_where_the_allowlist_says() -> None:
    offending = _offending()

    assert {key: calls for key, calls in offending.items() if key not in ALLOWLIST} == {}, (
        "file IO belongs to an adapter in platform or in the storage half of data; the "
        "allowlist does not grow"
    )
    assert sorted(key for key in ALLOWLIST if key not in offending) == [], (
        "this function no longer touches a file: delete its entry from ALLOWLIST"
    )


def test_every_entry_names_a_package_held_here_and_a_known_remedy() -> None:
    assert [
        module
        for module, _ in ALLOWLIST
        if not any(module.startswith(f"{package}.") for package in PACKAGES)
    ] == []
    assert set(ALLOWLIST.values()) == {LEAGUE_FILES, COMPONENT_HANDOFF}


def test_the_scan_finds_each_form_of_file_access() -> None:
    text = "\n".join(
        [
            "import shutil",
            "from os.path import exists, join",
            "LIMIT = open('limits.txt').read()",
            "def load(path):",
            "    frame = pd.read_csv(path)",
            "    os.makedirs(path.parent)",
            "    name = path.name.replace('-', '_')",
            "    return frame.rename(columns=str)",
            "class Store:",
            "    def write(self, path, text):",
            "        def inner():",
            "            return path.write_text(text)",
            "        return os.path.join(path, text)",
        ]
    )

    assert _file_access(text) == {
        "<module>": [
            "line 1: import shutil",
            "line 2: from os.path import exists",
            "line 3: open",
        ],
        "load": ["line 5: pd.read_csv", "line 6: os.makedirs"],
        "Store.write.inner": ["line 12: path.write_text"],
    }
