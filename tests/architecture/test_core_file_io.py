"""The vocabulary, the decision core and prediction touch no file, apart from a shrinking list.

ADR 0010 puts `contracts` in the vocabulary ring (R1) and `optimization`, `planning`,
`scenarios`, `evaluation` and `prediction` in the domain ring (R2). Reading and writing files is
an adapter's job (R4). The contract "The decision core imports no OS or process module" refuses
`os`, `shutil` and `tempfile` in the first five packages, but a file is also reached through
`pathlib`, the `open` builtin, pandas and NumPy, which no import contract can refuse. Today two
modules of `contracts` and one of `evaluation` do that, so this test states the rule with
today's calls as its allowlist, under the ratchet rule of ADR 0010 (Decision 4): `ALLOWLIST`
holds exactly today's violations, each with its remedy and phase, and may only shrink.
`prediction` makes no such call today, so it is held to the rule with no entry.

The scan reads every Python file of these packages and reports, for each function (written as
its qualified name, `<module>` for module level code), a call that touches the file system:

- the `open` builtin;
- a method named as a `pathlib.Path` method that touches the file system (`FILE_METHODS`), or
  as a pandas reader or writer that always does (`PANDAS_IO`), whatever object it is called on;
- a pandas writer that returns its text or bytes when it is given no target
  (`PANDAS_WRITERS_WITH_A_TARGET`), when it is given one: a positional argument or a target
  keyword (`to_csv(path)`, not `to_csv()` or `to_csv(index=False)`);
- a function of a module that only reads or writes files under that name
  (`MODULE_FILE_FUNCTIONS`: `os`, `os.path`, `glob`, NumPy and joblib), called through the
  module, through an alias of it (`import os as x`) or imported by name (`from glob import
  glob`);
- any import of `shutil`, `tempfile` or `glob`.

A method is matched by its name, so names that strings and data frames share with `Path`
(`replace`, `rename`) are left out, `ast.walk` is told apart from `Path.walk` by its module, and
a function that reaches a file only through another function is reported where the call is,
not where it is used. `tests/architecture/test_use_case_file_io.py` runs the same scan over
`application`, `live` and `features`.
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
        "walk",
        "exists",
        "is_file",
        "is_dir",
        "is_symlink",
        "stat",
        "lstat",
        "chmod",
        "lchmod",
        "symlink_to",
        "hardlink_to",
        "readlink",
        "samefile",
        # NumPy's `ndarray.tofile`, called on an array rather than on the module.
        "tofile",
    }
)
PANDAS_IO = frozenset(
    {
        "read_csv",
        "read_json",
        "read_parquet",
        "read_excel",
        "read_pickle",
        "read_feather",
        "read_table",
        "read_fwf",
        "read_hdf",
        "read_sql",
        "read_orc",
        "read_stata",
        "read_xml",
        "to_excel",
        "to_pickle",
        "to_feather",
        "to_hdf",
        "to_stata",
    }
)
PANDAS_WRITERS_WITH_A_TARGET = frozenset({"to_csv", "to_json", "to_parquet", "to_orc", "to_xml"})
TARGET_KEYWORDS = frozenset({"path_or_buf", "path", "buf"})
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
#: The modules whose file functions are matched by the module they come from, because their
#: names (`load`, `save`, `dump`) are too common to match on any object.
MODULE_FILE_FUNCTIONS: dict[str, frozenset[str]] = {
    "os": OS_FILE_FUNCTIONS,
    "os.path": OS_FILE_FUNCTIONS,
    "glob": frozenset({"glob", "iglob"}),
    "numpy": frozenset(
        {
            "save",
            "savez",
            "savez_compressed",
            "load",
            "loadtxt",
            "savetxt",
            "genfromtxt",
            "fromfile",
            "memmap",
        }
    ),
    "joblib": frozenset({"dump", "load"}),
}
#: Modules that share a method name with `Path` and touch no file under it.
NAMESAKE_MODULES = frozenset({"ast"})
FILE_MODULES = frozenset({"shutil", "tempfile", "glob"})

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

#: The size of `ALLOWLIST`. Lower it when an entry leaves; raising it is the growth the
#: ratchet refuses.
ALLOWLIST_SIZE = 9


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """Each name an import binds to a module or a module's attribute, by its dotted target.

    `import os as x` binds `x` to `os`, `import os.path as p` binds `p` to `os.path`, and
    `from glob import glob as g` binds `g` to `glob.glob`. A plain `import os` binds `os` to
    itself, so it needs no entry. Imports anywhere in the file count.
    """

    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update({alias.asname: alias.name for alias in node.names if alias.asname})
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.update(
                {alias.asname or alias.name: f"{node.module}.{alias.name}" for alias in node.names}
            )
    return names


def _resolve(dotted: str, names: dict[str, str]) -> str:
    """`dotted` with its first part replaced by what an import bound it to."""

    first, _, rest = dotted.partition(".")
    target = names.get(first, first)
    return f"{target}.{rest}" if rest else target


def _module_function(module: str, function: str) -> bool:
    """Whether `module.function` reads or writes a file, judged by the module it comes from."""

    if module in MODULE_FILE_FUNCTIONS:
        return function in MODULE_FILE_FUNCTIONS[module]
    return module in FILE_MODULES or (module == "pandas" and function in PANDAS_IO)


def _call_name(call: ast.Call, names: dict[str, str]) -> str | None:
    """What a call is reported as when it touches the file system, else None."""

    function = call.func
    if isinstance(function, ast.Name):
        if function.id in names:
            module, _, attribute = names[function.id].rpartition(".")
            touches = attribute == "open" or _module_function(module, attribute)
            return names[function.id] if touches else None
        return "open" if function.id == "open" else None
    if not isinstance(function, ast.Attribute):
        return None
    owner = ast.unparse(function.value)
    module = _resolve(owner, names)
    if module in MODULE_FILE_FUNCTIONS or module in FILE_MODULES or module in NAMESAKE_MODULES:
        return f"{owner}.{function.attr}" if _module_function(module, function.attr) else None
    if function.attr in FILE_METHODS | PANDAS_IO:
        return f"{owner}.{function.attr}"
    if function.attr in PANDAS_WRITERS_WITH_A_TARGET and (
        call.args or any(keyword.arg in TARGET_KEYWORDS for keyword in call.keywords)
    ):
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
    tree = ast.parse(text)
    names = _imported_names(tree)

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = [*scope, child.name]
            reported: list[str] = []
            line = 0
            if isinstance(child, ast.Call):
                name = _call_name(child, names)
                reported, line = ([name] if name else []), child.lineno
            elif isinstance(child, ast.Import | ast.ImportFrom):
                reported, line = _import_names(child), child.lineno
            if reported:
                found.setdefault(".".join(scope) or "<module>", []).extend(
                    f"line {line}: {name}" for name in reported
                )
            visit(child, inner)

    visit(tree, [])
    return found


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _package_files(package: str) -> list[Path]:
    return sorted((SOURCE_ROOT / Path(*package.split("."))).rglob("*.py"))


def _offending() -> dict[tuple[str, str], list[str]]:
    offending: dict[tuple[str, str], list[str]] = {}
    for package in PACKAGES:
        for path in _package_files(package):
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


def test_the_allowlist_keeps_its_size() -> None:
    assert len(ALLOWLIST) == ALLOWLIST_SIZE, (
        "the allowlist only shrinks: when an entry leaves, lower ALLOWLIST_SIZE with it"
    )


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


def test_the_scan_follows_aliases_modules_and_targets() -> None:
    text = "\n".join(
        [
            "import ast",
            "import joblib",
            "import numpy as np",
            "import os as _o",
            "import os.path as osp",
            "from glob import glob as g",
            "from io import open as io_open",
            "from numpy import load",
            "from pandas import read_feather",
            "from squadopt.contracts import Position",
            "def save(frame, path, array, model, tree):",
            "    frame.to_json(path)",
            "    frame.to_csv(path_or_buf=path)",
            "    text = frame.to_csv()",
            "    text = frame.to_csv(index=False)",
            "    np.save(path, array)",
            "    load(path)",
            "    array.tofile(path)",
            "    joblib.dump(model, path)",
            "    np.asarray(array)",
            "def scan(path, tree):",
            "    _o.remove(path)",
            "    osp.isfile(path)",
            "    g('*.csv')",
            "    path.walk()",
            "    path.symlink_to(path)",
            "    read_feather(path)",
            "    pd.read_table(path)",
            "    io_open(path)",
            "    nodes = list(ast.walk(tree))",
            "    _o.getcwd()",
            "    Position('GK')",
        ]
    )

    assert _file_access(text) == {
        "<module>": ["line 6: from glob import glob"],
        "save": [
            "line 12: frame.to_json",
            "line 13: frame.to_csv",
            "line 16: np.save",
            "line 17: numpy.load",
            "line 18: array.tofile",
            "line 19: joblib.dump",
        ],
        "scan": [
            "line 22: _o.remove",
            "line 23: osp.isfile",
            "line 24: glob.glob",
            "line 25: path.walk",
            "line 26: path.symlink_to",
            "line 27: pandas.read_feather",
            "line 28: pd.read_table",
            "line 29: io.open",
        ],
    }
