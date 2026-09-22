"""Publish all captured FPL players for the contribution form; never run a solver."""

import argparse
from pathlib import Path
from typing import cast

from squadopt.application.player_catalog import player_catalog
from squadopt.application.site import _write_json
from squadopt.application.views import JsonValue
from squadopt.data.snapshots import read_snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--out", type=Path, required=True, help="site public directory")
    args = parser.parse_args()
    catalog = player_catalog(read_snapshot(args.snapshot_root, args.snapshot_id))
    _write_json(args.out / "data/players.json", cast(dict[str, JsonValue], catalog))
    print(f"Published {len(catalog['players'])} players across {len(catalog['teams'])} teams")


if __name__ == "__main__":
    main()
