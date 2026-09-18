"""Exercise the operator recipe without contacting GitHub or releasing anything."""

import json
import os
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
            "ten live",
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
    assert output.count(" html ") == 7
    assert output.count(" json ") == 2
    assert "must be 404" in output
