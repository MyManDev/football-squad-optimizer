"""The restart helper runs the code of the live site release, not whatever develop holds.

`scripts/release/restart_backend.ps1` used to fetch develop, compare capture ids and pull,
so a restart could serve commits no release had reviewed. It now names the release (the
newest `site-*` tag whose production deploy succeeded, or `-ReleaseTag`), fetches that tag,
and refuses, unless `-Force`, when the fetched develop differs from the tag's commit in
`src`, `scripts` or `docs/contracts`.

Every run here is a `-DryRun` of the real script, started the documented way with
`powershell -File`, in a disposable clone whose `origin` is a local bare repository. GitHub
CLI is a recorded fake. No run reaches a backend, port 8000 or the network: the release
check comes before the script reads the backend registry, and these checkouts have none, so
a run the release check lets through stops there, as it would with the backend down.

The helper cannot start a stopped backend, so `docs/deployment_runbook.md` ("A stopped
backend starts from the release") does it by hand. The last tests type that subsection's
PowerShell blocks, line by line and in order, into the same kind of clone, with a recording
launcher in place of `run_backend_local.ps1`. They prove what following the text starts:
the release's code, and after the next release the main checkout's `src` at that release's
code, never the develop the checkout held when the backend went down.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs/deployment_runbook.md"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = [
    pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1"),
    pytest.mark.skipif(shutil.which("git") is None, reason="requires Git"),
]

DECISION = "site-2026-27-gw06-decision"
FIX = "site-2026-27-gw06-fix1"
LATER = "site-2026-27-gw06-fix2"
NEXT = "site-2026-27-gw07-settled"
APP = "src/squadopt/api/app.py"
DATA = "web/public/data/latest.json"
# What a backend runs and serves: the paths the runbook's comparisons name.
BACKEND_PATHS = ("src", "scripts", "docs/contracts", "web/public/data")
_LAUNCHER_MUST_NOT_RUN = "throw 'must not execute'\n"


def _git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "-c",
            "init.defaultBranch=develop",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")


def _release(author: Path, tag: str) -> str:
    """Tag a release commit whose tree is develop's, off develop as ship.sh's merge is."""

    tree = _git(author, "rev-parse", "HEAD^{tree}")
    commit = _git(author, "commit-tree", tree, "-p", "HEAD", "-m", f"release {tag}")
    _git(author, "tag", "-a", tag, commit, "-m", tag)
    return commit


class World:
    """A bare origin, the owner's clean develop checkout and a fake GitHub CLI."""

    def __init__(self, tmp_path: Path, launcher: str = _LAUNCHER_MUST_NOT_RUN) -> None:
        self.root = tmp_path
        self.origin = tmp_path / "origin.git"
        self.author = tmp_path / "author"
        self.checkout = tmp_path / "checkout"
        _git(tmp_path, "init", "--quiet", "--bare", str(self.origin))
        _git(tmp_path, "init", "--quiet", str(self.author))
        _git(self.author, "remote", "add", "origin", str(self.origin))
        script = (ROOT / "scripts/release/restart_backend.ps1").read_text(encoding="ascii")
        _write(self.author, "scripts/release/restart_backend.ps1", script)
        _write(self.author, "scripts/run_backend_local.ps1", launcher)
        _write(self.author, "docs/contracts/advice.schema.json", "{}\n")
        _write(self.author, "docs/notes.md", "notes\n")
        _write(self.author, DATA, '{"gameweek": 6}\n')
        # As in the repository: the launcher's store is never part of the tree.
        _write(self.author, ".gitignore", "data/runtime/\n")
        _write(self.author, APP, "VERSION = 1\n")
        _git(self.author, "add", ".")
        _git(self.author, "commit", "--quiet", "-m", "first release")
        self.decision = _release(self.author, DECISION)
        _write(self.author, APP, "VERSION = 2\n")
        _git(self.author, "commit", "--quiet", "-am", "second release")
        self.fix = _release(self.author, FIX)
        _git(self.author, "push", "--quiet", "origin", "develop", "--tags")
        # Without tags: the release tags reach the checkout only through the script's fetch.
        _git(tmp_path, "clone", "--quiet", "--no-tags", str(self.origin), str(self.checkout))
        self.head = _git(self.checkout, "rev-parse", "HEAD")
        self.calls = tmp_path / "gh_calls.txt"
        self.state = tmp_path / "gh_state.json"
        self.gh = tmp_path / "gh.cmd"
        fake = tmp_path / "fake_gh.py"
        fake.write_text(_FAKE_GH, encoding="ascii")
        self.gh.write_text(
            f'@echo off\n"{sys.executable}" "{fake}" %*\nexit /b %ERRORLEVEL%\n',
            encoding="ascii",
            newline="\r\n",
        )
        # Listed oldest first on purpose: the script orders the runs itself. Run 400 is the
        # newest, but its production job failed, so it deployed nothing.
        self.github([_deploy(200, DECISION), _deploy(300, FIX), _deploy(400, LATER, "failure")])

    def github(self, runs: list[dict[str, object]], *, fail: bool = False) -> None:
        self.state.write_text(json.dumps({"runs": runs, "fail": fail}), encoding="ascii")

    def develop_changes(self, relative: str) -> None:
        """A commit lands on origin's develop after the owner's checkout was cloned."""

        _write(self.author, relative, "changed after the release\n")
        _git(self.author, "add", ".")
        _git(self.author, "commit", "--quiet", "-m", f"change {relative}")
        _git(self.author, "push", "--quiet", "origin", "develop")

    def dry_run(self, *arguments: str, gh: Path | None = None) -> subprocess.CompletedProcess[str]:
        assert POWERSHELL is not None
        result = subprocess.run(
            [
                POWERSHELL,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.checkout / "scripts/release/restart_backend.ps1"),
                "-AcceptedGeneratedAt",
                "2026-09-22T22:04:06Z",
                "-Python",
                sys.executable,
                "-GitHubCli",
                str(gh or self.gh),
                "-DryRun",
                *arguments,
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        # A dry run leaves the checkout where it was, clean.
        assert _git(self.checkout, "rev-parse", "HEAD") == self.head
        assert _git(self.checkout, "status", "--porcelain") == ""
        return result


def _job(name: str, conclusion: str = "success") -> dict[str, str]:
    return {"name": name, "conclusion": conclusion}


def _deploy(run: int, tag: str, conclusion: str = "success") -> dict[str, object]:
    """A dispatch of deploy-pages.yml as `gh run view --json jobs` describes it."""

    production = _job(f"production {tag}", conclusion)
    return {"id": run, "jobs": [_job("verify production source"), production]}


_FAKE_GH = """import json
import sys
from pathlib import Path

here = Path(__file__).parent
arguments = sys.argv[1:]
with (here / "gh_calls.txt").open("a", encoding="ascii") as log:
    log.write(" ".join(arguments) + "\\n")
state = json.loads((here / "gh_state.json").read_text(encoding="ascii"))
if state["fail"]:
    sys.stderr.write("HTTP 401: Bad credentials\\n")
    sys.exit(1)
if arguments[:2] == ["run", "list"]:
    print(json.dumps([{"databaseId": run["id"]} for run in state["runs"]]))
elif arguments[:2] == ["run", "view"]:
    run = next(run for run in state["runs"] if str(run["id"]) == arguments[2])
    print(json.dumps({"jobs": run["jobs"]}))
else:
    sys.exit(99)
"""

_STOPPED_AT_REGISTRY = "backend.pids.json"


def _said(stream: str, message: str) -> bool:
    """PowerShell wraps an error record at the console width, even inside a word."""

    return re.sub(r"\s+", "", message) in re.sub(r"\s+", "", stream)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


@pytest.mark.parametrize(
    "changed", [APP, "scripts/run_backend_local.ps1", "docs/contracts/advice.schema.json"]
)
def test_a_develop_past_the_release_is_refused_before_the_backend_is_read(
    world: World, changed: str
) -> None:
    """The owner's checkout still equals the release; the develop it would pull does not."""

    world.develop_changes(changed)
    result = world.dry_run()
    assert result.returncode != 0
    assert (
        f"Release {FIX} at {world.fix}, the newest successful production deploy, run 300."
        in result.stdout
    )
    assert f"Fetched origin/develop differs from release {FIX} in 1 file(s)" in result.stdout
    assert f"  {changed}" in result.stdout
    assert _said(result.stderr, "Wait for the next site release, or pass -Force")
    assert not _said(result.stderr, _STOPPED_AT_REGISTRY)
    calls = world.calls.read_text(encoding="ascii")
    assert (
        "run list -R MyManDev/football-squad-optimizer --workflow deploy-pages.yml "
        "--event workflow_dispatch --status success" in calls
    )
    assert "run view 400 " in calls and "run view 300 " in calls
    assert "run view 200 " not in calls
    # The release commit is reachable only from its tag, which the script fetched.
    assert _git(world.checkout, "rev-parse", f"{FIX}^{{commit}}") == world.fix
    assert _git(world.checkout, "tag", "--list") == FIX


@pytest.mark.parametrize("changed", ["docs/notes.md", "web/src/page.ts"])
def test_a_develop_that_changed_nothing_the_backend_runs_passes(world: World, changed: str) -> None:
    world.develop_changes(changed)
    result = world.dry_run()
    assert f"Fetched origin/develop matches release {FIX} in src" in result.stdout
    assert f"DryRun fetched origin/develop and tag {FIX}" in result.stdout
    # The next check reads the backend registry, which this checkout does not have.
    assert result.returncode != 0
    assert _said(result.stderr, _STOPPED_AT_REGISTRY)


def test_force_runs_code_no_release_carries_and_says_so(world: World) -> None:
    world.develop_changes(APP)
    result = world.dry_run("-Force")
    assert f"Fetched origin/develop differs from release {FIX} in 1 file(s)" in result.stdout
    assert "FORCED: the backend will run code that no site release carries." in result.stdout
    assert not _said(result.stderr, "Wait for the next site release")
    assert _said(result.stderr, _STOPPED_AT_REGISTRY)


def test_a_named_release_needs_no_github_cli(world: World) -> None:
    """develop holds the second release, so it differs from the first in the app."""

    result = world.dry_run("-ReleaseTag", DECISION, gh=world.root / "absent" / "gh.exe")
    assert f"Release {DECISION} at {world.decision}, named by -ReleaseTag." in result.stdout
    assert f"  {APP}" in result.stdout
    assert _said(result.stderr, "Wait for the next site release, or pass -Force")
    assert not world.calls.exists()


def test_a_named_release_that_is_the_one_develop_holds_passes(world: World) -> None:
    result = world.dry_run("-ReleaseTag", FIX, gh=world.root / "absent" / "gh.exe")
    assert f"Fetched origin/develop matches release {FIX}" in result.stdout
    assert _said(result.stderr, _STOPPED_AT_REGISTRY)


@pytest.mark.parametrize(
    ("tag", "refusal"),
    [
        ("site-2026-27-gw04-settled-2", "is not a site release tag"),
        ("site-2026-27-gw07-decision", "Could not fetch release tag site-2026-27-gw07-decision"),
        ("site-2026-27-gw05-fix1", "is not annotated"),
    ],
)
def test_a_tag_production_could_not_have_deployed_is_refused(
    world: World, tag: str, refusal: str
) -> None:
    lightweight = "site-2026-27-gw05-fix1"
    _git(world.author, "tag", lightweight, world.decision)
    _git(world.author, "push", "--quiet", "origin", f"refs/tags/{lightweight}")
    result = world.dry_run("-ReleaseTag", tag)
    assert result.returncode != 0
    assert _said(result.stderr, refusal)
    assert not _said(result.stderr, _STOPPED_AT_REGISTRY)


def test_a_local_tag_that_differs_from_origin_is_not_replaced(world: World) -> None:
    _git(world.checkout, "tag", "-a", FIX, world.head, "-m", "moved")
    result = world.dry_run()
    assert result.returncode != 0
    assert _said(result.stderr, f"Could not fetch release tag {FIX} from origin")
    assert _git(world.checkout, "rev-parse", f"{FIX}^{{commit}}") == world.head


def test_an_unreadable_deploy_history_asks_for_the_release_by_name(world: World) -> None:
    world.github([], fail=True)
    result = world.dry_run()
    assert result.returncode != 0
    assert _said(result.stderr, "Name the release with -ReleaseTag instead.")

    world.github([_deploy(500, LATER, "cancelled")])
    result = world.dry_run()
    assert result.returncode != 0
    assert _said(result.stderr, "No successful production deploy among the last 30 deploy runs")


# What the runbook relies on in the real launcher: its defaults, its registry in the store under
# -RepoRoot, its refusal to start over a recorded backend, and the `code` line naming the
# source and the commit of the checkout that holds it. It starts no process and opens no port.
_RECORDING_LAUNCHER = r"""param(
    [int]$Workers = 2,
    [string]$RepoRoot = "",
    [string]$SourceRoot = "",
    [string]$SiteDataRoot = "",
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not $SourceRoot) { $SourceRoot = Join-Path $RepoRoot "src" }
if (-not $SiteDataRoot) { $SiteDataRoot = Join-Path $RepoRoot "web\public\data" }
$run = Join-Path $RepoRoot "data\runtime\backend\run"
$registry = Join-Path $run "backend.pids.json"
$log = $env:SQUADOPT_TEST_LAUNCHER_LOG
if ($Stop) {
    if (-not (Test-Path -LiteralPath $registry)) {
        Write-Host "Nothing to stop: no pid file at $registry"
        exit 0
    }
    Remove-Item -LiteralPath $registry
    Add-Content -LiteralPath $log -Value '{"action":"stop"}' -Encoding ASCII
    exit 0
}
if (Test-Path -LiteralPath $registry) {
    Write-Host "Refusing to start: a recorded backend is still running. Use -Stop first."
    exit 1
}
foreach ($required in @($SourceRoot, $SiteDataRoot)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "Missing directory: $required"
    }
}
$commit = (& git -C (Split-Path -Parent $SourceRoot) rev-parse HEAD | Select-Object -First 1).Trim()
New-Item -ItemType Directory -Force -Path $run | Out-Null
$line = [ordered]@{
    action = "start"; source_root = $SourceRoot; site_data_root = $SiteDataRoot
    repository_commit = $commit; workers = $Workers
} | ConvertTo-Json -Compress
Set-Content -LiteralPath $registry -Value $line -Encoding ASCII
Add-Content -LiteralPath $log -Value $line -Encoding ASCII
Write-Host ("code      {0} at {1}" -f $SourceRoot, $commit)
exit 0
"""

_CODE_LINE = re.compile(r"^code\s+\S.* at (?P<commit>[0-9a-f]{40})\s*$", re.M)
_PLACEHOLDER = re.compile(r"<[a-z-]+>")
WAY_BACK = "Back to the main checkout after the next release"


def _runbook() -> dict[str, list[list[str]]]:
    """The PowerShell blocks of 'A stopped backend starts from the release', part by part.

    The comparison before the first `####` heading is "compare"; each part after it is named
    by its heading. A block is its lines, each one command as the owner types it.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index("### A stopped backend starts from the release\n")
    section = text[start : text.index("\n## ", start)]
    pieces = re.split(r"^#### (.+)\n", section, flags=re.M)
    names = ["compare", *pieces[1::2]]
    parts = [pieces[0], *pieces[2::2]]
    return {
        name: [
            block.strip().splitlines()
            for block in re.findall(r"^```powershell\n(.*?)^```", part, flags=re.M | re.S)
        ]
        for name, part in zip(names, parts, strict=True)
    }


def _same(recorded: object, expected: Path) -> bool:
    return Path(str(recorded)).resolve() == expected.resolve()


class Owner:
    """Types documented commands into PowerShell from the main checkout, one line at a time."""

    def __init__(self, world: World) -> None:
        self.world = world
        self.log = world.root / "launcher.log"
        self.environment = {**os.environ, "SQUADOPT_TEST_LAUNCHER_LOG": str(self.log)}
        self.commit = ""

    def follow(self, blocks: list[list[str]], values: dict[str, str]) -> list[tuple[str, str]]:
        """Run every line; each must succeed. Returns (command, stdout) in order."""

        assert blocks, "the runbook part has no PowerShell block"
        typed: list[tuple[str, str]] = []
        for line in (line for block in blocks for line in block):
            command = line
            # <commit> is the one the last `code` line printed, as the runbook says.
            known = {**values, "commit": self.commit} if self.commit else values
            for name, value in known.items():
                command = command.replace(f"<{name}>", value)
            assert not _PLACEHOLDER.findall(command), f"no value for a placeholder in {line!r}"
            step = self.world.root / "step.ps1"
            step.write_text(command + "\nexit $LASTEXITCODE\n", encoding="ascii")
            assert POWERSHELL is not None
            done = subprocess.run(
                [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(step)],
                cwd=self.world.checkout,
                env=self.environment,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            assert done.returncode == 0, f"{command}\n{done.stdout}\n{done.stderr}"
            code = _CODE_LINE.search(done.stdout)
            if code is not None:
                self.commit = code["commit"]
            typed.append((command, done.stdout))
        return typed

    def launches(self) -> list[dict[str, object]]:
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="ascii").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


def _diffs(typed: list[tuple[str, str]]) -> list[str]:
    """What each documented `git diff --stat` printed; the runbook reads nothing as a pass."""

    return [output.strip() for command, output in typed if command.startswith("git diff")]


def test_a_stopped_backend_starts_from_exactly_the_develop_the_runbook_compared(
    tmp_path: Path,
) -> None:
    """develop carries the release's code, then moves on while the owner is typing."""

    world = World(tmp_path, launcher=_RECORDING_LAUNCHER)
    runbook = _runbook()
    owner = Owner(world)
    values = {"tag": FIX, "n": "3"}
    # After the release only a document changed, so the owner's older checkout may start it.
    world.develop_changes("docs/notes.md")
    assert _diffs(owner.follow(runbook["compare"], values)) == [""]
    compared = _git(world.checkout, "rev-parse", "origin/develop")
    # Unreleased code lands on develop between the comparison and the start.
    world.develop_changes(APP)

    started = owner.follow(runbook["Starting from develop"], values)

    assert _diffs(started) == ["", ""]
    [launch] = owner.launches()
    assert _same(launch["source_root"], world.checkout / "src")
    assert _same(launch["site_data_root"], world.checkout / "web/public/data")
    # develop's commit, not the tag's: the tag sits on main's release merge.
    assert launch["repository_commit"] == compared != world.fix
    assert _git(world.checkout, "diff", "--stat", FIX, compared, "--", *BACKEND_PATHS) == ""


@pytest.mark.parametrize("moved", [APP, DATA])
def test_a_backend_started_from_a_release_worktree_comes_back_on_the_next_release(
    tmp_path: Path, moved: str
) -> None:
    """The way back must not start the main checkout's older develop."""

    world = World(tmp_path, launcher=_RECORDING_LAUNCHER)
    runbook = _runbook()
    owner = Owner(world)
    worktree = tmp_path / "release-fix1"
    values = {
        "tag": FIX,
        "n": "3",
        "release-worktree": str(worktree),
        "main-checkout": str(world.checkout),
    }
    # The backend is down and develop has moved past the live release in what it runs.
    world.develop_changes(moved)
    [listed] = _diffs(owner.follow(runbook["compare"], values))
    assert moved in listed
    owner.follow(runbook["Starting from a release worktree"], values)
    [from_worktree] = owner.launches()
    assert _same(from_worktree["source_root"], worktree / "src")
    assert _same(from_worktree["site_data_root"], worktree / "web/public/data")
    assert from_worktree["repository_commit"] == world.fix
    # Nothing has moved the main checkout since.
    assert _git(world.checkout, "rev-parse", "HEAD") == world.head

    # The next release carries develop as it now stands.
    released = _release(world.author, NEXT)
    _git(world.author, "push", "--quiet", "origin", "develop", "--tags")
    values["tag"] = NEXT

    back = owner.follow(runbook[WAY_BACK], values)

    assert _diffs(back) == ["", "", ""]
    worktree_start, stop, main_start = owner.launches()
    assert worktree_start == from_worktree
    assert stop == {"action": "stop"}
    assert _same(main_start["source_root"], world.checkout / "src")
    assert _same(main_start["site_data_root"], world.checkout / "web/public/data")
    running = str(main_start["repository_commit"])
    assert running == _git(world.author, "rev-parse", "develop") != world.head
    assert _git(world.checkout, "diff", "--stat", released, running, "--", *BACKEND_PATHS) == ""
    assert not worktree.exists()
    assert _git(world.checkout, "worktree", "list", "--porcelain").count("worktree ") == 1
