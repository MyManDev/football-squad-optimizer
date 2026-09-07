"""The weekly loop as one command: capture, Top-100, handoff, league tree, site, publish.

    python -m scripts.run_week --season 2026-27 --gameweek 4 --league 352490
    python -m scripts.run_week --season 2026-27 --gameweek 4 --league 352490 --dry-run
    python -m scripts.run_week ... --snapshot-id <fpl-live id>      # reuse a capture
    python -m scripts.run_week ... --publish                        # open the site PR too

Every step already existed as its own script and was typed by hand, in order, under
deadline pressure; this runs them in order, with the ids each one produced handed to the
next, and stops at the first refusal. Nothing here decides anything of ours: the league
tree is computed from each member's own squad, the ledger is untouched, and the outward
half of publishing (merge, release, tag, dispatch) stays a person's act, printed at the
end exactly as ``publish_gameweek_site`` prints it.

Steps, each skippable by naming its output:

1. capture         one fpl-live snapshot with the registered entries and the league page
                   (``--snapshot-id`` reuses one; the capture's open deadline must be the
                   requested gameweek)
2. top100          the Overall Top-100 cohort, its members' last picks, and the
                   player_evidence_v1 export (``--cohort-snapshot`` / ``--elite-snapshot``
                   reuse captures; ``--skip-top100`` leaves the evidence out entirely)
3. handoff         the projection handoff for this capture: the Phase C component base
                   with the bounded Top-100 uplift on top when the evidence was exported
                   (``--projection component-only`` leaves the uplift out)
4. league          the league tree: every member's baseline and the rival menu
                   (``--workers``)
5. site            the season views
6. publish         optional: worktree, commit, push, PR (``--publish``)

Timing rules the scripts enforce and this one states up front: the Top-100 captures
must happen before the deadline and after the previous gameweek's picks are public; the
handoff must be built from the capture the decision will run on.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import gameweek_deadlines, next_open_deadline
from squadopt.live import handoff_path_for
from squadopt.platform.fpl_capture import capture

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"
HANDOFF_ROOT = REPOSITORY_ROOT / "data" / "handoffs"
EVIDENCE_ROOT = REPOSITORY_ROOT / "artifacts" / "phase_b"
SITE_OUT = REPOSITORY_ROOT / "web" / "public"

LIVE_PREFIX = "fpl-live-"
COHORT_PREFIX = "fpl-top100-"
ELITE_PREFIX = "fpl-elite-picks-"

STEPS = ("capture", "top100", "handoff", "league", "site", "publish")


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
) -> WeekPlan:
    """Decide the steps from what the caller already has; pure, so it can be tested."""

    if not 2 <= gameweek <= 38:
        raise WeekError(
            "The weekly loop serves gameweeks 2..38; the opening week is decided by hand."
        )
    steps: list[str] = []
    reasons: dict[str, str] = {}
    if snapshot_id:
        reasons["capture"] = f"reusing {snapshot_id}"
    else:
        steps.append("capture")
    if skip_top100:
        reasons["top100"] = "--skip-top100"
    elif cohort_snapshot and elite_snapshot:
        reasons["top100"] = f"reusing {cohort_snapshot} and {elite_snapshot} (export still runs)"
        steps.append("top100")
    else:
        steps.append("top100")
    steps.extend(["handoff", "league", "site"])
    if publish:
        steps.append("publish")
    else:
        reasons["publish"] = "pass --publish to open the site PR"
    return WeekPlan(season, gameweek, league_id, tuple(steps), reasons)


def new_snapshot(before: Sequence[str], after: Sequence[str], prefix: str) -> str:
    """The one snapshot a step wrote, found by difference rather than by parsing output."""

    added = [name for name in after if name not in before and name.startswith(prefix)]
    if len(added) != 1:
        raise WeekError(
            f"Expected exactly one new {prefix}* snapshot, found {added!r}. Nothing else was run."
        )
    return added[0]


def latest_live_snapshot(root: Path) -> str | None:
    live = [name for name in list_snapshot_ids(root) if name.startswith(LIVE_PREFIX)]
    return live[-1] if live else None


def capture_deadline(root: Path, snapshot_id: str) -> tuple[int, str, str]:
    """The gameweek a capture is open for, its deadline, and when it was captured."""

    snapshot = read_snapshot(root, snapshot_id)
    captured_at = snapshot.metadata.captured_at_utc
    target = next_open_deadline(
        gameweek_deadlines(snapshot.payloads["bootstrap-static.json"]), as_of_utc=captured_at
    )
    return int(target.gameweek), str(target.deadline_utc), str(captured_at)


def _run(arguments: list[str], *, cwd: Path = REPOSITORY_ROOT) -> str:
    print(f"$ {' '.join(arguments)}", flush=True)
    completed = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)
    output = (completed.stdout + completed.stderr).strip()
    if output:
        print(output, flush=True)
    if completed.returncode != 0:
        raise WeekError(f"`{' '.join(arguments[:3])} …` failed ({completed.returncode}).")
    return completed.stdout


def _python(module: str, *arguments: str) -> str:
    return _run([sys.executable, "-m", module, *arguments])


def _wrote_paths(output: str) -> list[Path]:
    """The ``Wrote <path>`` lines a producer prints, in order."""

    paths: list[Path] = []
    for line in output.splitlines():
        match = re.match(r"\s*(?:Wrote\s+)?(\S+\.(?:csv|json))\s*$", line)
        if match and ("Wrote" in line or paths):
            paths.append(Path(match.group(1)))
    return paths


def run_week(arguments: argparse.Namespace) -> int:
    plan = plan_week(
        season=arguments.season,
        gameweek=arguments.gameweek,
        league_id=arguments.league,
        snapshot_id=arguments.snapshot_id,
        cohort_snapshot=arguments.cohort_snapshot,
        elite_snapshot=arguments.elite_snapshot,
        skip_top100=arguments.skip_top100,
        publish=arguments.publish,
    )
    print(plan.describe(), flush=True)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"now (UTC): {now}", flush=True)
    if arguments.dry_run:
        print("Dry run: nothing captured, built or published.")
        return 0
    if not REGISTRY_PATH.is_file():
        raise WeekError(
            f"No entry registry at {REGISTRY_PATH}; seed it first with "
            "`python -m scripts.seed_entry_registry --league <id>`."
        )

    # 1. capture
    snapshot_id = arguments.snapshot_id
    if "capture" in plan.steps:
        written = capture(
            SNAPSHOT_ROOT,
            archive_root=ARCHIVE_ROOT,
            entry_registry=REGISTRY_PATH,
            league_id=plan.league_id,
        )
        if written is None:
            raise WeekError("The capture wrote nothing.")
        snapshot_id = written.snapshot_id
        print(f"captured {snapshot_id}", flush=True)
    assert snapshot_id is not None
    target, deadline_utc, captured_at = capture_deadline(SNAPSHOT_ROOT, snapshot_id)
    if target != plan.gameweek:
        raise WeekError(
            f"Capture {snapshot_id} is open for gameweek {target}, not {plan.gameweek}; "
            "the handoff and the league tree would decide the wrong week."
        )
    print(
        f"capture {snapshot_id}: gameweek {target}, deadline {deadline_utc}, captured {captured_at}"
    )

    # 2. Top-100: cohort, picks, evidence export
    evidence_table: Path | None = None
    evidence_manifest: Path | None = None
    if "top100" in plan.steps:
        cohort = arguments.cohort_snapshot
        if not cohort:
            before = list_snapshot_ids(SNAPSHOT_ROOT)
            _python(
                "scripts.capture_top100_cohort",
                "--target-gameweek",
                str(plan.gameweek),
                "--cohort-size",
                "100",
            )
            cohort = new_snapshot(before, list_snapshot_ids(SNAPSHOT_ROOT), COHORT_PREFIX)
        elite = arguments.elite_snapshot
        if not elite:
            before = list_snapshot_ids(SNAPSHOT_ROOT)
            _python(
                "scripts.capture_elite_picks",
                "--cohort-snapshot",
                cohort,
                "--target-gameweek",
                str(plan.gameweek),
                "--deadline-utc",
                deadline_utc,
            )
            elite = new_snapshot(before, list_snapshot_ids(SNAPSHOT_ROOT), ELITE_PREFIX)
        table_name = f"player_evidence_v1_{plan.season}_gw{plan.gameweek:02d}_top100"
        output = _python(
            "scripts.export_player_evidence",
            "--season",
            plan.season,
            "--target-gameweek",
            str(plan.gameweek),
            "--deadline-utc",
            deadline_utc,
            "--cohort-snapshot",
            cohort,
            "--snapshot",
            elite,
            "--output-dir",
            str(EVIDENCE_ROOT),
            "--table-name",
            table_name,
        )
        written_paths = _wrote_paths(output)
        evidence_table = next((p for p in written_paths if p.suffix == ".csv"), None)
        evidence_manifest = next((p for p in written_paths if p.suffix == ".json"), None)
        if evidence_table is None or evidence_manifest is None:
            raise WeekError("The evidence export did not report its table and manifest paths.")
        print(f"evidence {evidence_table.name} / {evidence_manifest.name}", flush=True)

    # 3. handoff: the component base, with the Top-100 uplift on top when the evidence
    # was exported this run and the caller did not ask for the bare projection
    handoff_arguments = ["--snapshot-id", snapshot_id, "--snapshot-root", str(SNAPSHOT_ROOT)]
    if arguments.projection == "component" and evidence_table is not None and evidence_manifest:
        handoff_arguments += [
            "--evidence-table",
            str(evidence_table),
            "--evidence-manifest",
            str(evidence_manifest),
        ]
    _python("scripts.build_projection_handoff", *handoff_arguments)
    handoff = handoff_path_for(HANDOFF_ROOT, plan.season, plan.gameweek)
    if not handoff.is_file():
        raise WeekError(f"The handoff {handoff} was not written.")

    # 4. league tree, 5. site views — into the checkout's web/public
    out = Path(arguments.out)
    _python(
        "scripts.build_league_site",
        "--league",
        str(plan.league_id),
        "--snapshot-id",
        snapshot_id,
        "--snapshot-root",
        str(SNAPSHOT_ROOT),
        "--in-season-projection",
        str(handoff),
        "--registry",
        str(REGISTRY_PATH),
        "--archive-root",
        str(ARCHIVE_ROOT),
        "--out",
        str(out),
        "--workers",
        str(arguments.workers),
    )
    _python("scripts.build_site", "--season", plan.season, "--out", str(out))

    # 6. publish
    if "publish" in plan.steps:
        _python(
            "scripts.publish_gameweek_site",
            "--kind",
            "decision",
            "--gameweek",
            str(plan.gameweek),
            "--season",
            plan.season,
            "--league",
            str(plan.league_id),
            "--snapshot-id",
            snapshot_id,
            "--in-season-projection",
            str(handoff),
            "--workers",
            str(arguments.workers),
        )
    else:
        print(
            "\nNot published. To open the site PR from this capture:\n"
            f"  python -m scripts.publish_gameweek_site --kind decision --gameweek {plan.gameweek} "
            f"--season {plan.season} --league {plan.league_id} --snapshot-id {snapshot_id} "
            f"--in-season-projection {handoff} --workers {arguments.workers}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--season", required=True)
    parser.add_argument("--gameweek", type=int, required=True)
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--snapshot-id", help="reuse this fpl-live capture instead of capturing")
    parser.add_argument("--cohort-snapshot", help="reuse this fpl-top100 capture")
    parser.add_argument("--elite-snapshot", help="reuse this fpl-elite-picks capture")
    parser.add_argument("--skip-top100", action="store_true", help="no Top-100 captures or export")
    parser.add_argument(
        "--projection",
        choices=("component", "component-only"),
        default="component",
        help="component: the Phase C component base with the bounded Top-100 uplift when "
        "the evidence was exported; component-only: the bare component base",
    )
    parser.add_argument("--workers", type=int, default=8, help="league tree solver processes")
    parser.add_argument("--out", default=str(SITE_OUT), help="site output root (web/public)")
    parser.add_argument("--publish", action="store_true", help="also open the site PR")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, run nothing")
    arguments = parser.parse_args()
    try:
        return run_week(arguments)
    except (WeekError, DataError) as error:
        print(f"\nrun_week stopped:\n  {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
