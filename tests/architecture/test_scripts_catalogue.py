"""Every file under `scripts/` has exactly one row in the script catalogue, and every row a file.

`scripts/README.md` says so in its first paragraph, and nothing held it: until the catalogue was
completed on 2026-10-13 (#1081), 52 of the 139 files under `scripts/` had no row, among them
operator commands such as `build_football_forecast.py` and `check_league_tree.py`, the whole
release recipe and three of the four Windows backend scripts. A missing row is found by the
reader who needed it. This test is the check, so a pull request that adds, removes or renames a
script edits its row in the same change.

A row is a line of a Markdown table whose first cell is one backticked name, the file's path
relative to `scripts/` (`build_site.py`, `release/deploy.sh`). The rows are read section by
section, by the `##` heading above them:

- outside the retired sections, each file has exactly one row and each row names a file that
  is there;
- the two retired sections, "Retired compatibility commands" and "Retired runners", name files
  that were removed on purpose, so a row there must name a file that is **not** there: a
  retired name that comes back is a live script again and belongs in a live section.

The files are what git lists under `scripts/` (tracked, or untracked and not ignored) and that
exist on disk, apart from the catalogue itself and anything under `__pycache__`. Through git, a
file written but not yet added counts while a pull request is being prepared, and an ignored
file on one machine does not.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from pathlib import Path

from tests.architecture.test_markdown_links import _lines_outside_fences

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPOSITORY_ROOT / "scripts"
CATALOGUE = SCRIPTS / "README.md"

#: The sections that list removed files, by their heading.
RETIRED_SECTIONS = ("Retired compatibility commands", "Retired runners")

#: The sections that list the files that are there, by their heading. A new section is added
#: here with its heading, so a renamed heading cannot silently drop its rows from the check.
LIVE_SECTIONS = (
    "Operational commands",
    "Release recipe",
    "Windows backend and data backup",
    "Measurement runners",
    "Artifact-only runners",
    "Fixture and code generators",
    "Imported helpers",
)

#: A table row whose first cell is one backticked name.
ROW = re.compile(r"^\| `([^`]+)` \|")

#: A second-level heading.
SECTION = re.compile(r"^## (.+?)\s*$")


def _script_files() -> list[str]:
    """Every file under `scripts/` but the catalogue, as a path relative to `scripts/`."""

    listing = subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-C",
            str(REPOSITORY_ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "scripts",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    files: set[str] = set()
    for path in listing.split("\0"):
        if not path or "__pycache__" in path.split("/"):
            continue
        if not (REPOSITORY_ROOT / path).is_file():
            continue  # Deleted from the working tree but still in the index.
        relative = path.removeprefix("scripts/")
        if relative != "README.md":
            files.add(relative)
    return sorted(files)


def _rows(text: str) -> list[tuple[str, str]]:
    """Every catalogue row, as the heading of its section and the name in its first cell."""

    rows: list[tuple[str, str]] = []
    section = ""
    for _, line in _lines_outside_fences(text):
        heading = SECTION.match(line)
        if heading:
            section = heading.group(1)
            continue
        row = ROW.match(line)
        if row:
            rows.append((section, row.group(1)))
    return rows


def _catalogue_rows() -> list[tuple[str, str]]:
    return _rows(CATALOGUE.read_text(encoding="utf-8"))


def test_the_catalogue_has_the_sections_this_file_reads() -> None:
    """A parser that read no rows, or a renamed heading, would pass the checks below emptily."""

    rows = _catalogue_rows()
    sections = {section for section, _ in rows}

    assert sections == set(LIVE_SECTIONS) | set(RETIRED_SECTIONS), sorted(sections)
    # If this ever falls near zero the pattern has stopped matching and the test is asleep.
    assert len(rows) >= 150, f"expected the catalogue to hold its rows; found {len(rows)}"


def test_every_file_under_scripts_has_exactly_one_row() -> None:
    named = Counter(name for section, name in _catalogue_rows() if section in LIVE_SECTIONS)
    files = _script_files()

    missing = [path for path in files if path not in named]
    repeated = sorted(name for name, count in named.items() if count > 1)
    assert not missing, "\n".join(
        [
            "A file under scripts/ has no row in scripts/README.md. Add one to the section of",
            "its class, keyed by its path relative to scripts/:",
            *missing,
        ]
    )
    assert not repeated, "\n".join(
        ["A file has more than one row in scripts/README.md; keep one:", *repeated]
    )


def test_every_row_names_a_file_that_is_there() -> None:
    files = set(_script_files())

    ghosts = [
        f"{section}: {name}"
        for section, name in _catalogue_rows()
        if section in LIVE_SECTIONS and name not in files
    ]
    assert not ghosts, "\n".join(
        [
            "A row of scripts/README.md names no file under scripts/. Remove the row, or move",
            "it to a retired section with how to recover the file:",
            *ghosts,
        ]
    )


def test_a_retired_row_names_a_file_that_is_gone() -> None:
    files = set(_script_files())

    back = [
        f"{section}: {name}"
        for section, name in _catalogue_rows()
        if section in RETIRED_SECTIONS and name in files
    ]
    assert not back, "\n".join(
        [
            "A retired row names a file that is under scripts/ again. Move its row to the live",
            "section of its class:",
            *back,
        ]
    )


def test_rows_are_read_by_section_outside_code() -> None:
    """The reading rule is exercised on a synthetic catalogue, so a drift in it is seen here."""

    catalogue = "\n".join(
        [
            "| Role | What it means |",
            "| --- | --- |",
            "| operational | not a row: its first cell is not backticked |",
            "## Operational commands",
            "| Script | Class |",
            "| --- | --- |",
            "| `build_site.py` | shim |",
            "```text",
            "| `inside_a_fence.py` | not a row |",
            "```",
            "## Release recipe",
            "| `release/deploy.sh` | release recipe |",
            "## Retired runners",
            "| `run_planner_doe.py` | acfcb0fa9 |",
        ]
    )

    assert _rows(catalogue) == [
        ("Operational commands", "build_site.py"),
        ("Release recipe", "release/deploy.sh"),
        ("Retired runners", "run_planner_doe.py"),
    ]
