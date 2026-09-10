"""Compatibility command for squadopt.application.projection_handoff."""

import argparse
import sys
from pathlib import Path

from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT

from squadopt.application.projection_handoff import (
    COMPONENT_FEATURE_CONTRACT_VERSION as COMPONENT_FEATURE_CONTRACT_VERSION,
)
from squadopt.application.projection_handoff import (
    COMPONENT_HISTORY_WINDOW as COMPONENT_HISTORY_WINDOW,
)
from squadopt.application.projection_handoff import (
    COMPONENT_MODEL_VERSION as COMPONENT_MODEL_VERSION,
)
from squadopt.application.projection_handoff import (
    CONTROL_MODEL_NAME as CONTROL_MODEL_NAME,
)
from squadopt.application.projection_handoff import (
    DEFAULT_HANDOFF_ROOT as DEFAULT_HANDOFF_ROOT,
)
from squadopt.application.projection_handoff import (
    DEFAULT_SNAPSHOT_ROOT as DEFAULT_SNAPSHOT_ROOT,
)
from squadopt.application.projection_handoff import (
    _component_table as _component_table,
)
from squadopt.application.projection_handoff import (
    _frame_fingerprint as _frame_fingerprint,
)
from squadopt.application.projection_handoff import (
    _latest_snapshot_id as _latest_snapshot_id,
)
from squadopt.application.projection_handoff import (
    _team_bridge as _team_bridge,
)
from squadopt.application.projection_handoff import (
    build as _build_handoff,
)
from squadopt.platform.projection_retention import publish_retained_handoff


def build(*args, **kwargs):
    """Retain capture-specific bytes on the historical script API as well."""
    kwargs.setdefault("writer", publish_retained_handoff)
    return _build_handoff(*args, **kwargs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument(
        "--snapshot-id", default=None, help="capture to project (default: the most recent)"
    )
    parser.add_argument(
        "--control-only",
        action="store_true",
        help="explicitly roll back to the previous in-season control",
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        default=None,
        help="override the deadline read from the capture; normally unnecessary",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument(
        "--development-only",
        action="store_true",
        help=(
            "restrict historical reads to the frozen Phase C training seasons; "
            "requires a 2026-27 in-season target and excludes withheld-season carry-over"
        ),
    )
    parser.add_argument(
        "--evidence-table",
        type=Path,
        default=None,
        help="the player_evidence_v1 table: applies the bounded Top-100 uplift on the "
        "chosen base (component by default, the legacy blend on fallback or "
        "--control-only); requires --evidence-manifest",
    )
    parser.add_argument(
        "--evidence-manifest",
        type=Path,
        default=None,
        help="manifest paired with --evidence-table",
    )
    arguments = parser.parse_args()

    if not arguments.snapshot_root.is_dir():
        print(f"No snapshot directory at {arguments.snapshot_root}.")
        return 1
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    _, written, report = build(
        arguments.snapshot_root,
        arguments.archive_root,
        arguments.handoff_root,
        snapshot_id=arguments.snapshot_id,
        gameweek=arguments.gameweek,
        evidence_table_path=arguments.evidence_table,
        evidence_manifest_path=arguments.evidence_manifest,
        control_only=arguments.control_only,
        development_only=arguments.development_only,
        dry_run=arguments.dry_run,
        writer=publish_retained_handoff,
    )

    print(f"Capture   {report['snapshot_id']}  ({report['captured_at_utc']})")
    print(f"Target    {report['season']} gameweek {report['gameweek']}")
    print(f"Played    {report['gameweeks_played']} gameweek(s) of in-season history")
    print()
    print("Projection routes")
    for key in (
        "players",
        "players_with_in_season_minutes",
        "players_blended_two_stage",
        "players_shrunk_against_the_price_prior",
        "players_from_carry_over_only",
        "players_priced_from_the_prior",
    ):
        print(f"  {key:42} {report[key]}")
    print(f"  {'in_season_weight':42} {report['in_season_weight']}")
    print(f"  {'carry_over_weight':42} {report['carry_over_weight']}")
    if "elite_evidence_policy_version" in report:
        print()
        print("Phase C elite evidence")
        for key in (
            "elite_evidence_policy_version",
            "elite_evidence_cohort_size",
            "elite_evidence_players_uplifted",
            "elite_evidence_mean_points_delta",
            "elite_evidence_max_points_delta",
            "elite_evidence_table_sha256",
            "elite_evidence_manifest_sha256",
        ):
            print(f"  {key:42} {report[key]}")
    if report.get("projection_selection") == "phase_c_component_default":
        print()
        print("Phase C component model")
        for key in (
            "component_training_rows",
            "component_training_appearance_rows",
            "component_training_conditional_rows",
            "component_history_gameweeks",
            "component_history_incomplete_players",
            "route:component_model",
            "route:direct_control",
            "component_fingerprint",
        ):
            print(f"  {key:42} {report[key]}")
    elif report.get("projection_selection") == "legacy_control_fallback":
        print()
        print(f"Phase C fallback  {report['component_fallback_reason']}")
    print()
    print(f"Identity  {report['model_name']} / {report['model_version']}")
    if not report["version_is_promoted"]:
        print(
            "  This version is NOT in IN_SEASON_CONTROL_MODEL_VERSIONS, so a decision "
            "made from this handoff will be refused at verification. Pinning it is the "
            "promotion decision and belongs in a reviewed change to 'live'."
        )
    print(f"Fingerprint {report['fingerprint']}")
    if written is None:
        print("\nDry run: nothing written.")
    else:
        print(f"\nWrote {written} and read it back identically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
