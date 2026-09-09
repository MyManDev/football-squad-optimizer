"""Transport-neutral weekly planning, provenance and preflight rules."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from squadopt.application.entries import EntryRegistry
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import gameweek_deadlines, next_open_deadline
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp
from squadopt.live import (
    CHIP_NAMES,
    LedgerError,
    SeasonRules,
    chip_availability_for,
    held_squad_from_ledger,
    load_ledger,
    read_season_rules,
)
from squadopt.optimization import OptimizationConfig
from squadopt.planning import CHIP_NAMES as PLANNER_CHIP_NAMES

STEPS = (
    "top100",
    "capture",
    "settled_outcomes",
    "rotation",
    "handoff",
    "decide",
    "league",
    "site",
    "scoreboard",
    "publish",
)


CHIP_CHOICES = tuple(sorted(set(CHIP_NAMES) & set(PLANNER_CHIP_NAMES)))


class WeekError(RuntimeError):
    """A step refused; the message says which and why."""


@dataclass(frozen=True, slots=True)
class WeekPlan:
    """What one run will do, decided before anything runs."""

    season: str
    gameweek: int
    league_id: int
    steps: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        lines = [f"week plan: {self.season} gameweek {self.gameweek}, league {self.league_id}"]
        for step in STEPS:
            state = "run" if step in self.steps else f"skip ({self.reasons.get(step, 'not asked')})"
            lines.append(f"  {step:<8} {state}")
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class WeeklyRequest:
    season: str
    gameweek: int
    league_id: int
    snapshot_id: str | None = None
    cohort_snapshot: str | None = None
    elite_snapshot: str | None = None
    skip_top100: bool = False
    projection: str = "component"
    decide: bool = False
    chip: str | None = None
    rotation: bool = False
    workers: int = 8
    publish: bool = False

    def plan(self) -> WeekPlan:
        if self.workers < 1 or self.league_id < 1:
            raise WeekError("League id and worker count must be positive.")
        if self.projection not in {"component", "component-only"}:
            raise WeekError("Unknown weekly projection selection.")
        return plan_week(
            season=self.season,
            gameweek=self.gameweek,
            league_id=self.league_id,
            snapshot_id=self.snapshot_id,
            cohort_snapshot=self.cohort_snapshot,
            elite_snapshot=self.elite_snapshot,
            skip_top100=self.skip_top100,
            publish=self.publish,
            decide=self.decide,
            chip=self.chip,
            rotation=self.rotation,
        )


@dataclass(frozen=True, slots=True)
class WeeklyPreparation:
    plan: WeekPlan
    decide: bool
    decide_skip_reason: str | None


def prepare_week(
    request: WeeklyRequest,
    *,
    registry_path: Path,
    snapshot_root: Path,
    ledger_root: Path,
    evidence_root: Path,
    rotation_root: Path,
    rules: SeasonRules | None = None,
) -> WeeklyPreparation:
    """Apply the existing domain refusals before collectors spend a capture."""

    plan = request.plan()
    if not registry_path.is_file() or not EntryRegistry.load(registry_path).entries:
        raise WeekError(f"No registered entries at {registry_path}; seed the registry first.")
    if (
        request.snapshot_id
        and "top100" in plan.steps
        and request.projection == "component"
        and request.elite_snapshot
    ):
        check_evidence_for_reused_capture(
            evidence_root,
            season=request.season,
            gameweek=request.gameweek,
            elite_snapshot=request.elite_snapshot,
            snapshot_id=request.snapshot_id,
        )
    if request.snapshot_id and request.rotation:
        check_rotation_for_reused_capture(
            rotation_root,
            season=request.season,
            gameweek=request.gameweek,
            snapshot_id=request.snapshot_id,
        )
    skip = None
    if request.decide:
        skip = preflight_decide(
            ledger_root,
            request.season,
            request.gameweek,
            chip=request.chip,
            rules=rules,
        )
    return WeeklyPreparation(plan, request.decide and skip is None, skip)


def plan_week(
    *,
    season: str,
    gameweek: int,
    league_id: int,
    snapshot_id: str | None,
    cohort_snapshot: str | None,
    elite_snapshot: str | None,
    skip_top100: bool,
    publish: bool,
    decide: bool = False,
    chip: str | None = None,
    rotation: bool = False,
) -> WeekPlan:
    """Decide the steps from what the caller already has; pure, so it can be tested."""

    if not 2 <= gameweek <= 38:
        raise WeekError(
            "The weekly loop serves gameweeks 2..38; the opening week is decided by hand."
        )
    if chip is not None and not decide:
        raise WeekError("--chip names the chip our own decision plays; it needs --decide.")
    if chip is not None and chip not in CHIP_CHOICES:
        raise WeekError(f"--chip must be one of {list(CHIP_CHOICES)!r}, got {chip!r}.")
    steps: list[str] = []
    reasons: dict[str, str] = {}
    if skip_top100:
        reasons["top100"] = "--skip-top100"
    elif cohort_snapshot and elite_snapshot:
        # The captures are reused; whether the export is reused too depends on what is on
        # disk, which this function does not read. ``evidence_artifact`` reports that.
        reasons["top100"] = f"reusing {cohort_snapshot} and {elite_snapshot}"
        steps.append("top100")
    elif snapshot_id:
        # The evidence must predate the decision capture it is applied to; a fresh
        # Top-100 capture after a reused live capture would be refused at the handoff.
        raise WeekError(
            "A reused live capture needs Top-100 captures taken before it: pass "
            "--cohort-snapshot and --elite-snapshot, or --skip-top100."
        )
    else:
        steps.append("top100")
    if snapshot_id:
        reasons["capture"] = f"reusing {snapshot_id}"
    else:
        steps.append("capture")
    steps.append("settled_outcomes")
    if rotation:
        # After the capture, not before it: the table is one row per roster player of the
        # decision capture. The lane's "before the capture" constraint binds the model call,
        # which is a step of its own and does not exist yet; this export is pure and offline
        # over bytes already frozen, so it can introduce nothing the capture could have shown.
        steps.append("rotation")
    else:
        reasons["rotation"] = (
            "pass --rotation to export this week's club-news evidence; the only source "
            "today is the committed synthetic fixture"
        )
    steps.append("handoff")
    if decide:
        steps.append("decide")
    else:
        reasons["decide"] = "pass --decide to record our own squad in the ledger"
    steps.extend(["league", "site", "scoreboard"])
    if publish:
        steps.append("publish")
    else:
        reasons["publish"] = "pass --publish to open the site PR"
    return WeekPlan(season, gameweek, league_id, tuple(steps), reasons)


def evidence_artifact(
    root: Path, season: str, gameweek: int, elite_snapshot: str
) -> tuple[Path, Path]:
    """The evidence table and manifest one picks capture's export writes.

    The export never overwrites a different artifact at the same path, and a rehearsal
    earlier in the week is a different artifact from Friday's; the picks capture's own hash
    makes the name unique per capture, so an export already on disk for that capture is the
    same artifact and is reused rather than remade.
    """

    name = f"player_evidence_v1_{season}_gw{gameweek:02d}_top100_{elite_snapshot[-12:]}"
    return root / f"{name}.csv", root / f"{name}.manifest.json"


def rotation_artifact(
    root: Path, season: str, gameweek: int, snapshot_id: str
) -> tuple[Path, Path]:
    """The rotation table and manifest one capture's export writes.

    The sibling of :func:`evidence_artifact`, and the name is built here rather than parsed
    out of the export's output for two reasons. The export prints its paths with a trailing
    ``(written)`` or ``(replay)``, which :func:`_wrote_paths` does not match; and a name
    constructed from the capture is stable whatever the export decides to print. It mirrors
    ``scripts.export_rotation_evidence._artifact_name``, including the twelve characters of
    the capture's own digest, so a rehearsal earlier in the week is a different artifact from
    Friday's and an export already on disk for that capture is the same one.
    """

    name = f"rotation_evidence_v1_{season}_gw{gameweek:02d}_{snapshot_id[-12:]}"
    return root / f"{name}.csv", root / f"{name}.manifest.json"


def check_rotation_for_reused_capture(
    rotation_root: Path, *, season: str, gameweek: int, snapshot_id: str
) -> None:
    """Refuse a reused live capture whose rotation export is not already on disk.

    The same shape as :func:`check_evidence_for_reused_capture` and the same argument, from
    this artifact's own contract rather than from Phase B's. ``rotation_evidence_v1`` records
    ``generated_at_utc``, and the lane's ordering constraint is that the claim chain is frozen
    before the decision capture: re-exporting now for a capture already taken stamps the
    artifact after it, always, and no amount of promptness escapes that. Said here, before
    anything is spent.

    A pair with only one half on disk does not count as reusable. A table without its manifest
    is not a readable artifact, and treating it as one would take the "already exported" branch
    and then fail at the read.
    """

    table, manifest = rotation_artifact(rotation_root, season, gameweek, snapshot_id)
    if table.is_file() and manifest.is_file():
        return
    raise WeekError(
        f"Reusing {snapshot_id} with --rotation needs its rotation export already on disk; "
        f"{table.name} is not under {rotation_root}. Exporting it now would stamp the artifact "
        f"after that capture was taken, which the claim chain does not allow. Export it for "
        "that capture first, or run without --rotation."
    )


def check_evidence_for_reused_capture(
    evidence_root: Path, *, season: str, gameweek: int, elite_snapshot: str, snapshot_id: str
) -> None:
    """Refuse a reused live capture whose evidence export is not already on disk.

    ``plan_week`` refuses a *fresh* Top-100 capture after a reused live capture, because
    the projection refuses evidence captured after the decision capture. The artifact is
    the second half of the same rule and was not covered: ``apply_elite_evidence`` checks
    the artifact's ``generated_at_utc`` as well as the evidence's ``captured_at_utc``, and
    ``export_player_evidence`` stamps the artifact with the wall clock. Re-exporting for a
    capture already taken therefore stamps it after that capture, always — the refusal is
    not a timing accident and no amount of promptness escapes it. Worse, the refused run
    leaves the artifact behind, so every later run for that pair takes the "already
    exported" branch and fails the same way. Said here, before anything is spent.
    """

    table, manifest = evidence_artifact(evidence_root, season, gameweek, elite_snapshot)
    if table.is_file() and manifest.is_file():
        return
    raise WeekError(
        f"Reusing {snapshot_id} needs the evidence export for {elite_snapshot} already on "
        f"disk; {table.name} is not under {evidence_root}. Re-exporting it now would stamp "
        "the artifact after that capture was taken, which the handoff refuses. Export it "
        "for that picks capture first, or run with --skip-top100 or --projection "
        "component-only to leave the Top-100 uplift out."
    )


def new_snapshot(before: Sequence[str], after: Sequence[str], prefix: str) -> str:
    """The one snapshot a step wrote, found by difference rather than by parsing output."""

    added = [name for name in after if name not in before and name.startswith(prefix)]
    if len(added) != 1:
        raise WeekError(
            f"Expected exactly one new {prefix}* snapshot, found {added!r}. Nothing else was run."
        )
    return added[0]


MODE_RULE = (
    "mode: live only when this run makes the capture and the clock is still before its "
    "deadline; a reused --snapshot-id, or a run past the deadline, is recorded as replay."
)


def decision_mode_for(
    *, reused_capture: bool, deadline_utc: str, now_utc: str
) -> Literal["live", "replay"]:
    """The mode this run's decision is recorded in — never asserted, always derived.

    Two independent reasons make a decision a replay rather than a live one, and the
    ledger, the site and the scoreboard all repeat whichever is stamped here. A reused
    capture is ``commands.decide``'s own rule (``replay`` whenever a snapshot is named
    rather than taken). Past the capture's own deadline is the second: a catch-up run
    from a pre-deadline capture is an honest record of what the model would have said,
    but it was not said before the deadline, and calling it live would claim it was.
    """

    if reused_capture:
        return "replay"
    now = as_instant(normalize_utc_timestamp(now_utc, label="now_utc"))
    deadline = as_instant(normalize_utc_timestamp(deadline_utc, label="deadline_utc"))
    return "replay" if now >= deadline else "live"


def preflight_decide(
    ledger_root: Path,
    season: str,
    gameweek: int,
    *,
    chip: str | None = None,
    rules: SeasonRules | None = None,
) -> str | None:
    """Check what the ledger can answer about a decision, before a capture is spent on it.

    ``decide`` itself checks these, but only after the Top-100 captures, the live capture
    and the handoff have all been made; a refusal there wastes the week's captures. Asked
    here first: can the ledger supply the squad this gameweek starts from
    (``held_squad_from_ledger`` wants exactly the previous week), and — when ``--chip``
    names one — is that chip's window open this week and the chip still unspent, which is
    exactly the question ``build_transfer_recommendation`` asks an hour later.

    A gameweek the ledger already holds is not a refusal but a skip, returned as the
    reason: a recorded decision is immutable, which is precisely why the rest of the week
    (the tree, the site, the scoreboard) can safely be re-run after a partial failure.
    """

    recorded = sorted(entry.gameweek for entry in load_ledger(ledger_root, season))
    if gameweek in recorded:
        return (
            f"the ledger already holds {season} GW{gameweek}; a recorded decision is "
            "immutable, so this run rebuilds the rest of the week around it"
        )
    try:
        held = held_squad_from_ledger(
            ledger_root,
            season,
            before_gameweek=gameweek,
            budget_tenths=OptimizationConfig().budget_tenths,
        )
    except LedgerError as error:
        raise WeekError(
            f"The ledger cannot supply the squad GW{gameweek} starts from: {error}"
        ) from error
    if chip is not None:
        if rules is None:
            raise WeekError(
                f"--chip {chip!r} cannot be checked before the capture: no snapshot on "
                "disk carries the season rules its window is published in."
            )
        played = {name: list(weeks) for name, weeks in held.chips_used.items()}
        offered = chip_availability_for(rules, (gameweek,), used=held.chips_used)
        if gameweek not in offered.gameweeks_for(chip):
            raise WeekError(
                f"--chip {chip!r} cannot be played in GW{gameweek}: its window is not open "
                f"there, or it was already played inside this window (chips played through "
                f"GW{held.decided_gameweek}: {played or 'none'})."
            )
    return None


def latest_live_snapshot(root: Path) -> str | None:
    """The newest live capture held, or ``None``.

    This step's own cohort and elite captures land in the same root, so the listing has
    to name the source it means; `list_snapshot_ids` takes that as a `source=` filter.
    """

    live = list_snapshot_ids(root, source=FPL_LIVE_SOURCE)
    return live[-1] if live else None


def rules_before_capture(root: Path, snapshot_id: str | None, season: str) -> SeasonRules | None:
    """The season rules the chip pre-flight reads, from a capture already on disk.

    This week's capture does not exist yet when the pre-flight runs — that is the point
    of running it first — so the chip windows come from the capture the caller reuses, or
    failing that from the most recent live one held. Chip windows are the season's, not
    the week's: the same ``game_config`` block every capture of the season carries.
    """

    identifier = snapshot_id or latest_live_snapshot(root)
    if identifier is None:
        return None
    return read_season_rules(read_snapshot(root, identifier), season=season)


def capture_deadline(root: Path, snapshot_id: str) -> tuple[int, str, str]:
    """The gameweek a capture is open for, its deadline, and when it was captured."""

    snapshot = read_snapshot(root, snapshot_id)
    captured_at = snapshot.metadata.captured_at_utc
    target = next_open_deadline(
        gameweek_deadlines(snapshot.payloads["bootstrap-static.json"]), as_of_utc=captured_at
    )
    return int(target.gameweek), str(target.deadline_utc), str(captured_at)
