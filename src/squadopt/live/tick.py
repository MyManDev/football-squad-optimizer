"""One tick of the season loop: what, if anything, should happen right now.

The season runbook is three actions — capture before a deadline, decide from the
capture, settle after the gameweek finishes — and a person has been choosing when to
run each. This module makes that choice a pure function of the clock and what is
already on disk, so a scheduler (a cron job, a workflow, a person typing one command
every hour) can call it repeatedly and get the same answer every time until something
changes. Every action is idempotent: a capture already held in the deadline window is
not taken again, a decision already recorded is not made again, an outcome already
settled is not settled again. When nothing is due, the plan says so and why.

The planner does no I/O and touches no network. The runner (`scripts.run_season_tick`)
reads the snapshots and the ledger, asks for the plan, and executes it — the capture
through the existing capture script, decide and settle through the gameweek operations
— then re-plans once, so a capture taken this tick can be decided in the same tick.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    GameweekDeadline,
    gameweek_deadlines,
    next_open_deadline,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live.recommendation import SUPPORTED_TARGET_GAMEWEEK, infer_season

SEASON_TICK_CONTRACT_VERSION: Final = "season_tick_v1"
ActionKind = Literal["capture", "decide", "settle", "wait"]


@dataclass(frozen=True, slots=True)
class TickConfig:
    """Timing rules of the loop; the runbook's numbers as data."""

    capture_window_hours: float = 3.0
    """Capture for a decision when the next deadline is this close or closer (and no
    capture from inside the window is held). Three hours: the runbook says ~2, and a
    scheduler can be late by tens of minutes."""
    settle_grace_hours: float = 48.0
    """Do not look for a settle capture before this long after the deadline: no
    gameweek finishes sooner."""
    settle_recapture_hours: float = 12.0
    """Between settle captures of a gameweek that has not finished yet, wait at least
    this long: the source is polled, not hammered."""

    def __post_init__(self) -> None:
        for name in ("capture_window_hours", "settle_grace_hours", "settle_recapture_hours"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise DataSourceError(f"{name} must be a positive number of hours.")


@dataclass(frozen=True, slots=True)
class HeldSnapshot:
    """A capture already on disk, by identity and instant (payloads not needed to plan
    except the latest one's deadlines)."""

    snapshot_id: str
    captured_at_utc: str


@dataclass(frozen=True, slots=True)
class LedgerState:
    """Which gameweeks the ledger has decided and settled for the season."""

    decided: frozenset[int] = frozenset()
    settled: frozenset[int] = frozenset()


@dataclass(frozen=True, slots=True)
class TickAction:
    kind: ActionKind
    reason: str
    gameweek: int | None = None
    snapshot_id: str | None = None
    handoff_path: str | None = None


@dataclass(frozen=True, slots=True)
class TickPlan:
    """What this tick should do, in order, and the state it read to decide."""

    now_utc: str
    season: str | None
    actions: tuple[TickAction, ...]
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = SEASON_TICK_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def wants_capture(self) -> bool:
        return any(action.kind == "capture" for action in self.actions)

    @property
    def is_idle(self) -> bool:
        return all(action.kind == "wait" for action in self.actions)


def handoff_path_for(root: Path, season: str, gameweek: int) -> Path:
    """Where the producer's projection handoff for a deadline is expected."""

    return Path(root) / f"{season}-gw{gameweek:02d}.json"


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600.0


def plan_tick(
    *,
    now_utc: str,
    held: Sequence[HeldSnapshot],
    latest: CapturedSnapshot | None,
    ledger: LedgerState,
    handoff_root: Path,
    config: TickConfig | None = None,
    season: str | None = None,
) -> TickPlan:
    """Decide the tick's actions from the clock, the captures held, and the ledger.

    ``held`` lists every capture on disk (any order); ``latest`` is the most recent
    one's content, whose published deadlines are the calendar this tick trusts.
    """

    settings = TickConfig() if config is None else config
    now_text = normalize_utc_timestamp(now_utc, label="now_utc")
    now = as_instant(now_text)
    diagnostics: dict[str, object] = {"captures_held": len(held)}

    if latest is None or not held:
        return TickPlan(
            now_utc=now_text,
            season=season,
            actions=(TickAction("capture", "no capture is held; the calendar is unknown"),),
            diagnostics=diagnostics,
        )

    bootstrap = latest.payloads.get(BOOTSTRAP_PAYLOAD)
    if bootstrap is None:
        raise DataSourceError("The latest capture carries no bootstrap payload.")
    resolved_season = season or infer_season(latest)
    deadlines: dict[int, GameweekDeadline] = {
        entry.gameweek: entry for entry in gameweek_deadlines(bootstrap)
    }
    ordered = sorted(held, key=lambda item: as_instant(item.captured_at_utc))
    latest_held = ordered[-1]
    latest_at = as_instant(latest_held.captured_at_utc)
    diagnostics["latest_capture"] = latest_held.snapshot_id
    diagnostics["latest_capture_age_hours"] = round(_hours(now - latest_at), 2)
    actions: list[TickAction] = []

    # ---- settle: decided gameweeks without an outcome -----------------------------
    settle_capture_requested = False
    for gameweek in sorted(ledger.decided - ledger.settled):
        published = deadlines.get(gameweek)
        if published is None:
            continue
        deadline = as_instant(published.deadline_utc)
        if published.finished:
            actions.append(
                TickAction(
                    "settle",
                    f"gameweek {gameweek} is finished in the latest capture and its "
                    "decision has no outcome",
                    gameweek=gameweek,
                    snapshot_id=latest_held.snapshot_id,
                )
            )
        elif now - deadline >= timedelta(hours=settings.settle_grace_hours):
            if _hours(now - latest_at) >= settings.settle_recapture_hours:
                if not settle_capture_requested:
                    actions.append(
                        TickAction(
                            "capture",
                            f"gameweek {gameweek} was decided, is not marked finished in "
                            f"the latest capture ({latest_held.snapshot_id}), and that "
                            f"capture is {_hours(now - latest_at):.1f} h old",
                            gameweek=gameweek,
                        )
                    )
                    settle_capture_requested = True
            else:
                actions.append(
                    TickAction(
                        "wait",
                        f"gameweek {gameweek} awaits its outcome; the latest capture is "
                        f"{_hours(now - latest_at):.1f} h old, next look after "
                        f"{settings.settle_recapture_hours:g} h",
                        gameweek=gameweek,
                    )
                )

    # ---- missed: a deadline that closed recently with no decision recorded ---------
    for gameweek in sorted(deadlines):
        published = deadlines[gameweek]
        deadline = as_instant(published.deadline_utc)
        recently_closed = deadline <= now and now - deadline <= timedelta(days=7)
        later_decision = any(decided > gameweek for decided in ledger.decided)
        if recently_closed and gameweek not in ledger.decided and not later_decision:
            actions.append(
                TickAction(
                    "wait",
                    f"gameweek {gameweek} deadline {published.deadline_utc} closed with no "
                    "decision recorded (missed); nothing can be decided for it now",
                    gameweek=gameweek,
                )
            )

    # ---- decide: the next open deadline ---------------------------------------------
    try:
        upcoming = next_open_deadline(list(deadlines.values()), as_of_utc=now_text)
    except DataSourceError:
        upcoming = None
    if upcoming is None:
        actions.append(TickAction("wait", "no deadline is open in the latest capture's calendar"))
        diagnostics["next_gameweek"] = None
    else:
        gameweek = upcoming.gameweek
        deadline = as_instant(upcoming.deadline_utc)
        hours_left = _hours(deadline - now)
        diagnostics["next_gameweek"] = gameweek
        diagnostics["next_deadline_utc"] = upcoming.deadline_utc
        diagnostics["hours_to_deadline"] = round(hours_left, 2)
        window_start = deadline - timedelta(hours=settings.capture_window_hours)
        in_window = [
            item for item in ordered if window_start <= as_instant(item.captured_at_utc) < deadline
        ]
        if gameweek in ledger.decided:
            actions.append(
                TickAction(
                    "wait",
                    f"gameweek {gameweek} is already decided; nothing to do until its outcome",
                    gameweek=gameweek,
                )
            )
        elif hours_left > settings.capture_window_hours:
            actions.append(
                TickAction(
                    "wait",
                    f"gameweek {gameweek} deadline in {hours_left:.1f} h; capture opens "
                    f"{settings.capture_window_hours:g} h before it",
                    gameweek=gameweek,
                )
            )
        elif not in_window:
            if not settle_capture_requested:
                actions.append(
                    TickAction(
                        "capture",
                        f"gameweek {gameweek} deadline in {hours_left:.1f} h and no capture "
                        "from inside the window is held",
                        gameweek=gameweek,
                    )
                )
        else:
            snapshot = in_window[-1]
            if gameweek == SUPPORTED_TARGET_GAMEWEEK:
                actions.append(
                    TickAction(
                        "decide",
                        f"opening gameweek: capture {snapshot.snapshot_id} is inside the window",
                        gameweek=gameweek,
                        snapshot_id=snapshot.snapshot_id,
                    )
                )
            else:
                handoff = handoff_path_for(handoff_root, resolved_season, gameweek)
                if handoff.is_file():
                    actions.append(
                        TickAction(
                            "decide",
                            f"capture {snapshot.snapshot_id} is inside the window and the "
                            f"projection handoff is present",
                            gameweek=gameweek,
                            snapshot_id=snapshot.snapshot_id,
                            handoff_path=str(handoff),
                        )
                    )
                else:
                    actions.append(
                        TickAction(
                            "wait",
                            f"gameweek {gameweek} deadline in {hours_left:.1f} h, capture "
                            f"held, but no projection handoff at {handoff}",
                            gameweek=gameweek,
                            snapshot_id=snapshot.snapshot_id,
                            handoff_path=str(handoff),
                        )
                    )

    if not actions:
        actions.append(TickAction("wait", "nothing is due"))
    return TickPlan(
        now_utc=now_text,
        season=resolved_season,
        actions=tuple(actions),
        diagnostics=diagnostics,
    )
