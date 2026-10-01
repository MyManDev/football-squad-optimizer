"""Count how stated playing chances resolved by the next decision capture; nothing is fitted.

    python -m scripts.measure_availability_transitions --snapshot-root <captures> \\
        --protocol-merged-at <UTC instant> --output <fresh directory>

The experimental football planner treats a held player's stated 25, 50 or 75 per cent
chance of playing as resolving before the next decision, eligible with that probability
(``live/football_observations.py``). The stored captures already hold the answer: the
decision capture of gameweek g says what the source stated, and the decision capture of
g+1 says how the same player stood when the next decision was made. This counts, per
stated chance, how many were by then available, still doubtful, out, or no longer listed.
Counts and player codes are recorded; no note text leaves the capture. Nothing is
fetched, fitted or scored against a match outcome.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    availability_snapshot,
    gameweek_deadlines,
    next_open_deadline,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.prediction.availability import (
    AVAILABILITY_RULE_CONTRACT_VERSION,
    STATUS_AVAILABLE,
    STATUS_DOUBTFUL,
    UNAVAILABLE_STATUSES,
)

CONTRACT_VERSION: Final = "availability_transitions_v1"
#: The stated chances the window consumer turns into an information branch.
STATED_CHANCES: Final = (25, 50, 75)
#: What the next decision capture can say. ``absent`` is a player the later capture no
#: longer lists; ``unknown`` is a status or chance the vocabulary has not shown. Both are
#: reported as their own count, never folded into another class or into zero.
OUTCOME_CLASSES: Final = ("available", "doubtful", "out", "absent", "unknown")
#: Two-sided 90 percent, the interval width the repository's other records use.
Z_90: Final = 1.6448536269514722


@dataclass(frozen=True, slots=True)
class DecisionCapture:
    """The latest stored live capture whose own open deadline is ``gameweek``."""

    gameweek: int
    snapshot_id: str
    captured_at_utc: str
    deadline_utc: str
    bootstrap: bytes

    def identity(self) -> dict[str, Any]:
        return {
            "gameweek": self.gameweek,
            "snapshot_id": self.snapshot_id,
            "captured_at_utc": self.captured_at_utc,
            "deadline_utc": self.deadline_utc,
        }


def wilson_interval(successes: int, trials: int, z: float = Z_90) -> tuple[float, float] | None:
    """Wilson score interval for a share; ``None`` when nothing was observed."""
    if trials <= 0:
        return None
    if not 0 <= successes <= trials:
        raise ValueError("Successes must lie between zero and the number of trials.")
    share = successes / trials
    denominator = 1 + z * z / trials
    centre = (share + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(share * (1 - share) / trials + z * z / (4 * trials * trials)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def resolve(status: object, chance: object) -> str:
    """Read one later-capture row by the availability rule's own precedence.

    A stated chance wins over the status, as ``apply_availability`` applies it: 100 is
    available, 0 is out, 25, 50 and 75 are still doubtful. Without a chance the status
    decides; a status the rule does not know is ``unknown``, not a guess.
    """
    if chance is not None and not pd.isna(chance):
        value = int(chance)
        if value == 100:
            return "available"
        if value == 0:
            return "out"
        if value in STATED_CHANCES:
            return "doubtful"
        return "unknown"
    text = str(status)
    if text == STATUS_AVAILABLE:
        return "available"
    if text == STATUS_DOUBTFUL:
        return "doubtful"
    if text in UNAVAILABLE_STATUSES:
        return "out"
    return "unknown"


def decision_captures(snapshot_root: Path) -> dict[int, DecisionCapture]:
    """One decision capture per gameweek: the latest capture whose open deadline is that week.

    This is the rule the prospective football protocol scores from. A capture with no
    bootstrap payload (an interrupted capture) or taken after every published deadline
    describes no decision and is skipped, not treated as a week.
    """
    chosen: dict[int, DecisionCapture] = {}
    for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, identifier)
        bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
        if bootstrap is None:
            continue
        captured_at_utc = snapshot.metadata.captured_at_utc
        try:
            deadline = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=captured_at_utc)
        except DataSourceError:
            continue
        candidate = DecisionCapture(
            deadline.gameweek, identifier, captured_at_utc, deadline.deadline_utc, bootstrap
        )
        held = chosen.get(candidate.gameweek)
        if held is None or as_instant(candidate.captured_at_utc) > as_instant(held.captured_at_utc):
            chosen[candidate.gameweek] = candidate
    return chosen


def _cell(stated: int | None, codes: list[int], later: pd.DataFrame) -> dict[str, Any]:
    outcomes: dict[str, list[int]] = {name: [] for name in OUTCOME_CLASSES}
    for code in codes:
        if code not in later.index:
            outcomes["absent"].append(code)
            continue
        row = later.loc[code]
        outcomes[resolve(row.status, row.chance_of_playing)].append(code)
    trials = len(codes)
    return {
        "stated_chance": stated,
        "players_stated": trials,
        "counts": {name: len(outcomes[name]) for name in OUTCOME_CLASSES},
        "players": {name: sorted(outcomes[name]) for name in OUTCOME_CLASSES},
        "shares": (
            None
            if trials == 0
            else {
                name: {
                    "value": len(outcomes[name]) / trials,
                    "wilson_90": list(wilson_interval(len(outcomes[name]), trials) or ()),
                }
                for name in OUTCOME_CLASSES
            }
        ),
    }


def pair_transitions(earlier: DecisionCapture, later: DecisionCapture) -> dict[str, Any]:
    """How every player stated at 25, 50 or 75 in the earlier capture stood in the later one."""
    if later.gameweek != earlier.gameweek + 1:
        raise ValueError("A pair is two consecutive decision captures.")
    if as_instant(later.captured_at_utc) <= as_instant(earlier.deadline_utc):
        raise ValueError("The later decision capture must follow the earlier deadline.")
    before = availability_snapshot(earlier.bootstrap)
    after = availability_snapshot(later.bootstrap).set_index("player_id")
    if after.index.duplicated().any():
        raise ValueError("The later capture repeats a player.")
    stated = pd.to_numeric(before.chance_of_playing, errors="coerce")
    cells = []
    for chance in STATED_CHANCES:
        codes = [int(code) for code in before.loc[stated.eq(chance), "player_id"]]
        cells.append(_cell(chance, codes, after))
    pooled = [int(code) for code in before.loc[stated.isin(STATED_CHANCES), "player_id"]]
    cells.append(_cell(None, pooled, after))
    return {"earlier": earlier.identity(), "later": later.identity(), "cells": cells}


def measure(snapshot_root: Path, protocol_merged_at: str) -> dict[str, Any]:
    """Every consecutive pair of decision captures under ``snapshot_root``, read once."""
    merged = normalize_utc_timestamp(protocol_merged_at, label="protocol merge instant")
    captures = decision_captures(snapshot_root)
    pairs: list[dict[str, Any]] = []
    without_partner: list[int] = []
    for gameweek in sorted(captures):
        later = captures.get(gameweek + 1)
        if later is None:
            without_partner.append(gameweek)
            continue
        pair = pair_transitions(captures[gameweek], later)
        # Prospective means the earlier week's decision was still open when the protocol
        # merged; a pair whose later state could already have been seen is retrospective.
        pair["prospective"] = as_instant(captures[gameweek].deadline_utc) > as_instant(merged)
        pairs.append(pair)
    return {
        "artifact_type": "availability_transitions",
        "contract_version": CONTRACT_VERSION,
        "resolution_rule": AVAILABILITY_RULE_CONTRACT_VERSION,
        "stated_chances": list(STATED_CHANCES),
        "outcome_classes": list(OUTCOME_CLASSES),
        "interval": "wilson_90",
        "protocol_merged_at_utc": merged,
        "captures_read": len(list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)),
        "decision_captures": [captures[week].identity() for week in sorted(captures)],
        "pairs": pairs,
        "prospective_pairs": sum(bool(pair["prospective"]) for pair in pairs),
        "gameweeks_without_partner": without_partner,
        "news_text_included": False,
        "outcomes_read": False,
        "measurement_only": True,
        "gate_evidence": False,
        "locked_holdout_accessed": False,
    }


def _share(cell: Mapping[str, Any], name: str) -> str:
    shares = cell.get("shares")
    if not shares:
        return "not observed"
    share = shares[name]
    low, high = share["wilson_90"]
    return f"{share['value']:.2f} [{low:.2f}, {high:.2f}]"


def summary(record: Mapping[str, Any]) -> str:
    """The record as prose and one table; counts are counts, shares carry their interval."""
    lines = [
        "# How stated playing chances resolved by the next decision",
        "",
        f"Contract `{record['contract_version']}`, resolution rule `{record['resolution_rule']}`, "
        f"protocol merged {record['protocol_merged_at_utc']}.",
        "",
        "A player stated at 25, 50 or 75 in one gameweek's decision capture, read again in the",
        "next gameweek's decision capture. A retrospective pair is one whose later state could",
        "already have been seen when the protocol merged; it is shown and never pooled with the",
        "prospective pairs. A gameweek with no following decision capture has no pair, which is",
        "absent rather than zero.",
        "",
        "| Pair | Prospective | Stated | Players | Available | Doubtful | Out | Absent | Unknown "
        "| Available share [90% Wilson] |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for pair in record["pairs"]:
        label = f"GW{pair['earlier']['gameweek']} to GW{pair['later']['gameweek']}"
        for cell in pair["cells"]:
            counts = cell["counts"]
            stated = "all" if cell["stated_chance"] is None else str(cell["stated_chance"])
            lines.append(
                f"| {label} | {'yes' if pair['prospective'] else 'no'} | {stated} | "
                f"{cell['players_stated']} | {counts['available']} | {counts['doubtful']} | "
                f"{counts['out']} | {counts['absent']} | {counts['unknown']} | "
                f"{_share(cell, 'available')} |"
            )
    missing = record["gameweeks_without_partner"]
    if missing:
        lines += ["", "No pair for gameweek(s) " + ", ".join(str(w) for w in missing) + "."]
    lines += [
        "",
        "Counts describe this season's captures. No share is a calibrated probability, and",
        "nothing here changes a forecast, a planner or a member page.",
    ]
    return "\n".join(lines) + "\n"


def run(snapshot_root: Path, protocol_merged_at: str, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=False)
    record = measure(snapshot_root, protocol_merged_at)
    (output / "record.json").write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--protocol-merged-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = run(arguments.snapshot_root, arguments.protocol_merged_at, arguments.output)
    print(
        json.dumps(
            {
                "pairs": len(result["pairs"]),
                "prospective_pairs": result["prospective_pairs"],
                "gameweeks_without_partner": result["gameweeks_without_partner"],
            }
        )
    )
