"""No new module of the use cases, the domain records or features reads or writes a file.

ADR 0010 puts `application` in the use-case ring (R3) and `live` and `features` in the domain
ring (R2); reading and writing files is an adapter's job (R4). The storage ratchet
(`tests/architecture/test_storage_ratchet.py`) holds these three packages to today's imports of
the storage half of `data`, but a module can also reach a file through `pathlib`, the `open`
builtin, pandas or `os` without importing that half. Today 33 modules do: 24 in `application`,
6 in `live` and 3 in `features`. Under the ratchet rule of ADR 0010 (Decision 4), `ALLOWLIST`
holds exactly those modules, each with its remedy and phase, and may only shrink.

The scan is the one `tests/architecture/test_core_file_io.py` runs over the decision core, so
it finds the same forms of file access. This list is kept by module rather than by function:
the use cases change more often than the core, and the remedy, the storage ports, takes a
module's file access out as a whole. A file access added inside a listed module is not seen
here; a module that starts to read or write files is.
"""

from __future__ import annotations

from collections import Counter

from tests.architecture.test_core_file_io import (
    SOURCE_ROOT,
    _file_access,
    _module_name,
    _package_files,
)

PACKAGES = ("squadopt.application", "squadopt.live", "squadopt.features")

#: The remedy and phase of an entry, as ARCHITECTURE.md's known violations write them.
STORAGE_PORTS = (
    "File adapters in platform behind the storage ports, so the module receives and returns "
    "records rather than paths; Phase 3, with the storage ports"
)

#: Every module of these packages that reads or writes a file on 2026-10-13, with its remedy
#: and phase: 33 modules, 24 in `application`, 6 in `live` and 3 in `features`. **It may only
#: shrink.** If this test fails because a module is new, take the file access to an adapter in
#: `platform` or to the storage half of `data`; do not add it here.
ALLOWLIST: dict[str, str] = dict.fromkeys(
    (
        "squadopt.application.advice_record",
        "squadopt.application.build",
        "squadopt.application.commands",
        "squadopt.application.contract",
        "squadopt.application.entries",
        "squadopt.application.evidence_io",
        "squadopt.application.football_live",
        "squadopt.application.horizon_plans",
        "squadopt.application.horizon_publish",
        "squadopt.application.league_publication",
        "squadopt.application.league_tree_identity",
        "squadopt.application.league_views",
        "squadopt.application.manager_words",
        "squadopt.application.player_evidence",
        "squadopt.application.projection_handoff",
        "squadopt.application.rotation_export",
        "squadopt.application.scoreboard",
        "squadopt.application.scoreboard_baselines",
        "squadopt.application.settled_outcomes",
        "squadopt.application.settled_publication",
        "squadopt.application.site",
        "squadopt.application.top100_weight",
        "squadopt.application.weekly_plan",
        "squadopt.application.weekly_suggestion_eval",
        "squadopt.live.calibration",
        "squadopt.live.football_artifact",
        "squadopt.live.ledger",
        "squadopt.live.recommendation",
        "squadopt.live.risk",
        "squadopt.live.tick",
        "squadopt.features.evidence_artifact",
        "squadopt.features.rotation_evidence_artifact",
        "squadopt.features.settled_outcomes",
    ),
    STORAGE_PORTS,
)

#: The size of `ALLOWLIST` by package. Lower a count when an entry leaves; raising one is the
#: growth the ratchet refuses.
ALLOWLIST_SIZE = {"application": 24, "live": 6, "features": 3}


def _modules_touching_files() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for package in PACKAGES:
        for path in _package_files(package):
            access = _file_access(path.read_text(encoding="utf-8"))
            if access:
                found[_module_name(path)] = sorted(access)
    return found


def test_every_package_named_here_is_under_src() -> None:
    assert [
        package
        for package in PACKAGES
        if not (SOURCE_ROOT.joinpath(*package.split(".")) / "__init__.py").is_file()
    ] == []


def test_only_the_allowlisted_modules_read_or_write_files() -> None:
    found = _modules_touching_files()

    assert {module: where for module, where in found.items() if module not in ALLOWLIST} == {}, (
        "file IO belongs to an adapter in platform or in the storage half of data; the "
        "allowlist does not grow"
    )
    assert sorted(module for module in ALLOWLIST if module not in found) == [], (
        "this module no longer reads or writes a file: delete its entry from ALLOWLIST"
    )


def test_the_allowlist_keeps_its_size_and_its_remedy() -> None:
    packages = Counter(module.split(".")[1] for module in ALLOWLIST)

    assert packages == ALLOWLIST_SIZE, (
        "the allowlist only shrinks: when an entry leaves, lower its package's count with it"
    )
    assert [m for m in ALLOWLIST if not m.startswith(tuple(f"{p}." for p in PACKAGES))] == []
    assert set(ALLOWLIST.values()) == {STORAGE_PORTS}


def test_an_in_memory_csv_is_not_file_access() -> None:
    """`live/report.py` turns a frame into CSV bytes with `to_csv` and no target: no file."""

    assert _file_access("def render(frame):\n    return frame.to_csv(index=False)\n") == {}
