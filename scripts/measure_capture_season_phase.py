"""Measure what a capture's cumulative counters describe, and record it.

    python -m scripts.measure_capture_season_phase

The element records in a captured bootstrap payload carry cumulative counters --
``minutes``, ``total_points``, ``starts`` and the rest. The number in them is not a
property of the payload alone: before the platform resets for a new season they hold
the *previous* season's totals, and afterwards they hold this season's. Nothing in the
payload says which, and both readings are plausible integers, so the mistake does not
announce itself.

This script measures the claim rather than asserting it. For every stored capture it
reports the phase the adapter derives, and for a pre-reset capture it checks the
counters against the archive's completed-season totals for the same players. An exact
match across the roster is what makes "these are last season's numbers" a measurement.

Only stored captures and the local archive are read. Nothing is fetched, so the number
this prints is reproducible from what is on disk.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, write_json, write_text

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    SEASON_RELATIVE_ELEMENT_FIELDS,
    capture_season_phase,
)

CAPTURE_SEASON_PHASE_CONTRACT_VERSION: Final = "capture_season_phase_v1"

# The season a pre-reset 2026-27 capture should be echoing.
COMPARISON_SEASON: Final = "2025-26"

DEFAULT_SNAPSHOT_ROOT: Final = Path("data/snapshots")
DEFAULT_RECORD: Final = Path("docs/capture_season_phase.json")
DEFAULT_SUMMARY: Final = Path("docs/capture_season_phase.md")


def _archive_season_totals(archive_root: Path, season: str) -> pd.DataFrame:
    """Return one completed season's per-player totals, keyed on the persistent code."""

    gameweeks = pd.read_csv(
        archive_root / "data" / season / "gws" / "merged_gw.csv",
        usecols=["element", "total_points", "minutes"],
        low_memory=False,
    )
    roster = pd.read_csv(archive_root / "data" / season / "players_raw.csv", usecols=["id", "code"])
    totals = (
        gameweeks.groupby("element")
        .agg(archive_total_points=("total_points", "sum"), archive_minutes=("minutes", "sum"))
        .reset_index()
    )
    joined = totals.merge(roster, left_on="element", right_on="id", how="inner")
    return joined.loc[:, ["code", "archive_total_points", "archive_minutes"]].rename(
        columns={"code": "player_id"}
    )


def _counters(bootstrap: bytes) -> pd.DataFrame:
    """Read the counters directly, bypassing the guard, because measuring is the point.

    :func:`in_season_totals` refuses a pre-reset capture, which is correct for a
    consumer and useless for the measurement that establishes why it refuses.
    """

    document = json.loads(bootstrap.decode("utf-8"))
    rows = [
        {
            "player_id": int(record["code"]),
            "capture_total_points": int(record["total_points"]),
            "capture_minutes": int(record["minutes"]),
        }
        for record in document["elements"]
        if "total_points" in record and "minutes" in record
    ]
    return pd.DataFrame.from_records(rows)


def _agreement(bootstrap: bytes, archive: pd.DataFrame) -> dict[str, object]:
    """Compare a capture's counters against a completed season's totals."""

    merged = _counters(bootstrap).merge(archive, on="player_id", how="inner")
    if merged.empty:
        return {"players_compared": 0, "players_identical": 0, "identical_fraction": None}
    identical = (
        (merged["capture_total_points"] == merged["archive_total_points"])
        & (merged["capture_minutes"] == merged["archive_minutes"])
    ).sum()
    compared = len(merged)
    return {
        "players_compared": int(compared),
        "players_identical": int(identical),
        "identical_fraction": round(float(identical) / float(compared), 4),
    }


def _reset_evidence(bootstrap: bytes, archive: pd.DataFrame) -> dict[str, object]:
    """Show the reset concretely, not just as a fallen agreement rate.

    The vivid form of this measurement is a player who read a full previous campaign
    before the reset and a single appearance after it. Reported as the largest drops in
    accumulated minutes, so the sample is chosen by the data rather than by hand.
    """

    merged = _counters(bootstrap).merge(archive, on="player_id", how="inner")
    if merged.empty:
        return {"players_compared": 0, "largest_minute_drops": []}
    merged["minute_drop"] = merged["archive_minutes"] - merged["capture_minutes"]
    top = merged.nlargest(5, "minute_drop")
    # Columns are pulled out as typed lists rather than walked with itertuples(), whose
    # rows carry no element type and so cannot be narrowed to int without a cast.
    columns = {
        name: top[source].astype("int64").tolist()
        for name, source in (
            ("player_id", "player_id"),
            ("prior_season_minutes", "archive_minutes"),
            ("prior_season_points", "archive_total_points"),
            ("capture_minutes", "capture_minutes"),
            ("capture_points", "capture_total_points"),
        )
    }
    # A player with no prior-season record has nothing to reset, so "still identical"
    # is expected for them and says nothing either way. Counting those separately is
    # what turns residual agreement into a real count of counterexamples.
    identical = (merged["capture_total_points"] == merged["archive_total_points"]) & (
        merged["capture_minutes"] == merged["archive_minutes"]
    )
    blank = (merged["archive_minutes"] == 0) & (merged["archive_total_points"] == 0)
    return {
        "players_compared": len(merged),
        "players_whose_minutes_fell": int((merged["minute_drop"] > 0).sum()),
        "still_identical": int(identical.sum()),
        "still_identical_with_no_prior_record": int((identical & blank).sum()),
        "counterexamples": int((identical & ~blank).sum()),
        "largest_minute_drops": [
            {name: values[index] for name, values in columns.items()} for index in range(len(top))
        ],
    }


def measure(snapshot_root: Path, archive_root: Path) -> dict[str, object]:
    """Report every stored capture's phase, and the archive agreement where it applies."""

    archive = _archive_season_totals(archive_root, COMPARISON_SEASON)
    captures: list[dict[str, object]] = []
    for directory in sorted(p for p in snapshot_root.iterdir() if p.is_dir()):
        snapshot = read_snapshot(snapshot_root, directory.name)
        payloads = snapshot.payloads
        phase = capture_season_phase(
            payloads[BOOTSTRAP_PAYLOAD],
            payloads[FIXTURES_PAYLOAD],
            captured_at_utc=snapshot.metadata.captured_at_utc,
        )
        entry: dict[str, object] = {
            "snapshot_id": directory.name,
            "captured_at_utc": phase.captured_at_utc,
            "phase": phase.phase,
            "opening_deadline_utc": phase.opening_deadline_utc,
            "first_kickoff_utc": phase.first_kickoff_utc,
        }
        entry[f"agreement_with_{COMPARISON_SEASON}"] = _agreement(
            payloads[BOOTSTRAP_PAYLOAD], archive
        )
        if phase.phase == "current_season":
            entry["reset_evidence"] = _reset_evidence(payloads[BOOTSTRAP_PAYLOAD], archive)
        captures.append(entry)

    phases = sorted({str(entry["phase"]) for entry in captures})
    return {
        "artifact_type": "capture_season_phase",
        "contract_version": CAPTURE_SEASON_PHASE_CONTRACT_VERSION,
        "comparison_season": COMPARISON_SEASON,
        "season_relative_fields": list(SEASON_RELATIVE_ELEMENT_FIELDS),
        "captures_measured": len(captures),
        "phases_present": phases,
        "captures": captures,
        "gate_evidence": False,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }


def summary(record: dict[str, object]) -> str:
    """Write the record as prose, saying plainly what is measured and what is not."""

    captures = list(record["captures"])  # type: ignore[call-overload]
    lines = [
        "# What a capture's cumulative counters describe",
        "",
        f"Contract: `{record['contract_version']}`",
        "",
        "An element record's `minutes`, `total_points`, `starts` and the rest are",
        "cumulative, and which season they accumulate is not stated anywhere in the",
        "payload. Before the platform resets they are the previous season's totals;",
        "afterwards they are this season's. Both are plausible integers, so reading the",
        "wrong one produces a wrong feature and no error.",
        "",
        "## Stored captures",
        "",
        "| snapshot | captured | phase | agrees with " + str(record["comparison_season"]) + " |",
        "| --- | --- | --- | ---: |",
    ]
    for entry in captures:
        agreement = entry.get(f"agreement_with_{record['comparison_season']}")
        if isinstance(agreement, dict) and agreement.get("identical_fraction") is not None:
            cell = (
                f"{agreement['players_identical']}/{agreement['players_compared']}"
                f" ({float(agreement['identical_fraction']):.1%})"
            )
        else:
            cell = "not applicable"
        lines.append(
            f"| `{entry['snapshot_id']}` | {entry['captured_at_utc']} | "
            f"`{entry['phase']}` | {cell} |"
        )

    current = [e for e in captures if e["phase"] == "current_season"]
    if current:
        evidence = current[0].get("reset_evidence")
        if isinstance(evidence, dict):
            lines += [
                "",
                "## The reset, measured",
                "",
                "A capture taken after the first kick-off no longer echoes the completed",
                "season. The clearest form is the players whose accumulated minutes fell",
                "the furthest -- a full previous campaign before, a single appearance or",
                "none after:",
                "",
                "| player | before | after |",
                "| --- | ---: | ---: |",
            ]
            for row in list(evidence.get("largest_minute_drops") or []):
                lines.append(
                    f"| `{row['player_id']}` | {row['prior_season_minutes']} min / "
                    f"{row['prior_season_points']} pts | {row['capture_minutes']} min / "
                    f"{row['capture_points']} pts |"
                )
            lines += [
                "",
                f"Of {evidence.get('players_compared')} players compared, "
                f"{evidence.get('players_whose_minutes_fell')} had their accumulated",
                "minutes fall. A counter that only ever accumulates cannot fall, so this",
                "is the reset rather than a slow divergence.",
                "",
                f"{evidence.get('still_identical')} players still match the completed "
                f"season, and {evidence.get('still_identical_with_no_prior_record')} of",
                "those had no prior-season record at all -- nothing to reset, so their",
                "agreement carries no information. That leaves "
                f"**{evidence.get('counterexamples')}** genuine counterexamples: no player",
                "who held a prior-season record kept it.",
            ]

    prior = [e for e in captures if e["phase"] == "prior_season"]
    if prior:
        first = prior[0]
        lines += [
            "",
            "A pre-reset capture's counters are not merely *similar* to the completed",
            "season's totals, they are the same integers. That is what makes this a",
            "measurement rather than an interpretation.",
            "",
            "## The boundary, and the part of it nobody has observed",
            "",
            f"The opening deadline is {first['opening_deadline_utc']} and the season's first",
            f"kick-off is {first['first_kickoff_utc']}. The reset happens somewhere in",
            "between, and no capture exists inside that window, so which of the two",
            "instants triggers it is **unmeasured**. The adapter therefore reports three",
            "phases rather than two: a capture in that window is `unobserved_transition`",
            "and is refused, because guessing there would be an assertion about data",
            "nobody has. A capture taken inside the window would close this.",
        ]

    lines += [
        "",
        "## What this decides",
        "",
        "Nothing on its own. It is the reason `in_season_totals` refuses a pre-reset",
        "capture, and the reason a single capture taken after the opening gameweek",
        "completes is enough to give that gameweek's played history: once the counters",
        "have reset, a season-to-date total after one gameweek *is* that gameweek. From",
        "the third gameweek onward a single total no longer isolates one week, so",
        "consecutive captures must be differenced.",
        "",
        f"The locked holdout was not read. Fields classified as season-relative: "
        f"{len(list(record['season_relative_fields']))}.",  # type: ignore[call-overload]
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_SUMMARY)
    arguments = parser.parse_args()

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    record = measure(arguments.snapshot_root, arguments.archive_root)
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, summary(record))

    print(f"Measured {record['captures_measured']} capture(s).")
    for entry in list(record["captures"]):  # type: ignore[call-overload]
        agreement = entry.get(f"agreement_with_{record['comparison_season']}")
        detail = ""
        if isinstance(agreement, dict) and agreement.get("identical_fraction") is not None:
            detail = (
                f"  agrees with {record['comparison_season']}: "
                f"{agreement['players_identical']}/{agreement['players_compared']}"
            )
        print(f"  {entry['snapshot_id']}  {entry['phase']}{detail}")
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
