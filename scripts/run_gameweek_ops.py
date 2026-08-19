"""Run one gameweek of season operations against the ledger.

    python -m scripts.run_gameweek_ops --phase decide
    python -m scripts.run_gameweek_ops --phase decide --snapshot-id <id> --gameweek 1
    python -m scripts.run_gameweek_ops --phase decide --gameweek 2 \
        --in-season-projection handoffs/2026-27-gw02.json [--chip bboost]
    python -m scripts.run_gameweek_ops --phase settle --gameweek 1

This script is the human-facing adapter for the public application command services.
Decision and settlement behavior lives in ``squadopt.application`` so this CLI, the
scheduled tick, and a later HTTP API cannot drift into separate implementations.
"""

import argparse
import sys
from pathlib import Path

from squadopt.application import (
    DecideRequest,
    DecisionVerificationError,
    SettleRequest,
    decide,
    settle,
    verify_decision,
)
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import CHIP_NAMES
from squadopt.planning import CHIP_NAMES as PLANNER_CHIP_NAMES

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("decide", "settle"), required=True)
    parser.add_argument(
        "--snapshot-id",
        help="use this capture; omitted, the most recent capture is used",
    )
    parser.add_argument(
        "--gameweek",
        type=int,
        help="decide: target gameweek (default: earliest open at capture time); "
        "settle: the finished gameweek to score (required)",
    )
    parser.add_argument("--season", help="override the season inferred from the capture")
    parser.add_argument(
        "--in-season-projection",
        type=Path,
        help="decide, gameweek 2 onward: the producer's projection handoff "
        "(projection_handoff_v1) for this capture and gameweek",
    )
    parser.add_argument(
        "--chip",
        choices=sorted(set(CHIP_NAMES) & set(PLANNER_CHIP_NAMES)),
        help="decide, gameweek 2 onward: play this chip now",
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="settle: where the committed season summary is written",
    )
    return parser.parse_args()


def _decide(arguments: argparse.Namespace) -> int:
    """Compatibility shell retained until the installed CLI replaces script callers."""

    try:
        result = decide(
            DecideRequest(
                snapshot_root=arguments.snapshot_root,
                snapshot_id=arguments.snapshot_id,
                gameweek=arguments.gameweek,
                season=arguments.season,
                ledger_root=arguments.ledger_root,
                archive_root=arguments.archive_root,
                in_season_projection=arguments.in_season_projection,
                chip=arguments.chip,
            ),
            panel_builder=build_panel,
            verifier=verify_decision,
        )
    except DecisionVerificationError as error:
        print("\nDecision verification FAILED; nothing was recorded:")
        for failure in error.failures:
            print(f"  - {failure}")
        return 1

    print(
        f"{result.mode}: snapshot {result.snapshot_id}, targeting "
        f"{result.season} gameweek {result.gameweek}"
    )
    print("Decision verification passed: all runbook checks hold.")
    print(result.report)
    print(f"Recorded decision at {result.decision_directory}")
    return 0


def _settle(arguments: argparse.Namespace) -> int:
    """Compatibility shell retained until the installed CLI replaces script callers."""

    if arguments.gameweek is None:
        raise DataError("settle requires --gameweek: the finished gameweek to score.")
    result = settle(
        SettleRequest(
            snapshot_root=arguments.snapshot_root,
            snapshot_id=arguments.snapshot_id,
            gameweek=arguments.gameweek,
            season=arguments.season,
            ledger_root=arguments.ledger_root,
            summary_root=REPOSITORY_ROOT / "docs",
            summary_output=arguments.summary_output,
        )
    )
    print(f"Recorded outcome at {result.outcome_path}")
    print(result.summary)
    print(f"Wrote {result.summary_path}")
    return 0


def main() -> int:
    arguments = _parse_arguments()
    try:
        if arguments.phase == "decide":
            return _decide(arguments)
        return _settle(arguments)
    except DataError as error:
        print(f"\nGameweek operations failed:\n  {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
