"""Read-only scoreboard settlement from verified event-live captures."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pandas as pd

from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live import LedgerEntry, infer_season


def settled_scoreboard_entries(
    entries: Sequence[LedgerEntry],
    snapshots: Iterable[CapturedSnapshot],
    *,
    season: str,
    as_of_utc: str,
) -> tuple[LedgerEntry, ...]:
    """Settle in memory using the latest checked capture at the publication cutoff.

    Scan the archive once and retain at most one source per requested gameweek.
    The caller verifies ledger manifests and capture digests. Missing captures keep
    legacy outcomes and their stated scoring basis; no decision is reconstructed.
    """
    if not entries:
        return ()
    if any(entry.season != season for entry in entries):
        raise DataError("Scoreboard ledger entry belongs to another season.")
    cutoff = as_instant(as_of_utc)
    weeks = {entry.gameweek for entry in entries}
    sources: dict[int, tuple[datetime, str, CapturedSnapshot]] = {}
    for snapshot in snapshots:
        at = as_instant(snapshot.metadata.captured_at_utc)
        if (
            at > cutoff
            or BOOTSTRAP_PAYLOAD not in snapshot.payloads
            or infer_season(snapshot) != season
        ):
            continue
        bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
        deadlines = {
            row.gameweek: as_instant(row.deadline_utc) for row in gameweek_deadlines(bootstrap)
        }
        for week in weeks & scored_gameweeks(bootstrap):
            if live_payload(week) not in snapshot.payloads or at <= deadlines[week]:
                continue
            key = (at, snapshot.metadata.snapshot_id)
            if week not in sources or key > sources[week][:2]:
                sources[week] = (*key, snapshot)
    results: list[LedgerEntry] = []
    for entry in entries:
        if entry.gameweek not in sources:
            results.append(entry)
            continue
        source = sources[entry.gameweek][2]
        projections_path = Path(entry.directory) / "projections.csv"
        if not projections_path.is_file():
            raise DataError(f"Frozen projections missing for GW{entry.gameweek}.")
        outcomes = live_event_outcomes(
            source.payloads[live_payload(entry.gameweek)],
            source.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=entry.gameweek,
        )
        scored = score_recorded_decision(entry.decision, pd.read_csv(projections_path), outcomes)
        results.append(
            replace(
                entry,
                outcome={
                    **dict(entry.outcome or {}),
                    "realized_net_score": scored["net"],
                    "realized_xi_score": scored["xi"],
                    "scoring_basis": scored["scoring_basis"],
                    "diagnostics": scored["diagnostics"],
                    "source_snapshot_id": source.metadata.snapshot_id,
                },
            )
        )
    return tuple(results)
