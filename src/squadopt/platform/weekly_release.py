"""The release of a scheduled weekly run, from its site pull request to the live site (#1243).

    python -m squadopt.platform.weekly_release --run-id 2026-27-gw10-friday-20261106T1430Z

D1 on #1243 (6559389043, 2026-11-01): a scheduled run opens its site pull request with no
person, and its release runs only after İbo has seen that run's preview and said yes. So the
release is a command of its own, run by hand for one completed run by its id. The gate's
``--release``, which would call `release_run` in the same tick once the weekly command exited
0, stays off; switching it on is a new decision, recorded on #1243 first. The chain is
``scripts/weekly_release.ps1`` (#1249) in Python, so a Linux host releases too: what
``weekly_run.ps1`` prints for a person, in order, stopping at the first step that fails:

1. read what the run left: its journal (``data/runtime/weekly/<run id>/run.json``, through
   `weekly_journal.held_run`), the site pull request its log names, the accepted stamp
   (``generated_at_utc`` in the preview's ``data/leagues.json``) and the first unused tag;
2. ``scripts.check_league_tree`` on the preview;
3. wait for the pull request's required checks;
4. enqueue it with the GraphQL ``enqueuePullRequest`` mutation, pinned to the commit the run
   published (develop merges only through its queue), and wait until it has merged;
5. ``scripts/release/ship.sh`` with that tag and stamp, which verifies the live site;
6. move the backend to the release, through one hook (below);
7. on a run that rode on club news, seal the football bundle, once the forecast it seals
   exists.

The PC's step 6 was ``vm_push.sh``: it streams the PC's captures to the VM and restarts the
backend's containers there. On the backend host the run wrote its data on that host already,
so that step does not apply and the chain never calls it. No agent or automation
starts, restarts or stops the backend, so the default hook writes one line and runs nothing:
the backend's operator moves it to the release.

Each step writes one line to ``data/logs/weekly/<run id>.release.log`` and prints it; the
commands' output goes to ``<run id>.release-commands.log``. The release log is the run's
marker too: a run that has one is never released again, because a release that stopped
part-way may already be public and only a person can tell (``docs/deployment_runbook.md``,
"The release window is closed to develop"). The exit code is 0 when every step completed, 2
for a refusal before the enqueue, which changes nothing, and 1 for a stop after it, which a
person reconciles from the two logs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from squadopt.contracts.run_logs import LOG_ROOT_NAME
from squadopt.platform.weekly_journal import WeeklyJournalError, held_run
from squadopt.platform.weekly_publish import WEEKLY_RUNS

WEEKLY_LOGS: Final = LOG_ROOT_NAME / "weekly"
SUMMARY: Final = "Publish the tree the scheduled weekly run recorded (#1243)."
#: How long the chain waits for the required checks, and again for the merge.
WAIT_MINUTES: Final = 60
#: The expected head makes the queue refuse a pull request that moved after the run published it.
ENQUEUE_MUTATION: Final = (
    "mutation($id: ID!, $head: GitObjectID) { enqueuePullRequest(input: {pullRequestId: $id, "
    "expectedHeadOid: $head}) { mergeQueueEntry { position } } }"
)
#: `gh pr checks` exits 8 while a check is pending, and reports none before CI has started.
CHECKS_PENDING: Final = 8
NO_CHECKS: Final = re.compile(r"no (required )?checks reported", re.IGNORECASE)
RUN_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}")
RUN_KIND: Final = re.compile(r"-gw[0-9]{2}-(tuesday|friday)-")
#: The line `weekly_publish` prints once it has opened the site pull request.
PULL_REQUEST: Final = re.compile(r"^PR: (https://github\.com/\S+)", re.MULTILINE)
#: A handoff retained by capture, the copy the seal names rather than the gameweek's alias.
RETAINED: Final = re.compile(r"[\\/]by-capture[\\/]")
#: The two documents of the forecast a seal reads, beside each other under `<root>/football`.
FORECAST: Final = (".json", ".components.json")


@dataclass(frozen=True, slots=True)
class Completed:
    """One outside command's exit code and the lines it printed, stdout and stderr together."""

    code: int
    lines: tuple[str, ...] = ()


#: Runs one outside command (its arguments, working directory and log) to its end.
Runner = Callable[[Sequence[str], Path, Path], Completed]
#: Writes one line to the release log.
Say = Callable[[str], None]
#: Moves the backend to the release tag once the site is live, saying what it did; 0, or the
#: code that stops the chain.
MoveBackend = Callable[[str, Say], int]
#: Waits a number of seconds between two reads of GitHub.
Pause = Callable[[float], None]


class ReleaseRefused(ValueError):
    """A refusal before the enqueue: nothing changed, and the chain exits 2."""


@dataclass(frozen=True, slots=True)
class ReleaseInputs:
    """What a completed run left for its release: its journal, its log and its preview."""

    kind: str
    season: str
    gameweek: int
    pull_request: str
    preview: Path
    stamp: str
    commit: str
    news: str
    capture: str
    snapshots: Path
    handoff: Path
    rotation: str

    @property
    def number(self) -> str:
        return self.pull_request.rsplit("/", 1)[-1]


def published_pull_request(log: Path) -> str:
    """The site pull request the run's log names, as `Published-PullRequest` reads it."""

    if not log.is_file():
        return ""
    match = PULL_REQUEST.search(log.read_text(encoding="utf-8", errors="replace"))
    return match[1] if match else ""


def release_inputs(workspace: Path, run_id: str) -> ReleaseInputs:
    """Read what the completed run `run_id` left, refusing a run that did not publish."""

    try:
        with held_run(workspace / WEEKLY_RUNS, run_id) as journal:
            status = journal["status"]
            declared = journal["request"]
            stages = {stage["name"]: stage for stage in journal["stages"]}
    except WeeklyJournalError as error:
        raise ReleaseRefused(str(error)) from error
    if status != "completed":
        raise ReleaseRefused(f"Run {run_id} is {status}, not completed.")
    kind = RUN_KIND.search(run_id)
    if kind is None:
        raise ReleaseRefused(f"Run id {run_id} names no tuesday or friday run.")
    try:
        request, paths = declared["request"], declared["paths"]
        season, gameweek = str(request["season"]), int(request["gameweek"])
        news = str(request.get("rotation_capture") or "")
        commit = str(stages["publish"]["value"].get("publication_commit") or "")
        capture = str(stages["capture"]["value"]["snapshot_id"])
        retained = [
            str(output["path"])
            for output in stages["handoff"]["outputs"]
            if RETAINED.search(str(output["path"]))
        ]
        handoff = Path(retained[0] if retained else str(stages["handoff"]["value"]["path"]))
        rotation = str(stages["rotation"]["value"]["table"]) if news else ""
        preview, snapshots = Path(str(paths["out"])) / "data", Path(str(paths["snapshots"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ReleaseRefused(
            f"The journal of run {run_id} does not record what a release reads ({error!r})."
        ) from error
    if not commit:
        raise ReleaseRefused(f"Run {run_id} published no commit, so there is nothing to release.")
    leagues = preview / "leagues.json"
    try:
        stamp = json.loads(leagues.read_text(encoding="utf-8")).get("generated_at_utc")
    except (OSError, ValueError, AttributeError) as error:
        raise ReleaseRefused(
            f"The preview has no readable {leagues} to read the accepted stamp from."
        ) from error
    if not isinstance(stamp, str) or not stamp:
        raise ReleaseRefused(f"{leagues} names no generated_at_utc, the accepted stamp.")
    pull_request = published_pull_request(workspace / WEEKLY_LOGS / f"{run_id}.log")
    if not pull_request:
        raise ReleaseRefused("The run's log names no site pull request.")
    return ReleaseInputs(
        kind=kind[1],
        season=season,
        gameweek=gameweek,
        pull_request=pull_request,
        preview=preview,
        stamp=stamp,
        commit=commit,
        news=news,
        capture=capture,
        snapshots=snapshots,
        handoff=handoff,
        rotation=rotation,
    )


def remote_tags(lines: Sequence[str]) -> frozenset[str]:
    """The tag names `git ls-remote --tags` lists, without the peeled `^{}` entries."""

    names = (line.split()[1] for line in lines if len(line.split()) >= 2)
    return frozenset(name.removeprefix("refs/tags/") for name in names if not name.endswith("^{}"))


def suggested_tag(kind: str, season: str, gameweek: int, existing: Collection[str]) -> str:
    """The first unused tag under the cadence's naming, as `Suggested-Tag` in `weekly_run.ps1`.

    Tags are immutable and never reused. A Tuesday run carries the week it settles.
    """

    week = gameweek - 1 if kind == "tuesday" else gameweek
    first = f"site-{season}-gw{week:02d}-{'settled' if kind == 'tuesday' else 'decision'}"
    if first not in existing:
        return first
    fix = 1
    while f"site-{season}-gw{week:02d}-fix{fix}" in existing:
        fix += 1
    return f"site-{season}-gw{week:02d}-fix{fix}"


def ship_arguments(run: ReleaseInputs, tag: str, summary: str) -> list[str]:
    """The `ship.sh` line `weekly_run.ps1` prints; a Tuesday run states the week it settles."""

    branch = "release/" + re.sub(r"^site-[0-9]{4}-[0-9]{2}-", "", tag)
    arguments = ["sh", "scripts/release/ship.sh", run.number, tag, branch, run.stamp, summary]
    if run.kind == "tuesday":
        arguments.append(str(run.gameweek - 1))
    return arguments


def bundle_root(workspace: Path) -> Path:
    """The root the backend reads and the forecast is built in (``docs/backend_runbook.md``)."""

    selection = workspace / "artifacts" / "backend-artifact-root.json"
    if not selection.is_file():
        return workspace / "artifacts"
    root = Path(str(json.loads(selection.read_text(encoding="utf-8"))["artifact_root"]))
    return root if root.is_absolute() else workspace / root


def leave_backend_to_its_operator(tag: str, say: Say) -> int:
    """The default backend move: one line in the release log, and no command at all.

    The team rule is that no agent or automation starts, restarts or stops the backend. So
    the move of the backend to `tag` (checking the tag out where its image is built,
    rebuilding the image and restarting its containers, as ``scripts/vm_sync.sh`` does) is
    left to its operator, and this hook only says so.
    """

    say(f"backend: left to its operator to move to {tag}; nothing was started or stopped")
    return 0


def posix_shell() -> str:
    """`sh` on a POSIX host; on Windows Git for Windows' own, never another one on PATH."""

    if os.name != "nt" or (git := shutil.which("git")) is None:
        return "sh"
    # git.exe sits in <Git>\cmd, <Git>\bin or <Git>\mingw64\bin; the shell in <Git>\bin.
    install = Path(git).resolve().parent
    while install.name.lower() in {"cmd", "bin", "mingw64"}:
        install = install.parent
    return str(install / "bin" / "sh.exe")


def run_captured(arguments: Sequence[str], cwd: Path, log: Path) -> Completed:
    """Run one command from `cwd` on the checkout's `src` to its end; append its output to `log`."""

    command = list(arguments)
    if command and command[0] == "sh":
        command[0] = posix_shell()
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(cwd / "src"), str(cwd)))}
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        code, output = completed.returncode, completed.stdout
    except OSError as error:
        # A command that cannot start is a step that failed, never one that passed.
        code, output = 127, f"{command[0]}: {error}"
    lines = tuple(output.splitlines())
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write("".join(f"{line}\n" for line in (f"$ {' '.join(arguments)}", *lines)))
    return Completed(code, lines)


def wait_checks(
    number: str, run: Callable[[Sequence[str]], Completed], minutes: int, pause: Pause
) -> int:
    """`gh pr checks --required`'s exit code once no check is pending; 8 if one still is."""

    for _ in range(minutes):
        checks = run(["gh", "pr", "checks", number, "--required"])
        reported = not any(NO_CHECKS.search(line) for line in checks.lines)
        if checks.code != CHECKS_PENDING and reported:
            return checks.code
        pause(60)
    return CHECKS_PENDING


def wait_merged(
    number: str, run: Callable[[Sequence[str]], Completed], minutes: int, pause: Pause
) -> str:
    """The pull request's state once it is MERGED or CLOSED, or the last one read."""

    state = ""
    for _ in range(minutes):
        read = run(["gh", "pr", "view", number, "--json", "state", "--jq", ".state"])
        state = "".join(read.lines).strip()
        if state in {"MERGED", "CLOSED"}:
            return state
        pause(60)
    return state


def release_run(
    workspace: Path,
    run_id: str,
    *,
    runner: Runner = run_captured,
    move_backend: MoveBackend = leave_backend_to_its_operator,
    pause: Pause = time.sleep,
    wait_minutes: int = WAIT_MINUTES,
    summary: str = SUMMARY,
) -> int:
    """Release the completed run `run_id`: every step in order, the first that fails stops it.

    `runner` is the one door to every outside command and `move_backend` the backend's move,
    both seams; the exit code is 0 when every step completed, 2 for a refusal before the
    enqueue and 1 for a stop after it.
    """

    if not RUN_ID.fullmatch(run_id):
        print(f"release: refused: {run_id!r} is not a run id")
        return 2
    logs = workspace / WEEKLY_LOGS
    log = logs / f"{run_id}.release.log"
    commands = logs / f"{run_id}.release-commands.log"

    def say(text: str) -> None:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {text}\n")
        print(f"release: {text}")

    def run(arguments: Sequence[str]) -> Completed:
        return runner(arguments, workspace, commands)

    if log.exists():
        say(
            "refused: this run was released before; a release is attempted once, and one that "
            "stopped is reconciled by hand"
        )
        return 2
    logs.mkdir(parents=True, exist_ok=True)
    try:
        release = release_inputs(workspace, run_id)
        pattern = f"site-{release.season}-gw*"
        listed = run(["git", "-C", str(workspace), "ls-remote", "--tags", "origin", pattern])
        if listed.code != 0:
            raise ReleaseRefused(
                f"git ls-remote exited {listed.code}; the next unused tag is unknown."
            )
        tag = suggested_tag(
            release.kind, release.season, release.gameweek, remote_tags(listed.lines)
        )
    except ReleaseRefused as error:
        say(f"refused: {error}")
        return 2
    number = release.number
    say(
        f"run {run_id}: site pull request {release.pull_request}, accepted stamp "
        f"{release.stamp}, tag {tag}"
    )
    tree = run([sys.executable, "-m", "scripts.check_league_tree", str(release.preview)])
    if tree.code != 0:
        say(f"refused: check_league_tree exited {tree.code}; nothing was enqueued")
        return 2
    say("check_league_tree: ALL GOOD")
    checks = wait_checks(number, run, wait_minutes, pause)
    if checks != 0:
        say(
            f"refused: the required checks of #{number} did not pass (gh pr checks exited "
            f"{checks}); nothing was enqueued"
        )
        return 2
    node = run(["gh", "pr", "view", number, "--json", "id", "--jq", ".id"])
    node_id = "".join(node.lines).strip()
    if node.code != 0 or not node_id:
        say("refused: the pull request could not be read; nothing was enqueued")
        return 2
    queued = run(
        [
            *("gh", "api", "graphql", "-f", f"query={ENQUEUE_MUTATION}"),
            *("-f", f"id={node_id}", "-f", f"head={release.commit}"),
        ]
    )
    if queued.code != 0:
        say(
            f"stopped: the enqueue exited {queued.code}; read the pull request before anything else"
        )
        return 1
    say(f"enqueued at {release.commit}")
    state = wait_merged(number, run, wait_minutes, pause)
    if state != "MERGED":
        say(
            f"stopped: #{number} is {state or 'unread'}, not merged within {wait_minutes} min; "
            "nothing was released"
        )
        return 1
    say("merged into develop")
    ship = run(ship_arguments(release, tag, summary))
    if ship.code != 0:
        say(
            f'stopped: ship.sh exited {ship.code}; after "release PR #N merged" recover by hand '
            "as docs/deployment_runbook.md says, never by running ship.sh again"
        )
        return 1
    say(f"live: {tag}")
    moved = move_backend(tag, say)
    if moved != 0:
        say(
            f"stopped: the backend move exited {moved}; the site is live, the backend is not "
            f"on {tag}"
        )
        return 1
    if not release.news:
        say("bundle: none, the run read no club-news capture")
        return 0
    return seal_bundle(workspace, release, run, say)


def seal_bundle(
    workspace: Path, release: ReleaseInputs, run: Callable[[Sequence[str]], Completed], say: Say
) -> int:
    """Seal the football bundle with the run's club news, once the forecast it seals exists.

    The seal records its attempt before it reads the forecast, and a refused attempt turns
    the manager's word off for the capture, so it is not attempted without the forecast.
    """

    try:
        root = bundle_root(workspace)
    except (OSError, ValueError, KeyError, TypeError) as error:
        say(
            f"stopped: the backend artifact root is unreadable ({error}); the seal was not "
            "attempted"
        )
        return 1
    forecast = root / "football"
    if not all((forecast / f"{release.capture}{suffix}").is_file() for suffix in FORECAST):
        say(
            f"stopped: no football forecast for {release.capture} under {root}; the seal was "
            "not attempted"
        )
        return 1
    bundle = run(
        [
            *(sys.executable, "-m", "scripts.prepare_football_bundle", "--artifact-root"),
            *(str(root), "--snapshot-root", str(release.snapshots)),
            *("--snapshot-id", release.capture, "--handoff", str(release.handoff)),
            *("--site-data-root", str(release.preview), "--news-capture-id", release.news),
            *("--rotation-table", release.rotation),
        ]
    )
    if bundle.code != 0:
        say(
            f"stopped: prepare_football_bundle exited {bundle.code}; retry only with the "
            "identical inputs"
        )
        return 1
    say(f"bundle: sealed for {release.capture} with club news {release.news}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--run-id",
        required=True,
        help="the completed run to release, as the gate's start line on #1093 names it",
    )
    return parser


def main(
    argv: list[str] | None = None, *, release: Callable[[Path, str], int] = release_run
) -> int:
    """Release one completed run by its id, after its preview and a yes (D1 on #1243).

    `release` is the seam: the chain's own `release_run` unless a test passes another.
    """

    arguments = build_parser().parse_args(argv)
    return release(arguments.workspace.resolve(), arguments.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
