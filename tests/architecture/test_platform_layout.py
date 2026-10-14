"""The platform's deployment units: what has moved, what the old path still answers, who imports it.

ADR 0011 (decision 3) splits `squadopt.platform` into seven subpackages, one pull request per
unit, and (decision 8) leaves an alias at each old path: a `sys.modules` alias for a moved
module, so private names and monkeypatches reach the one module through either path, and a
permanent entry file for an operator command. This file holds the moves done so far to one
registry, `MOVED`, and checks:

- the old path and the new path are one module object, and the file at the old path is the
  alias the decision describes (the entry alias runs `main` only as `__main__`);
- no code under `src`, `scripts` or `tests` imports an old path, in any statement form, or
  names it in a string (a monkeypatch target), apart from the alias files, so the aliases
  carry only callers the repository does not control;
- the units contract in `pyproject.toml` ignores exactly the flat modules, aliases included,
  so the list changes only when an alias goes or a new flat module is placed on purpose;
- each unit has its package file, only `storage` holds modules yet, and the platform guide
  places every moved module under `storage/` and names each alias once with its kind.
"""

from __future__ import annotations

import ast
import importlib
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLATFORM = REPOSITORY_ROOT / "src" / "squadopt" / "platform"
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
GUIDE = PLATFORM / "README.md"
UNITS_CONTRACT = "Platform deployment units import only the shared adapters below them"
UNITS = ("storage", "runs", "capture", "club_news", "football", "backend", "operations")

#: Each move done so far: the old module, its new module and the alias left at the old path
#: ("one release" goes in the first pull request after the next `site-*` release; "permanent
#: entry" stays).
MOVED: dict[str, tuple[str, str]] = {
    "squadopt.platform._queue_lock": ("squadopt.platform.storage._queue_lock", "one release"),
    "squadopt.platform.projection_retention": (
        "squadopt.platform.storage.projection_retention",
        "one release",
    ),
    "squadopt.platform.store_probe": ("squadopt.platform.storage.store_probe", "one release"),
    "squadopt.platform.backup_recovery": (
        "squadopt.platform.storage.backup_recovery",
        "permanent entry",
    ),
}

SCANNED = ("src", "scripts", "tests")


def _alias_file(old: str) -> Path:
    return PLATFORM / f"{old.rsplit('.', 1)[1]}.py"


def _units_contract() -> dict[str, object]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (contract,) = [
        contract
        for contract in document["tool"]["importlinter"]["contracts"]
        if contract["name"] == UNITS_CONTRACT
    ]
    return dict(contract)


@pytest.mark.parametrize("old", sorted(MOVED))
def test_the_old_path_and_the_new_path_are_one_module(old: str) -> None:
    new, _ = MOVED[old]
    moved = importlib.import_module(new)

    assert importlib.import_module(old) is moved
    assert moved.__name__ == new
    assert moved.__file__ is not None
    assert Path(moved.__file__).resolve().parent == (PLATFORM / "storage").resolve()
    assert _alias_file(old).is_file()


@pytest.mark.parametrize("old", sorted(MOVED))
def test_the_file_at_the_old_path_is_the_alias_the_decision_describes(old: str) -> None:
    new, kind = MOVED[old]
    source = _alias_file(old).read_text(encoding="utf-8")
    unit, _, basename = new.rpartition(".")

    assert f"from {unit} import {basename} as _moved" in source
    if kind == "permanent entry":
        assert f'if __name__ == "{old}":\n    sys.modules[__name__] = _moved' in source
        assert 'if __name__ == "__main__":\n    raise SystemExit(_moved.main())' in source
    else:
        assert "sys.modules[__name__] = _moved" in source
        assert "__main__" not in source


def _old_path_uses(path: Path) -> list[str]:
    """Every import of an old path in `path`, and every string that names one."""

    old_names = {old.rsplit(".", 1)[1]: old for old in MOVED}
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            if node.module in MOVED:
                found.append(f"{node.lineno}: from {node.module} import ...")
            elif node.module == "squadopt.platform":
                for alias in node.names:
                    if alias.name in old_names:
                        found.append(f"{node.lineno}: from squadopt.platform import {alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in MOVED or alias.name.rpartition(".")[0] in MOVED:
                    found.append(f"{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if text in MOVED or any(text.startswith(f"{old}.") for old in MOVED):
                found.append(f"{node.lineno}: {text!r}")
    return found


def test_no_code_outside_the_aliases_imports_or_names_an_old_path() -> None:
    aliases = {_alias_file(old).resolve() for old in MOVED}
    found: list[str] = []
    for top in SCANNED:
        for path in sorted((REPOSITORY_ROOT / top).rglob("*.py")):
            if path.resolve() in aliases or path.resolve() == Path(__file__).resolve():
                continue
            if "__pycache__" in path.parts:
                continue
            where = path.relative_to(REPOSITORY_ROOT).as_posix()
            found.extend(f"{where}:{use}" for use in _old_path_uses(path))
    assert found == [], "\n".join(
        ["An old platform path is imported or named outside its alias; use the new path:", *found]
    )


def test_the_units_contract_ignores_exactly_the_flat_modules() -> None:
    contract = _units_contract()
    flat = sorted(path.stem for path in PLATFORM.glob("*.py") if path.name != "__init__.py")

    assert contract["containers"] == ["squadopt.platform"]
    assert contract["exhaustive"] is True
    assert contract["exhaustive_ignores"] == flat
    assert contract["layers"] == [
        "operations | backend",
        "football",
        "club_news",
        "capture",
        "runs",
        "storage",
    ]


def test_each_unit_has_its_package_file_and_only_storage_holds_modules() -> None:
    for unit in UNITS:
        assert (PLATFORM / unit / "__init__.py").is_file(), unit
    populated = {
        unit
        for unit in UNITS
        if any(path.name != "__init__.py" for path in (PLATFORM / unit).glob("*.py"))
    }
    assert populated == {"storage"}
    storage = (PLATFORM / "storage").glob("*.py")
    moved = {f"squadopt.platform.storage.{path.stem}" for path in storage}
    assert moved - {"squadopt.platform.storage.__init__"} == {new for new, _ in MOVED.values()}


def test_the_guide_places_each_moved_module_under_storage_and_each_alias_once() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for old, (new, kind) in MOVED.items():
        name = old.rsplit(".", 1)[1]
        assert text.count(f"| `storage/{name}.py` |") == 1, new
        assert text.count(f"| `{name}.py` |") == 1, old
        row = next(line for line in text.splitlines() if line.startswith(f"| `{name}.py` |"))
        assert ("Permanent" if kind == "permanent entry" else "One-release") in row, old
