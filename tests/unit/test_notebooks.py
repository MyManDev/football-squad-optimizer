"""Structural checks on committed notebooks.

Notebooks cannot be unit tested meaningfully, but they can be stopped from rotting
in two specific ways: becoming unparseable, and carrying stale committed outputs
that a reader mistakes for current results.
"""

import json
from pathlib import Path

import pytest

NOTEBOOK_DIR = Path(__file__).resolve().parents[2] / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))


def test_notebook_directory_exists() -> None:
    assert NOTEBOOK_DIR.is_dir()


def test_at_least_one_notebook_is_committed() -> None:
    assert NOTEBOOKS


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda path: path.name)
def test_notebook_is_valid_json_with_the_expected_structure(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["nbformat"] == 4
    assert isinstance(document["cells"], list)
    assert document["cells"], "notebook has no cells"
    for cell in document["cells"]:
        assert cell["cell_type"] in {"code", "markdown"}
        # nbformat allows source as a string or a list of strings; both are valid,
        # and different editors write different ones.
        assert isinstance(cell["source"], str | list)
        assert cell["source"], "notebook has an empty cell"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda path: path.name)
def test_notebook_carries_no_committed_outputs(path: Path) -> None:
    """Stale outputs read as current results and bloat every diff."""

    document = json.loads(path.read_text(encoding="utf-8"))
    offenders = [
        index
        for index, cell in enumerate(document["cells"])
        if cell["cell_type"] == "code" and (cell.get("outputs") or cell.get("execution_count"))
    ]

    assert not offenders, f"clear outputs before committing; cells {offenders} still carry them"


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda path: path.name)
def test_notebook_cell_identifiers_are_unique(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    identifiers = [cell["id"] for cell in document["cells"]]

    assert len(identifiers) == len(set(identifiers))
