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

import pytest
from scripts.release import verify_live

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
        assert len(lines) == 15
        for required in (
            "two parents",
            "unexpired site artifact",
            "deploy-pages.yml",
            "live smoke checks",
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


@pytest.mark.parametrize("scenario", ["interrupt", "body-failure", "empty-body", "python-failure"])
def test_queue_refuses_before_merge(tmp_path: Path, scenario: str) -> None:
    if not Path(SHELL).is_file():
        pytest.skip("A POSIX shell is required")
    commands = tmp_path / "commands"
    commands.mkdir()
    venv = tmp_path / ".venv/bin"
    venv.mkdir(parents=True)
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    calls = tmp_path / "calls"
    stubs = {
        "git": """case "$*" in
  "rev-parse --show-toplevel") pwd;;
  "worktree list --porcelain") printf 'worktree %s\\nbranch refs/heads/test\\n' "$PWD";;
  *"rev-parse "*) echo same;;
  *"status --porcelain"*) :;;
  *) :;;
esac
""",
        "gh": """case "$*" in
  *"headRefName,state"*)
    if [ "$SCENARIO" = interrupt ]; then kill -INT "$QUEUE_PID"; fi
    echo 'OPEN test';;
  *"isDraft"*) echo false;;
  *"--json body"*) [ "$SCENARIO" = body-failure ] && exit 1; echo 'Generated with a tool';;
  *) exit 99;;
esac
""",
        "python": "exit 99\n",
        "sleep": "exit 99\n",
    }
    for name, body in stubs.items():
        target = commands / name
        target.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n' + body,
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o755)
    interpreter = venv / "python"
    interpreter.write_text(
        '#!/bin/sh\n[ "$SCENARIO" = python-failure ] && exit 1\nexec "$REAL_PY" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    interpreter.chmod(0o755)
    result = subprocess.run(
        [
            SHELL,
            "-c",
            'PATH="$(cd "$COMMANDS" && pwd):$PATH"; QUEUE_PID=$$; '
            'export PATH QUEUE_PID; exec /bin/sh "$@"',
            "queue-test",
            str(ROOT / "scripts/release/queue2.sh"),
            "1",
            "2",
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "COMMANDS": commands.as_posix(),
            "CALLS": calls.as_posix(),
            "REAL_PY": Path(sys.executable).as_posix(),
            "SCENARIO": scenario,
            "TMPDIR": temporary.as_posix(),
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    log = calls.read_text()
    assert "pr merge" not in log
    assert list(temporary.iterdir()) == []
    if scenario == "interrupt":
        assert result.returncode == 130, result.stderr
        assert "reset" not in log
        assert "pr view 2" not in log
    elif scenario == "python-failure":
        assert result.returncode == 1
        assert "python could not start" in result.stderr
        assert "pr view" not in log
    else:
        assert result.returncode == 0, result.stderr
        assert "body unreadable" in result.stdout or "body scan FAILED" in result.stdout


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
    """A live site that has settled ``settled`` and says so in all three documents."""

    def fetch(path: str) -> tuple[int, bytes]:
        if path == verify_live.ABSENT:
            return 404, b""
        if path in verify_live.ROUTES:
            return 200, b'<div id="root"></div>'
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
        if path == verify_live.ABSENT:
            return absent_status, b""
        if path in verify_live.ROUTES:
            return 200, b'<div id="root"></div>'
        if path == "/data/index.json":
            return 200, _index()
        return 200, json.dumps({"generated_at_utc": "2026-09-18T18:00:00Z", "payload": {}}).encode()

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T18:00:00Z") == (0 if absent_status == 404 else 1)
    output = capsys.readouterr().out
    assert output.count(" html ") == len(verify_live.ROUTES)
    assert output.count(" json ") == len(verify_live.DOCUMENTS)
    assert "must be 404" in output


def test_the_verifier_checks_the_same_routes_the_deployment_smoke_does() -> None:
    """The two lists drifted once: `/fixtures` was added to one and not the other."""

    source = (ROOT / "web/scripts/smoke-deployment.mjs").read_text(encoding="utf-8")
    block = source.split("export const SMOKE_CHECKS = [", 1)[1].split("\n];", 1)[0]
    paths = re.findall(r'path:\s*"([^"]+)"', block)
    kinds = re.findall(r'kind:\s*"([^"]+)"', block)
    assert len(paths) == len(kinds), block
    named = dict(zip(paths, kinds, strict=True))
    assert [path for path, kind in named.items() if kind == "html"] == verify_live.ROUTES
    assert [path for path, kind in named.items() if kind == "json"] == verify_live.DOCUMENTS
    assert [path for path, kind in named.items() if kind == "absent"] == [verify_live.ABSENT]


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

#: git answers as a release-ready main would; ls-remote lists $REMOTE_TAGS.
_DEPLOY_GIT = """case "$*" in
  "rev-parse --show-toplevel") pwd;;
  "fetch -q origin") :;;
  "rev-parse origin/main") echo mainsha;;
  "rev-parse origin/develop") echo devsha;;
  "rev-list --parents -n1 origin/main") echo "mainsha parent1 parent2";;
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
  "run list --workflow ci.yml"*) echo "11 completed success";;
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


@pytest.mark.parametrize(
    "scenario", ["own-run", "existing-tag", "unregistered", "other-tag", "failed"]
)
def test_deploy_watches_only_the_run_it_dispatched(tmp_path: Path, scenario: str) -> None:
    """The newest dispatch run was taken as this one, so a run GitHub had not registered yet
    left the script watching the previous release's finished run and reporting its result."""

    if not Path(SHELL).is_file():
        pytest.skip("A POSIX shell is required")
    commands = tmp_path / "commands"
    commands.mkdir()
    calls = tmp_path / "calls"
    stubs = {"git": _DEPLOY_GIT, "gh": _DEPLOY_GH, "sleep": ":\n"}
    for name, body in stubs.items():
        target = commands / name
        target.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$CALLS"\n' + body,
            encoding="utf-8",
            newline="\n",
        )
        target.chmod(0o755)
    # A tag the release tag is a prefix of must not read as the release tag itself.
    remote = [f"{_DEPLOY_TAG}0", "site-2026-27-gw06-decision"]
    if scenario == "existing-tag":
        remote.append(_DEPLOY_TAG)
    result = subprocess.run(
        [
            SHELL,
            "-c",
            'PATH="$(cd "$COMMANDS" && pwd):$PATH"; export PATH; exec /bin/sh "$@"',
            "deploy-test",
            str(ROOT / "scripts/release/deploy.sh"),
            _DEPLOY_TAG,
        ],
        cwd=tmp_path,
        env={
            **os.environ,
            "COMMANDS": commands.as_posix(),
            "CALLS": calls.as_posix(),
            "DISPATCHED": (tmp_path / "dispatched").as_posix(),
            "OLD_CREATED": str(int(time.time()) - 3 * 86400),
            "REMOTE_TAGS": " ".join(remote),
            "SCENARIO": scenario,
            "TAG": _DEPLOY_TAG,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    log = calls.read_text()
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
