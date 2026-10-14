"""The storage imports of the use cases, the domain records and features may only shrink.

ADR 0010 puts the storage and source modules of `data` in the adapter ring (R4), so a use case
(`application`), a domain record (`live`) or a feature builder (`features`) should not import
them. Today they do, so the import-linter contract "Use cases, domain records and features
import no storage or source module" states the rule with today's imports as `ignore_imports`
entries, under the ratchet rule of ADR 0010 (Decision 4): its allowlist holds exactly today's
violations, each with its remedy and phase, and may only shrink.

This file holds that list to `BASELINE`, a frozen copy that gives each entry its remedy and
phase. An entry in `pyproject.toml` that `BASELINE` lacks fails, so the list cannot grow by
editing the contract alone; an entry of `BASELINE` that the contract lacks fails, so a removed
entry leaves both. The scan below reads every Python file of the sources, including imports
inside functions, and resolves each import to the module it names the way import-linter's graph
does: it must find exactly the entries of `BASELINE`, so a new direct import fails here as it
fails `lint-imports`, and an entry whose import is gone fails until it is deleted from both
lists. Adding an import together with its entry in both lists would still pass those checks,
so `BASELINE_SIZE` pins the size of `BASELINE` by package, and growth changes a number a
reviewer sees. An import of the `data` package root would reach the storage modules without an
edge here; `tests/architecture/test_storage_imports.py` refuses it from these sources.
"""

from __future__ import annotations

import ast
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"

RATCHET_CONTRACT = "Use cases, domain records and features import no storage or source module"
CORE_CONTRACT = "The decision core imports no storage or source module"
SOURCES = ("squadopt.application", "squadopt.live", "squadopt.features")

#: The remedy and phase of an entry, as ARCHITECTURE.md's known violations write them.
STORAGE_PORTS = (
    "Storage ports declared in application, with file adapters in platform; Phase 3, "
    "under ADR 0011 (decision 1)"
)
SOURCE_REVISION = (
    "The composition root resolves the source revision and passes it in, or a revision port "
    "with its adapter in platform; Phase 3, with the storage ports"
)

#: The direct imports from a source to a storage or source module of `data` whose remedy is the
#: storage ports: every one of 2026-10-13 except `advice_record` reaching `source_revision`.
STORAGE_PORT_EDGES: tuple[str, ...] = (
    "squadopt.application.advice -> squadopt.data.snapshots",
    "squadopt.application.advice_record -> squadopt.data._long_paths",
    "squadopt.application.advice_record -> squadopt.data.atomic",
    "squadopt.application.capture_entries -> squadopt.data.sources.fpl_live",
    "squadopt.application.chip_forecast_publication -> squadopt.data.snapshots",
    "squadopt.application.chip_forecast_publication -> squadopt.data.sources.fpl_live",
    "squadopt.application.commands -> squadopt.data.snapshots",
    "squadopt.application.commands -> squadopt.data.sources",
    "squadopt.application.commands -> squadopt.data.sources.fpl_live",
    "squadopt.application.commands -> squadopt.data.sources.vaastav",
    "squadopt.application.defcon_component -> squadopt.data.snapshots",
    "squadopt.application.defcon_component -> squadopt.data.sources.fpl_live",
    "squadopt.application.device_plan -> squadopt.data.sources.fpl_live",
    "squadopt.application.entries -> squadopt.data.sources.fpl_live",
    "squadopt.application.fixtures_view -> squadopt.data.snapshots",
    "squadopt.application.fixtures_view -> squadopt.data.sources.fpl_live",
    "squadopt.application.football_live -> squadopt.data.snapshots",
    "squadopt.application.football_live -> squadopt.data.sources.football_history",
    "squadopt.application.football_live -> squadopt.data.sources.fpl_live",
    "squadopt.application.football_live -> squadopt.data.sources.fpl_set_pieces",
    "squadopt.application.horizon_plans -> squadopt.data.snapshots",
    "squadopt.application.horizon_plans -> squadopt.data.sources",
    "squadopt.application.league -> squadopt.data.snapshots",
    "squadopt.application.league -> squadopt.data.sources.fpl_live",
    "squadopt.application.league_publication -> squadopt.data.atomic",
    "squadopt.application.league_publication -> squadopt.data.snapshots",
    "squadopt.application.league_publication -> squadopt.data.sources",
    "squadopt.application.league_publication -> squadopt.data.sources.fpl_live",
    "squadopt.application.league_publication -> squadopt.data.sources.vaastav",
    "squadopt.application.league_tree_identity -> squadopt.data._long_paths",
    "squadopt.application.league_tree_identity -> squadopt.data.atomic",
    "squadopt.application.live_score -> squadopt.data.snapshots",
    "squadopt.application.live_score -> squadopt.data.sources.fpl_live",
    "squadopt.application.manager_words -> squadopt.data._long_paths",
    "squadopt.application.manager_words -> squadopt.data.snapshots",
    "squadopt.application.manager_words -> squadopt.data.sources.club_news",
    "squadopt.application.manager_words -> squadopt.data.sources.club_news_capture",
    "squadopt.application.manager_words -> squadopt.data.sources.club_news_coding",
    "squadopt.application.manager_words -> squadopt.data.sources.club_news_metadata",
    "squadopt.application.manager_words -> squadopt.data.sources.club_news_scope",
    "squadopt.application.manager_words -> squadopt.data.sources.fpl_live",
    "squadopt.application.player_catalog -> squadopt.data.snapshots",
    "squadopt.application.player_catalog -> squadopt.data.sources.fpl_live",
    "squadopt.application.player_evidence -> squadopt.data.atomic",
    "squadopt.application.player_evidence -> squadopt.data.checksums",
    "squadopt.application.player_evidence -> squadopt.data.snapshots",
    "squadopt.application.player_evidence -> squadopt.data.tables",
    "squadopt.application.projection_csv -> squadopt.data.loaders",
    "squadopt.application.projection_handoff -> squadopt.data.snapshots",
    "squadopt.application.projection_handoff -> squadopt.data.sources",
    "squadopt.application.projection_handoff -> squadopt.data.sources.fpl_live",
    "squadopt.application.projection_handoff -> squadopt.data.sources.vaastav",
    "squadopt.application.rotation_export -> squadopt.data._long_paths",
    "squadopt.application.rotation_export -> squadopt.data.atomic",
    "squadopt.application.rotation_export -> squadopt.data.snapshots",
    "squadopt.application.rotation_export -> squadopt.data.sources.club_news",
    "squadopt.application.rotation_export -> squadopt.data.sources.club_news_capture",
    "squadopt.application.rotation_export -> squadopt.data.sources.club_news_claims",
    "squadopt.application.rotation_export -> squadopt.data.sources.club_news_coding",
    "squadopt.application.rotation_export -> squadopt.data.tables",
    "squadopt.application.scoreboard -> squadopt.data._long_paths",
    "squadopt.application.scoreboard -> squadopt.data.snapshots",
    "squadopt.application.scoreboard -> squadopt.data.sources",
    "squadopt.application.scoreboard -> squadopt.data.sources.fpl_live",
    "squadopt.application.scoreboard_baselines -> squadopt.data.snapshots",
    "squadopt.application.scoreboard_baselines -> squadopt.data.sources.fpl_live",
    "squadopt.application.season -> squadopt.data.snapshots",
    "squadopt.application.season -> squadopt.data.sources",
    "squadopt.application.season -> squadopt.data.sources.vaastav",
    "squadopt.application.settled_outcomes -> squadopt.data.atomic",
    "squadopt.application.settled_outcomes -> squadopt.data.checksums",
    "squadopt.application.settled_outcomes -> squadopt.data.snapshots",
    "squadopt.application.settled_outcomes -> squadopt.data.sources",
    "squadopt.application.settled_outcomes -> squadopt.data.sources.fpl_live",
    "squadopt.application.settled_outcomes -> squadopt.data.tables",
    "squadopt.application.settled_publication -> squadopt.data.atomic",
    "squadopt.application.settled_publication -> squadopt.data.snapshots",
    "squadopt.application.settled_publication -> squadopt.data.sources",
    "squadopt.application.settled_publication -> squadopt.data.sources.fpl_live",
    "squadopt.application.site -> squadopt.data.atomic",
    "squadopt.application.site -> squadopt.data.snapshots",
    "squadopt.application.site_publication -> squadopt.data.snapshots",
    "squadopt.application.site_publication -> squadopt.data.sources",
    "squadopt.application.weekly_plan -> squadopt.data.snapshots",
    "squadopt.application.weekly_plan -> squadopt.data.sources",
    "squadopt.application.weekly_plan -> squadopt.data.sources.fpl_live",
    "squadopt.application.weekly_suggestion_eval -> squadopt.data.snapshots",
    "squadopt.application.weekly_suggestion_eval -> squadopt.data.sources.fpl_live",
    "squadopt.live.banking -> squadopt.data.sources.fpl_live",
    "squadopt.live.calibration -> squadopt.data.snapshots",
    "squadopt.live.free_hit -> squadopt.data.sources.fpl_live",
    "squadopt.live.horizon -> squadopt.data.snapshots",
    "squadopt.live.horizon -> squadopt.data.sources.fpl_live",
    "squadopt.live.ledger -> squadopt.data._long_paths",
    "squadopt.live.ledger -> squadopt.data.atomic",
    "squadopt.live.ledger -> squadopt.data.snapshots",
    "squadopt.live.ledger -> squadopt.data.sources.fpl_live",
    "squadopt.live.purchase_prices -> squadopt.data.sources.fpl_live",
    "squadopt.live.recommendation -> squadopt.data.snapshots",
    "squadopt.live.recommendation -> squadopt.data.sources.fpl_information",
    "squadopt.live.recommendation -> squadopt.data.sources.fpl_live",
    "squadopt.live.rules -> squadopt.data.snapshots",
    "squadopt.live.rules -> squadopt.data.sources.fpl_live",
    "squadopt.live.tick -> squadopt.data.snapshots",
    "squadopt.live.tick -> squadopt.data.sources.fpl_live",
    "squadopt.features.evidence -> squadopt.data.snapshots",
    "squadopt.features.evidence -> squadopt.data.sources.fpl_live",
    "squadopt.features.football_phase_inputs -> squadopt.data.snapshots",
    "squadopt.features.football_phase_inputs -> squadopt.data.sources.fpl_live",
    "squadopt.features.football_phase_inputs -> squadopt.data.sources.fpl_set_pieces",
    "squadopt.features.rotation_evidence -> squadopt.data.snapshots",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.club_news",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.club_news_claims",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.club_news_coding",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.club_news_metadata",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.club_news_scope",
    "squadopt.features.rotation_evidence -> squadopt.data.sources.fpl_live",
    "squadopt.features.rotation_evidence_artifact -> squadopt.data._long_paths",
    "squadopt.features.rotation_evidence_artifact -> squadopt.data.sources.club_news",
    "squadopt.features.rotation_evidence_artifact -> squadopt.data.sources.club_news_metadata",
    "squadopt.features.rotation_evidence_artifact -> squadopt.data.sources.club_news_scope",
)

#: Every direct import from a source to a storage or source module of `data` on 2026-10-13,
#: with its remedy and phase: 122 edges from 43 modules (`application` 89 from 30, `live` 17
#: from 9, `features` 16 from 4). **It may only shrink.** If this test fails because an import
#: is new, remove the import; do not add it here.
BASELINE: dict[str, str] = {
    **dict.fromkeys(STORAGE_PORT_EDGES, STORAGE_PORTS),
    "squadopt.application.advice_record -> squadopt.data.source_revision": SOURCE_REVISION,
}

#: The size of `BASELINE` by source package. Lower a count when an entry leaves; raising one
#: is the growth the ratchet refuses, so it cannot happen by adding an entry to both lists.
BASELINE_SIZE = {"application": 89, "live": 17, "features": 16}


def _contract(name: str) -> dict[str, Any]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    (contract,) = [
        contract
        for contract in document["tool"]["importlinter"]["contracts"]
        if contract["name"] == name
    ]
    found: dict[str, Any] = contract
    return found


def _is_module(name: str) -> bool:
    location = SOURCE_ROOT / Path(*name.split("."))
    return location.with_suffix(".py").is_file() or (location / "__init__.py").is_file()


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(SOURCE_ROOT).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imported(text: str, importer: str, *, package: bool) -> set[str]:
    """Every module that `text`, the source of module `importer`, imports directly.

    `import a.b` names `a.b`. `from a import b` names `a.b` when that is a module and `a`
    otherwise, which is how import-linter's graph records it. A relative import starts from
    the importer's package, which is the importer itself when it is a package's `__init__`.
    """

    parts = importer.split(".") if package else importer.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                start = parts[: len(parts) - node.level + 1]
                base = ".".join([*start, *([node.module] if node.module else [])])
            else:
                base = node.module or ""
            for alias in node.names:
                submodule = f"{base}.{alias.name}"
                found.add(submodule if _is_module(submodule) else base)
    return found


def _within(name: str, modules: list[str]) -> bool:
    return any(name == module or name.startswith(f"{module}.") for module in modules)


def _storage_edges() -> set[str]:
    """Every direct import edge from a source of the contract to one of its forbidden modules."""

    contract = _contract(RATCHET_CONTRACT)
    forbidden: list[str] = contract["forbidden_modules"]
    edges: set[str] = set()
    for source in contract["source_modules"]:
        for path in sorted((SOURCE_ROOT / Path(*source.split("."))).rglob("*.py")):
            importer = _module_name(path)
            text = path.read_text(encoding="utf-8")
            imported = _imported(text, importer, package=path.name == "__init__.py")
            edges.update(f"{importer} -> {name}" for name in imported if _within(name, forbidden))
    return edges


def test_the_contract_names_the_three_sources_and_the_storage_half_of_data() -> None:
    contract = _contract(RATCHET_CONTRACT)

    assert contract["type"] == "forbidden"
    assert tuple(contract["source_modules"]) == SOURCES
    assert contract["forbidden_modules"] == _contract(CORE_CONTRACT)["forbidden_modules"]
    assert contract["allow_indirect_imports"] is True


def test_the_contract_ignores_exactly_the_frozen_baseline() -> None:
    entries: list[str] = _contract(RATCHET_CONTRACT)["ignore_imports"]

    assert len(entries) == len(set(entries)), "an ignore_imports entry is listed twice"
    assert sorted(set(entries) - set(BASELINE)) == [], (
        "the storage baseline may only shrink: remove the import instead of ignoring it"
    )
    assert sorted(set(BASELINE) - set(entries)) == [], (
        "an entry left the contract: delete it from BASELINE as well"
    )


def test_every_entry_is_a_direct_import_from_a_source_to_a_storage_module() -> None:
    forbidden: list[str] = _contract(RATCHET_CONTRACT)["forbidden_modules"]
    malformed = []
    for entry in BASELINE:
        importer, imported = entry.split(" -> ")
        if not (_within(importer, list(SOURCES)) and _within(imported, forbidden)):
            malformed.append(entry)

    assert malformed == []
    assert len(STORAGE_PORT_EDGES) == len(set(STORAGE_PORT_EDGES)), "an edge is listed twice"
    assert set(BASELINE.values()) == {STORAGE_PORTS, SOURCE_REVISION}


def test_the_baseline_keeps_its_size() -> None:
    assert Counter(entry.split(".")[1] for entry in BASELINE) == BASELINE_SIZE, (
        "the storage baseline only shrinks: when an entry leaves, lower its package's count"
    )


def test_the_sources_import_the_storage_half_exactly_where_the_baseline_says() -> None:
    edges = _storage_edges()

    assert sorted(edges - set(BASELINE)) == [], (
        "a new storage import: the baseline does not grow, so the module gets what it needs "
        "from its caller instead"
    )
    assert sorted(set(BASELINE) - edges) == [], (
        "this import is gone: delete the entry from BASELINE and from ignore_imports"
    )


def test_the_scan_resolves_each_import_form_as_the_graph_does() -> None:
    text = "\n".join(
        [
            "import squadopt.data.snapshots",
            "from squadopt.data.sources import fpl_live, FPL_LIVE_SOURCE",
            "from squadopt.data.atomic import replace_retrying",
            "def late():",
            "    from ..data import _long_paths",
            "    from .season import run",
        ]
    )

    assert _imported(text, "squadopt.application.advice", package=False) == {
        "squadopt.data.snapshots",
        "squadopt.data.sources.fpl_live",
        "squadopt.data.sources",
        "squadopt.data.atomic",
        "squadopt.data._long_paths",
        "squadopt.application.season",
    }
