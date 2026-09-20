"""Build a scratch GW5 outcome candidate while retaining the accepted decision bytes.

All inputs are explicit. The ledger must already be settled; this command never
executes a weekly operation. Post its changed-file list for review before a site PR.
"""

import argparse
import sys
from pathlib import Path

from squadopt.application.settled_publication import SettledPublicationRequest, publish_settled
from squadopt.data.errors import DataError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("accepted-dir", "snapshot-root", "registry", "record-root", "ledger-root", "out"):
        parser.add_argument(f"--{flag}", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--season", required=True, choices=("2026-27",))
    parser.add_argument("--gameweek", type=int, required=True, choices=(5,))
    args = parser.parse_args(argv)
    try:
        result = publish_settled(
            SettledPublicationRequest(
                accepted_dir=args.accepted_dir,
                snapshot_root=args.snapshot_root,
                snapshot_id=args.snapshot_id,
                registry_path=args.registry,
                record_root=args.record_root,
                ledger_root=args.ledger_root,
                out_dir=args.out,
                season=args.season,
                gameweek=args.gameweek,
            )
        )
    except (DataError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"Settled publication refused: {error}", file=sys.stderr)
        return 1
    print(f"Scratch candidate: {result.out_dir}")
    print(f"Accepted outcome stamp: {result.generated_at_utc}")
    season_count = sum(name.startswith(f"data/{args.season}/") for name in result.changed_files)
    print(f"Changed file count: {len(result.changed_files)} ({season_count} season documents)")
    print("Before a site PR, run the candidate check and report its result in #632:")
    print(f'python -m scripts.check_league_tree "{result.out_dir / "data"}"')
    print("Frozen season-schema and root-index consistency still need separate verification.")
    print("Changed files (post this list before a site PR):")
    for name in result.changed_files:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
