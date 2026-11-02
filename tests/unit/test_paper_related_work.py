"""Every quote in `docs/paper/related_work.md` is verbatim on the line it names.

Issue #1152 allows a model to extract, not to write: the related-work table is made of
fragments of committed documents, each cell `[Ln] "fragment"` (more fragments of the same line
follow as `"fragment"`). A `Source:` line names the document the tables below it quote. This
file reads every fragment and finds it on its line of that document as checked out (CRLF read
as LF), so a fragment that was paraphrased, cut from the wrong line or left behind by an edit
of its source fails here, naming itself. The review's reference list is held to the table as
well: each `E<n>` reference has one row, and each row a reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TABLE = REPOSITORY_ROOT / "docs" / "paper" / "related_work.md"
REVIEW = "docs/research/literature_forecast_accuracy_2026_10.md"
NOT_STATED = "not stated in the document"

SOURCE = re.compile(r"^Source: `(docs/[^`]+\.md)`")
TOKEN = re.compile(r'\[L(\d+)\]|"([^"]*)"')
SEPARATOR = re.compile(r"^\|( --- \|)+$")


@dataclass(frozen=True)
class Fragment:
    row: str
    source: str
    line: int
    text: str


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split(" | ")]


def fragments(text: str) -> tuple[list[Fragment], list[str]]:
    """Every quoted fragment of the table rows, and every malformed cell found on the way."""

    found: list[Fragment] = []
    problems: list[str] = []
    source = ""
    header = True
    for number, line in enumerate(text.splitlines(), start=1):
        match = SOURCE.match(line)
        if match:
            source = match.group(1)
            continue
        if not line.startswith("| "):
            header = True
            continue
        if SEPARATOR.match(line):
            header = False
            continue
        if header:
            continue
        if not source:
            problems.append(f"line {number}: a table row before any Source line")
            continue
        cells = _cells(line)
        row = cells[0]
        for cell in cells[1:]:
            current: int | None = None
            quotes = 0
            for token in TOKEN.finditer(cell):
                if token.group(1) is not None:
                    current = int(token.group(1))
                    continue
                quotes += 1
                if current is None:
                    problems.append(f"line {number}, {row}: a fragment without [Ln]: {cell}")
                    continue
                found.append(Fragment(row, source, current, token.group(2)))
            if quotes == 0 and cell not in {"", NOT_STATED} and "[L" in cell:
                problems.append(f"line {number}, {row}: a line number without a fragment")
            if cell.count('"') != 2 * quotes:
                problems.append(f"line {number}, {row}: an unpaired quote mark in {cell}")
    return found, problems


def unverified(text: str, root: Path) -> list[str]:
    """The fragments that are not on their line of their source, and the malformed cells."""

    found, problems = fragments(text)
    lines: dict[str, list[str]] = {}
    for fragment in found:
        if fragment.source not in lines:
            raw = (root / fragment.source).read_bytes().replace(b"\r\n", b"\n")
            lines[fragment.source] = raw.decode("utf-8").split("\n")
        source_lines = lines[fragment.source]
        if not 1 <= fragment.line <= len(source_lines):
            problems.append(f"{fragment.row}: {fragment.source} has no line {fragment.line}")
        elif fragment.text not in source_lines[fragment.line - 1]:
            problems.append(
                f"{fragment.row}: {fragment.text!r} is not on line {fragment.line} of "
                f"{fragment.source}"
            )
    return problems


def test_every_quote_is_verbatim_on_the_line_it_names() -> None:
    text = TABLE.read_text(encoding="utf-8")

    found, _ = fragments(text)
    assert unverified(text, REPOSITORY_ROOT) == []
    # If this falls near zero the parser has stopped reading the rows and the test is asleep.
    assert len(found) >= 200
    assert {fragment.source for fragment in found} >= {REVIEW}


def test_a_changed_or_moved_quote_is_reported() -> None:
    text = TABLE.read_text(encoding="utf-8")
    found, _ = fragments(text)
    first = found[0]
    quoted = f'[L{first.line}] "{first.text}"'
    assert quoted in text

    paraphrased = text.replace(quoted, f'[L{first.line}] "{first.text} (paraphrased)"', 1)
    moved = text.replace(quoted, f'[L{first.line + 1}] "{first.text}"', 1)
    unnumbered = text.replace(quoted, f'"{first.text}"', 1)

    assert len(unverified(paraphrased, REPOSITORY_ROOT)) == 1
    assert len(unverified(moved, REPOSITORY_ROOT)) == 1
    assert any("without [Ln]" in problem for problem in unverified(unnumbered, REPOSITORY_ROOT))


def test_every_reference_of_the_review_has_one_row() -> None:
    review = (REPOSITORY_ROOT / REVIEW).read_text(encoding="utf-8")
    references = re.findall(r"^- \*\*(E\d+)\.\*\*", review, re.MULTILINE)
    found, _ = fragments(TABLE.read_text(encoding="utf-8"))

    rows = {fragment.row for fragment in found if fragment.source == REVIEW}
    assert len(references) == len(set(references))
    assert rows == set(references)
