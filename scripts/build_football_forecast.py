"""Build a capture-specific optional football artifact; never replaces the current handoff."""

import argparse
import json
from pathlib import Path

from squadopt.application.football_live import (
    produce_football_components,
    produce_football_forecast,
)
from squadopt.application.manager_words import load_manager_words
from squadopt.data.snapshots import read_snapshot
from squadopt.live import infer_season, read_inputs
from squadopt.platform.football_publication import publish_football_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--training-season",
        action="append",
        dest="training_seasons",
        help="Allowed training season; repeat for every archive/current season to include. "
        "Excluded seasons are not read. Omit to retain the existing training population.",
    )
    parser.add_argument("--contextual", action="store_true", help="Build football_contextual_v3.")
    parser.add_argument(
        "--role-minutes",
        action="store_true",
        help="Fit joint starting/substitute minutes using the explicit training-season allowlist.",
    )
    parser.add_argument(
        "--with-components",
        action="store_true",
        help="Publish the forecast and its verified fixture companion from one model fit.",
    )
    parser.add_argument("--rotation-evidence", type=Path)
    parser.add_argument("--club-news-source", type=Path)
    args = parser.parse_args()
    if args.role_minutes and (args.contextual or not args.training_seasons):
        parser.error("--role-minutes requires --training-season and excludes --contextual")
    if args.with_components and args.contextual:
        parser.error("--with-components does not support --contextual")
    if bool(args.rotation_evidence) != bool(args.club_news_source):
        parser.error("--rotation-evidence and --club-news-source must be supplied together")
    if args.with_components and args.rotation_evidence:
        parser.error("--with-components does not accept contextual manager inputs")
    snapshot = read_snapshot(args.snapshot_root, args.snapshot_id)
    words = (
        load_manager_words(
            args.rotation_evidence,
            club_news_source=args.club_news_source,
            snapshot_root=args.snapshot_root,
        )
        if args.rotation_evidence
        else None
    )
    if args.with_components:
        document, companion = produce_football_components(
            snapshot,
            args.archive_root,
            training_seasons=args.training_seasons,
            **({"role_minutes": True} if args.role_minutes else {}),
        )
    else:
        document = produce_football_forecast(
            snapshot,
            args.archive_root,
            contextual=args.contextual,
            manager_words=words,
            training_seasons=args.training_seasons,
            **({"role_minutes": True} if args.role_minutes else {}),
        )
        companion = None
    publish_football_artifacts(
        artifact_root=args.artifact_root,
        snapshot=snapshot,
        inputs=read_inputs(snapshot, season=infer_season(snapshot)),
        document=document,
        companion=companion,
    )
    print(
        json.dumps(
            {
                "fingerprint": document["fingerprint"],
                "rows": len(document["rows"]),
                "model_version": document["model_version"],
                **(
                    {"components_fingerprint": companion["fingerprint"]}
                    if companion is not None
                    else {}
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
