"""Exercise the operator recipe without contacting GitHub or releasing anything."""

import json
import os
import re
import shutil
import subprocess
import sys
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


def _live(settled: int, scored: int | None, next_gameweek: int) -> object:
    """A live site that has settled ``settled`` and says so in all three documents."""

    def fetch(path: str) -> tuple[int, bytes]:
        if path == verify_live.ABSENT:
            return 404, b""
        if path in verify_live.ROUTES:
            return 200, b'<div id="root"></div>'
        if path == "/data/league/scoreboard.json":
            weeks = [
                {"gameweek": week, "finished": True, "data_checked": True}
                for week in range(1, settled + 1)
            ]
            return 200, json.dumps({"payload": {"gameweeks": weeks}}).encode()
        if path == "/data/2026-27/status.json":
            return 200, json.dumps({"payload": {"next_gameweek": next_gameweek}}).encode()
        return 200, json.dumps(
            {
                "generated_at_utc": "2026-09-18T18:00:00Z",
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
        return 200, json.dumps({"generated_at_utc": "2026-09-18T18:00:00Z", "payload": {}}).encode()

    monkeypatch.setattr(verify_live, "fetch", fetch)
    assert verify_live.main("2026-09-18T17:00:00Z") == (0 if absent_status == 404 else 1)
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
    assert verify_live.main("2026-09-18T17:00:00Z") == 0
    assert verify_live.main("2026-09-18T17:00:00Z", 4) == 0
    # One exit code, three named failures: the count is in the output, not the return.
    assert verify_live.main("2026-09-18T17:00:00Z", 5) == 1
    output = capsys.readouterr().out
    assert "BAD scoreboard settles gameweek 5" in output
    assert "BAD members.json scored_gameweek is 5" in output
    assert "BAD status moved past gameweek 5" in output


def test_each_of_the_three_settled_claims_fails_on_its_own(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(verify_live, "fetch", _live(settled=5, scored=4, next_gameweek=6))
    assert verify_live.main("2026-09-18T17:00:00Z", 5) == 1
    monkeypatch.setattr(verify_live, "fetch", _live(settled=5, scored=5, next_gameweek=5))
    assert verify_live.main("2026-09-18T17:00:00Z", 5) == 1
    monkeypatch.setattr(verify_live, "fetch", _live(settled=4, scored=5, next_gameweek=6))
    assert verify_live.main("2026-09-18T17:00:00Z", 5) == 1
    capsys.readouterr()


def test_the_generated_after_argument_has_no_default_any_more() -> None:
    """A stale default made the only freshness check vacuous when the argument was forgotten."""

    with pytest.raises(SystemExit):
        verify_live._arguments([])
    assert verify_live._arguments(["2026-09-18T17:00:00Z"]).settled is None
    assert verify_live._arguments(["2026-09-18T17:00:00Z", "--settled", "5"]).settled == 5
