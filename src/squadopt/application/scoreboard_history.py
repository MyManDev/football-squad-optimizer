"""Read-only settlement of the scoreboard from verified event-live captures."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pandas as pd

from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live import LedgerEntry, infer_season


def settled_scoreboard_entries(
    entries: Sequence[LedgerEntry],
    snapshots: Sequence[CapturedSnapshot],
    *,
    season: str,
    as_of_utc: str,
) -> tuple[LedgerEntry, ...]:
    """Attach checked event-live results in memory, never rewrite the private ledger.

    Choose the latest settled capture visible at the publication cutoff. Each outcome
    retains its source. A capture from another season cannot settle a repeating GW ID.
    """
    captures = sorted(
        (
            snapshot
            for snapshot in snapshots
            if BOOTSTRAP_PAYLOAD in snapshot.payloads
            and as_instant(snapshot.metadata.captured_at_utc) <= as_instant(as_of_utc)
            and infer_season(snapshot) == season
        ),
        key=lambda snapshot: (
            as_instant(snapshot.metadata.captured_at_utc),
            snapshot.metadata.snapshot_id,
        ),
        reverse=True,
    )
    results: list[LedgerEntry] = []
    for entry in entries:
        if entry.season != season:
            raise DataError("Scoreboard ledger entry belongs to another season.")
        source = next(
            (
                capture
                for capture in captures
                if live_payload(entry.gameweek) in capture.payloads
                and entry.gameweek in scored_gameweeks(capture.payloads[BOOTSTRAP_PAYLOAD])
            ),
            None,
        )
        if source is None:
            results.append(entry)
            continue
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
