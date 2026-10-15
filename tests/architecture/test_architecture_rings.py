"""The ring of every package is stated once, here, and every other statement of it agrees.

ADR 0010 reads the packages under `src/squadopt` as five clean-architecture rings, R1
(vocabulary) to R5 (composition), with the measurement laboratory as a research side tree. The
rings are written in five places: the `RINGS` mapping below, the package table of
`ARCHITECTURE.md`, the package map `src/squadopt/README.md`, the layer order and the contracts
in `pyproject.toml`, and the `LABORATORY` list of `tests/architecture/test_run_boundary.py`. A
ring written in prose drifts from the code the first time a package is added or moved, so this
file holds the five to one another:

- the mapping names exactly the entries under `src/squadopt` (the packages and the one
  top-level module, `integration.py`), and exactly the packages of the exhaustive layers list;
- read from the bottom, the layer order reaches each product package only after every package
  of an inner ring, with no exception, and reaches the research arm only after every R2
  package;
- the research ring is the forbidden list of "Product does not import the laboratory", every
  other package is a source of that contract, and the research ring is also the `LABORATORY`
  list the run-boundary probe reads;
- the package table of `ARCHITECTURE.md` matches the mapping row for row, and every contract in
  `pyproject.toml` has a row in its enforcement map and is named in the verification section of
  `docs/architecture/dependency_rules.md`;
- the package map's table matches the mapping row for row, gives each package its position in
  the layers list, and names, by the keys of its contract table, exactly the contracts that hold
  the package as a source (a layers contract holds the packages under its containers: the
  top-level one every package, the platform units one only `platform`).

A package that spans two rings, such as `data` (vocabulary and storage), is written with both
rings, innermost first, exactly as the table writes it, and is placed by its innermost ring.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from tests.architecture.test_run_boundary import LABORATORY

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPOSITORY_ROOT / "src" / "squadopt"
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
ARCHITECTURE = REPOSITORY_ROOT / "ARCHITECTURE.md"
DEPENDENCY_RULES = REPOSITORY_ROOT / "docs" / "architecture" / "dependency_rules.md"
PACKAGE_MAP = PACKAGE / "README.md"

RESEARCH = "Research"

#: The ring of every entry under `src/squadopt`, written as the package table of
#: ARCHITECTURE.md writes it.
RINGS: dict[str, str] = {
    "contracts": "R1",
    "data": "R1, R4",
    "features": "R2",
    "prediction": "R2",
    "optimization": "R2",
    "evaluation": "R2",
    "scenarios": "R2",
    "planning": "R2",
    "live": "R2",
    "integration": "R3",
    "application": "R3",
    "api": "R4, R5",
    "platform": "R4, R5",
    "experiments": RESEARCH,
    "backtest": RESEARCH,
    "bayesopt": RESEARCH,
    "recalibration": RESEARCH,
    "preflight": RESEARCH,
}

LAYERS_CONTRACT = "Layered architecture"
LABORATORY_CONTRACT = "Product does not import the laboratory"


def _contracts() -> list[dict[str, Any]]:
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    contracts: list[dict[str, Any]] = document["tool"]["importlinter"]["contracts"]
    return contracts


def _contract(name: str) -> dict[str, Any]:
    (contract,) = [contract for contract in _contracts() if contract["name"] == name]
    return contract


def _layers() -> list[str]:
    """The layers list, highest first, as import-linter reads it."""

    contract = _contract(LAYERS_CONTRACT)
    assert contract["containers"] == ["squadopt"]
    assert contract["exhaustive"] is True
    layers: list[str] = contract["layers"]
    return layers


def _covers(container: str, package: str) -> bool:
    """Whether a layers contract with this container holds `package`."""

    return container in ("squadopt", f"squadopt.{package}") or container.startswith(
        f"squadopt.{package}."
    )


def _depth(ring: str) -> int:
    """The innermost ring of a cell such as "R1, R4", as a number."""

    return min(int(part.strip().removeprefix("R")) for part in ring.split(","))


def _table(text: str, header: str) -> list[list[str]]:
    """The body rows of the Markdown table that starts with `header`, as stripped cells."""

    lines = text.splitlines()
    start = lines.index(header)
    rows: list[list[str]] = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _unquoted(cell: str) -> str:
    match = re.fullmatch(r"`([^`]+)`", cell)
    assert match, f"expected a backticked name, found {cell!r}"
    return match.group(1)


def test_the_mapping_names_every_entry_under_the_package_and_every_layer() -> None:
    packages = {
        entry.name
        for entry in PACKAGE.iterdir()
        if entry.is_dir() and (entry / "__init__.py").is_file()
    }
    modules = {entry.stem for entry in PACKAGE.glob("*.py") if entry.name != "__init__.py"}

    assert set(RINGS) == packages | modules
    assert set(RINGS) == set(_layers())
    assert len(_layers()) == len(set(_layers()))


def test_the_layer_order_reads_the_rings_from_the_inside_out() -> None:
    innermost_first = list(reversed(_layers()))
    product = [name for name in innermost_first if RINGS[name] != RESEARCH]

    depths = [_depth(RINGS[name]) for name in product]
    assert depths == sorted(depths), list(zip(product, depths, strict=True))

    research = [innermost_first.index(name) for name in RINGS if RINGS[name] == RESEARCH]
    domain = [innermost_first.index(name) for name in RINGS if RINGS[name] == "R2"]
    assert min(research) > max(domain), "the research arm sits above every R2 package"


def test_the_research_ring_is_the_laboratory_every_check_forbids() -> None:
    research = {name for name, ring in RINGS.items() if ring == RESEARCH}
    contract = _contract(LABORATORY_CONTRACT)

    assert {module.removeprefix("squadopt.") for module in contract["forbidden_modules"]} == (
        research
    )
    assert {module.removeprefix("squadopt.") for module in contract["source_modules"]} == (
        set(RINGS) - research
    )
    assert set(LABORATORY) == research


def test_the_package_table_in_the_architecture_overview_matches_the_mapping() -> None:
    rows = _table(ARCHITECTURE.read_text(encoding="utf-8"), "| Package | Ring | Role |")

    assert {_unquoted(row[0]): row[1] for row in rows} == RINGS
    assert len(rows) == len(RINGS), "a package has two rows"


def test_every_contract_is_in_the_enforcement_map_and_the_dependency_rules() -> None:
    names = [contract["name"] for contract in _contracts()]
    mapped = [
        row[0]
        for row in _table(ARCHITECTURE.read_text(encoding="utf-8"), "| Contract | What it holds |")
    ]
    rules = DEPENDENCY_RULES.read_text(encoding="utf-8")
    verification = rules[rules.index("\n## Verification\n") :].split("\n## ", 2)[1]

    assert sorted(mapped) == sorted(names)
    assert [name for name in names if f"`{name}`" not in verification] == []


def test_the_package_map_places_every_package_by_ring_layer_and_contract() -> None:
    text = PACKAGE_MAP.read_text(encoding="utf-8")
    keys = {key: name for key, name in _table(text, "| Key | Contract |")}
    contracts = _contracts()
    assert list(keys.values()) == [contract["name"] for contract in contracts]

    layers = _layers()
    expected = {
        name: (
            RINGS[name],
            str(layers.index(name) + 1),
            {
                contract["name"]
                for contract in contracts
                if (
                    contract["type"] == "layers"
                    and any(_covers(container, name) for container in contract["containers"])
                )
                or f"squadopt.{name}" in contract.get("source_modules", [])
            },
        )
        for name in RINGS
    }
    rows = _table(text, "| Package | Ring | Layer | Owner | Checked by | Known violation |")
    found = {
        _unquoted(row[0]): (row[1], row[2], {keys[key.strip()] for key in row[4].split(",")})
        for row in rows
    }

    assert found == expected
    assert len(rows) == len(RINGS), "a package has two rows"
