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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--list", action="store_true")
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
    try:
        written = capture(
            SNAPSHOT_ROOT,
            archive_root=ARCHIVE_ROOT,
            dry_run=bool(arguments.dry_run),
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
