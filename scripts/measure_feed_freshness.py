"""Measure how old the feed's own notes are at each stored capture.

    python -m scripts.measure_feed_freshness

`docs/weekly_runbook.md` warns against reading the feed's `news` as cover for capturing
early, and it cited a brief for the reason: on 2026-09-07 the notes were a median of 22.9
days older than the capture, and 3 of 71 had been added since the previous deadline. That
capture was lost on 10 September, so this does not reproduce the figure; it measures the
same two things on every live capture the store holds (#1109).

For each capture it reports:

- **the age of each current note**, the hours from its ``news_added`` stamp to the capture,
  as a median and quartiles in days;
- **how many notes were stamped since the previous deadline**, the latest deadline the
  capture's own payload published before it was taken.

What counts as a note is declared, not inferred. A note is a squad-eligible player whose
``news`` is not empty and whose ``news_added`` is stamped. Three other states are counted
apart and never enter an age:

- a player with no note at all: never flagged, so he has no age, and counting him as zero
  would make the feed look fresher than it is;
- a cleared flag, an empty ``news`` with the stamp still on it: the note it dated is gone;
- a note with no stamp, or a stamp after the capture: no age can be read from it.

A capture taken before the season's first deadline has no previous deadline, so its
since-deadline count is **not measured**, never zero.

Only stored captures are read, through the same reader as
``scripts.measure_capture_lead_time``: nothing is fetched, and the notes' words are not
written anywhere. The quartiles are NumPy's linear interpolation, declared in the record.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
from scripts._experiment_cli import repository_provenance, write_json, write_text
from scripts.measure_capture_lead_time import _captures

from squadopt.data.errors import DataSourceError
from squadopt.data.sources.fpl_live import gameweek_deadlines, news_snapshot
from squadopt.data.timestamps import as_instant

FEED_FRESHNESS_CONTRACT_VERSION: Final = "feed_freshness_v1"
QUANTILE_METHOD: Final = "linear"
NOTE_RULE: Final = "nonempty_news_with_news_added_v1"

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_RECORD: Final = Path("docs/feed_freshness.json")
DEFAULT_SUMMARY: Final = Path("docs/feed_freshness.md")


@dataclass(frozen=True, slots=True)
class _Ages:
    """The notes of one capture, sorted into what has an age and what does not."""

    ages_days: tuple[float, ...]
    since_previous_deadline: int | None
    players_without_note: int
    cleared_flags: int
    notes_without_stamp: int
    stamps_after_capture: int


def _previous_deadline(bootstrap: bytes, captured_at_utc: str) -> str | None:
    """The latest deadline the payload published at or before the capture, or None."""

    captured = as_instant(captured_at_utc)
    passed = [
        deadline.deadline_utc
        for deadline in gameweek_deadlines(bootstrap)
        if as_instant(deadline.deadline_utc) <= captured
    ]
    return max(passed, key=as_instant) if passed else None


def _ages(bootstrap: bytes, captured_at_utc: str, previous: str | None) -> _Ages:
    captured = as_instant(captured_at_utc)
    notes = news_snapshot(bootstrap)
    ages: list[float] = []
    since = 0
    without_note = cleared = unstamped = after = 0
    for row in notes.itertuples(index=False):
        text = str(row.news).strip()
        stamped = row.news_added_utc is not None and not _missing(row.news_added_utc)
        if not text and not stamped:
            without_note += 1
            continue
        if not text:
            cleared += 1
            continue
        if not stamped:
            unstamped += 1
            continue
        added = as_instant(str(row.news_added_utc))
        if added > captured:
            after += 1
            continue
        ages.append((captured - added).total_seconds() / 86400.0)
        if previous is not None and added > as_instant(previous):
            since += 1
    return _Ages(
        ages_days=tuple(sorted(ages)),
        since_previous_deadline=since if previous is not None else None,
        players_without_note=without_note,
        cleared_flags=cleared,
        notes_without_stamp=unstamped,
        stamps_after_capture=after,
    )


def _missing(value: object) -> bool:
    try:
        return bool(value != value)  # NaN and pandas NA compare unequal to themselves
    except TypeError:
        return True


def _quartiles(ages: tuple[float, ...]) -> dict[str, float] | None:
    if not ages:
        return None
    q1, median, q3 = np.quantile(np.asarray(ages), [0.25, 0.5, 0.75], method=QUANTILE_METHOD)
    return {
        "q1_days": round(float(q1), 2),
        "median_days": round(float(median), 2),
        "q3_days": round(float(q3), 2),
    }


def measure(snapshot_root: Path) -> dict[str, object]:
    """Report, per stored live capture, how old its notes are and how many are recent."""

    rows: list[dict[str, object]] = []
    captures = sorted(
        _captures(snapshot_root), key=lambda capture: as_instant(capture.captured_at_utc)
    )
    for capture in captures:
        previous = _previous_deadline(capture.bootstrap, capture.captured_at_utc)
        ages = _ages(capture.bootstrap, capture.captured_at_utc, previous)
        rows.append(
            {
                "snapshot_id": capture.snapshot_id,
                "captured_at_utc": capture.captured_at_utc,
                "gameweek": capture.gameweek,
                "deadline_utc": capture.deadline_utc,
                "previous_deadline_utc": previous,
                "notes": len(ages.ages_days),
                "age": _quartiles(ages.ages_days),
                "notes_since_previous_deadline": ages.since_previous_deadline,
                "notes_since_previous_deadline_unavailable_reason": (
                    "no_previous_deadline" if previous is None else None
                ),
                "players_without_note": ages.players_without_note,
                "cleared_flags": ages.cleared_flags,
                "notes_without_stamp": ages.notes_without_stamp,
                "stamps_after_capture": ages.stamps_after_capture,
            }
        )
    return {
        "artifact_type": "feed_freshness",
        "contract_version": FEED_FRESHNESS_CONTRACT_VERSION,
        "note_rule": NOTE_RULE,
        "quantile_method": QUANTILE_METHOD,
        "captures_read": len(rows),
        "captures": rows,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
        # Which code produced the record; it reads no archive, so the commit is all of it.
        **repository_provenance(),
    }


def _row(entry: dict[str, object]) -> str:
    age = entry["age"]
    if isinstance(age, dict):
        ages = f"{age['median_days']} | {age['q1_days']} | {age['q3_days']}"
    else:
        ages = "no note | no note | no note"
    since = entry["notes_since_previous_deadline"]
    since_cell = "not measured" if since is None else str(since)
    return (
        f"| {entry['snapshot_id']} | {entry['gameweek']} | {entry['notes']} | {ages} | "
        f"{since_cell} |"
    )


def summary(record: dict[str, object]) -> str:
    """Write the record as prose, saying what is measured and what is not."""

    captures = [entry for entry in list(record["captures"]) if isinstance(entry, dict)]  # type: ignore[call-overload]
    lines = [
        "# How old the feed's notes are at each capture",
        "",
        f"Contract: `{record['contract_version']}`, note rule `{record['note_rule']}`, "
        f"quartiles by NumPy's `{record['quantile_method']}` method.",
        "",
        "The weekly runbook warns against reading the feed's own notes as cover for capturing",
        "early. This measures why: for each stored live capture, how many days old its",
        "current notes were, and how many were stamped since the previous deadline.",
        "",
        "## Per capture",
        "",
        "| capture | gameweek | notes | median days | first quartile | third quartile "
        "| since previous deadline |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        *[_row(entry) for entry in captures],
        "",
        "## What counts",
        "",
        "A note is a squad-eligible player whose `news` is not empty and whose `news_added` is",
        "stamped; its age is the time from that stamp to the capture. A player never flagged",
        "has no note and no age, and is not counted as zero. A cleared flag, a note with no",
        "stamp and a stamp after the capture are counted in the JSON and enter no age. A",
        "capture taken before the season's first deadline has no previous deadline, so its",
        "count since then is **not measured**, never zero.",
        "",
        "## What this decides",
        "",
        "Nothing on its own. It is the evidence behind the feed-age sentence in",
        "`docs/weekly_runbook.md`, measured on our own captures rather than cited from a",
        "brief. The notes' words are not in this artifact; the locked holdout was not read and",
        "no gate is evaluated here.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    arguments = parser.parse_args(argv)

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1
    try:
        record = measure(arguments.snapshot_root)
    except DataSourceError as error:
        print(f"Refused: {error}")
        return 1
    if not record["captures_read"]:
        print(f"No pre-deadline live capture under {arguments.snapshot_root}.")
        return 1

    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, summary(record))
    print(f"Read {record['captures_read']} live capture(s).")
    for entry in list(record["captures"]):  # type: ignore[call-overload]
        age = entry["age"]
        median = "no note" if age is None else f"median {age['median_days']} d"
        since = entry["notes_since_previous_deadline"]
        print(
            f"  {entry['snapshot_id']}  gw{entry['gameweek']:02d}  {entry['notes']} note(s), "
            f"{median}, {'not measured' if since is None else since} since the previous deadline"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
