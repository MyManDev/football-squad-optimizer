"""Seal already produced football inputs; no fetch, model fit, or runtime activation."""

import argparse
import json
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.platform.football_bundle import seal_football_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument("--site-data-root", required=True, type=Path)
    parser.add_argument("--news-capture-id")
    parser.add_argument("--rotation-table", type=Path)
    parser.add_argument("--official-injury-capture-id")
    args = parser.parse_args(argv)
    try:
        bundle = seal_football_bundle(
            artifact_root=args.artifact_root,
            snapshot_root=args.snapshot_root,
            snapshot_id=args.snapshot_id,
            handoff_path=args.handoff,
            site_data_root=args.site_data_root,
            news_capture_id=args.news_capture_id,
            rotation_table_path=args.rotation_table,
            official_injury_capture_id=args.official_injury_capture_id,
        )
    except (DataError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Refused: {error}")
        return 1
    print(
        json.dumps(
            {
                "status": "ready",
                "snapshot_id": bundle.snapshot_id,
                "season": bundle.season,
                "gameweek": bundle.gameweek,
                "bundle_sha256": bundle.fingerprint,
                "news_capture_id": bundle.news_capture_id,
                "official_injury_capture_id": bundle.official_injury_capture_id,
                "activation": "not_performed",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
