"""Build a capture-specific optional football artifact; never replaces the current handoff."""

import argparse
import json
from pathlib import Path
from typing import Any

from squadopt.application.football_live import (
    LOCKED_OUTCOME_SEASON,
    TEAM_FORM_ARCHIVE_SEASONS,
    produce_flagged_football_components,
    produce_football_components,
    produce_football_forecast,
    reconstruct_flag_training,
)
from squadopt.application.manager_words import load_manager_words
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live import infer_season, read_inputs
from squadopt.platform.football_publication import publish_football_artifacts


def _flag_pairs(
    root: Path, target: CapturedSnapshot, pairs: list[list[str]]
) -> tuple[tuple[CapturedSnapshot, CapturedSnapshot], ...]:
    """Exclude other-season and target-time files before opening any outcome payload."""
    bootstrap = json.loads(target.payloads[BOOTSTRAP_PAYLOAD])
    first_deadline = min(as_instant(event["deadline_time"]) for event in bootstrap["events"])
    cutoff = as_instant(target.metadata.captured_at_utc)
    root = root.resolve()
    for pair in pairs:
        for identifier in pair:
            directory = (root / identifier).resolve()
            if directory.parent != root:
                raise ValueError("A training capture must be a direct child of --snapshot-root.")
            metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
            captured = as_instant(
                normalize_utc_timestamp(metadata["captured_at_utc"], label="training capture")
            )
            if not first_deadline <= captured < cutoff:
                raise ValueError(
                    "Training capture clocks must follow this season's first deadline "
                    "and precede the target capture; no outcome payload was opened."
                )
    return tuple(
        (read_snapshot(root, before), read_snapshot(root, after)) for before, after in pairs
    )


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
        "--team-form",
        action="store_true",
        help="Build the separate football_team_form_v1 candidate from explicit training seasons.",
    )
    parser.add_argument(
        "--match-context",
        action="store_true",
        help="Build football_match_context_v1 with PL workload and venue defense; "
        "requires an explicit permitted training-season allowlist.",
    )
    parser.add_argument(
        "--role-minutes",
        action="store_true",
        help="Fit joint starting/substitute minutes using the explicit training-season allowlist.",
    )
    parser.add_argument(
        "--retained-role-history",
        action="store_true",
        help="Select the retained-history joint role candidate; requires --role-minutes "
        "and --with-components. The existing model remains the default.",
    )
    parser.add_argument(
        "--flag-training-capture",
        action="append",
        nargs=2,
        metavar=("BEFORE", "SETTLED"),
        help="Original same-season pre-decision and settled capture IDs; repeat per training "
        "week. Fits categorical flags on causal native reconstructions, for the first week only.",
    )
    parser.add_argument(
        "--flag-decision-at",
        help="Explicit UTC decision time for learned flags; strictly after the target capture "
        "and before its deadline. Requires --flag-training-capture.",
    )
    parser.add_argument(
        "--with-components",
        action="store_true",
        help="Publish the forecast and its verified fixture companion from one model fit.",
    )
    parser.add_argument("--rotation-evidence", type=Path)
    parser.add_argument("--club-news-source", type=Path)
    args = parser.parse_args()
    if args.team_form and (args.contextual or args.role_minutes or not args.training_seasons):
        parser.error(
            "--team-form requires --training-season and excludes --contextual/--role-minutes"
        )
    if args.team_form and LOCKED_OUTCOME_SEASON in args.training_seasons:
        parser.error(
            f"--team-form cannot read the locked {LOCKED_OUTCOME_SEASON} outcome population"
        )
    if args.match_context and (
        not args.training_seasons
        or args.contextual
        or args.role_minutes
        or args.retained_role_history
        or args.rotation_evidence
        or args.club_news_source
        or args.team_form
    ):
        parser.error(
            "--match-context requires --training-season "
            "and excludes other candidates/manager inputs"
        )
    if args.match_context and "2025-26" in args.training_seasons:
        parser.error("--match-context cannot read the locked 2025-26 outcome population")
    if args.role_minutes and (args.contextual or not args.training_seasons):
        parser.error("--role-minutes requires --training-season and excludes --contextual")
    if args.retained_role_history and not (args.role_minutes and args.with_components):
        parser.error("--retained-role-history requires --role-minutes and --with-components")
    if args.with_components and args.contextual:
        parser.error("--with-components does not support --contextual")
    if bool(args.rotation_evidence) != bool(args.club_news_source):
        parser.error("--rotation-evidence and --club-news-source must be supplied together")
    if args.with_components and args.rotation_evidence:
        parser.error("--with-components does not accept contextual manager inputs")
    if bool(args.flag_training_capture) != bool(args.flag_decision_at):
        parser.error("--flag-training-capture and --flag-decision-at must be supplied together")
    if args.flag_training_capture and not args.retained_role_history:
        parser.error("--flag-training-capture requires --retained-role-history")
    snapshot = read_snapshot(args.snapshot_root, args.snapshot_id)
    if args.flag_training_capture:
        season = infer_season(snapshot)
        archives = (
            *TEAM_FORM_ARCHIVE_SEASONS,
            *((LOCKED_OUTCOME_SEASON,) if LOCKED_OUTCOME_SEASON in args.training_seasons else ()),
        )
        if season == LOCKED_OUTCOME_SEASON or sorted(args.training_seasons) != sorted(
            (*archives, season)
        ):
            parser.error(
                "Learned flags require the three permitted archives and target season; "
                "2025-26 may be explicitly included in native history."
            )
        decision = as_instant(normalize_utc_timestamp(args.flag_decision_at, label="flag decision"))
        inputs = read_inputs(snapshot, season=season)
        if (
            not as_instant(inputs.captured_at_utc)
            < decision
            < as_instant(inputs.deadline.deadline_utc)
        ):
            parser.error(
                "The flag decision must follow the target capture and precede its deadline"
            )
    variant_options: dict[str, Any] = {}
    for name in ("role_minutes", "retained_role_history", "team_form", "match_context"):
        if getattr(args, name):
            variant_options[name] = True
    words = (
        load_manager_words(
            args.rotation_evidence,
            club_news_source=args.club_news_source,
            snapshot_root=args.snapshot_root,
        )
        if args.rotation_evidence
        else None
    )
    if args.flag_training_capture:
        training = reconstruct_flag_training(
            snapshot,
            args.archive_root,
            _flag_pairs(args.snapshot_root, snapshot, args.flag_training_capture),
            include_2025_26_history=LOCKED_OUTCOME_SEASON in args.training_seasons,
        )
        document, companion = produce_flagged_football_components(
            snapshot,
            args.archive_root,
            training=training,
            decision_at=args.flag_decision_at,
            include_2025_26_history=LOCKED_OUTCOME_SEASON in args.training_seasons,
        )
    elif args.with_components:
        document, companion = produce_football_components(
            snapshot,
            args.archive_root,
            training_seasons=args.training_seasons,
            **variant_options,
        )
    else:
        document = produce_football_forecast(
            snapshot,
            args.archive_root,
            contextual=args.contextual,
            manager_words=words,
            training_seasons=args.training_seasons,
            **variant_options,
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
