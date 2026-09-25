"""Build a scratch GW5 outcome candidate while retaining the accepted decision bytes.

All inputs are explicit. The ledger must already be settled; this command never
executes a weekly operation. Before the candidate is written it is held to the frozen
schemas, the frozen root index, the outcome capture's fixture list and the league tree
release check (whatever that finds in the candidate and not in the accepted tree); any
finding refuses it. Post its changed-file list for review before a site PR.
"""

import argparse
import sys
from pathlib import Path

from scripts.check_league_tree import Tree, run_checks

from squadopt.application.settled_publication import SettledPublicationRequest, publish_settled
from squadopt.data.errors import DataError


def league_tree_findings(data: Path) -> list[str]:
    """``python -m scripts.check_league_tree <data>``, on the accepted tree and the candidate."""
    print(f"League tree check on {data}:")
    return run_checks(Tree(str(data)))


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
            ),
            league_tree_check=league_tree_findings,
        )
    except (DataError, ValueError, OSError, KeyError, TypeError) as error:
        print(f"Settled publication refused: {error}", file=sys.stderr)
        return 1
    print(f"Scratch candidate: {result.out_dir}")
    print(f"Accepted outcome stamp: {result.generated_at_utc}")
    print("Checked before the candidate was written:")
    for check in result.checks:
        print(f"  {check}")
    season_count = sum(name.startswith(f"data/{args.season}/") for name in result.changed_files)
    print(f"Changed file count: {len(result.changed_files)} ({season_count} season documents)")
    print("Changed files (post this list before a site PR):")
    for name in result.changed_files:
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
