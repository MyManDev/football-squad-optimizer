"""Deprecated manual capture shell; scheduled callers use ``squadopt season tick``."""

import argparse
import sys
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.platform.fpl_capture import capture

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--entries",
        action="store_true",
        help=(
            "also read the three documents each registered entry publishes, from "
            f"{REGISTRY_PATH.relative_to(REPOSITORY_ROOT).as_posix()} "
            "(seed it first with scripts.seed_entry_registry)"
        ),
    )
    parser.add_argument(
        "--league",
        type=int,
        help="also record this classic league's standings page in the capture",
    )
    arguments = parser.parse_args()
    if arguments.list:
        identifiers = list_snapshot_ids(SNAPSHOT_ROOT)
        if not identifiers:
            print(f"No snapshots under {SNAPSHOT_ROOT}.")
            return 0
        print(f"{len(identifiers)} snapshot(s) under {SNAPSHOT_ROOT}:")
        for identifier in identifiers:
            metadata = read_snapshot(SNAPSHOT_ROOT, identifier).metadata
            print(f"  {identifier}  captured {metadata.captured_at_utc}")
        return 0
    if arguments.entries and not REGISTRY_PATH.is_file():
        print(f"\nNo entry registry at {REGISTRY_PATH}.")
        print("Seed it first: python -m scripts.seed_entry_registry --league <id>")
        return 1
    try:
        written = capture(
            SNAPSHOT_ROOT,
            archive_root=ARCHIVE_ROOT,
            dry_run=bool(arguments.dry_run),
            entry_registry=REGISTRY_PATH if arguments.entries else None,
            league_id=arguments.league,
        )
    except DataError as error:
        print(f"\nThe capture does not satisfy the adapter contract:\n  {error}")
        return 1
    if written is None:
        print("\nDry run: nothing written.")
        return 0
    print(f"\nWrote snapshot {written.snapshot_id}")
    print(f"  fingerprint    {written.fingerprint}")
    print(f"  directory      {SNAPSHOT_ROOT / written.snapshot_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
