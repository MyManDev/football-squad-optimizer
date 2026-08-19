"""Run capture, decide, or settle—whichever the season needs now.

    python -m scripts.run_season_tick
    python -m scripts.run_season_tick --dry-run
    python -m scripts.run_season_tick --now 2026-08-21T15:00:00Z --dry-run

The application service owns planning and execution.  This script supplies the one
network capture operation and adapts its typed lifecycle to console output, structured
logging, and process exit codes.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts.capture_deadline_snapshot import capture as capture_snapshot

from squadopt.application import (
    DecideResult,
    SettleResult,
    TickObserver,
    TickRequest,
    TickValue,
    run_season_tick,
)
from squadopt.data.errors import DataError
from squadopt.data.snapshots import SnapshotMetadata
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import LedgerError
from squadopt.live.runlog import RunLog, configure_run_logging
from squadopt.live.tick import TickAction, TickConfig, TickPlan

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_HANDOFF_ROOT = REPOSITORY_ROOT / "data" / "handoffs"
DEFAULT_LOG_ROOT = REPOSITORY_ROOT / "data" / "logs"
EXIT_OK = 0
EXIT_KNOWN_FAILURE = 1
EXIT_UNEXPECTED_FAILURE = 2
_PLAN_KEYS = ("latest_capture", "next_gameweek", "next_deadline_utc", "hours_to_deadline")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    parser.add_argument("--season", help="override the season inferred from the capture")
    parser.add_argument("--now", help="pretend it is this UTC instant (replay / tests)")
    parser.add_argument("--capture-window-hours", type=float, default=3.0)
    parser.add_argument("--settle-grace-hours", type=float, default=48.0)
    parser.add_argument("--settle-recapture-hours", type=float, default=12.0)
    parser.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    parser.add_argument(
        "--log-root",
        type=Path,
        default=DEFAULT_LOG_ROOT,
        help="structured JSON-lines run log root; '-' disables the file",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        help="settle: where the season summary is written",
    )
    return parser.parse_args()


class _CliTickObserver(TickObserver):
    """Render the transport-neutral tick lifecycle for an operator."""

    def __init__(self, log: RunLog) -> None:
        self.log = log
        self.completed = 0

    def planned(self, plan: TickPlan, *, replanned: bool) -> None:
        if replanned:
            print("re-planned after capture:")
        print(f"tick at {plan.now_utc} (season {plan.season or 'unknown'})")
        for key in _PLAN_KEYS:
            if key in plan.diagnostics:
                print(f"  {key:<20} {plan.diagnostics[key]}")
        for action in plan.actions:
            target = f" GW{action.gameweek}" if action.gameweek is not None else ""
            print(f"  -> {action.kind}{target}: {action.reason}")
        self.log.event(
            "tick.plan",
            now_utc=plan.now_utc,
            season=plan.season,
            replanned=replanned,
            actions=[
                {
                    "kind": action.kind,
                    "gameweek": action.gameweek,
                    "snapshot_id": action.snapshot_id,
                    "reason": action.reason,
                }
                for action in plan.actions
            ],
            diagnostics={
                key: plan.diagnostics[key] for key in _PLAN_KEYS if key in plan.diagnostics
            },
        )

    def action_started(self, action: TickAction) -> None:
        self.log.event(
            "tick.action.start",
            kind=action.kind,
            gameweek=action.gameweek,
            snapshot_id=action.snapshot_id,
        )

    def action_completed(self, action: TickAction, value: TickValue) -> None:
        if isinstance(value, SnapshotMetadata):
            print(f"captured {value.snapshot_id}")
        elif isinstance(value, DecideResult):
            print("Decision verification passed: all runbook checks hold.")
            print(value.report)
            print(f"Recorded decision at {value.decision_directory}")
        elif isinstance(value, SettleResult):
            print(f"Recorded outcome at {value.outcome_path}")
            print(value.summary)
            print(f"Wrote {value.summary_path}")
        self.completed += 1
        self.log.event(
            "tick.action.done",
            kind=action.kind,
            gameweek=action.gameweek,
            snapshot_id=action.snapshot_id,
        )

    def action_failed(self, action: TickAction, error: Exception) -> None:
        self.log.failure(
            "tick.action.failed",
            kind=action.kind,
            gameweek=action.gameweek,
            snapshot_id=action.snapshot_id,
            error=str(error),
        )


def main() -> int:
    arguments = _parse_arguments()
    now_utc = arguments.now or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    log_root = None if str(arguments.log_root) == "-" else Path(arguments.log_root)
    log = configure_run_logging("season_tick", log_root=log_root, console=False)
    observer = _CliTickObserver(log)
    request = TickRequest(
        snapshot_root=arguments.snapshot_root,
        ledger_root=arguments.ledger_root,
        archive_root=arguments.archive_root,
        handoff_root=arguments.handoff_root,
        summary_root=REPOSITORY_ROOT / "docs",
        now_utc=now_utc,
        season=arguments.season,
        summary_output=arguments.summary_output,
        config=TickConfig(
            capture_window_hours=arguments.capture_window_hours,
            settle_grace_hours=arguments.settle_grace_hours,
            settle_recapture_hours=arguments.settle_recapture_hours,
        ),
    )
    log.event("tick.start", now_utc=now_utc, dry_run=bool(arguments.dry_run))
    try:
        result = run_season_tick(
            request,
            capture=capture_snapshot,
            panel_builder=build_panel,
            dry_run=bool(arguments.dry_run),
            observer=observer,
        )
    except (DataError, LedgerError) as error:
        print(f"\nSeason tick failed:\n  {error}")
        log.failure("tick.failed", performed=observer.completed, error=str(error))
        return EXIT_KNOWN_FAILURE
    except Exception as error:  # a scheduled tick must never die silently
        print(f"\nSeason tick crashed:\n  {type(error).__name__}: {error}")
        log.failure("tick.crashed", performed=observer.completed, error=str(error))
        return EXIT_UNEXPECTED_FAILURE

    if result.dry_run:
        print("dry run: nothing changed")
    else:
        print(f"tick done: {result.action_count} action(s) performed")
    log.event(
        "tick.done",
        performed=result.action_count,
        dry_run=result.dry_run,
        exit_code=EXIT_OK,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
