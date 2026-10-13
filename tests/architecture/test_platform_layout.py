"""The platform's deployment units: what has moved, what the old path still answers, who imports it.

ADR 0011 (decision 3) splits `squadopt.platform` into seven subpackages, one pull request per
unit, and (decision 8) leaves an alias at each old path: a one-release re-export for most
modules, a permanent entry file for the operator commands. This file holds the moves done so
far to one registry, `MOVED`, and checks:

- every name the alias at the old path exports is the moved object itself, so a caller that
  still uses the old path and a caller on the new one share one class, one function and one
  constant;
- no code under `src`, `scripts` or `tests` imports an old path, apart from the alias files,
  so the aliases carry only callers the repository does not control;
- the units contract in `pyproject.toml` ignores exactly the flat modules that have not moved,
  so a move must shorten the list and a new flat module must be placed on purpose;
- each unit has its package file, and the platform guide places every moved module under
  `storage/` and names each alias once.
"""

from __future__ import annotations

import importlib
import re
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
#: ("one release" goes in the release after the next `site-*` tag; "permanent entry" stays).
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

#: The names each alias re-exports, as its `__all__` states them.
EXPORTS: dict[str, tuple[str, ...]] = {
    "squadopt.platform._queue_lock": ("QueueFileLock", "QueueLockTimeout"),
    "squadopt.platform.projection_retention": (
        "ProjectionRetentionError",
        "publish_retained_handoff",
        "retained_handoff_path",
    ),
    "squadopt.platform.store_probe": ("StoreProbeResult", "probe_store"),
    "squadopt.platform.backup_recovery": (
        "BACKUP_SCHEMA_VERSION",
        "MANIFEST_NAME",
        "BackupError",
        "BackupReceipt",
        "create_backup",
        "main",
        "restore_backup",
        "verify_backup",
    ),
}

SCANNED = ("src", "scripts", "tests")
OLD_IMPORT = re.compile(
    r"^\s*(?:from\s+(squadopt\.platform\.[A-Za-z_]+)\s+import"
    r"|import\s+(squadopt\.platform\.[A-Za-z_]+)"
    r"|from\s+squadopt\.platform\s+import\s+([^\n]+))",
    re.MULTILINE,
)


def _units_contract() -> dict[str, object]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (contract,) = [
        contract
        for contract in document["tool"]["importlinter"]["contracts"]
        if contract["name"] == UNITS_CONTRACT
    ]
    return dict(contract)


@pytest.mark.parametrize("old", sorted(MOVED))
def test_every_name_the_alias_exports_is_the_moved_object(old: str) -> None:
    alias = importlib.import_module(old)
    new, _ = MOVED[old]
    moved = importlib.import_module(new)

    assert tuple(alias.__all__) == EXPORTS[old]
    for name in EXPORTS[old]:
        assert getattr(alias, name) is getattr(moved, name), f"{old}.{name}"
    assert alias.__file__ is not None and moved.__file__ is not None
    assert Path(moved.__file__).parent == PLATFORM / "storage"
    assert Path(alias.__file__).parent == PLATFORM


def test_the_permanent_entry_alias_runs_main_only_as_main() -> None:
    entry = [old for old, (_, kind) in MOVED.items() if kind == "permanent entry"]
    assert entry == ["squadopt.platform.backup_recovery"]
    source = (PLATFORM / "backup_recovery.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":\n    raise SystemExit(main())' in source
    for old, (_, kind) in MOVED.items():
        if kind == "one release":
            text = (PLATFORM / f"{old.rsplit('.', 1)[1]}.py").read_text(encoding="utf-8")
            assert "__main__" not in text, old


def test_no_code_outside_the_aliases_imports_an_old_path() -> None:
    aliases = {PLATFORM / f"{old.rsplit('.', 1)[1]}.py" for old in MOVED}
    old_names = {old.rsplit(".", 1)[1] for old in MOVED}
    found: list[str] = []
    for top in SCANNED:
        for path in (REPOSITORY_ROOT / top).rglob("*.py"):
            if path in aliases or path == Path(__file__) or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for match in OLD_IMPORT.finditer(text):
                dotted = match.group(1) or match.group(2)
                if dotted is not None and dotted in MOVED:
                    found.append(f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: {dotted}")
                elif match.group(3) is not None:
                    imported = {
                        part.strip().split(" as ")[0].strip("() ")
                        for part in match.group(3).split(",")
                    }
                    for name in sorted(imported & old_names):
                        found.append(
                            f"{path.relative_to(REPOSITORY_ROOT).as_posix()}: "
                            f"squadopt.platform.{name}"
                        )
    assert found == [], "\n".join(
        ["An old platform path is imported outside its alias; use the new path:", *found]
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
    moved = {
        f"squadopt.platform.storage.{path.stem}" for path in (PLATFORM / "storage").glob("*.py")
    }
    assert moved - {"squadopt.platform.storage.__init__"} == {new for new, _ in MOVED.values()}


def test_the_guide_places_each_moved_module_under_storage_and_each_alias_once() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for old, (new, kind) in MOVED.items():
        name = old.rsplit(".", 1)[1]
        assert text.count(f"| `storage/{name}.py` |") == 1, new
        assert text.count(f"| `{name}.py` |") == 1, old
        row = next(line for line in text.splitlines() if line.startswith(f"| `{name}.py` |"))
        assert ("Permanent" if kind == "permanent entry" else "One-release") in row, old
