"""Measure the shared strategy scale from one named settled live capture.

No product imports this command. It measures the method declared in
docs/strategy_rule_scale_prereg.md, whose decisions the owner accepted on #1002 on
2026-10-10, and it opens no capture until that declaration is merged on origin/develop
with the bytes DECLARATION_SHA256 pins. An amendment needs a reviewed update to the
declaration, DECLARATION_SHA256 and this instrument before it can read a capture.

A GW1 to GW3 control that does not round to 21.2 still writes the aggregate record,
marked control_failed, and exits 2: step 4 is held until the difference is explained
on #1002. Reading (d) divides by sqrt(k) times the unrounded S on GW1 to N. Reading (e)
covers every other league in config/leagues.json at the measured revision and marks one
it cannot measure as unavailable, never refusing the primary reading. The command
writes no constant and no rule id: step 4 applies the declaration's update rule.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from hashlib import sha256
from itertools import combinations
from pathlib import Path
from typing import Any

from scripts._provenance import REPOSITORY_ROOT, _git_revision, write_json, write_text

from squadopt.contracts.league_list import LEAGUE_LIST_FILE, read_league_list
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.fpl_live import (
    entry_history_payload,
    fpl_entry_history_points,
    fpl_league_standings,
    scored_gameweeks,
)

DECLARATION_PATH = "docs/strategy_rule_scale_prereg.md"
DECLARATION_SHA256 = "9b5f36ed5651dee692cbb9dab3157ddbb00456840b1811271dc994e34546d442"
PRIMARY_LEAGUE = 352490
CONTRACT_VERSION = "strategy_rule_scale_v1"
CONTROL_EXPECTED = 21.2
CONTROL_FAILED_EXIT = 2
_LIVE_ID = re.compile(r"fpl-live-(\d{8}T\d{6}Z)-[0-9a-f]{12}")
_FIRST_DATE = datetime(2026, 8, 26, tzinfo=UTC)
_LAST_DATE = datetime(2027, 7, 1, tzinfo=UTC)
NetRows = tuple[Mapping[int, int], ...]


class ScaleMeasurementError(ValueError):
    """A declared input or precondition is unavailable."""


@dataclass(frozen=True, slots=True)
class Reading:
    squared_difference_sum: int
    counted: int
    expected: int

    def scale(self) -> Decimal | None:
        if not self.counted:
            return None
        with localcontext() as context:
            context.prec = 50
            return (Decimal(self.squared_difference_sum) / self.counted).sqrt()

    def document(self) -> dict[str, Any]:
        value = self.scale()
        return {
            "squared_difference_sum": self.squared_difference_sum,
            "pair_weeks_counted": self.counted,
            "pair_weeks_expected": self.expected,
            "pair_weeks_dropped": self.expected - self.counted,
            "scale_unrounded": float(value) if value is not None else None,
            "scale_rounded": round_half_up(value) if value is not None else None,
        }


def round_half_up(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def admitted_gameweek(bootstrap: bytes, through_gameweek: int) -> int:
    checked = scored_gameweeks(bootstrap)
    highest = max(checked, default=0)
    if (
        highest < 6
        or highest > 38
        or through_gameweek != highest
        or not set(range(1, highest + 1)).issubset(checked)
    ):
        raise ScaleMeasurementError(
            "Use the highest finished and data_checked week, at least GW6, "
            "with every prior week checked."
        )
    return highest


def league_net_rows(
    payloads: Mapping[str, bytes], league: int, n: int, *, cost_through_n_only: bool = False
) -> NetRows:
    """Consume FPL readers while keeping member identities out of the output.

    The primary league refuses any history row without event_transfers_cost. Reading (e)
    passes cost_through_n_only, since a secondary league needs the cost on GW1 to N only.
    """
    try:
        standings = fpl_league_standings(
            payloads[f"league-{league}-standings.json"], league_id=league
        )
        rows: list[Mapping[int, int]] = []
        for member in standings:
            history = fpl_entry_history_points(
                payloads[entry_history_payload(member.entry_id)], entry_id=member.entry_id
            )
            if any(
                week.transfer_cost is None
                for week in history
                if not cost_through_n_only or week.gameweek <= n
            ):
                raise ScaleMeasurementError("A history row lacks event_transfers_cost.")
            rows.append(
                {
                    week.gameweek: week.points - week.transfer_cost
                    for week in history
                    if week.gameweek <= n and week.transfer_cost is not None
                }
            )
    except KeyError as error:
        raise ScaleMeasurementError(
            "The capture lacks a standings or required history payload."
        ) from error
    except DataError as error:
        # A duplicated week or a null value raises a DataError that is not a DataSourceError.
        raise ScaleMeasurementError("The capture has invalid standings or history rows.") from error
    if len(rows) < 2:
        raise ScaleMeasurementError("The league needs at least two captured members.")
    return tuple(rows)


def pair_week_reading(rows: NetRows, weeks: Sequence[int]) -> Reading:
    squares = counted = 0
    for first, second in combinations(rows, 2):
        for week in weeks:
            if week in first and week in second:
                squares += (first[week] - second[week]) ** 2
                counted += 1
    return Reading(squares, counted, len(rows) * (len(rows) - 1) // 2 * len(weeks))


def cumulative_reading(rows: NetRows, k: int, unrounded_scale: Decimal) -> dict[str, Any]:
    """Reading (d): the divisor is sqrt(k) times the unrounded S on GW1 to N."""
    squares = counted = 0
    weeks = range(1, k + 1)
    for first, second in combinations(rows, 2):
        if all(week in first and week in second for week in weeks):
            squares += sum(first[week] - second[week] for week in weeks) ** 2
            counted += 1
    reading = Reading(squares, counted, len(rows) * (len(rows) - 1) // 2)
    rms = reading.scale()
    with localcontext() as context:
        context.prec = 50
        ratio = (
            rms / (Decimal(k).sqrt() * unrounded_scale)
            if rms is not None and unrounded_scale
            else None
        )
    return {
        "through_gameweek": k,
        "pair_counted": counted,
        "pair_expected": reading.expected,
        "pair_dropped": reading.expected - counted,
        "cumulative_squared_difference_sum": squares,
        "cumulative_rms": float(rms) if rms is not None else None,
        "cumulative_rms_over_sqrt_k_times_unrounded_scale": (
            float(ratio) if ratio is not None else None
        ),
    }


def secondary_reading(payloads: Mapping[str, bytes], league: int, n: int) -> dict[str, Any]:
    """Reading (e) for one listed league other than the primary, recorded only.

    The league is available only when the capture holds its standings and every member has
    a history row with event_transfers_cost for every week from GW1 to N. Otherwise it is
    marked unavailable with no number, and it never refuses or changes the primary reading.
    """
    unavailable = {"league": league, "available": False}
    if f"league-{league}-standings.json" not in payloads:
        return {**unavailable, "reason": "The capture has no standings for this listed league."}
    try:
        rows = league_net_rows(payloads, league, n, cost_through_n_only=True)
    except ScaleMeasurementError as error:
        return {**unavailable, "reason": str(error)}
    if any(not set(range(1, n + 1)).issubset(row) for row in rows):
        return {**unavailable, "reason": "A member lacks a history row for a week from GW1 to N."}
    return {
        "league": league,
        "available": True,
        "members": len(rows),
        "through_gameweek": n,
        **pair_week_reading(rows, range(1, n + 1)).document(),
    }


def measure_payloads(
    payloads: Mapping[str, bytes],
    *,
    league: int,
    through_gameweek: int,
    listed_leagues: Sequence[int],
) -> dict[str, Any]:
    """Calculate aggregates only; unit tests supply synthetic FPL-shaped payloads."""
    if league != PRIMARY_LEAGUE:
        raise ScaleMeasurementError("The shared scale is measured on league 352490.")
    try:
        n = admitted_gameweek(payloads["bootstrap-static.json"], through_gameweek)
    except KeyError as error:
        raise ScaleMeasurementError("The capture lacks bootstrap-static.json.") from error
    rows = league_net_rows(payloads, league, n)
    control = pair_week_reading(rows, range(1, 4))
    control_scale = control.scale()
    # A failed control is recorded with its aggregates, never refused or repaired, and the
    # record then holds step 4 until the difference is explained on #1002.
    control_failed = control_scale is None or round_half_up(control_scale) != CONTROL_EXPECTED
    primary = pair_week_reading(rows, range(1, n + 1))
    scale = primary.scale()
    if scale is None:
        # An empty population is unavailable, never zero.
        raise ScaleMeasurementError("No pair-week on GW1 to N has both members' rows.")
    return {
        "contract_version": CONTRACT_VERSION,
        "season": "2026-27",
        "league": league,
        "through_gameweek": n,
        "members": len(rows),
        "scale": primary.document(),
        "control_gw1_to_gw3": {
            **control.document(),
            "expected_scale_rounded": CONTROL_EXPECTED,
        },
        "control_failed": control_failed,
        "by_gameweek": [
            {"gameweek": week, **pair_week_reading(rows, (week,)).document()}
            for week in range(1, n + 1)
        ],
        "prefixes": [
            {"through_gameweek": k, **pair_week_reading(rows, range(1, k + 1)).document()}
            for k in range(3, n + 1)
        ],
        "cumulative_comparisons": [cumulative_reading(rows, k, scale) for k in range(3, n + 1)],
        "secondary_leagues": [
            secondary_reading(payloads, other, n) for other in listed_leagues if other != league
        ],
    }


def markdown(record: Mapping[str, Any]) -> str:
    control = record["control_gw1_to_gw3"]
    lines = [
        "# Strategy rule scale checkpoint",
        "",
        f"Source capture: `{record['snapshot_id']}`",
        f"Source fingerprint: `{record['snapshot_fingerprint']}`",
        f"Capture UTC: {record['captured_at_utc']}",
        f"Repository commit: `{record['repository_commit']}`",
        f"Declaration SHA-256: `{record['preregistration_sha256']}`",
        "",
        f"League: {record['league']}; through GW{record['through_gameweek']}; "
        f"members: {record['members']}",
        f"S: {record['scale']['scale_rounded']} (unrounded {record['scale']['scale_unrounded']})",
        f"Pair-weeks counted: {record['scale']['pair_weeks_counted']}; "
        f"dropped: {record['scale']['pair_weeks_dropped']}",
        f"GW1 to GW3 control: {control['scale_rounded']} "
        f"(unrounded {control['scale_unrounded']}; expected {control['expected_scale_rounded']}); "
        f"pair-weeks counted: {control['pair_weeks_counted']}; "
        f"dropped: {control['pair_weeks_dropped']}",
        "Control: " + ("failed" if record["control_failed"] else "passed"),
        "",
    ]
    if record["control_failed"]:
        lines.extend(
            [
                "The control failed, so step 4 is held. This record updates no constant "
                "until the difference is explained on #1002.",
                "",
            ]
        )
    lines += [
        "Companion readings are recorded diagnostics. They do not change the rule's shape.",
        "",
        "## Single gameweeks",
        "",
        "| GW | S | Unrounded S | Pair-weeks counted | Dropped |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in record["by_gameweek"]:
        lines.append(
            f"| {row['gameweek']} | {row['scale_rounded']} | {row['scale_unrounded']} | "
            f"{row['pair_weeks_counted']} | {row['pair_weeks_dropped']} |"
        )
    lines.extend(
        [
            "",
            "## Prefixes",
            "",
            "| Through GW | S | Counted | Dropped |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in record["prefixes"]:
        lines.append(
            f"| {row['through_gameweek']} | {row['scale_rounded']} | "
            f"{row['pair_weeks_counted']} | {row['pair_weeks_dropped']} |"
        )
    lines.extend(
        [
            "",
            "## Cumulative comparisons",
            "",
            "Ratio is the cumulative RMS divided by sqrt(k) times the unrounded S on GW1 to N.",
            "",
            "| Through GW | RMS | Ratio | Pairs counted | Dropped |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in record["cumulative_comparisons"]:
        lines.append(
            f"| {row['through_gameweek']} | {row['cumulative_rms']} | "
            f"{row['cumulative_rms_over_sqrt_k_times_unrounded_scale']} | "
            f"{row['pair_counted']} | {row['pair_dropped']} |"
        )
    lines.extend(
        [
            "",
            "## Other listed leagues",
            "",
            "| League | Members | S | Counted | Dropped |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    measured = [row for row in record["secondary_leagues"] if row["available"]]
    for row in measured:
        lines.append(
            f"| {row['league']} | {row['members']} | {row['scale_rounded']} | "
            f"{row['pair_weeks_counted']} | {row['pair_weeks_dropped']} |"
        )
    if not measured:
        lines.extend(["", "No additional listed league was measured."])
    for row in record["secondary_leagues"]:
        if not row["available"]:
            lines.extend(
                [
                    "",
                    f"League {row['league']} is listed but was not measured: {row['reason']}",
                ]
            )
    return "\n".join(lines) + "\n"


def write_records(record: Mapping[str, Any], repository_root: Path) -> None:
    json_path = repository_root / "docs" / "strategy_rule_scale.json"
    write_json(json_path, record)
    written = json.loads(json_path.read_text(encoding="utf-8"))
    write_text(repository_root / "docs" / "strategy_rule_scale.md", markdown(written))


def _validate_live_id(snapshot_id: str) -> None:
    match = _LIVE_ID.fullmatch(snapshot_id)
    if match is None:
        raise ScaleMeasurementError("Use one explicit dated fpl-live capture from 2026-27.")
    stamp = datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    if not _FIRST_DATE <= stamp < _LAST_DATE:
        raise ScaleMeasurementError("The declared capture is outside live season 2026-27.")


def _git_output(*arguments: str) -> bytes:
    return subprocess.run(
        ["git", *arguments], cwd=REPOSITORY_ROOT, capture_output=True, check=True
    ).stdout


def preregistration_gate() -> tuple[str, str]:
    """Before opening any capture, require the accepted declaration on origin/develop."""
    revision, dirty = _git_revision()
    if dirty:
        raise ScaleMeasurementError("Commit the reviewed instrument before a real measurement.")
    try:
        remote = _git_output("ls-remote", "origin", "refs/heads/develop").split()[:1]
        tracked = _git_output("rev-parse", "--verify", "origin/develop").split()
    except (OSError, subprocess.CalledProcessError) as error:
        raise ScaleMeasurementError(
            "Cannot compare origin/develop with the remote's develop."
        ) from error
    if not remote or remote != tracked:
        # A clone fetched before an amendment would otherwise run the superseded method.
        raise ScaleMeasurementError("Fetch origin/develop before a real measurement.")
    try:
        merged = (
            _git_output("show", f"origin/develop:{DECLARATION_PATH}")
            .decode("utf-8")
            .replace("\r\n", "\n")
            .encode("utf-8")
        )
        local = (REPOSITORY_ROOT / DECLARATION_PATH).read_text(encoding="utf-8").encode("utf-8")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ScaleMeasurementError(
            "The accepted preregistration must first merge into origin/develop."
        ) from error
    digest = sha256(merged).hexdigest()
    if local != merged or digest != DECLARATION_SHA256:
        raise ScaleMeasurementError(
            "The declaration differs from the accepted method this instrument pins. "
            "Update this instrument by review."
        )
    return revision, digest


def run_measurement(
    *, snapshot_root: Path, snapshot_id: str, league: int, through_gameweek: int
) -> dict[str, Any]:
    _validate_live_id(snapshot_id)
    if league != PRIMARY_LEAGUE:
        raise ScaleMeasurementError("The primary league is 352490.")
    revision, preregistration_hash = preregistration_gate()
    # The gate refused a dirty tree, so this is config/leagues.json at the recorded revision.
    # An unreadable list refuses before any capture opens, since reading (e) cannot be named.
    listed_leagues = read_league_list(REPOSITORY_ROOT / LEAGUE_LIST_FILE)
    snapshot: CapturedSnapshot = read_snapshot(snapshot_root, snapshot_id)
    if snapshot.metadata.source != "fpl-live":
        raise ScaleMeasurementError("Use the declared live capture source.")
    record = measure_payloads(
        snapshot.payloads,
        league=league,
        through_gameweek=through_gameweek,
        listed_leagues=listed_leagues,
    )
    record.update(
        {
            "snapshot_id": snapshot.metadata.snapshot_id,
            "snapshot_fingerprint": snapshot.metadata.fingerprint,
            "captured_at_utc": snapshot.metadata.captured_at_utc,
            "repository_commit": revision,
            "working_tree_dirty": False,
            "preregistration_sha256": preregistration_hash,
        }
    )
    write_records(record, REPOSITORY_ROOT)
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--through-gameweek", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        record = run_measurement(
            snapshot_root=args.snapshot_root,
            snapshot_id=args.snapshot_id,
            league=args.league,
            through_gameweek=args.through_gameweek,
        )
    except (ScaleMeasurementError, DataError, OSError, ValueError, SystemExit) as error:
        # Third-party parse/integrity exceptions can contain member ids or names.
        message = (
            str(error)
            if isinstance(error, ScaleMeasurementError)
            else "Capture or provenance validation failed."
        )
        print(f"Measurement refused: {message}", file=sys.stderr)
        return 1
    if record["control_failed"]:
        # The record is written; a distinct exit keeps any caller from treating it as a pass.
        print(
            f"Recorded GW1 to GW{record['through_gameweek']} scale "
            f"{record['scale']['scale_rounded']} with a failed GW1 to GW3 control "
            f"({record['control_gw1_to_gw3']['scale_rounded']}, expected {CONTROL_EXPECTED}). "
            "Step 4 is held until the difference is explained on #1002.",
            file=sys.stderr,
        )
        return CONTROL_FAILED_EXIT
    print(
        f"Recorded GW1 to GW{record['through_gameweek']} scale {record['scale']['scale_rounded']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
