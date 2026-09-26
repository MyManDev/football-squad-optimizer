"""The price honesty row in the index gives each week the reason its protocol gives.

The first ``live_price_honesty`` row said the Top 100 and manager's word documents "of those two
weeks were published but not recorded". That was true of GW5 only. GW4 had neither setting: the
manager's word merged in #581 and the Top 100 setting in #594, both after the GW4 deadline, the
GW4 view (#499) published neither, and every GW4 record was written at a commit that holds
neither. The protocol's own table (``docs/live_price_honesty_prereg.md``, "What is on disk")
says "recorded only since #645" in the GW5 row and nowhere else.

So the check below takes both facts from committed files rather than from memory: which weeks
the record read (``docs/live_price_honesty.json``) and which of those the protocol calls
recorded late, with the pull request it names. Every sentence of the index row that cites that
pull request has to name its weeks, and name only weeks the protocol gives that reason to; every
week the protocol gives it to has to be named in one. A collective "those two weeks" names no
week, so it fails.
"""

import json
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPOSITORY_ROOT / "docs"
INDEX = DOCS / "measurements_index.md"
PREREG = DOCS / "live_price_honesty_prereg.md"
RECORD = DOCS / "live_price_honesty.json"

RECORDED_LATE = re.compile(r"recorded only since (#\d+)")
WEEK = re.compile(r"\bGW(\d+)\b")


def _row_of(stem: str) -> str:
    rows = [
        line
        for line in INDEX.read_text(encoding="utf-8").splitlines()
        if line.startswith(f"| `{stem}`")
    ]
    assert len(rows) == 1, f"expected one index row for `{stem}`, found {len(rows)}"
    return " ".join(rows[0].split())


def _sentences(text: str) -> list[str]:
    """Split prose at a full stop followed by a capital or a bold marker.

    Decimals (``+0.918``) carry no space after the stop, so they stay whole.
    """

    return re.split(r"(?<=\.)\s+(?=[A-Z*])", text)


def _documents_on_disk_by_gameweek() -> dict[int, str]:
    """The protocol's "What is on disk" table: gameweek to its documents cell.

    Rows whose first cell is not a single gameweek ("6 onwards") are left out; they describe
    records the price honesty table has not read yet.
    """

    text = PREREG.read_text(encoding="utf-8")
    assert "## What is on disk" in text, "The table this check reads has left the protocol."
    section = text.split("## What is on disk", 1)[1].split("\n## ", 1)[0]
    documents: dict[int, str] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0].isdigit():
            documents[int(cells[0])] = cells[2]
    return documents


def _weeks_recorded_late() -> tuple[set[int], set[str]]:
    """Weeks the record read whose documents the protocol says were recorded late, and the PRs
    it names as the point the record starts holding them."""

    read = json.loads(RECORD.read_text(encoding="utf-8"))["reading"]["pooled"]["gameweeks"]
    documents = _documents_on_disk_by_gameweek()
    weeks: set[int] = set()
    pulls: set[str] = set()
    for gameweek in read:
        match = RECORDED_LATE.search(documents.get(int(gameweek), ""))
        if match:
            weeks.add(int(gameweek))
            pulls.add(match.group(1))
    return weeks, pulls


def test_the_protocol_table_this_check_reads_is_still_there() -> None:
    """If the table moved, the check below would compare the row against nothing."""

    documents = _documents_on_disk_by_gameweek()
    late, pulls = _weeks_recorded_late()

    assert {4, 5} <= set(documents)
    assert late == {5}
    assert pulls == {"#645"}


def test_the_row_names_the_weeks_it_says_were_recorded_late() -> None:
    """A week is only "published but not recorded" if its protocol row says so."""

    late, pulls = _weeks_recorded_late()
    row = _row_of("live_price_honesty")
    citing = [
        sentence
        for sentence in _sentences(row)
        if any(re.search(rf"{re.escape(pull)}\b", sentence) for pull in pulls)
    ]

    assert citing, (
        f"The row never cites {sorted(pulls)!r}, so it does not say why weeks {sorted(late)!r} "
        "have no Top 100 or manager's word pairs."
    )
    named_anywhere: set[int] = set()
    for sentence in citing:
        named = {int(week) for week in WEEK.findall(sentence)}
        assert named, (
            f"This sentence says documents were recorded late without naming a week: {sentence!r}"
        )
        assert named <= late, (
            f"This sentence gives weeks {sorted(named - late)!r} a reason the protocol gives only "
            f"to {sorted(late)!r}: {sentence!r}"
        )
        named_anywhere |= named
    assert late <= named_anywhere, (
        f"The protocol says weeks {sorted(late - named_anywhere)!r} were recorded late and the "
        "row does not say so."
    )
