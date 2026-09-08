"""Measure what a later capture recovers, gameweek by gameweek.

    python -m scripts.measure_capture_lead_time

The weekly loop captures the live endpoints "before the deadline" and nothing said how
long before. In practice it has run about thirty hours ahead, and the platform keeps
editing until kick-off: an availability note added inside those thirty hours is not in
the capture the week was decided from, and no later step recovers it, because
availability is applied once from that capture.

This script measures the size of that hole rather than asserting it. For every gameweek
with two or more stored live captures it reports each capture's lead time before the
deadline the payload itself published, and counts the source's own editorial notes whose
``news_added`` instant falls in the window between the earliest and the latest capture.
Those are exactly the notes the earlier capture could not have held.

Only stored captures are read. Nothing is fetched, so the numbers are reproducible from
what is on disk.

**The split is a keyword rule, not a reading of the notes.** A note is in a bucket
because it matched the declared vocabulary below, and the counts are counts of that
match. A note matching nothing stays ``unclassified`` and is reported as its own number:
an item we could not classify is not a transfer, and folding it into either bucket would
fill that bucket with our own uncertainty. The words never enter this artifact -- the
player ids do, so a bucket can be audited against the local capture without the notes
being copied out of it.
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts._experiment_cli import write_json, write_text

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    gameweek_deadlines,
    news_snapshot,
    next_open_deadline,
)
from squadopt.data.timestamps import as_instant

CAPTURE_LEAD_TIME_CONTRACT_VERSION: Final = "capture_lead_time_v1"

#: The classifier, versioned so a count can be reproduced against the rule that produced
#: it. Bump this whenever a pattern below changes: counts are not comparable across
#: versions, and a silent edit would make a week-over-week series say something it never
#: measured.
NEWS_CLASSIFIER_VERSION: Final = "news_keywords_v1"

#: Transfer first, deliberately. A departure is the more specific claim -- a note naming
#: a move names it explicitly -- while fitness words are broad enough to turn up inside
#: one ("joined on loan, currently recovering"). Declaring the precedence is what makes
#: the split reproducible; it does not make either bucket a reading of intent.
_TRANSFER_PATTERN: Final = re.compile(
    r"\b(?:transfer\w*|join\w*|loan\w*|sign\w*|sold|departed|released|"
    r"left\s+the\s+club|moved\s+to)\b",
    re.IGNORECASE,
)

_FITNESS_OR_SUSPENSION_PATTERN: Final = re.compile(
    r"\b(?:injur\w*|knock|strain\w*|hamstring|knee|ankle|groin|calf|thigh|hip|"
    r"shoulder|foot|toe|rib|back|muscle|muscular|surgery|operation|concussion|"
    r"ill|illness|unwell|virus|sick|"
    r"suspend\w*|suspension|red\s+card|ban|banned|"
    r"doubt\w*|fitness|training|recover\w*|return\w*)\b",
    re.IGNORECASE,
)

#: The one status the source's own vocabulary settles by itself: ``s`` is suspended. It is
#: read only when the note matched nothing, and only for this value. ``u`` -- unavailable
#: -- is **not** mapped to a transfer however often it happens to be one: the payload
#: never says why a player is unavailable, and guessing there is the kind of claim this
#: repository refuses.
_SUSPENDED_STATUS: Final = "s"

BUCKETS: Final = ("fitness_or_suspension", "transfer", "unclassified")

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_RECORD: Final = Path("docs/capture_lead_time.json")
DEFAULT_SUMMARY: Final = Path("docs/capture_lead_time.md")


class LeadTimeMeasurementError(RuntimeError):
    """The stored captures cannot support the measurement that was asked for."""


@dataclass(frozen=True, slots=True)
class _Capture:
    """One stored live capture, and the deadline it was still open for."""

    snapshot_id: str
    captured_at_utc: str
    gameweek: int
    deadline_utc: str
    bootstrap: bytes

    @property
    def lead_time_hours(self) -> float:
        """Hours between this capture and the deadline it was taken before.

        Always positive: the gameweek was chosen by :func:`next_open_deadline`, which
        returns the earliest deadline strictly after the capture. A capture at or past
        every deadline names no open gameweek and is not one of these at all.
        """

        elapsed = as_instant(self.deadline_utc) - as_instant(self.captured_at_utc)
        return round(elapsed.total_seconds() / 3600.0, 2)


def classify(news: str, status: str) -> str:
    """Put one note in a bucket by the declared vocabulary, or in neither.

    The note is read, the bucket is recorded, and the words are dropped. A note matching
    nothing -- including the empty note a cleared flag leaves behind -- is
    ``unclassified``, which is a third answer rather than a quiet vote for either side.
    """

    if _TRANSFER_PATTERN.search(news):
        return "transfer"
    if _FITNESS_OR_SUSPENSION_PATTERN.search(news):
        return "fitness_or_suspension"
    if status == _SUSPENDED_STATUS:
        return "fitness_or_suspension"
    return "unclassified"


def _captures(snapshot_root: Path) -> tuple[_Capture, ...]:
    """Read every stored live capture, with the gameweek it was taken for.

    ``list_snapshot_ids`` names the source it means, so the cohort and elite-picks
    captures sharing this root are never walked. Two shapes are skipped rather than
    fatal, because one unusable capture must not stop a measurement over the others: a
    live capture carrying no bootstrap payload, which is what an interrupted capture
    leaves behind, and a capture taken after every published deadline, which describes no
    open gameweek and so is a pre-deadline capture of nothing.
    """

    captures: list[_Capture] = []
    for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, identifier)
        bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
        if bootstrap is None:
            continue
        captured_at_utc = snapshot.metadata.captured_at_utc
        try:
            open_deadline = next_open_deadline(
                gameweek_deadlines(bootstrap), as_of_utc=captured_at_utc
            )
        except DataSourceError:
            continue
        captures.append(
            _Capture(
                snapshot_id=identifier,
                captured_at_utc=captured_at_utc,
                gameweek=open_deadline.gameweek,
                deadline_utc=open_deadline.deadline_utc,
                bootstrap=bootstrap,
            )
        )
    return tuple(captures)


def _recovered(early: _Capture, late: _Capture) -> dict[str, object]:
    """Count the notes stamped inside the window the later capture recovers.

    Read from the *later* capture, the only one holding them. The window is half-open at
    the early end and closed at the late end: a note stamped at the exact instant of the
    earlier capture was already in it, and one stamped at the instant of the later
    capture is in that one.
    """

    opened = as_instant(early.captured_at_utc)
    closed = as_instant(late.captured_at_utc)
    if closed <= opened:
        raise LeadTimeMeasurementError(
            f"Capture {late.snapshot_id} is not after {early.snapshot_id}: both are "
            f"stamped {early.captured_at_utc}. Two captures inside one second measure no "
            "window."
        )
    if early.deadline_utc != late.deadline_utc:
        raise LeadTimeMeasurementError(
            f"Captures {early.snapshot_id} and {late.snapshot_id} disagree about the "
            f"gameweek {late.gameweek} deadline: {early.deadline_utc} against "
            f"{late.deadline_utc}. A moved deadline is a different week, not a window."
        )

    notes = news_snapshot(late.bootstrap)
    stamped = notes.loc[notes["news_added_utc"].notna()]

    buckets: dict[str, list[int]] = {bucket: [] for bucket in BUCKETS}
    for row in stamped.itertuples(index=False):
        added = as_instant(str(row.news_added_utc))
        if not opened < added <= closed:
            continue
        buckets[classify(str(row.news), str(row.status))].append(int(row.player_id))

    return {
        "window_opened_utc": early.captured_at_utc,
        "window_closed_utc": late.captured_at_utc,
        "window_hours": round((closed - opened).total_seconds() / 3600.0, 2),
        "items_recovered": sum(len(players) for players in buckets.values()),
        "items_by_bucket": {bucket: len(buckets[bucket]) for bucket in BUCKETS},
        "players_by_bucket": {bucket: sorted(buckets[bucket]) for bucket in BUCKETS},
    }


def measure(snapshot_root: Path) -> dict[str, object]:
    """Report, per gameweek, what a capture at the later instant held and the earlier did not."""

    captures = _captures(snapshot_root)
    by_gameweek: dict[int, list[_Capture]] = {}
    for capture in captures:
        by_gameweek.setdefault(capture.gameweek, []).append(capture)

    gameweeks: list[dict[str, object]] = []
    for gameweek in sorted(by_gameweek):
        ordered = sorted(by_gameweek[gameweek], key=lambda entry: as_instant(entry.captured_at_utc))
        entry: dict[str, object] = {
            "gameweek": gameweek,
            "deadline_utc": ordered[-1].deadline_utc,
            "captures": [
                {
                    "snapshot_id": capture.snapshot_id,
                    "captured_at_utc": capture.captured_at_utc,
                    "lead_time_hours": capture.lead_time_hours,
                }
                for capture in ordered
            ],
            "earliest_lead_time_hours": ordered[0].lead_time_hours,
            "latest_lead_time_hours": ordered[-1].lead_time_hours,
        }
        if len(ordered) < 2:
            # One capture measures no window. Absent, never zero: a gameweek captured once
            # says nothing about what a second capture would have recovered, and a zero
            # here would read as "nothing was added".
            entry["recovered"] = None
            entry["recovered_unavailable_reason"] = "one_capture"
        else:
            entry["recovered"] = _recovered(ordered[0], ordered[-1])
        gameweeks.append(entry)

    measured = [entry for entry in gameweeks if entry["recovered"] is not None]
    return {
        "artifact_type": "capture_lead_time",
        "contract_version": CAPTURE_LEAD_TIME_CONTRACT_VERSION,
        "news_classifier_version": NEWS_CLASSIFIER_VERSION,
        "buckets": list(BUCKETS),
        "captures_read": len(captures),
        "gameweeks_seen": len(gameweeks),
        "gameweeks_measured": len(measured),
        "gameweeks": gameweeks,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }


def _per_gameweek_rows(gameweeks: list[object]) -> list[str]:
    rows: list[str] = []
    for entry in gameweeks:
        if not isinstance(entry, dict):
            continue
        recovered = entry.get("recovered")
        if isinstance(recovered, dict):
            window = f"{recovered['window_hours']} h"
            count = str(recovered["items_recovered"])
        else:
            window = "not measured"
            count = "not measured"
        rows.append(
            f"| {entry['gameweek']} | {len(list(entry['captures']))} | "
            f"{entry['earliest_lead_time_hours']} h | {entry['latest_lead_time_hours']} h | "
            f"{window} | {count} |"
        )
    return rows


def _bucket_rows(gameweeks: list[object], buckets: list[str]) -> list[str]:
    rows: list[str] = []
    for entry in gameweeks:
        if not isinstance(entry, dict):
            continue
        recovered = entry.get("recovered")
        if not isinstance(recovered, dict):
            continue
        counts = recovered["items_by_bucket"]
        if not isinstance(counts, dict):
            continue
        cells = " | ".join(str(counts[bucket]) for bucket in buckets)
        rows.append(f"| {entry['gameweek']} | {cells} |")
    return rows


def summary(record: dict[str, object]) -> str:
    """Write the record as prose, saying plainly what is measured and what is not."""

    gameweeks = list(record["gameweeks"])  # type: ignore[call-overload]
    buckets = [str(bucket) for bucket in list(record["buckets"])]  # type: ignore[call-overload]
    lines = [
        "# What a later capture recovers",
        "",
        f"Contract: `{record['contract_version']}`, "
        f"classifier `{record['news_classifier_version']}`",
        "",
        "Availability is applied once, from the capture the week was decided from. A note",
        "the platform adds after that capture is not late -- it is absent, and no later",
        "step recovers it. This counts what a capture taken at the later of two stored",
        "instants held that the earlier one could not.",
        "",
        "## Per gameweek",
        "",
        "| gameweek | captures | earliest lead | latest lead | window | recovered |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        *_per_gameweek_rows(gameweeks),
        "",
        "A gameweek captured once has no window, so its recovered count is **not",
        "measured** rather than zero. Those are different claims and only one of them is",
        "true here.",
        "",
        "## The split, and what it is",
        "",
        f"Buckets: {', '.join(f'`{bucket}`' for bucket in buckets)}.",
        "",
        f"A note is in a bucket because it matched `{record['news_classifier_version']}`'s",
        "declared vocabulary, and the counts are counts of that match -- not a reading of",
        "what the note meant. A note matching nothing stays `unclassified` and is reported",
        "as its own number, because an item we could not classify is not a transfer. The",
        "notes' words are not in this artifact; the player ids are, so any bucket can be",
        "checked against the local capture.",
        "",
    ]

    bucket_rows = _bucket_rows(gameweeks, buckets)
    if bucket_rows:
        lines += [
            "## By bucket, per measured gameweek",
            "",
            "| gameweek | " + " | ".join(buckets) + " |",
            "| ---: | " + " | ".join("---:" for _ in buckets) + " |",
            *bucket_rows,
            "",
        ]

    lines += [
        "## What this decides",
        "",
        "Nothing on its own, and it licenses no claim about points. It is the evidence",
        "behind the lead-time line in `docs/weekly_runbook.md`: a number for how much a",
        "week's own decision could not see, measured on our own captures rather than",
        "argued. The locked holdout was not read and no gate is evaluated here.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    arguments = parser.parse_args()

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1

    try:
        record = measure(arguments.snapshot_root)
    except (LeadTimeMeasurementError, DataSourceError) as error:
        print(f"Refused: {error}")
        return 1

    if not record["gameweeks_seen"]:
        print(f"No pre-deadline live capture under {arguments.snapshot_root}.")
        return 1

    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, summary(record))

    print(f"Read {record['captures_read']} live capture(s).")
    for entry in list(record["gameweeks"]):  # type: ignore[call-overload]
        recovered = entry.get("recovered")
        if isinstance(recovered, dict):
            detail = (
                f"window {recovered['window_hours']} h, "
                f"{recovered['items_recovered']} item(s) recovered "
                f"{recovered['items_by_bucket']}"
            )
        else:
            detail = f"not measured ({entry.get('recovered_unavailable_reason')})"
        print(
            f"  gw{entry['gameweek']:02d}  lead {entry['earliest_lead_time_hours']} h -> "
            f"{entry['latest_lead_time_hours']} h  {detail}"
        )
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
