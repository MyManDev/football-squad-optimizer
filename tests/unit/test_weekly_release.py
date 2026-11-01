"""`squadopt.platform.weekly_release` releases one completed weekly run by its id (#1243).

The decision table of the PowerShell chain's tests (`scripts/weekly_release.ps1`, #1249), run on
the Python chain with no PowerShell: the step order, the stop at each failure, the tag and stamp
passed to `ship.sh`, the bundle seal only on a club-news run, and one release per run. Every
outside command passes through the chain's one runner, and these tests put a recorder in its
place, so nothing here reads GitHub, runs a release script or touches a backend. On the backend
host the PC's `vm_push.sh` does not apply: the chain never calls it, and its backend hook by
default writes one line and runs no command.

The journal each test releases is written by `WeeklyRun` itself, with the stages and values a
completed publishing run records, so the chain reads it as it reads a real one.
"""

from __future__ import annotations

import functools
import inspect
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from squadopt.platform import weekly_release as chain
from squadopt.platform.weekly_journal import WeeklyRun, WeeklyStageResult
from squadopt.platform.weekly_publish import WEEKLY_RUNS

FRIDAY = "2026-27-gw10-friday-20261106T1430Z"
TUESDAY = "2026-27-gw10-tuesday-20261103T0200Z"
STAMP = "2026-11-06T17:02:44.512Z"
CAPTURE = "fpl-live-20261106T143000Z-0123456789ab"
NEWS = "club-news-20261106T141500Z-ba9876543210"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
PR = "https://github.com/MyManDev/football-squad-optimizer/pull/1250"
TABLE = Path("artifacts/rotation/rotation_evidence_v4_2026-27_gw10_aa_decision_bb.csv")
RETAINED = Path("data/handoffs/by-capture") / CAPTURE / ("e" * 64 + ".json")
TAGS = (
    "1\trefs/tags/site-2026-27-gw09-settled",
    "2\trefs/tags/site-2026-27-gw10-decision",
    "2\trefs/tags/site-2026-27-gw10-decision^{}",
)


class _Host:
    """The runner, recorded: answers the reads the chain makes and fails the call it names."""

    def __init__(self, failing: str = "", states: Sequence[str] = ("MERGED",)) -> None:
        self.calls: list[str] = []
        self.failing = failing
        self.states = list(states)

    def runner(self, arguments: Sequence[str], cwd: Path, log: Path) -> chain.Completed:
        name = "python" if arguments[0] == sys.executable else arguments[0]
        line = " ".join([name, *arguments[1:]])
        self.calls.append(line)
        lines: tuple[str, ...] = ()
        if "ls-remote" in arguments:
            lines = TAGS
        elif list(arguments[4:6]) == ["--json", "id"]:
            lines = ("PR_node",)
        elif list(arguments[4:6]) == ["--json", "state"]:
            lines = (self.states.pop(0) if len(self.states) > 1 else self.states[0],)
        return chain.Completed(1 if self.failing and self.failing in line else 0, lines)


def _output(path: Path, text: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _repository(
    tmp_path: Path, run_id: str = FRIDAY, *, news: bool = True, forecast: bool = True
) -> Path:
    """What a completed run leaves: its log, its journal and its preview, in their places."""

    repo = tmp_path / "repo"
    runs = repo / WEEKLY_RUNS
    preview = runs / run_id / "preview"
    _output(repo / chain.WEEKLY_LOGS / f"{run_id}.log", f"Published 212 files\nPR: {PR}\n")
    leagues = {"contract_version": "league_directory_v1", "generated_at_utc": STAMP}
    _output(preview / "data/leagues.json", json.dumps(leagues))
    request = {"season": "2026-27", "gameweek": 10, "rotation_capture": NEWS if news else None}
    paths = {"snapshots": str(repo / "data/snapshots"), "out": str(preview)}
    alias = _output(repo / "data/handoffs/2026-27-gw10.json")
    values = {
        "capture": ({"snapshot_id": CAPTURE}, [_output(repo / "data/snapshots" / CAPTURE / "a")]),
        "rotation": ({"table": str(repo / TABLE)}, [_output(repo / TABLE, "player_id\n")]),
        "handoff": ({"path": str(alias)}, [alias, _output(repo / RETAINED)]),
        "publish": (
            {"status": "pr_open", "publication_commit": COMMIT, "pr_url": PR},
            [preview / "data/leagues.json"],
        ),
    }
    run = WeeklyRun(runs, run_id, {"request": request, "paths": paths}, list(values))
    with run.hold():
        for stage, (value, outputs) in values.items():
            result = WeeklyStageResult(tuple(outputs), value)
            run.stage(stage, inputs=[], operation=lambda result=result: result)
        run.finish()
    for suffix in chain.FORECAST if forecast else ():
        _output(repo / "artifacts/football" / f"{CAPTURE}{suffix}")
    return repo


def _release(
    repo: Path,
    run_id: str = FRIDAY,
    host: _Host | None = None,
    move_backend: chain.MoveBackend = chain.leave_backend_to_its_operator,
) -> tuple[list[str], int, list[str]]:
    host = host or _Host()
    code = chain.release_run(
        repo,
        run_id,
        runner=host.runner,
        move_backend=move_backend,
        pause=lambda seconds: None,
        wait_minutes=2,
        summary="Publish the week.",
    )
    log = repo / chain.WEEKLY_LOGS / f"{run_id}.release.log"
    steps = [line.split(" ", 1)[1] for line in log.read_text(encoding="utf-8").splitlines()]
    return host.calls, code, steps


def test_a_club_news_run_is_released_in_order_and_its_bundle_sealed_last(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    calls, code, steps = _release(repo)
    preview = repo / WEEKLY_RUNS / FRIDAY / "preview" / "data"
    tag = "site-2026-27-gw10-fix1"
    assert code == 0, steps
    assert calls[:4] == [
        f"git -C {repo} ls-remote --tags origin site-2026-27-gw*",
        f"python -m scripts.check_league_tree {preview}",
        "gh pr checks 1250 --required",
        "gh pr view 1250 --json id --jq .id",
    ]
    assert calls[4].startswith("gh api graphql -f query=mutation(")
    assert "enqueuePullRequest(input: {pullRequestId: $id, expectedHeadOid: $head})" in calls[4]
    assert calls[4].endswith(f" -f id=PR_node -f head={COMMIT}")
    assert calls[5:] == [
        "gh pr view 1250 --json state --jq .state",
        f"sh scripts/release/ship.sh 1250 {tag} release/gw10-fix1 {STAMP} Publish the week.",
        f"python -m scripts.prepare_football_bundle --artifact-root {repo / 'artifacts'} "
        f"--snapshot-root {repo / 'data/snapshots'} --snapshot-id {CAPTURE} "
        f"--handoff {repo / RETAINED} --site-data-root {preview} "
        f"--news-capture-id {NEWS} --rotation-table {repo / TABLE}",
    ]
    assert steps == [
        f"run {FRIDAY}: site pull request {PR}, accepted stamp {STAMP}, tag {tag}",
        "check_league_tree: ALL GOOD",
        f"enqueued at {COMMIT}",
        "merged into develop",
        f"live: {tag}",
        f"backend: left to its operator to move to {tag}; nothing was started or stopped",
        f"bundle: sealed for {CAPTURE} with club news {NEWS}",
    ]


def test_a_tuesday_run_ships_the_settled_week_and_seals_no_bundle(tmp_path: Path) -> None:
    calls, code, steps = _release(_repository(tmp_path, TUESDAY, news=False), TUESDAY)
    assert code == 0, steps
    ship = "sh scripts/release/ship.sh 1250 site-2026-27-gw09-fix1 release/gw09-fix1"
    assert calls[-1] == f"{ship} {STAMP} Publish the week. 9"
    assert steps[-2:] == [
        "backend: left to its operator to move to site-2026-27-gw09-fix1; nothing was started "
        "or stopped",
        "bundle: none, the run read no club-news capture",
    ]


@pytest.mark.parametrize(
    "failing,states,code,last_call,last_step",
    [
        ("check_league_tree", ["MERGED"], 2, "python -m", "check_league_tree exited 1;"),
        ("pr checks", ["MERGED"], 2, "gh pr checks", "(gh pr checks exited 1); nothing was"),
        ("graphql", ["MERGED"], 1, "gh api graphql", "the enqueue exited 1; read the pull"),
        ("", ["OPEN"], 1, "gh pr view 1250 --json state", "is OPEN, not merged within 2 min;"),
        ("", ["CLOSED"], 1, "gh pr view 1250 --json state", "is CLOSED, not merged within"),
        ("ship.sh", ["MERGED"], 1, "sh scripts/release/ship.sh", "never by running ship.sh"),
        ("prepare_football", ["MERGED"], 1, "python -m scripts.prepare", "identical inputs"),
    ],
)
def test_the_chain_stops_at_the_first_step_that_fails(
    tmp_path: Path, failing: str, states: list[str], code: int, last_call: str, last_step: str
) -> None:
    calls, exit_code, steps = _release(_repository(tmp_path), host=_Host(failing, states))
    assert (exit_code, calls[-1].startswith(last_call)) == (code, True), calls
    assert steps[-1].startswith("refused: " if code == 2 else "stopped: "), steps
    assert last_step in steps[-1]
    # A refusal comes before the enqueue, and a stop after it.
    assert ("graphql" in " ".join(calls)) == (code == 1)


def test_the_states_are_read_until_the_merge_and_each_wait_pauses(tmp_path: Path) -> None:
    pauses: list[float] = []
    host = _Host(states=["OPEN", "MERGED"])
    code = chain.release_run(
        _repository(tmp_path / "a", news=False),
        FRIDAY,
        runner=host.runner,
        pause=pauses.append,
        wait_minutes=3,
    )
    assert code == 0
    assert host.calls.count("gh pr view 1250 --json state --jq .state") == 2
    assert pauses == [60]


def test_pending_or_unreported_checks_are_waited_for_and_a_pass_is_awaited_no_longer() -> None:
    answers = [
        chain.Completed(8, ("build pending",)),
        chain.Completed(1, ("no required checks reported on the 'site' branch",)),
        chain.Completed(0, ("build pass",)),
    ]
    pauses: list[float] = []
    assert chain.wait_checks("1250", lambda arguments: answers.pop(0), 5, pauses.append) == 0
    assert (answers, pauses) == ([], [60, 60])
    pending = chain.Completed(8, ())
    assert chain.wait_checks("1250", lambda arguments: pending, 2, pauses.append) == 8


def test_a_failed_backend_move_stops_the_chain_after_the_site_is_live(tmp_path: Path) -> None:
    def failing_move(tag: str, say: chain.Say) -> int:
        say(f"backend: tried {tag}")
        return 5

    calls, code, steps = _release(_repository(tmp_path), move_backend=failing_move)
    assert (code, calls[-1].startswith("sh scripts/release/ship.sh")) == (1, True)
    assert steps[-2:] == [
        "backend: tried site-2026-27-gw10-fix1",
        "stopped: the backend move exited 5; the site is live, the backend is not on "
        "site-2026-27-gw10-fix1",
    ]


def test_the_default_backend_hook_says_so_and_runs_no_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*arguments: object, **options: object) -> None:
        pytest.fail(f"the backend hook ran a command: {arguments}")

    for name in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr("os.system", forbidden)
    said: list[str] = []
    assert chain.leave_backend_to_its_operator("site-2026-27-gw10-fix1", said.append) == 0
    assert said == [
        "backend: left to its operator to move to site-2026-27-gw10-fix1; nothing was started "
        "or stopped"
    ]
    # Through the whole chain the runner sees no backend command: ship.sh, then the seal.
    calls, code, _ = _release(_repository(tmp_path))
    assert code == 0
    assert not [call for call in calls if "vm_push" in call or "vm_sync" in call]
    assert [call.split()[:3] for call in calls[-2:]] == [
        ["sh", "scripts/release/ship.sh", "1250"],
        ["python", "-m", "scripts.prepare_football_bundle"],
    ]


def test_no_seal_is_attempted_without_the_forecast_it_seals(tmp_path: Path) -> None:
    repo = _repository(tmp_path, forecast=False)
    calls, code, steps = _release(repo)
    assert (code, calls[-1].startswith("sh scripts/release/ship.sh")) == (1, True)
    assert steps[-1] == (
        f"stopped: no football forecast for {CAPTURE} under {repo / 'artifacts'}; "
        "the seal was not attempted"
    )


def test_the_seal_reads_the_root_the_backend_selection_names(tmp_path: Path) -> None:
    repo = _repository(tmp_path, forecast=False)
    selected = repo / "artifacts/football-retained-gw10"
    for suffix in chain.FORECAST:
        _output(selected / "football" / f"{CAPTURE}{suffix}")
    selection = json.dumps({"artifact_root": "artifacts/football-retained-gw10"})
    _output(repo / "artifacts/backend-artifact-root.json", selection)
    calls, code, _ = _release(repo)
    assert code == 0
    assert f"--artifact-root {selected} " in calls[-1]


def test_a_run_is_released_once(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    earlier = repo / chain.WEEKLY_LOGS / f"{FRIDAY}.release.log"
    earlier.write_text("2026-11-06T18:00:00Z stopped: ship.sh exited 1\n", encoding="utf-8")
    calls, code, steps = _release(repo)
    assert (calls, code) == ([], 2)
    assert steps[-1].startswith("refused: this run was released before;")


@pytest.mark.parametrize(
    "spoil,reason",
    [
        ("log", "The run's log names no site pull request."),
        ("stamp", "names no generated_at_utc, the accepted stamp."),
        ("journal", "No weekly run 2026-27-gw10-friday-20261106T1430Z is journalled under"),
    ],
)
def test_a_run_missing_what_a_release_reads_is_refused_before_any_command(
    tmp_path: Path, spoil: str, reason: str
) -> None:
    repo = _repository(tmp_path)
    run = repo / WEEKLY_RUNS / FRIDAY
    if spoil == "log":
        _output(repo / chain.WEEKLY_LOGS / f"{FRIDAY}.log", "Published 212 files\n")
    elif spoil == "stamp":
        _output(run / "preview/data/leagues.json", json.dumps({"generated_at_utc": ""}))
    else:
        (run / "run.json").unlink()
    calls, code, steps = _release(repo)
    assert (calls, code) == ([], 2)
    assert steps[-1].startswith("refused: ") and reason in steps[-1]


def test_the_tag_is_the_first_unused_one_of_the_cadence() -> None:
    tags = chain.remote_tags(TAGS)
    assert tags == {"site-2026-27-gw09-settled", "site-2026-27-gw10-decision"}
    assert chain.suggested_tag("friday", "2026-27", 11, tags) == "site-2026-27-gw11-decision"
    assert chain.suggested_tag("tuesday", "2026-27", 11, tags) == "site-2026-27-gw10-settled"
    held = {*tags, "site-2026-27-gw10-fix1"}
    assert chain.suggested_tag("friday", "2026-27", 10, held) == "site-2026-27-gw10-fix2"


def test_the_real_runner_appends_each_command_and_its_output_and_a_missing_one_fails(
    tmp_path: Path,
) -> None:
    log = tmp_path / "logs" / "run.release-commands.log"
    said = chain.run_captured([sys.executable, "-c", "print('checked')"], tmp_path, log)
    missing = chain.run_captured(["squadopt-no-such-command"], tmp_path, log)
    assert (said.code, said.lines) == (0, ("checked",))
    assert missing.code == 127
    text = log.read_text(encoding="utf-8").splitlines()
    assert text[:2] == [f"$ {sys.executable} -c print('checked')", "checked"]
    assert text[2] == "$ squadopt-no-such-command"


def test_the_release_is_a_command_of_its_own_that_takes_one_run_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repository(tmp_path)
    host = _Host()
    chained = functools.partial(
        chain.release_run, runner=host.runner, pause=lambda seconds: None, wait_minutes=2
    )
    assert chain.main(["--workspace", str(repo), "--run-id", FRIDAY], release=chained) == 0
    assert host.calls[-1].startswith("python -m scripts.prepare_football_bundle")
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"release: bundle: sealed for {CAPTURE} with club news {NEWS}"
    )

    asked: list[tuple[Path, str]] = []

    def release(workspace: Path, run_id: str) -> int:
        asked.append((workspace, run_id))
        return 2

    assert chain.main(["--workspace", str(repo), "--run-id", TUESDAY], release=release) == 2
    assert asked == [(repo.resolve(), TUESDAY)]
    with pytest.raises(SystemExit) as missing:
        chain.main(["--workspace", str(repo)], release=release)
    assert missing.value.code == 2
    assert "the following arguments are required: --run-id" in capsys.readouterr().err
    assert inspect.signature(chain.main).parameters["release"].default is chain.release_run
