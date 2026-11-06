"""Build requested-answer history from an offline store and retained captures."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import jsonschema

from squadopt.platform.requested_suggestion_history import (
    build_requested_history as build_requested_history,
)


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
