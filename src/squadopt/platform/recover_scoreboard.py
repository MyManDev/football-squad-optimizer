"""Collect public settled outcomes and reconcile surviving publication records.

Writes only to explicitly supplied artifact/output roots. A new capture is stamped
now and never presented as a recovered pre-deadline capture.
"""

import argparse
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from squadopt.application.scoreboard import scoreboard_payload
from squadopt.application.scoreboard_recovery import (
    enrich_recovered_scoreboard,
    load_publication_recovery,
)
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    live_payload,
    scored_gameweeks,
)
from squadopt.platform.fpl_capture import BASE_URL, fetch


def recovery_scoreboard(
    *,
    snapshot: CapturedSnapshot,
    publication_root: Path,
    advice_root: Path,
    league_id: int,
    entry_ids: tuple[int, ...],
) -> dict[str, object]:
    recovery = load_publication_recovery(
        snapshot=snapshot,
        publication_root=publication_root,
        advice_root=advice_root,
        league_id=league_id,
        entry_ids=entry_ids,
    )
    document = scoreboard_payload(
        season=recovery.entry.season,
        league_id=league_id,
        bootstrap=snapshot.payloads[BOOTSTRAP_PAYLOAD],
        captured_at_utc=snapshot.metadata.captured_at_utc,
        source_snapshot_id=snapshot.metadata.snapshot_id,
        histories={
            entry_id: snapshot.payloads[name]
            for entry_id in entry_ids
            if (name := f"entry-{entry_id}-history.json") in snapshot.payloads
        },
        registered=entry_ids,
        ledger_entries=(recovery.entry,),
        cohort=None,
        generated_at_utc=snapshot.metadata.captured_at_utc,
        pending_gameweeks=(4,) if recovery.records else (),
    )
    enrich_recovered_scoreboard(document, recovery, snapshot)
    return document


def collect_outcomes(root: Path, *, entry_ids: tuple[int, ...]) -> CapturedSnapshot:
    bootstrap = fetch(f"{BASE_URL}/bootstrap-static/")
    weeks = tuple(week for week in scored_gameweeks(bootstrap) if week <= 4)
    endpoints = {live_payload(week): f"event/{week}/live/" for week in weeks}
    for entry_id in entry_ids:
        endpoints[f"entry-{entry_id}-history.json"] = f"entry/{entry_id}/history/"
        for week in weeks:
            endpoints[f"entry-{entry_id}-picks-gw{week:02d}.json"] = (
                f"entry/{entry_id}/event/{week}/picks/"
            )
    payloads = {BOOTSTRAP_PAYLOAD: bootstrap}

    def read(item: tuple[str, str]) -> tuple[str, bytes]:
        name, endpoint = item
        return name, fetch(f"{BASE_URL}/{endpoint}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        payloads.update(executor.map(read, sorted(endpoints.items())))
    payloads["collection-purpose.json"] = json.dumps(
        {
            "purpose": "public_settled_outcomes",
            "historical_availability": "not_recovered",
            "endpoints": endpoints,
        },
        sort_keys=True,
    ).encode()
    metadata = write_snapshot(
        root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=datetime.now(UTC).isoformat(),
        payloads=payloads,
    )
    return read_snapshot(root, metadata.snapshot_id)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--advice-root", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", help="replay an existing outcome collection offline")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--league", type=int, default=352490)
    args = parser.parse_args(argv)
    entry_ids = tuple(
        sorted(
            int(path.name.removeprefix("entry-"))
            for path in (args.advice_root / "2026-27/gw04").glob("entry-*")
            if path.is_dir()
        )
    )
    snapshot = (
        read_snapshot(args.capture_root, args.snapshot_id)
        if args.snapshot_id
        else collect_outcomes(args.capture_root, entry_ids=entry_ids)
    )
    document = recovery_scoreboard(
        snapshot=snapshot,
        publication_root=args.publication_root,
        advice_root=args.advice_root,
        league_id=args.league,
        entry_ids=entry_ids,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "snapshot_id": snapshot.metadata.snapshot_id,
                "entries": len(entry_ids),
                "output": str(args.out),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
