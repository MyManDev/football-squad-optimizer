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
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")
pytestmark = [
    pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1"),
    pytest.mark.skipif(shutil.which("git") is None, reason="requires Git"),
]

DECISION = "site-2026-27-gw06-decision"
FIX = "site-2026-27-gw06-fix1"
LATER = "site-2026-27-gw06-fix2"
APP = "src/squadopt/api/app.py"


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

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.origin = tmp_path / "origin.git"
        self.author = tmp_path / "author"
        self.checkout = tmp_path / "checkout"
        _git(tmp_path, "init", "--quiet", "--bare", str(self.origin))
        _git(tmp_path, "init", "--quiet", str(self.author))
        _git(self.author, "remote", "add", "origin", str(self.origin))
        script = (ROOT / "scripts/release/restart_backend.ps1").read_text(encoding="ascii")
        _write(self.author, "scripts/release/restart_backend.ps1", script)
        _write(self.author, "scripts/run_backend_local.ps1", "throw 'must not execute'\n")
        _write(self.author, "docs/contracts/advice.schema.json", "{}\n")
        _write(self.author, "docs/notes.md", "notes\n")
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
