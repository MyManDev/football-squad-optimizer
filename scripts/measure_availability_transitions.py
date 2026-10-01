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
fetched, fitted or scored against a match outcome. Protocol:
``docs/availability_transitions_prereg.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.data.errors import DataError, DataSourceError
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
#: This runner's five classes. The precedence and the status vocabulary are the
#: availability rule's; the classes, and ``unknown`` where that rule would stop, are ours.
CLASSIFICATION_VERSION: Final = "availability_transitions_classes_v1"
#: The stated chances the window consumer turns into an information branch.
STATED_CHANCES: Final = (25, 50, 75)
#: What the next decision capture can say. ``absent`` is a player the later capture no
#: longer lists; ``unknown`` is a status the rule does not know or a chance outside 0 to
#: 100. Both are reported as their own count, never folded into another class or zero.
OUTCOME_CLASSES: Final = ("available", "doubtful", "out", "absent", "unknown")
#: Below this many stated players a cell's interval is printed and marked thin.
SMALL_SAMPLE: Final = 10
#: Two-sided 90 percent, the interval width the repository's other records use.
Z_90: Final = 1.6448536269514722


class TransitionsRefusal(ValueError):
    """The stored captures or the arguments cannot support the count that was asked for."""


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


def resolve(status: str, chance: float | None) -> str:
    """Read one later-capture row by the availability rule's precedence, into our classes.

    A stated chance wins over the status, as ``apply_availability`` applies it: 100 is
    available, 0 is out, and any chance between them is a partial multiplier, so the
    player is still doubtful. Without a chance the status decides. A status the rule
    does not know would stop that rule; here it is ``unknown``, not a guess, and so is a
    chance outside 0 to 100, which the rule would clip.
    """
    if chance is not None:
        value = int(chance)
        if value == 100:
            return "available"
        if value == 0:
            return "out"
        if 0 < value < 100:
            return "doubtful"
        return "unknown"
    if status == STATUS_AVAILABLE:
        return "available"
    if status == STATUS_DOUBTFUL:
        return "doubtful"
    if status in UNAVAILABLE_STATUSES:
        return "out"
    return "unknown"


def decision_captures(
    snapshot_root: Path,
) -> tuple[dict[int, DecisionCapture], list[dict[str, str]]]:
    """One decision capture per gameweek, and the captures that were no decision at all.

    The decision capture is the latest capture whose open deadline is that week, the rule
    the prospective football protocol scores from. A capture with no bootstrap payload,
    one whose deadlines cannot be read, or one taken after every published deadline
    describes no decision; it is listed as skipped with its reason, not treated as a week.
    """
    if not snapshot_root.is_dir():
        raise TransitionsRefusal(f"No snapshot directory at {snapshot_root}.")
    identifiers = list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    if not identifiers:
        raise TransitionsRefusal(f"No {FPL_LIVE_SOURCE} captures under {snapshot_root}.")
    chosen: dict[int, DecisionCapture] = {}
    skipped: list[dict[str, str]] = []
    for identifier in identifiers:
        snapshot = read_snapshot(snapshot_root, identifier)
        bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
        if bootstrap is None:
            skipped.append({"snapshot_id": identifier, "reason": "no_bootstrap_payload"})
            continue
        captured_at_utc = snapshot.metadata.captured_at_utc
        try:
            deadlines = gameweek_deadlines(bootstrap)
        except DataError:
            skipped.append({"snapshot_id": identifier, "reason": "deadlines_unreadable"})
            continue
        try:
            deadline = next_open_deadline(deadlines, as_of_utc=captured_at_utc)
        except DataSourceError:
            skipped.append({"snapshot_id": identifier, "reason": "after_every_deadline"})
            continue
        candidate = DecisionCapture(
            deadline.gameweek, identifier, captured_at_utc, deadline.deadline_utc, bootstrap
        )
        held = chosen.get(candidate.gameweek)
        if held is None or as_instant(candidate.captured_at_utc) > as_instant(held.captured_at_utc):
            chosen[candidate.gameweek] = candidate
    return chosen, skipped


def _share(successes: int, trials: int) -> dict[str, Any] | None:
    interval = wilson_interval(successes, trials)
    if interval is None:
        return None
    return {"value": successes / trials, "wilson_90": list(interval)}


def cell_from_outcomes(stated: int | None, outcomes: Mapping[str, Sequence[int]]) -> dict[str, Any]:
    """One cell: counts, codes, shares with their interval, and the share among the resolved.

    ``available_among_resolved`` reads available against available plus out, the two
    states the planner's binary branch can represent; a player still doubtful is
    unresolved, not evidence either way.
    """
    counts = {name: len(outcomes[name]) for name in OUTCOME_CLASSES}
    trials = sum(counts.values())
    resolved = counts["available"] + counts["out"]
    return {
        "stated_chance": stated,
        "players_stated": trials,
        "small_sample": trials < SMALL_SAMPLE,
        "counts": counts,
        "players": {name: sorted(outcomes[name]) for name in OUTCOME_CLASSES},
        "shares": (
            None
            if trials == 0
            else {name: _share(counts[name], trials) for name in OUTCOME_CLASSES}
        ),
        "available_among_resolved": _share(counts["available"], resolved),
    }


def _outcomes(
    codes: Sequence[int], later: pd.DataFrame, chances: pd.Series
) -> dict[str, list[int]]:
    outcomes: dict[str, list[int]] = {name: [] for name in OUTCOME_CLASSES}
    for code in codes:
        if code not in later.index:
            outcomes["absent"].append(code)
            continue
        chance = chances.loc[code]
        outcomes[
            resolve(str(later.loc[code, "status"]), None if pd.isna(chance) else float(chance))
        ].append(code)
    return outcomes


def pair_transitions(earlier: DecisionCapture, later: DecisionCapture) -> dict[str, Any]:
    """How every player stated at 25, 50 or 75 in the earlier capture stood in the later one."""
    if later.gameweek != earlier.gameweek + 1:
        raise TransitionsRefusal("A pair is two consecutive decision captures.")
    if as_instant(later.captured_at_utc) <= as_instant(earlier.deadline_utc):
        raise TransitionsRefusal(
            f"The later decision capture {later.snapshot_id} must follow the earlier "
            f"deadline {earlier.deadline_utc}; a moved deadline is a different week."
        )
    before = availability_snapshot(earlier.bootstrap)
    if before.player_id.duplicated().any():
        raise TransitionsRefusal(f"The earlier capture {earlier.snapshot_id} repeats a player.")
    after = availability_snapshot(later.bootstrap).set_index("player_id")
    if after.index.duplicated().any():
        raise TransitionsRefusal(f"The later capture {later.snapshot_id} repeats a player.")
    chances = pd.to_numeric(after.chance_of_playing, errors="coerce")
    stated = pd.to_numeric(before.chance_of_playing, errors="coerce")
    cells = []
    for chance in STATED_CHANCES:
        codes = [int(code) for code in before.loc[stated.eq(chance), "player_id"]]
        cells.append(cell_from_outcomes(chance, _outcomes(codes, after, chances)))
    pooled = [int(code) for code in before.loc[stated.isin(STATED_CHANCES), "player_id"]]
    cells.append(cell_from_outcomes(None, _outcomes(pooled, after, chances)))
    return {"earlier": earlier.identity(), "later": later.identity(), "cells": cells}


def pooled_prospective(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The reading's figure: prospective pairs only, per stated chance and over the three.

    Counts are player-pairs; a player doubtful in two consecutive decisions is two
    observations. Retrospective pairs never enter here.
    """
    kept = [pair for pair in pairs if pair["prospective"]]
    cells = []
    for stated in (*STATED_CHANCES, None):
        outcomes: dict[str, list[int]] = {name: [] for name in OUTCOME_CLASSES}
        for pair in kept:
            cell = next(c for c in pair["cells"] if c["stated_chance"] == stated)
            for name in OUTCOME_CLASSES:
                outcomes[name].extend(cell["players"][name])
        cells.append(cell_from_outcomes(stated, outcomes))
    return {"pairs": len(kept), "cells": cells}


def measure(
    snapshot_root: Path,
    protocol_merged_at: str,
    *,
    protocol_commit: str | None = None,
    through_gameweek: int | None = None,
) -> dict[str, Any]:
    """Every consecutive pair of decision captures under ``snapshot_root``, read once."""
    merged = normalize_utc_timestamp(protocol_merged_at, label="protocol merge instant")
    if through_gameweek is not None and (
        isinstance(through_gameweek, bool) or not 1 <= through_gameweek <= 38
    ):
        raise TransitionsRefusal("through_gameweek must be a gameweek in 1..38.")
    captures, skipped = decision_captures(snapshot_root)
    pairs: list[dict[str, Any]] = []
    without_partner: list[int] = []
    for gameweek in sorted(captures):
        later = captures.get(gameweek + 1)
        if later is None:
            without_partner.append(gameweek)
            continue
        if through_gameweek is not None and later.gameweek > through_gameweek:
            continue
        pair = pair_transitions(captures[gameweek], later)
        # Prospective means the earlier week's decision was still open when the protocol
        # merged; a pair whose later state could already have been seen is retrospective.
        pair["prospective"] = as_instant(captures[gameweek].deadline_utc) > as_instant(merged)
        pairs.append(pair)
    return {
        "artifact_type": "availability_transitions",
        "contract_version": CONTRACT_VERSION,
        "classification": CLASSIFICATION_VERSION,
        "precedence_from": AVAILABILITY_RULE_CONTRACT_VERSION,
        "stated_chances": list(STATED_CHANCES),
        "outcome_classes": list(OUTCOME_CLASSES),
        "interval": "wilson_90",
        "small_sample_below": SMALL_SAMPLE,
        "protocol_merged_at_utc": merged,
        "protocol_commit": protocol_commit,
        "through_gameweek": through_gameweek,
        "captures_read": len(list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)),
        "captures_skipped": skipped,
        "decision_captures": [captures[week].identity() for week in sorted(captures)],
        "pairs": pairs,
        "prospective_pairs": sum(bool(pair["prospective"]) for pair in pairs),
        "pooled_prospective": pooled_prospective(pairs),
        "gameweeks_without_partner": without_partner,
        "news_text_included": False,
        "outcomes_read": False,
        "measurement_only": True,
        "gate_evidence": False,
        "locked_holdout_accessed": False,
    }


def _interval(share: Mapping[str, Any] | None) -> str:
    if share is None:
        return "not observed"
    low, high = share["wilson_90"]
    return f"{share['value']:.2f} [{low:.2f}, {high:.2f}]"


def _row(label: str, prospective: str, cell: Mapping[str, Any]) -> str:
    counts = cell["counts"]
    stated = "all" if cell["stated_chance"] is None else str(cell["stated_chance"])
    available = _interval(None if cell["shares"] is None else cell["shares"]["available"])
    if cell["small_sample"]:
        available += " thin"
    return (
        f"| {label} | {prospective} | {stated} | {cell['players_stated']} | "
        f"{counts['available']} | {counts['doubtful']} | {counts['out']} | {counts['absent']} | "
        f"{counts['unknown']} | {available} | {_interval(cell['available_among_resolved'])} |"
    )


_HEADER: Final = (
    "| Pair | Prospective | Stated | Players | Available | Doubtful | Out | Absent | Unknown "
    "| Available share [90% Wilson] | Available among resolved |",
    "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
)


def summary(record: Mapping[str, Any]) -> str:
    """The record as prose and two tables; counts are counts, shares carry their interval."""
    pooled = record["pooled_prospective"]
    lines = [
        "# How stated playing chances resolved by the next decision",
        "",
        f"Contract `{record['contract_version']}`, classes `{record['classification']}` with the "
        f"precedence of `{record['precedence_from']}`, protocol merged "
        f"{record['protocol_merged_at_utc']}"
        + (f" at `{record['protocol_commit']}`" if record.get("protocol_commit") else "")
        + ".",
        "",
        "A player stated at 25, 50 or 75 in one gameweek's decision capture, read again in the",
        "next gameweek's decision capture. A retrospective pair is one whose earlier deadline",
        "had already passed when the protocol merged, so its later state could have been seen;",
        "it is shown and never pooled with the prospective pairs. A gameweek with no following",
        "decision capture has no pair, which is absent rather than zero. An interval on fewer",
        f"than {record['small_sample_below']} stated players is marked thin. Available among",
        "resolved reads available against available plus out, the two states the planner's",
        "binary branch can represent.",
        "",
        f"## Pooled over {pooled['pairs']} prospective pair(s)",
        "",
        *_HEADER,
        *(_row("prospective pooled", "yes", cell) for cell in pooled["cells"]),
        "",
        "## Per pair",
        "",
        *_HEADER,
    ]
    for pair in record["pairs"]:
        label = f"GW{pair['earlier']['gameweek']} to GW{pair['later']['gameweek']}"
        lines.extend(
            _row(label, "yes" if pair["prospective"] else "no", cell) for cell in pair["cells"]
        )
    missing = record["gameweeks_without_partner"]
    if missing:
        lines += ["", "No pair for gameweek(s) " + ", ".join(str(w) for w in missing) + "."]
    if record["captures_skipped"]:
        lines += [
            "",
            "Captures that were no decision: "
            + ", ".join(f"{s['snapshot_id']} ({s['reason']})" for s in record["captures_skipped"])
            + ".",
        ]
    lines += [
        "",
        "Counts describe this season's captures. No share is a calibrated probability, and",
        "nothing here changes a forecast, a planner or a member page.",
    ]
    return "\n".join(lines) + "\n"


def _refuse_destination(output: Path, snapshot_root: Path) -> None:
    """The record goes into a fresh directory of the operator's, never into the inputs or data/."""
    target = output.resolve()
    for forbidden, why in (
        (snapshot_root.resolve(), "inside the snapshot root"),
        (Path("data").resolve(), "under data/"),
        (Path("docs").resolve(), "under docs/"),
    ):
        if target == forbidden or forbidden in target.parents:
            raise TransitionsRefusal(f"Refusing to write {why}: {output}.")


def run(
    snapshot_root: Path,
    protocol_merged_at: str,
    output: Path,
    *,
    protocol_commit: str | None = None,
    through_gameweek: int | None = None,
) -> dict[str, Any]:
    """Measure first, then create the directory, so a refusal leaves nothing behind."""
    _refuse_destination(output, snapshot_root)
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    record = measure(
        snapshot_root,
        protocol_merged_at,
        protocol_commit=protocol_commit,
        through_gameweek=through_gameweek,
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "record.json").write_text(
        json.dumps(record, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "summary.md").write_text(summary(record), encoding="utf-8")
    return record


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--protocol-merged-at", required=True)
    parser.add_argument("--protocol-commit", default=None)
    parser.add_argument("--through-gameweek", type=int, default=None)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        result = run(
            arguments.snapshot_root,
            arguments.protocol_merged_at,
            arguments.output,
            protocol_commit=arguments.protocol_commit,
            through_gameweek=arguments.through_gameweek,
        )
    except (TransitionsRefusal, FileExistsError, DataError, ValueError) as error:
        print(f"Refused: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "pairs": len(result["pairs"]),
                "prospective_pairs": result["prospective_pairs"],
                "gameweeks_without_partner": result["gameweeks_without_partner"],
                "captures_skipped": len(result["captures_skipped"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
