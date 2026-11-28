"""Exercise the operator recipe without contacting GitHub or releasing anything."""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from scripts.release import verify_live

from squadopt.contracts.league_publication_identity import publication_identity

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which("sh") or "C:/Program Files/Git/bin/bash.exe"


@pytest.mark.parametrize("tag", ["site-2026-27-gw05-fix8", "bad-tag"])
def test_ship_dry_run_only_reads_repository_location(tmp_path: Path, tag: str) -> None:
    if not Path(SHELL).is_file():
        pytest.skip("A POSIX shell is required")
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "calls"
    # No real git, network, sleep or file-changing command can run through these stubs.
    for name in ("git", "gh", "python", "python3", "sleep", "rm", "mkdir"):
        body = '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n'
        if name == "git":
            body += '[ "$*" = "rev-parse --show-toplevel" ] || exit 99\npwd\n'
        else:
            body += "exit 99\n"
        target = commands / name
        target.write_text(body, encoding="utf-8", newline="\n")
        target.chmod(0o755)
    env = {
        **os.environ,
        "COMMANDS": commands.as_posix(),
        "CALLS": calls.as_posix(),
    }
    result = subprocess.run(
        [
            SHELL,
            "-c",
            'PATH="$(cd "$COMMANDS" && pwd):$PATH"; export PATH; exec /bin/sh "$@"',
            "dry-run-test",
            str(ROOT / "scripts/release/ship.sh"),
            "--dry-run",
            "618",
            tag,
            "release/gw05-fix8",
            "2026-09-18T17:00:00Z",
            "Publish the accepted tree.",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == (0 if tag.startswith("site-") else 1), result.stderr
    assert calls.read_text().splitlines()[0].endswith("git rev-parse --show-toplevel")
    assert len(calls.read_text().splitlines()) == 1
    assert {p.name for p in tmp_path.iterdir()} == {"commands", "calls"}
    if result.returncode == 0:
        lines = result.stdout.splitlines()
        assert len(lines) == 16
        for required in (
            "two parents",
            "unexpired site artifact",
            "deploy-pages.yml",
            "live smoke checks",
            "full page tour",
            "60 minutes",
            "45 minutes",
            "40 minutes",
        ):
            assert required in result.stdout
        assert tag in result.stdout
        assert "2026-09-18T17:00:00Z" in result.stdout


def test_clean_body_preserves_content_and_removes_attribution(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    body.write_text(
        "Keep this \u2014 result.\nGenerated with a tool\nCo-authored-by: example\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/release/clean_body.py"), str(body)], check=True
    )
    assert body.read_text(encoding="utf-8") == "Keep this, result.\n"


@pytest.mark.parametrize("content", ["", "  \n", "Generated with a tool\n"])
def test_clean_body_refuses_empty_result(tmp_path: Path, content: str) -> None:
    body = tmp_path / "body.md"
    body.write_text(content, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/release/clean_body.py"), str(body)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "NOT merging" in result.stderr


def test_clean_body_keeps_repository_paths(tmp_path: Path) -> None:
    body = tmp_path / "body.md"
    content = "Keep .codex-tmp and codex/release-recipe.\nKeep .claude/worktrees.\n"
    body.write_text(content + "Codex wrote this.\nClaude wrote this.\n", encoding="utf-8")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/release/clean_body.py"), str(body)],
        check=True,
    )
    assert body.read_text(encoding="utf-8") == content


def test_a_settled_tag_refuses_to_ship_without_the_gameweek_it_settles() -> None:
    """The verifier can only assert a week the operator names, so the tag demands it.

    Run from the repository, because a dry run reads its own location; it prints and exits
    before touching anything, which the stubbed test above is what proves.
    """

    if not Path(SHELL).is_file():
        pytest.skip("A POSIX shell is required")
    common = [
        SHELL,
        str(ROOT / "scripts/release/ship.sh"),
        "--dry-run",
        "618",
        "site-2026-27-gw05-settled",
        "release/gw05-settled",
        "2026-09-18T17:00:00Z",
        "Publish the accepted tree.",
    ]
    without = subprocess.run(common, cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert without.returncode == 2
    assert "pass it as the sixth argument" in without.stderr

    with_week = subprocess.run([*common, "5"], cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert with_week.returncode == 0, with_week.stderr
    assert "settling gameweek 5" in with_week.stdout

    not_a_number = subprocess.run(
        [*common, "five"], cwd=ROOT, capture_output=True, text=True, timeout=15
    )
    assert not_a_number.returncode == 2
    assert "must be a number" in not_a_number.stderr


#: The checks of a site from before the directory, which publishes the legacy tree alone.
_ROUTES, _DOCUMENTS, (_ABSENT,) = verify_live.smoke_checks([verify_live.LEGACY])
#: The shell as the build serves it: the entry chunk by its hashed name.
_SHELL = b'<!doctype html><script type="module" src="/assets/index-AbCd1234.js"></script>'
_SHELL += b'<div id="root"></div>'


def _index(season: str | None = "2026-27") -> bytes:
    latest = {} if season is None else {"season": season, "gameweek": 5}
    return json.dumps({"payload": {"latest": latest, "seasons": [season]}}).encode()


def _live(
    settled: int,
    scored: int | None,
    next_gameweek: int,
    generated: str = "2026-09-18T18:00:00Z",
    season: str = "2026-27",
) -> Callable[[str], tuple[int, bytes]]:
    """A live site that has settled ``settled`` and says so in all three documents.

    The site is one from before the league directory: it answers 404 for the directory and
    publishes the legacy tree alone.
    """

    def fetch(path: str) -> tuple[int, bytes]:
        if path in (verify_live.DIRECTORY, _ABSENT, verify_live.ABSENT_ASSET):
            return 404, b""
        if path in _ROUTES:
            return 200, _SHELL
        if path == "/data/index.json":
            return 200, _index(season)
        if path == "/data/league/scoreboard.json":
            weeks = [
                {"gameweek": week, "finished": True, "data_checked": True}
                for week in range(1, settled + 1)
            ]
            return 200, json.dumps({"payload": {"gameweeks": weeks}}).encode()
        if path == f"/data/{season}/status.json":
            return 200, json.dumps({"payload": {"next_gameweek": next_gameweek}}).encode()
        if path.endswith("/status.json"):
            return 404, b""
        return 200, json.dumps(
            {
                "generated_at_utc": generated,
                "payload": {"scored_gameweek": scored, "members": []},
            }
        ).encode()

    return fetch


@pytest.mark.parametrize("absent_status", [404, 200])
def test_live_checks_retain_the_absent_document_rule(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], absent_status: int
) -> None:
    def fetch(path: str) -> tuple[int, bytes]:
        if path in (verify_live.DIRECTORY, verify_live.ABSENT_ASSET):
            return 404, b""
        if path == _ABSENT:
            return absent_status, b""
        if path in _ROUTES:
            return 200, _SHELL
        if path == "/data/index.json":
            return 200, _index()
        return 200, json.dumps({"generated_at_utc": "2026-09-18T18:00:00Z", "payload": {}}).encode()

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z") == (0 if absent_status == 404 else 1)
    output = capsys.readouterr().out
    assert output.count(" html ") == len(_ROUTES)
    assert output.count(" json ") == len(_DOCUMENTS)
    assert "must be 404" in output


def _directory(*leagues: tuple[int, str], stamp: str = "2026-09-18T18:00:00Z") -> bytes:
    rows = [
        {
            "league_id": league_id,
            "league_name": f"League {league_id}",
            "season": "2026-27",
            "gameweek": 5,
            "path": path,
        }
        for league_id, path in leagues
    ]
    return json.dumps(
        {
            "contract_version": "league_directory_v1",
            "generated_at_utc": stamp,
            "payload": {"leagues": rows},
        }
    ).encode()


def _directory_site(
    *,
    directory_stamp: str = "2026-09-18T18:00:00Z",
    tree_stamps: dict[str, str] | None = None,
    captures: dict[str, str] | None = None,
) -> Callable[[str], tuple[int, bytes]]:
    """A two-league directory site: each tree's members stamp and its member's capture."""

    stamps = tree_stamps or {}
    held = captures or {}
    served = _live(5, 5, 6)

    def fetch(path: str) -> tuple[int, bytes]:
        if path == verify_live.DIRECTORY:
            return 200, _directory(
                (352490, "leagues/352490"), (7, "leagues/7"), stamp=directory_stamp
            )
        if path.endswith("/publication-identity.json"):
            return 404, b""
        if path.startswith("/league/") and path.endswith("/members/0"):
            return 200, b'<div id="root"></div>'
        if path.endswith("/entries/0.json"):
            return 404, b""
        if path.endswith("/scoreboard.json"):
            return served("/data/league/scoreboard.json")
        for tree in ("leagues/352490", "leagues/7"):
            if path == f"/data/{tree}/members.json":
                return 200, json.dumps(
                    {
                        "generated_at_utc": stamps.get(tree, "2026-09-18T17:00:00Z"),
                        "payload": {
                            "scored_gameweek": 5,
                            "members": [{"member_kind": "human", "entry_id": 101}],
                        },
                    }
                ).encode()
            if path == f"/data/{tree}/entries/101.json":
                capture = held.get(tree, "fpl-live-one")
                if capture is None:
                    return 404, b""
                return 200, json.dumps({"payload": {"source_snapshot_id": capture}}).encode()
        return served(path)

    return fetch


@pytest.mark.parametrize(
    "changed",
    [
        None,
        "history/101.json",
        "entries/101.json",
        "expected",
        "missing-expected",
        "missing-served",
    ],
)
def test_history_refresh_proves_its_stamp_with_the_complete_identity(
    monkeypatch: pytest.MonkeyPatch, changed: str | None, tmp_path: Path
) -> None:
    accepted = "2026-09-18T18:00:00Z"
    old = "2026-09-18T17:00:00Z"
    documents = {
        "members.json": {
            "generated_at_utc": old,
            "payload": {
                "season": "2026-27",
                "gameweek": 5,
                "league_id": 7,
                "members": [{"entry_id": 101, "member_kind": "human"}],
            },
        },
        "entries/101.json": {
            "generated_at_utc": old,
            "payload": {
                "season": "2026-27",
                "gameweek": 5,
                "league_id": 7,
                "source_snapshot_id": "fpl-live-one",
                "entry": {"entry_id": 101},
            },
        },
        "history/101.json": {
            "generated_at_utc": old,
            "payload": {"entry_id": 101, "weeks": []},
        },
    }
    identity = publication_identity(documents)
    expected = {**identity}
    if changed == "expected":
        expected["source_snapshot_id"] = "different-release"
    expected_file = tmp_path / "leagues/7/publication-identity.json"
    expected_file.parent.mkdir(parents=True)
    if changed != "missing-expected":
        expected_file.write_text(json.dumps(expected), encoding="utf-8")
    if changed in documents:
        documents[changed]["generated_at_utc"] = accepted
    served = _directory_site()

    def fetch(path: str) -> tuple[int, bytes]:
        if path == verify_live.DIRECTORY:
            return 200, _directory((7, "leagues/7"), stamp=accepted)
        prefix = "/data/leagues/7/"
        if path.startswith(prefix):
            name = path.removeprefix(prefix)
            if name == "publication-identity.json":
                if changed == "missing-served":
                    return 404, b""
                return 200, json.dumps(identity).encode()
            if name in documents:
                return 200, json.dumps(documents[name]).encode()
        return served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main(accepted) == 1
    assert verify_live.main(accepted, expected_data_root=tmp_path) == (0 if changed is None else 1)


@pytest.mark.parametrize(
    ("site", "said"),
    [
        pytest.param(
            {"tree_stamps": {"leagues/7": "2026-09-18T18:00:00Z"}},
            None,
            id="the-last-league-carries-the-publication-stamp",
        ),
        pytest.param(
            {},
            "BAD no tree carries the publication stamp 2026-09-18T18:00:00Z",
            id="every-tree-older-than-the-publication",
        ),
        pytest.param(
            {
                "tree_stamps": {"leagues/7": "2026-09-18T18:00:00Z"},
                "captures": {"leagues/352490": None},
            },
            "BAD no human member's entry document of leagues/352490 can be read",
            id="no-entry-readable",
        ),
        pytest.param(
            {"directory_stamp": "2026-09-18T17:30:00Z"},
            "BAD /data/leagues.json generated_at_utc 2026-09-18T17:30:00Z",
            id="directory-of-another-publication",
        ),
        pytest.param(
            {"tree_stamps": {"leagues/7": "2026-09-18T19:00:00Z"}},
            "BAD generated_at_utc 2026-09-18T19:00:00Z  (must not be newer than the publication",
            id="tree-newer-than-the-directory",
        ),
        pytest.param(
            {"captures": {"leagues/7": "fpl-live-two"}},
            "BAD the trees name more than one capture",
            id="two-captures",
        ),
    ],
)
def test_a_directory_site_is_one_publication_of_one_capture(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    site: dict[str, Any],
    said: str | None,
) -> None:
    """Each league is stamped after its own solves, so the trees' stamps differ; the
    directory is the publication and carries the accepted stamp, no tree is newer, and
    every tree names the one capture."""

    monkeypatch.setattr(verify_live, "fetch", _directory_site(**site))
    code = verify_live.main("2026-09-18T18:00:00Z", 5)
    output = capsys.readouterr().out
    if said is None:
        assert code == 0, output
        assert "ok  /data/leagues.json generated_at_utc 2026-09-18T18:00:00Z" in output
    else:
        assert code == 1
        assert said in output


def _run_ship_recipe(
    tmp_path: Path, settled: str = "", preflight_exit: int = 0
) -> tuple[subprocess.CompletedProcess[str], str, list[list[str]], Path]:
    """Run ship with inert git/gh/deploy commands, never a real release."""
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "calls"
    branch = "release/gw06-fix1"
    worktree = tmp_path / ".codex-tmp/worktrees" / branch.replace("/", "-")
    (worktree / "web/public/data").mkdir(parents=True)
    git = """case "$*" in
  "rev-parse --show-toplevel") echo "$SHIP_ROOT";;
  "rev-parse origin/develop") echo devsha;;
  "rev-list --count origin/main..origin/develop") echo 3;;
  "rev-list --parents -n1 HEAD") echo 'merge parent1 parent2';;
  "ls-remote --tags origin"|"diff origin/develop HEAD") :;;
  "fetch "*|"worktree "*|"branch -D "*|"merge "*|"read-tree "*|"commit "*|"push "*) :;;
  *) exit 99;;
esac
"""
    gh = """case "$*" in
  "pr view 618 --json state --jq .state") echo MERGED;;
  "pr create "*) echo https://github.invalid/owner/repo/pull/701;;
  "pr view 701 --json mergeStateStatus --jq .mergeStateStatus") echo CLEAN;;
  "pr merge 701 --merge") :;;
  *) exit 99;;
esac
"""
    deploy = """printf 'SHBEGIN\\n' >> "$CALLS"
for argument in "$@"; do printf 'ARG:%s\\n' "$argument" >> "$CALLS"; done
printf 'SHEND\\n' >> "$CALLS"
[ "${2:-}" != --preflight ] || exit "$PREFLIGHT_EXIT"
exit 0
"""
    for name, body in {
        "git": git,
        "gh": gh,
        "sh": deploy,
        "sleep": ":\n",
        "date": '[ "$*" = "-u +%H:%M:%S" ] || exit 99\nprintf "01:02:03\\n"\n',
    }.items():
        target = commands / name
        target.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n' + body,
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o755)
    arguments = ["618", _DEPLOY_TAG, branch, _DEPLOY_STAMP, "Publish the accepted tree."]
    if settled:
        arguments.append(settled)
    result = subprocess.run(
        [
            SHELL,
            "-c",
            'PATH="$(cd "$COMMANDS" && pwd):$PATH"; export PATH; exec /bin/sh "$@"',
            "ship-test",
            str(ROOT / "scripts/release/ship.sh"),
            *arguments,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "COMMANDS": commands.as_posix(),
            "CALLS": calls.as_posix(),
            "SHIP_ROOT": tmp_path.as_posix(),
            "PREFLIGHT_EXIT": str(preflight_exit),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    log = calls.read_text()
    invocations = [
        [line.removeprefix("ARG:") for line in block.splitlines()]
        for block in re.findall(r"SHBEGIN\n(.*?)SHEND", log, re.DOTALL)
    ]
    return result, log, invocations, worktree


def test_ship_preflight_precedes_the_site_pr_wait(tmp_path: Path) -> None:
    result, log, calls, _ = _run_ship_recipe(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls[0][1:] == ["--preflight"]
    assert log.index("--preflight") < log.index("gh pr view 618")


def test_ship_stops_before_the_site_pr_wait_when_preflight_refuses(tmp_path: Path) -> None:
    result, log, _, _ = _run_ship_recipe(tmp_path, preflight_exit=7)
    assert result.returncode == 1
    assert "gh pr view" not in log
    assert "git fetch" not in log


@pytest.mark.parametrize("settled", ["", "6"])
def test_ship_passes_stamp_empty_or_settled_week_and_worktree_data_positionally(
    tmp_path: Path, settled: str
) -> None:
    result, _, calls, worktree = _run_ship_recipe(tmp_path, settled)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls) == 2
    assert calls[1][1:] == [
        _DEPLOY_TAG,
        _DEPLOY_STAMP,
        settled,
        (worktree / "web/public/data").as_posix(),
    ]


def test_ship_logs_in_utc(tmp_path: Path) -> None:
    result, log, _, _ = _run_ship_recipe(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    dates = [line for line in log.splitlines() if "/date " in line]
    assert dates and all(line.endswith("date -u +%H:%M:%S") for line in dates)
    assert all(line.startswith("01:02:03 ") for line in result.stdout.splitlines())


@pytest.mark.parametrize("enabled", [None, "0", "1"])
def test_host_browser_provisioning_is_explicitly_optional_and_uses_the_service_cache(
    tmp_path: Path, enabled: str | None
) -> None:
    """Source only the optional functions; every host-changing command is a recorder."""
    bash = "C:/Program Files/Git/bin/bash.exe" if sys.platform == "win32" else shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("A POSIX bash is required")
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("")
    checkout = tmp_path / "checkout"
    (checkout / "web").mkdir(parents=True)
    for name in ("apt-get", "curl", "gpg", "chmod", "install", "npx", "dpkg", "node"):
        target = commands / name
        answer = {"dpkg": "printf 'amd64\\n'", "node": "printf '22\\n'"}.get(name, ":")
        target.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n' + answer + "\n",
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o755)
    environment = {**os.environ, "COMMANDS": commands.as_posix(), "CALLS": calls.as_posix()}
    environment.pop("SQUADOPT_LIVE_BROWSER", None)
    if enabled is not None:
        environment["SQUADOPT_LIVE_BROWSER"] = enabled
    result = subprocess.run(
        [
            bash,
            "-c",
            'PATH="$(cd "$COMMANDS" && pwd):$PATH"; export PATH; source "$1"; '
            'write_if_changed() { cat >> "$CALLS"; return 0; }; '
            'as_user() { printf "as_user %s\\n" "$*" >> "$CALLS"; }; '
            'browser_node "$2/keyrings" "$2/nodesource.list"; '
            'browser_runtime "$2/checkout" "$2/service-home"',
            "provision-test",
            str(ROOT / "deploy/weekly-schedule/provision.sh"),
            tmp_path.as_posix(),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log = calls.read_text()
    if enabled != "1":
        assert log == "" and result.stdout == ""
        return
    assert "https://deb.nodesource.com/node_22.x nodistro main" in log
    assert "apt-get install -y -q nodejs" in log
    assert "npm ci" in log
    assert "npx --no-install playwright install --with-deps chromium" in log
    assert "as_user env HOME=" in log
    assert "PLAYWRIGHT_BROWSERS_PATH=" in log
    assert "/service-home/.cache/ms-playwright" in log
    assert log.index("npm ci") < log.index("playwright install --with-deps chromium")
    assert log.index("playwright install --with-deps chromium") < log.index("chromium.launch")


def test_a_site_with_a_directory_is_checked_tree_by_tree(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each listed league adds its member page by its address, its members document and
    the entry 0 document it must refuse; the legacy paths are not asked for."""

    served = _live(5, 5, 6)
    asked: list[str] = []

    def fetch(path: str) -> tuple[int, bytes]:
        asked.append(path)
        if path == verify_live.DIRECTORY:
            return 200, _directory((352490, "leagues/352490"), (7, "leagues/7"))
        if path.startswith("/league/") and path.endswith("/members/0"):
            return 200, _SHELL
        if path.endswith("/entries/0.json"):
            return 404, b""
        if path.endswith("/scoreboard.json"):
            return served("/data/league/scoreboard.json")
        return served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 0
    output = capsys.readouterr().out
    assert "ok  200 html   /league/352490/members/0" in output
    assert "ok  200 html   /league/7/members/0" in output
    assert "ok  200 json   /data/leagues/352490/members.json" in output
    assert "ok  200 json   /data/leagues/7/members.json" in output
    assert "ok  404 absent /data/leagues/352490/entries/0.json" in output
    assert "ok  404 absent /data/leagues/7/entries/0.json" in output
    # The address from before the number is served on every site; the legacy tree is not.
    assert "/league/members/0" in asked
    assert "/data/league/members.json" not in asked
    assert "ALL GOOD" in output


@pytest.mark.parametrize(
    ("status", "body", "reported"),
    [
        pytest.param(0, b"", "BAD 0 /data/leagues.json is not a league directory", id="no-answer"),
        pytest.param(500, b"", "BAD 500 /data/leagues.json is not a league directory", id="server"),
        pytest.param(
            200, b"[]", "BAD 200 /data/leagues.json is not a league directory", id="shape"
        ),
        pytest.param(200, _directory(), "BAD /data/leagues.json lists no league", id="empty"),
    ],
)
def test_a_directory_that_cannot_be_read_is_a_counted_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    status: int,
    body: bytes,
    reported: str,
) -> None:
    """The legacy tree is checked in its place, so the run still reports the rest."""

    served = _live(5, 5, 6)

    def fetch(path: str) -> tuple[int, bytes]:
        return (status, body) if path == verify_live.DIRECTORY else served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    output = capsys.readouterr().out
    assert reported in output
    assert "ok  200 json   /data/league/members.json" in output
    assert output.rstrip().endswith("\n1 FAILURE(S)")


def test_the_verifier_checks_the_same_routes_the_deployment_smoke_does() -> None:
    """The two lists drifted once: `/fixtures` was added to one and not the other.

    The static checks are compared in order; the checks a tree adds are compared by
    reading the smoke's templates with one directory line and one legacy tree.
    """

    source = (ROOT / "web/scripts/smoke-deployment.mjs").read_text(encoding="utf-8")
    prefix = re.search(r'ABSENT_ASSET_PREFIX = "([^"]+)"', source)
    assert prefix is not None and prefix.group(1) == verify_live.ABSENT_ASSET_PREFIX
    assert verify_live.ABSENT_ASSET.startswith(verify_live.ABSENT_ASSET_PREFIX)
    block = source.split("export const SMOKE_CHECKS = [", 1)[1].split("\n];", 1)[0]
    # The absent asset is named by its constant; read it as the path it stands for.
    block = block.replace("path: ABSENT_ASSET", f'path: "{verify_live.ABSENT_ASSET}"')
    paths = re.findall(r'path:\s*"([^"]+)"', block)
    kinds = re.findall(r'kind:\s*"([^"]+)"', block)
    assert len(paths) == len(kinds), block
    named = dict(zip(paths, kinds, strict=True))
    assert [path for path, kind in named.items() if kind == "html"] == verify_live.ROUTES
    assert [path for path, kind in named.items() if kind == "json"] == verify_live.DOCUMENTS
    assert [path for path, kind in named.items() if kind == "absent"] == [verify_live.ABSENT_ASSET]
    directory = re.search(r'DIRECTORY = "([^"]+)"', source)
    legacy = re.search(r'LEGACY_TREE = "([^"]+)"', source)
    assert directory is not None and directory.group(1) == verify_live.DIRECTORY
    assert legacy is not None and legacy.group(1) == verify_live.LEGACY_TREE

    tree_block = source.split("export function treeChecks(", 1)[1].split("\n}\n", 1)[0]
    templates = re.findall(r"path: `([^`]+)`", tree_block)
    tree_kinds = re.findall(r'kind:\s*"([^"]+)"', tree_block)
    assert len(templates) == len(tree_kinds), tree_block
    for league_id, tree in ((7, "leagues/7"), (None, "league")):
        rendered = [
            (template.replace("${leagueId}", str(league_id)).replace("${path}", tree), kind)
            for template, kind in zip(templates, tree_kinds, strict=True)
            if league_id is not None or "${leagueId}" not in template
        ]
        routes, documents, (absent,) = verify_live.smoke_checks([(league_id, tree)])
        assert [p for p, k in rendered if k == "html"] == routes[len(verify_live.ROUTES) :]
        expected_documents = documents[len(verify_live.DOCUMENTS) :]
        assert [p for p, k in rendered if k == "json"] == expected_documents
        assert [p for p, k in rendered if k == "absent"] == [absent]


def test_a_week_that_did_not_settle_fails_instead_of_being_printed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --settled the verifier printed the settled weeks and returned ALL GOOD."""

    monkeypatch.setattr(verify_live, "fetch", _live(settled=4, scored=4, next_gameweek=5))
    assert verify_live.main("2026-09-18T18:00:00Z") == 0
    assert verify_live.main("2026-09-18T18:00:00Z", 4) == 0
    # One exit code, three named failures: the count is in the output, not the return.
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    output = capsys.readouterr().out
    assert "BAD scoreboard settles gameweek 5" in output
    assert "BAD members.json scored_gameweek is 5" in output
    assert "BAD status moved past gameweek 5" in output


def test_each_of_the_three_settled_claims_fails_on_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify_live, "fetch", _live(settled=5, scored=4, next_gameweek=6))
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    monkeypatch.setattr(verify_live, "fetch", _live(settled=5, scored=5, next_gameweek=5))
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    monkeypatch.setattr(verify_live, "fetch", _live(settled=4, scored=5, next_gameweek=6))
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    capsys.readouterr()


@pytest.mark.parametrize(
    ("served", "accepted", "expected"),
    [
        pytest.param("2026-09-22T12:00:00Z", "2026-09-22T12:00:00Z", 0, id="same-tag-redispatch"),
        pytest.param("2026-09-18T12:26:35Z", "2026-09-22T12:00:00Z", 1, id="dashboard-rollback"),
        pytest.param("2026-09-22T13:00:00Z", "2026-09-22T13:00:00Z", 0, id="fix-own-candidate"),
        pytest.param("2026-09-22T13:00:00Z", "2026-09-22T12:00:00Z", 1, id="unaccepted-newer-tree"),
    ],
)
def test_live_stamp_must_match_the_accepted_candidate(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: str,
    accepted: str,
    expected: int,
) -> None:
    # Entirely synthetic HTTP responses: no real tag, release or live-site request.
    monkeypatch.setattr(verify_live, "fetch", _live(5, 5, 6, generated=served))
    assert verify_live.main(accepted, 5) == expected
    output = capsys.readouterr().out
    assert f"generated_at_utc {served}  (must equal accepted {accepted})" in output
    assert ("ALL GOOD" in output) == (expected == 0)


def test_the_accepted_stamp_argument_is_required() -> None:
    """The operator must name the accepted publication even when re-dispatching its tag."""

    with pytest.raises(SystemExit):
        verify_live._arguments([])
    assert verify_live._arguments(["2026-09-18T17:00:00Z"]).accepted_generated_at == (
        "2026-09-18T17:00:00Z"
    )
    assert verify_live._arguments(["2026-09-18T17:00:00Z"]).settled is None
    assert verify_live._arguments(["2026-09-18T17:00:00Z", "--settled", "5"]).settled == 5


def test_the_status_document_is_read_from_the_season_the_index_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path was written as `/data/2026-27/status.json`, which next season would 404."""

    served = _live(5, 5, 6, season="2027-28")
    asked: list[str] = []

    def fetch(path: str) -> tuple[int, bytes]:
        asked.append(path)
        return served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 0
    assert "/data/2027-28/status.json" in asked
    assert "/data/2026-27/status.json" not in asked
    assert "status season=2027-28 next_gameweek=6" in capsys.readouterr().out


@pytest.mark.parametrize("season", [None, "../league"])
def test_an_index_that_names_no_season_fails_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], season: str | None
) -> None:
    served = _live(5, 5, 6)

    def fetch(path: str) -> tuple[int, bytes]:
        return (200, _index(season)) if path == "/data/index.json" else served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z") == 1
    output = capsys.readouterr().out
    assert "BAD index.json names no latest season" in output
    assert "ALL GOOD" not in output


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(urllib.error.URLError("connection refused"), id="refused-or-dns"),
        pytest.param(TimeoutError("timed out"), id="timeout"),
        pytest.param(ConnectionResetError(10054, "reset by peer"), id="reset"),
        pytest.param(http.client.RemoteDisconnected("closed"), id="remote-disconnected"),
        pytest.param(http.client.IncompleteRead(b"{"), id="cut-short"),
    ],
)
def test_a_request_with_no_answer_is_a_failed_check_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    """Only HTTPError was caught, so a dropped connection ended the run in a traceback."""

    def urlopen(*_args: object, **_kwargs: object) -> object:
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert verify_live.fetch("/league") == (0, b"")
    assert "network error on /league" in capsys.readouterr().out
    assert verify_live.main("2026-09-18T18:00:00Z", 5) == 1
    output = capsys.readouterr().out
    assert "BAD 0 html   /" in output
    assert "BAD 0 could not read /data/league/members.json" in output
    assert "FAILURE(S)" in output


@pytest.mark.parametrize(
    "unreadable",
    [
        "/data/league/members.json",
        "/data/league/scoreboard.json",
        "/data/index.json",
        "/data/2026-27/status.json",
    ],
)
def test_one_unreadable_content_document_is_a_counted_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], unreadable: str
) -> None:
    """Each of these was `json.loads` on whatever came back, so a failed read raised."""

    served = _live(5, 5, 6)

    def fetch(path: str) -> tuple[int, bytes]:
        return (0, b"") if path == unreadable else served(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z") == 1
    output = capsys.readouterr().out
    assert f"BAD 0 could not read {unreadable}" in output
    assert "FAILURE(S)" in output


_STAMP = "2026-09-18T18:00:00Z"
_MEMBERS = "/data/league/members.json"
_SCOREBOARD = "/data/league/scoreboard.json"
_INDEX = "/data/index.json"
_STATUS = "/data/2026-27/status.json"


def _members(payload: object) -> bytes:
    return json.dumps({"generated_at_utc": _STAMP, "payload": payload}).encode()


@pytest.mark.parametrize(
    ("path", "body", "reported", "failures"),
    [
        pytest.param(
            _MEMBERS,
            _members(None),
            f"BAD could not read the payload of {_MEMBERS}",
            1,
            id="members-payload-null",
        ),
        pytest.param(
            _MEMBERS,
            _members([]),
            f"BAD could not read the payload of {_MEMBERS}",
            1,
            id="members-payload-list",
        ),
        pytest.param(
            _MEMBERS,
            _members({"members": [None]}),
            f"BAD members of {_MEMBERS} is not a list of objects",
            1,
            id="members-entry-null",
        ),
        pytest.param(
            _MEMBERS,
            _members({"members": "ab"}),
            f"BAD members of {_MEMBERS} is not a list of objects",
            1,
            id="members-not-a-list",
        ),
        # The smoke check parses this and passes; the content read counts it, and the stamp
        # it does not carry is a second failure.
        pytest.param(_MEMBERS, b"[]", f"BAD 200 could not read {_MEMBERS}", 2, id="top-level-list"),
        # Deeper than the parser recurses: the smoke check, the content read and the missing
        # stamp each fail.
        pytest.param(
            _MEMBERS, b"[" * 100_000, f"BAD 200 could not read {_MEMBERS}", 3, id="nested-too-deep"
        ),
        pytest.param(
            _SCOREBOARD,
            b'{"payload": null}',
            f"BAD could not read the payload of {_SCOREBOARD}",
            1,
            id="scoreboard-payload-null",
        ),
        pytest.param(
            _SCOREBOARD,
            b'{"payload": {"gameweeks": [null]}}',
            f"BAD gameweeks of {_SCOREBOARD} is not a list of objects",
            1,
            id="scoreboard-entry-null",
        ),
        pytest.param(
            _SCOREBOARD,
            b'{"payload": {"gameweeks": {"5": {}}}}',
            f"BAD gameweeks of {_SCOREBOARD} is not a list of objects",
            1,
            id="scoreboard-not-a-list",
        ),
        pytest.param(
            _INDEX,
            b'{"payload": null}',
            f"BAD could not read the payload of {_INDEX}",
            1,
            id="index-payload-null",
        ),
        pytest.param(
            _INDEX,
            b'{"payload": {"latest": "2026-27"}}',
            "BAD index.json names no latest season (latest='2026-27')",
            1,
            id="index-latest-not-an-object",
        ),
        pytest.param(
            _STATUS,
            b'{"payload": null}',
            f"BAD could not read the payload of {_STATUS}",
            1,
            id="status-payload-null",
        ),
    ],
)
def test_a_document_of_the_wrong_shape_inside_is_a_counted_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    path: str,
    body: bytes,
    reported: str,
    failures: int,
) -> None:
    """Only the top level was type-checked, so a null payload, a null entry or a latest entry
    that is not an object ended the run in a traceback instead of its failure count."""

    served = _live(5, 5, 6)

    def fetch(asked: str) -> tuple[int, bytes]:
        return (200, body) if asked == path else served(asked)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main(_STAMP) == 1
    output = capsys.readouterr().out
    assert reported in output
    assert output.rstrip().endswith(f"\n{failures} FAILURE(S)")


def test_a_movement_that_is_not_text_is_printed_not_raised(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The movement value was a dictionary key as served, so a list there raised TypeError."""

    served = _live(5, 5, 6)
    body = _members(
        {"scored_gameweek": 5, "members": [{"movement": ["up"]}, {"movement": "up"}, {}]}
    )

    def fetch(asked: str) -> tuple[int, bytes]:
        return (200, body) if asked == _MEMBERS else served(asked)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main(_STAMP, 5) == 0
    output = capsys.readouterr().out
    assert "movement={\"['up']\": 1, 'up': 1, 'None': 1}" in output
    assert "members=3" in output


_DEPLOY_TAG = "site-2026-27-gw06-fix1"
_DEPLOY_STAMP = "2026-09-18T17:00:00Z"

#: git answers as a release-ready main would; ls-remote lists $REMOTE_TAGS.
_DEPLOY_GIT = """case "$*" in
  "rev-parse --show-toplevel") pwd;;
  "fetch -q origin") :;;
  "rev-parse origin/main") echo mainsha;;
  "rev-parse origin/develop") echo devsha;;
  "rev-list --parents -n1 origin/main") echo "mainsha ${MAIN_PARENTS-parent1 parent2}";;
  "rev-parse origin/main^{tree}"|"rev-parse origin/develop^{tree}") echo treesha;;
  "ls-remote --tags origin")
    for tag in $REMOTE_TAGS; do printf 'sha\\trefs/tags/%s\\n' "$tag"; done;;
  "tag -a "*|"push -q origin "*) :;;
  *) exit 99;;
esac
"""

#: GitHub as the deploy script sees it. Run 100 is the previous release's dispatch, finished
#: and successful three days ago; run 200 appears only once this dispatch has happened, unless
#: the scenario says GitHub never registers it. The run list honours the `>= <epoch>` filter
#: the script passes, and without one returns the newest run, as `--limit 1` did.
_DEPLOY_GH = """case "$*" in
  "run list --workflow ci.yml"*) echo "11 1 completed success";;
  "api repos/"*) echo 1;;
  "workflow run deploy-pages.yml"*) date -u +%s > "$DISPATCHED";;
  "run list --workflow deploy-pages.yml"*)
    since=$(printf '%s' "$*" | sed -n 's/.*>= \\([0-9][0-9]*\\).*/\\1/p')
    new=""
    if [ -f "$DISPATCHED" ] && [ "$SCENARIO" != unregistered ]; then new=$(cat "$DISPATCHED"); fi
    if [ -z "$since" ]; then
      if [ -n "$new" ]; then echo 200; else echo 100; fi
    elif [ "$OLD_CREATED" -ge "$since" ]; then echo 100
    elif [ -n "$new" ] && [ "$new" -ge "$since" ]; then echo 200
    fi;;
  "run watch "*) [ "$SCENARIO" != failed ];;
  "run view "*"--json conclusion,jobs"*)
    if [ "$SCENARIO" = failed ]; then echo "failure jobs=[verify production source:failure]"
    else echo "success jobs=[]"; fi;;
  "run view 200 --json jobs"*)
    echo "verify production source"
    case "$SCENARIO" in
      other-tag) echo "production site-2026-27-gw06-fix2";;
      failed) echo "production ";;
      *) echo "production $TAG";;
    esac;;
  "run view 100 --json jobs"*) echo "production site-2026-27-gw06-decision";;
  *) exit 99;;
esac
"""


def _run_deploy_recipe(
    tmp_path: Path,
    *,
    scenario: str = "own-run",
    gh_script: str = _DEPLOY_GH,
    arguments: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
    browser: str = "ready",
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the real recipe against disposable commands, including its local preflight.

    Every operation that could contact a service or change a repository is a stand-in.
    The verifier's command, browser launch and browser tests are stand-ins too; no real
    deployment, verification request or browser process runs through this harness.
    """
    if not Path(SHELL).is_file():
        pytest.skip("A POSIX shell is required")
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "calls"
    cli = tmp_path / "web/node_modules/@playwright/test/cli.js"
    cli.parent.mkdir(parents=True)
    if browser != "missing-runner":
        cli.write_text("local runner stand-in\n", encoding="utf-8")
    expected_data = tmp_path / "accepted data"
    expected_data.mkdir()
    python = """case "${1:-}" in
  -c) exit "${PYTHON_EXIT:-0}";;
  */verify_live.py)
    [ "${2:-}" = "$ACCEPTED_STAMP" ] || exit 98
    exit "${VERIFY_EXIT:-0}";;
  *) exit 99;;
esac
"""
    node = """case "${1:-}" in
  -e) exit "${PREFLIGHT_EXIT:-0}";;
  */cli.js)
    case "${2:-}" in
      --version) exit 0;;
      test)
        [ "${LIVE_BASE_URL:-}" = https://squadopt.mymandev.com ] || exit 98
        [ -z "${LIVE_SMOKE_COMPUTE:-}" ] || exit 98
        exit "${BROWSER_EXIT:-0}";;
    esac;;
esac
exit 99
"""
    for name, body in {
        "git": _DEPLOY_GIT,
        "gh": gh_script,
        "sleep": ":\n",
        "python": python,
        "python3": python,
        "node": node,
    }.items():
        if name == "node" and browser == "missing-node":
            continue
        target = commands / name
        target.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n' + body,
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o755)
    if browser == "missing-node":
        # Isolate PATH from the machine's Node. Only inert stubs and the named
        # read-only POSIX utilities remain available, on both Windows and Linux.
        for name in ("cat", "cut", "date", "dirname", "grep", "sed", "wc"):
            target = commands / name
            target.write_text(
                f'#!/bin/sh\nexec /usr/bin/{name} "$@"\n', encoding="utf-8", newline="\n"
            )
            target.chmod(0o755)
    remote = [f"{_DEPLOY_TAG}0", "site-2026-27-gw06-decision"]
    if scenario == "existing-tag":
        remote.append(_DEPLOY_TAG)
    result = subprocess.run(
        [
            SHELL,
            "-c",
            'TOOL_PATH="$(cd "$COMMANDS" && pwd)"; '
            'if [ "$ISOLATE_TOOL_PATH" = 1 ]; then PATH="$TOOL_PATH"; '
            'else PATH="$TOOL_PATH:$PATH"; fi; export PATH; exec /bin/sh "$@"',
            "deploy-test",
            str(ROOT / "scripts/release/deploy.sh"),
            *(arguments if arguments is not None else [_DEPLOY_TAG, _DEPLOY_STAMP]),
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            # This is a hermetic operator simulation; the production CI refusal stays on.
            "CI": "",
            "COMMANDS": commands.as_posix(),
            "CALLS": calls.as_posix(),
            "DISPATCHED": (tmp_path / "dispatched").as_posix(),
            "OLD_CREATED": str(int(time.time()) - 3 * 86400),
            "REMOTE_TAGS": " ".join(remote),
            "SCENARIO": scenario,
            "TAG": _DEPLOY_TAG,
            "ACCEPTED_STAMP": _DEPLOY_STAMP,
            "MAIN_PARENTS": "parent1 parent2",
            "PREFLIGHT_EXIT": "1" if browser == "missing-chromium" else "0",
            "ISOLATE_TOOL_PATH": "1" if browser == "missing-node" else "0",
            "VERIFY_EXIT": "0",
            "BROWSER_EXIT": "0",
            "POLLS": (tmp_path / "polls").as_posix(),
            "RERUN": (tmp_path / "rerun").as_posix(),
            **(extra_env or {}),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return result, calls.read_text()


@pytest.mark.parametrize(
    "scenario", ["own-run", "existing-tag", "unregistered", "other-tag", "failed"]
)
def test_deploy_watches_only_the_run_it_dispatched(tmp_path: Path, scenario: str) -> None:
    """The newest dispatch run was taken as this one, so a run GitHub had not registered yet
    left the script watching the previous release's finished run and reporting its result."""

    result, log = _run_deploy_recipe(tmp_path, scenario=scenario)
    assert "run watch 100" not in log
    assert "run view 100" not in log
    if scenario == "own-run":
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"tag -a {_DEPLOY_TAG}" in log
        assert "run watch 200 --exit-status" in log
        assert "deploy run 200 finished" in result.stdout
    elif scenario == "existing-tag":
        assert result.returncode == 1
        assert f"tag {_DEPLOY_TAG} exists on origin; refusing" in result.stdout
        assert "tag -a" not in log
        assert "workflow run" not in log
    elif scenario == "unregistered":
        assert result.returncode == 1
        assert "could not find a dispatch run created since the dispatch" in result.stdout
        assert "run watch" not in log
    elif scenario == "other-tag":
        assert result.returncode == 1
        assert f"has no job 'production {_DEPLOY_TAG}'" in result.stdout
    else:
        # A failed run is reported as the failure it is. Its source check resolved no tag, so
        # its production job names none, and checking the name there would call this
        # release's own failure another run's.
        assert result.returncode == 1
        assert "run watch 200 --exit-status" in log
        assert "deploy run 200 finished: failure" in result.stdout
        assert "not this release's run" not in result.stdout


#: main's push CI as the deploy script polls it: the first attempt fails; `run rerun 11
#: --failed` starts a second, which GitHub shows one poll late, then running, then finished.
_RERUN_GH = """case "$*" in
  "run list --workflow ci.yml"*)
    if [ ! -f "$RERUN" ]; then echo "11 1 completed failure"; exit 0; fi
    polls=$(( $(cat "$POLLS" 2>/dev/null || echo 0) + 1 )); echo "$polls" > "$POLLS"
    case "$polls" in
      1) echo "11 1 completed failure";;
      2) echo "11 2 in_progress ";;
      *) if [ "$SCENARIO" = fails-again ]; then echo "11 2 completed failure"
         else echo "11 2 completed success"; fi;;
    esac;;
  "run rerun 11 --failed") [ "$SCENARIO" != rerun-refused ] && touch "$RERUN";;
  "api repos/"*) echo 1;;
  "workflow run deploy-pages.yml"*) date -u +%s > "$DISPATCHED";;
  "run list --workflow deploy-pages.yml"*) [ -f "$DISPATCHED" ] && echo 200;;
  "run watch "*) :;;
  "run view "*"--json conclusion,jobs"*) echo "success jobs=[]";;
  "run view 200 --json jobs"*) printf 'verify production source\nproduction %s\n' "$TAG";;
  *) exit 99;;
esac
"""


@pytest.mark.parametrize("scenario", ["passes-on-rerun", "fails-again", "rerun-refused"])
def test_a_failed_main_ci_is_rerun_once_before_the_deploy_refuses(
    tmp_path: Path, scenario: str
) -> None:
    """A flaky check on main stopped the scheduled releases of 14 and 15 Nov 2026 after their
    release PRs had merged. The failed jobs now run once more; a second failure refuses."""

    result, log = _run_deploy_recipe(tmp_path, scenario=scenario, gh_script=_RERUN_GH)
    assert log.count("run rerun 11 --failed") == 1
    assert (
        "main CI run 11 attempt 1 ended failure; re-running its failed jobs once" in result.stdout
    )
    if scenario == "passes-on-rerun":
        assert result.returncode == 0, result.stdout + result.stderr
        assert "main CI run 11 succeeded with one site artifact" in result.stdout
        assert f"tag -a {_DEPLOY_TAG}" in log
    elif scenario == "fails-again":
        assert result.returncode == 1
        assert "attempt 2 ended failure after the re-run; refusing to deploy" in result.stdout
        assert "tag -a" not in log
        assert "workflow run" not in log
    else:
        assert result.returncode == 1
        assert "main CI run 11 could not be re-run; refusing to deploy" in result.stdout
        assert "tag -a" not in log


@pytest.mark.parametrize("settled", [False, True])
@pytest.mark.parametrize("data_root", [False, True])
def test_deploy_forwards_publication_verification_arguments(
    tmp_path: Path, settled: bool, data_root: bool
) -> None:
    arguments = [_DEPLOY_TAG, _DEPLOY_STAMP]
    if settled or data_root:
        arguments.append("6" if settled else "")
    if data_root:
        arguments.append((tmp_path / "accepted data").as_posix())
    result, log = _run_deploy_recipe(tmp_path, arguments=arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    verification = next(line for line in log.splitlines() if "verify_live.py" in line)
    assert _DEPLOY_STAMP in verification
    assert ("--settled 6" in verification) is settled
    assert ("--expected-data-root" in verification) is data_root
    if data_root:
        assert (tmp_path / "accepted data").as_posix() in verification
    assert log.index("node -e ") < log.index("fetch -q origin")
    assert log.index("verify_live.py") < log.index("cli.js test --config playwright.live.config.ts")


def test_deploy_requires_the_accepted_publication_stamp(tmp_path: Path) -> None:
    result, log = _run_deploy_recipe(tmp_path, arguments=[_DEPLOY_TAG])
    assert result.returncode == 2
    assert "accepted-generated-at-ISO" in result.stderr
    assert "fetch -q origin" not in log
    assert "tag -a" not in log
    assert "workflow run" not in log


def test_deploy_preflight_only_checks_local_prerequisites(tmp_path: Path) -> None:
    result, log = _run_deploy_recipe(tmp_path, arguments=["--preflight"])
    assert result.returncode == 0, result.stdout + result.stderr
    assert "node -e " in log
    assert "cli.js --version" in log
    assert "fetch -q origin" not in log
    assert "verify_live.py" not in log
    assert "cli.js test " not in log
    assert "tag -a" not in log
    assert "workflow run" not in log


@pytest.mark.parametrize("parents", ["", "parent1", "parent1 parent2 parent3"])
def test_deploy_refuses_main_without_exactly_two_parents(tmp_path: Path, parents: str) -> None:
    result, log = _run_deploy_recipe(tmp_path, extra_env={"MAIN_PARENTS": parents})
    assert result.returncode == 1
    assert f"main tip mainsha has {len(parents.split())} parent(s)" in result.stdout
    assert "not a release merge; refusing" in result.stdout
    assert "run list --workflow ci.yml" not in log
    assert "tag -a" not in log
    assert "workflow run" not in log


@pytest.mark.parametrize("failure", ["PYTHON_EXIT", "CI"])
def test_deploy_preflight_failure_refuses_before_fetch(tmp_path: Path, failure: str) -> None:
    result, log = _run_deploy_recipe(tmp_path, extra_env={failure: "1"})
    assert result.returncode == 1
    assert "live verification preflight failed" in result.stdout
    assert "fetch -q origin" not in log
    assert "tag -a" not in log
    assert "workflow run" not in log


@pytest.mark.parametrize("browser", ["missing-node", "missing-runner", "missing-chromium"])
def test_a_host_without_a_browser_keeps_http_as_its_gate(tmp_path: Path, browser: str) -> None:
    result, log = _run_deploy_recipe(tmp_path, browser=browser)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("SKIP browser smoke and tour:") == 1
    assert "/verify_live.py " in log
    assert "cli.js test " not in log
    assert "required publication verification passed" in result.stdout


def test_a_browserless_host_still_refuses_a_failed_http_gate(tmp_path: Path) -> None:
    result, log = _run_deploy_recipe(
        tmp_path, browser="missing-node", extra_env={"VERIFY_EXIT": "7"}
    )
    assert result.returncode == 1
    assert log.count("/verify_live.py ") == 2
    assert "cli.js test " not in log
    assert "SKIP browser" not in result.stdout


def test_a_provisioned_browser_runs_without_backend_compute_diagnostics(tmp_path: Path) -> None:
    result, log = _run_deploy_recipe(tmp_path, extra_env={"LIVE_SMOKE_COMPUTE": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cli.js test --config playwright.live.config.ts" in log
    assert "SKIP browser" not in result.stdout


@pytest.mark.parametrize("failure", ["VERIFY_EXIT", "BROWSER_EXIT"])
def test_deploy_propagates_post_deployment_verification_failure(
    tmp_path: Path, failure: str
) -> None:
    result, log = _run_deploy_recipe(tmp_path, extra_env={failure: "7"})
    assert result.returncode == 1
    assert "post-deployment verification failed" in result.stdout
    assert "run watch 200 --exit-status" in log
    assert "verify_live.py" in log
    if failure == "VERIFY_EXIT":
        assert log.count("/verify_live.py ") == 2
        assert "cli.js test " not in log
    else:
        assert log.count("/verify_live.py ") == 1
        assert "cli.js test --config playwright.live.config.ts" in log


@pytest.mark.parametrize(
    ("served", "said"),
    [
        pytest.param({}, None, id="every-asset-is-itself"),
        pytest.param(
            {"/assets/Page-IjKl9012.js": (200, _SHELL)},
            "BAD 200 asset /assets/Page-IjKl9012.js  (the HTML shell)",
            id="a-lazy-chunk-is-the-shell",
        ),
        pytest.param(
            {"/assets/solver.worker-Uv-Wx123.js": (404, b"")},
            "BAD 404 asset /assets/solver.worker-Uv-Wx123.js",
            id="the-worker-is-missing",
        ),
        pytest.param(
            {verify_live.ABSENT_ASSET: (200, _SHELL)},
            f"BAD 200 absent {verify_live.ABSENT_ASSET}",
            id="a-missing-asset-is-the-shell",
        ),
    ],
)
def test_every_asset_the_shell_reaches_is_served_as_itself(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    served: dict[str, tuple[int, bytes]],
    said: str | None,
) -> None:
    """A deploy is green while an edge near the operator serves a chunk as the shell: the
    verifier follows the shell to every chunk, the lazy pages and the solver's worker."""

    assets = {
        "/assets/index-AbCd1234.js": (
            b'import("./Page-IjKl9012.js");m.f=["assets/Page-IjKl9012.js"]'
        ),
        "/assets/Page-IjKl9012.js": b"new URL(`/assets/solver.worker-Uv-Wx123.js`,import.meta.url)",
        "/assets/solver.worker-Uv-Wx123.js": b"self.onmessage=()=>{}",
    }
    live = _live(5, 5, 6)

    def fetch(path: str) -> tuple[int, bytes]:
        if path in served:
            return served[path]
        if path in assets:
            return 200, assets[path]
        return live(path)

    monkeypatch.setattr(verify_live, "fetch", fetch)
    code = verify_live.main("2026-09-18T18:00:00Z", 5)
    output = capsys.readouterr().out
    if said is None:
        assert code == 0, output
        assert "ok  3 assets, each served as itself" in output
    else:
        assert code == 1
        assert said in output
