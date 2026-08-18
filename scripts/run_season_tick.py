"""One tick of the season loop: capture, decide, or settle — whichever is due now.

    python -m scripts.run_season_tick                 # do what is due, print what was done
    python -m scripts.run_season_tick --dry-run       # print the plan, change nothing
    python -m scripts.run_season_tick --now 2026-08-21T15:00:00Z --dry-run

Meant to be called on a schedule (hourly is plenty) by a cron job, a workflow, or a
person. It reads the captures held under the snapshot root and the season ledger, asks
the tick planner (`squadopt.live.tick`) what is due, and executes it in order:

- **capture** when the next deadline is inside the capture window and no capture from
  inside the window is held, or when a decided gameweek needs a post-gameweek capture
  to settle (polled at most every `--settle-recapture-hours`);
- **decide** when an in-window capture exists and the gameweek is undecided — the
  opening gameweek from the capture alone, later gameweeks only if the producer's
  projection handoff `<handoff-root>/<season>-gwNN.json` is present (otherwise it waits
  and says so);
- **settle** when the latest capture marks a decided gameweek finished.

After a capture the plan is recomputed once, so a deadline capture is decided in the
same tick. Every step is idempotent and each is the same code path as running the
capture script or `run_gameweek_ops` by hand; the tick only chooses the moment. A
failed step exits non-zero with the reason; nothing half-done is recorded.

The tick never plays a chip: chips are hand decisions (`run_gameweek_ops --chip ...`
before the tick would decide), because a one-week horizon does not time them well
(docs/season_chain_note.md).
"""

import argparse
import sys
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import scripts.run_gameweek_ops as ops
from scripts.capture_deadline_snapshot import capture as capture_snapshot

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.live import LedgerError, infer_season, load_ledger
from squadopt.live.tick import (
    HeldSnapshot,
    LedgerState,
    TickAction,
    TickConfig,
    TickPlan,
    plan_tick,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_HANDOFF_ROOT = REPOSITORY_ROOT / "data" / "handoffs"


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
        "--summary-output",
        type=Path,
        help="settle: where the season summary is written (default docs/season_ledger_<season>.md)",
    )
    return parser.parse_args()


def _read_state(
    arguments: argparse.Namespace,
) -> tuple[list[HeldSnapshot], CapturedSnapshot | None, str | None, LedgerState]:
    identifiers = list_snapshot_ids(arguments.snapshot_root)
    held: list[HeldSnapshot] = []
    latest: CapturedSnapshot | None = None
    for identifier in identifiers:
        snapshot = read_snapshot(arguments.snapshot_root, identifier)
        held.append(HeldSnapshot(identifier, snapshot.metadata.captured_at_utc))
        latest = snapshot
    season = arguments.season or (infer_season(latest) if latest is not None else None)
    ledger = LedgerState()
    if season is not None:
        entries = load_ledger(arguments.ledger_root, season)
        ledger = LedgerState(
            decided=frozenset(entry.gameweek for entry in entries),
            settled=frozenset(entry.gameweek for entry in entries if entry.outcome is not None),
        )
    return held, latest, season, ledger


def _plan(arguments: argparse.Namespace, now_utc: str, config: TickConfig) -> TickPlan:
    held, latest, season, ledger = _read_state(arguments)
    return plan_tick(
        now_utc=now_utc,
        held=held,
        latest=latest,
        ledger=ledger,
        handoff_root=arguments.handoff_root,
        config=config,
        season=season,
    )


def _print_plan(plan: TickPlan) -> None:
    print(f"tick at {plan.now_utc} (season {plan.season or 'unknown'})")
    for key in ("latest_capture", "next_gameweek", "next_deadline_utc", "hours_to_deadline"):
        if key in plan.diagnostics:
            print(f"  {key:<20} {plan.diagnostics[key]}")
    for action in plan.actions:
        target = f" GW{action.gameweek}" if action.gameweek is not None else ""
        print(f"  -> {action.kind}{target}: {action.reason}")


def _execute(action: TickAction, arguments: argparse.Namespace, season: str | None) -> int:
    if action.kind == "capture":
        metadata = capture_snapshot(arguments.snapshot_root)
        assert metadata is not None
        print(f"captured {metadata.snapshot_id}")
        return 0
    if action.kind == "decide":
        return ops._decide(
            Namespace(
                snapshot_root=arguments.snapshot_root,
                snapshot_id=action.snapshot_id,
                gameweek=action.gameweek,
                season=season,
                ledger_root=arguments.ledger_root,
                archive_root=arguments.archive_root,
                in_season_projection=(
                    Path(action.handoff_path) if action.handoff_path is not None else None
                ),
                chip=None,
                summary_output=arguments.summary_output,
            )
        )
    if action.kind == "settle":
        return ops._settle(
            Namespace(
                snapshot_root=arguments.snapshot_root,
                snapshot_id=action.snapshot_id,
                gameweek=action.gameweek,
                season=season,
                ledger_root=arguments.ledger_root,
                archive_root=arguments.archive_root,
                summary_output=arguments.summary_output,
            )
        )
    return 0


def main() -> int:
    arguments = _parse_arguments()
    now_utc = arguments.now or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    config = TickConfig(
        capture_window_hours=arguments.capture_window_hours,
        settle_grace_hours=arguments.settle_grace_hours,
        settle_recapture_hours=arguments.settle_recapture_hours,
    )
    try:
        plan = _plan(arguments, now_utc, config)
        _print_plan(plan)
        if arguments.dry_run:
            print("dry run: nothing changed")
            return 0
        performed = 0
        if plan.wants_capture:
            for action in plan.actions:
                if action.kind == "capture":
                    _execute(action, arguments, plan.season)
                    performed += 1
            # A capture changes what is due: re-plan once so this tick can decide or
            # settle from what it just captured (a second capture is never taken).
            plan = _plan(arguments, now_utc, config)
            print("re-planned after capture:")
            _print_plan(plan)
        for action in plan.actions:
            if action.kind in {"decide", "settle"}:
                code = _execute(action, arguments, plan.season)
                if code != 0:
                    print(f"{action.kind} for GW{action.gameweek} failed; stopping this tick.")
                    return code
                performed += 1
    except (DataError, LedgerError) as error:
        print(f"\nSeason tick failed:\n  {error}")
        return 1
    print(f"tick done: {performed} action(s) performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
