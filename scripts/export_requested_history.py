"""Export completed server answers from an offline backend-store snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from squadopt.platform.requested_suggestion_history import requested_history as requested_history


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-snapshot", required=True, type=Path)
    parser.add_argument("--season", required=True)
    parser.add_argument("--gameweek", required=True, type=int)
    parser.add_argument("--entry-id", required=True, type=int)
    parser.add_argument("--deadline-utc", required=True)
    args = parser.parse_args(argv)
    try:
        document = requested_history(
            args.store_snapshot,
            season=args.season,
            gameweek=args.gameweek,
            entry_id=args.entry_id,
            deadline_utc=args.deadline_utc,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Requested history export refused: {error}", file=sys.stderr)
        return 1
    print(json.dumps(document, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
