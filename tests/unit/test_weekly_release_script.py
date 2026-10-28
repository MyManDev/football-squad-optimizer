"""`scripts/weekly_release.ps1` releases one completed weekly run with no person in the loop.

It does what `weekly_run.ps1` prints for a person, in order, and stops at the first step that
fails (#1243, step 3). Every outside command passes through one wrapper, `Invoke-External`;
these tests dot-source the script under Windows PowerShell 5.1 and put a fake in its place that
records each call, so nothing here reads GitHub, runs a release script or reaches the VM. The
gate's `-Release` switch is pinned the same way, with a fake `Invoke-PowerShell`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.unit.test_weekly_schedule_script import _dry_run

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "weekly_release.ps1"
SCHEDULE = ROOT / "scripts" / "weekly_schedule.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")

FRIDAY = "2026-27-gw10-friday-20261106T1430Z"
STAMP = "2026-11-06T17:02:44.512Z"
CAPTURE = "fpl-live-20261106T143000Z-0123456789ab"
NEWS = "club-news-20261106T141500Z-ba9876543210"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
PR = "https://github.com/MyManDev/football-squad-optimizer/pull/1250"
TABLE = Path("artifacts/rotation/rotation_evidence_v4_2026-27_gw10_aa_decision_bb.csv")
RETAINED = Path("data/handoffs/by-capture") / CAPTURE / ("e" * 64 + ".json")

# Records each call, answers the reads the chain makes, and fails the call `$failing` matches.
FAKE = r"""
$global:calls = New-Object System.Collections.Generic.List[string]
function Invoke-External([string]$name, [string[]]$arguments) {
    $line = $name + ' ' + ($arguments -join ' ')
    $global:calls.Add($line)
    $lines = @()
    if ($line -match 'ls-remote') { $lines = @("1`trefs/tags/site-2026-27-gw09-settled",
        "2`trefs/tags/site-2026-27-gw10-decision", "2`trefs/tags/site-2026-27-gw10-decision^{}") }
    if ($line -match '--json id ') { $lines = @('PR_node') }
    if ($line -match '--json state') { $lines = @($global:state) }
    $exit = if ($global:failing -and $line -match $global:failing) { 1 } else { 0 }
    return [pscustomobject]@{ Exit = $exit; Lines = $lines }
}
function Pause-Release([int]$seconds) { }
"""


def _powershell(script: Path, parameters: str, *lines: str) -> str:
    prelude = ["$ErrorActionPreference = 'Stop'", "Set-StrictMode -Version 2.0"]
    command = "\n".join([*prelude, f". '{script}' {parameters}", *lines])
    completed = subprocess.run(
        [POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def _stage(name: str, value: dict[str, object], *outputs: Path) -> dict[str, object]:
    paths = [{"path": str(path)} for path in outputs]
    return {"name": name, "status": "completed", "value": value, "outputs": paths}


def _repository(
    tmp_path: Path, run_id: str = FRIDAY, news: bool = True, forecast: bool = True
) -> Path:
    # What a completed run leaves: its log, its journal and its preview, in their places.
    repo = tmp_path / "repo"
    logs, run = repo / "data/logs/weekly", repo / "data/runtime/weekly" / run_id
    for directory in (logs, run / "preview/data", repo / "artifacts/football"):
        directory.mkdir(parents=True)
    (logs / f"{run_id}.log").write_text(f"Published 212 files\nPR: {PR}\n", encoding="utf-8")
    leagues = json.dumps({"contract_version": "league_directory_v1", "generated_at_utc": STAMP})
    (run / "preview/data/leagues.json").write_text(leagues, encoding="utf-8")
    alias = repo / "data/handoffs/2026-27-gw10.json"
    request = {"season": "2026-27", "gameweek": 10, "rotation_capture": NEWS if news else None}
    journal = {
        "status": "completed",
        "request": {"request": request, "paths": {"snapshots": str(repo / "data/snapshots")}},
        "stages": [
            _stage("capture", {"snapshot_id": CAPTURE}),
            _stage("rotation", {"table": str(repo / TABLE)}, repo / TABLE),
            _stage("handoff", {"path": str(alias)}, alias, repo / RETAINED),
            _stage("publish", {"status": "pr_open", "publication_commit": COMMIT}),
        ],
    }
    (run / "run.json").write_text(json.dumps(journal), encoding="utf-8")
    for suffix in (".json", ".components.json") if forecast else ():
        (repo / "artifacts/football" / (CAPTURE + suffix)).write_text("{}", encoding="utf-8")
    return repo


def _release(
    repo: Path, run_id: str = FRIDAY, failing: str = "", state: str = "MERGED"
) -> tuple[list[str], int, list[str]]:
    out = _powershell(
        RELEASE,
        f"-RunId {run_id} -RepoRoot '{repo}'",
        FAKE,
        f"$global:failing = '{failing}'; $global:state = '{state}'",
        f"$code = Release-Run '{repo}' '{run_id}' 'Publish the week.' 2",
        "$global:calls | ForEach-Object { 'call: ' + $_ }",
        "'exit: ' + $code",
    ).splitlines()
    log = repo / "data/logs/weekly" / f"{run_id}.release.log"
    steps = [line.split(" ", 1)[1] for line in log.read_text(encoding="utf-8-sig").splitlines()]
    return [line[6:] for line in out if line.startswith("call: ")], int(out[-1][6:]), steps


def test_a_club_news_run_is_released_in_order_and_its_bundle_sealed_last(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    calls, code, steps = _release(repo)
    preview = repo / "data/runtime/weekly" / FRIDAY / "preview/data"
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
        f"bash scripts/vm_push.sh {tag}",
        f"python -m scripts.prepare_football_bundle --artifact-root {repo}\\artifacts "
        f"--snapshot-root {repo}\\data\\snapshots --snapshot-id {CAPTURE} "
        f"--handoff {repo / RETAINED} --site-data-root {preview} "
        f"--news-capture-id {NEWS} --rotation-table {repo / TABLE}",
    ]
    assert steps == [
        f"run {FRIDAY}: site pull request {PR}, accepted stamp {STAMP}, tag {tag}",
        "check_league_tree: ALL GOOD",
        f"enqueued at {COMMIT}",
        "merged into develop",
        f"live: {tag}",
        f"vm: {tag}",
        f"bundle: sealed for {CAPTURE} with club news {NEWS}",
    ]


def test_a_tuesday_run_ships_the_settled_week_and_seals_no_bundle(tmp_path: Path) -> None:
    run_id = "2026-27-gw10-tuesday-20261103T0200Z"
    calls, code, steps = _release(_repository(tmp_path, run_id, news=False), run_id)
    assert code == 0, steps
    ship = "sh scripts/release/ship.sh 1250 site-2026-27-gw09-fix1 release/gw09-fix1"
    assert calls[-2:] == [
        f"{ship} {STAMP} Publish the week. 9",
        "bash scripts/vm_push.sh site-2026-27-gw09-fix1",
    ]
    assert steps[-1] == "bundle: none, the run read no club-news capture"


@pytest.mark.parametrize(
    "failing,state,code,last_call,last_step",
    [
        ("check_league_tree", "MERGED", 2, "python -m", "check_league_tree exited 1;"),
        ("pr checks", "MERGED", 2, "gh pr checks", "(gh pr checks exited 1); nothing was enqueued"),
        ("", "OPEN", 1, "gh pr view 1250 --json state", "is OPEN, not merged within 2 min;"),
        ("ship\\.sh", "MERGED", 1, "sh scripts/release/ship.sh", "never by running ship.sh again"),
        ("vm_push", "MERGED", 1, "bash scripts/vm_push.sh", "the site is live, the VM is not on"),
    ],
)
def test_the_chain_stops_at_the_first_step_that_fails(
    tmp_path: Path, failing: str, state: str, code: int, last_call: str, last_step: str
) -> None:
    calls, exit_code, steps = _release(_repository(tmp_path), failing=failing, state=state)
    assert (exit_code, calls[-1].startswith(last_call)) == (code, True)
    assert (
        steps[-1].startswith("refused: " if code == 2 else "stopped: ") and last_step in steps[-1]
    )
    assert ("graphql" in " ".join(calls)) == (code == 1)


def test_no_seal_is_attempted_without_the_forecast_it_seals(tmp_path: Path) -> None:
    repo = _repository(tmp_path, forecast=False)
    calls, code, steps = _release(repo)
    assert (code, calls[-1]) == (1, "bash scripts/vm_push.sh site-2026-27-gw10-fix1")
    assert steps[-1] == (
        f"stopped: no football forecast for {CAPTURE} under {repo}\\artifacts; "
        "the seal was not attempted"
    )


def test_a_run_is_released_once(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    earlier = repo / "data/logs/weekly" / f"{FRIDAY}.release.log"
    earlier.write_text("2026-11-06T18:00:00Z stopped: ship.sh exited 1\n", encoding="utf-8")
    calls, code, steps = _release(repo)
    assert (calls, code) == ([], 2)
    assert steps[-1].startswith("refused: this run was released before;")


GATE_FAKE = r"""
$global:started = New-Object System.Collections.Generic.List[string]
function Invoke-PowerShell([string[]]$arguments) {
    $global:started.Add(($arguments -join ' '))
    $global:LASTEXITCODE = $global:exits[$global:started.Count - 1]
    if ($arguments -contains '-Kind') { 'log: C:\r\logs\2026-27-gw09-friday-20261031T0700Z.log' }
}
"""


@pytest.mark.parametrize(
    "release,run_exit,started,exit_code",
    [(False, 0, 1, 0), (False, 1, 1, 1), (True, 1, 1, 1), (True, 0, 2, 7)],
)
def test_the_gate_releases_only_with_the_switch_and_only_a_run_that_exited_0(
    release: bool, run_exit: int, started: int, exit_code: int
) -> None:
    out = _powershell(
        SCHEDULE,
        "",
        GATE_FAKE,
        f"$global:exits = @({run_exit}, 7)",
        f"Start-WeeklyRun @('-File', 'run.ps1', '-Kind', 'friday') ${release} 'C:\\r\\rel.ps1'",
        "'exit: ' + $LASTEXITCODE",
        "$global:started | ForEach-Object { 'started: ' + $_ }",
    ).splitlines()
    runs = [line[9:] for line in out if line.startswith("started: ")]
    assert (len(runs), f"exit: {exit_code}" in out) == (started, True)
    assert runs[0] == "-File run.ps1 -Kind friday"
    if started == 2:
        expected = "-File C:\\r\\rel.ps1 -RunId 2026-27-gw09-friday-20261031T0700Z"
        assert runs[1] == "-NoProfile -ExecutionPolicy Bypass " + expected


def test_a_dry_run_names_the_release_only_with_the_switch(tmp_path: Path) -> None:
    plain = _dry_run(tmp_path / "plain", "2026-10-31T07:05:00Z").stdout.splitlines()
    switched = _dry_run(tmp_path / "switched", "2026-10-31T07:05:00Z", "-Release").stdout
    gate, decision, would, release = switched.splitlines()
    assert ([gate, decision], len(plain), would.startswith("would run: ")) == (plain[:2], 3, True)
    assert release.startswith("would release a run that exits 0: powershell.exe ")
    assert release.endswith("weekly_release.ps1 -RunId <its run id>")
