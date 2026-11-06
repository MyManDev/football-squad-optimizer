"""Build a site's requested-answer history from an offline store and retained captures."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import jsonschema
from scripts.export_requested_history import requested_history

from squadopt.application.weekly_suggestion_eval import CONTRACT_VERSION
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE, gameweek_deadlines
from squadopt.data.timestamps import as_instant
from squadopt.live.recommendation import infer_season
from squadopt.platform.history_documents import history_schema
from squadopt.platform.requested_suggestion_history import requested_week


def build_requested_history(
    *,
    store_snapshot: Path,
    snapshot_root: Path,
    as_of_snapshot_id: str,
    league_id: int,
    entry_id: int,
    gameweeks: Sequence[int],
    out_dir: Path,
) -> Path:
    """Write only history/requested/{entry}.json; leave legacy history files untouched."""
    if type(league_id) is not int or league_id < 1 or type(entry_id) is not int or entry_id < 1:
        raise ValueError("History publication requires a positive league and entry identity.")
    if not gameweeks or any(type(week) is not int or week < 1 for week in gameweeks):
        raise ValueError("At least one positive gameweek is required.")
    as_of = read_snapshot(snapshot_root, as_of_snapshot_id)
    season = infer_season(as_of)
    deadlines = {
        event.gameweek: event.deadline_utc
        for event in gameweek_deadlines(as_of.payloads[BOOTSTRAP_PAYLOAD])
    }
    captures = [
        read_snapshot(snapshot_root, identifier)
        for identifier in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE)
    ]
    path = out_dir / "history" / "requested" / f"{entry_id}.json"
    weeks: dict[int, Any] = {}
    if path.exists():
        previous = json.loads(path.read_bytes())
        jsonschema.validate(previous, history_schema())
        payload = previous["payload"]
        if (payload["season"], payload["league_id"], payload["entry_id"]) != (
            season,
            league_id,
            entry_id,
        ):
            raise ValueError("Existing requested history identifies another member or season.")
        if as_instant(previous["generated_at_utc"]) > as_instant(as_of.metadata.captured_at_utc):
            raise ValueError("An older capture cannot replace a newer history publication.")
        for row in payload["weeks"]:
            if row.get("advice_source") != "requested_server" or row["gameweek"] in weeks:
                raise ValueError("Existing requested history has invalid or duplicate weeks.")
            weeks[row["gameweek"]] = row
    for week in sorted(set(gameweeks)):
        if week not in deadlines:
            raise ValueError("The captured FPL calendar has no requested gameweek.")
        exported = requested_history(
            store_snapshot,
            season=season,
            gameweek=week,
            entry_id=entry_id,
            deadline_utc=deadlines[week],
        )
        reviewed = requested_week(exported, captures=captures, as_of=as_of)
        if reviewed is None:
            if week in weeks:
                raise ValueError("The supplied store would erase an existing requested week.")
            continue
        weeks[week] = reviewed
    document = {
        "contract_version": CONTRACT_VERSION,
        "generated_at_utc": as_of.metadata.captured_at_utc,
        "payload": {
            "league_id": league_id,
            "entry_id": entry_id,
            "season": season,
            "as_of_snapshot_id": as_of.metadata.snapshot_id,
            "weeks": [weeks[week] for week in sorted(weeks, reverse=True)],
        },
    }
    jsonschema.validate(document, history_schema())
    raw = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-snapshot", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--as-of-snapshot", required=True)
    parser.add_argument("--league-id", required=True, type=int)
    parser.add_argument("--entry-id", required=True, type=int)
    parser.add_argument("--gameweek", required=True, type=int, action="append")
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        path = build_requested_history(
            store_snapshot=args.store_snapshot,
            snapshot_root=args.snapshot_root,
            as_of_snapshot_id=args.as_of_snapshot,
            league_id=args.league_id,
            entry_id=args.entry_id,
            gameweeks=args.gameweek,
            out_dir=args.out_dir,
        )
    except (OSError, ValueError, KeyError, TypeError, jsonschema.ValidationError) as error:
        print(f"Requested history publication refused: {error}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
