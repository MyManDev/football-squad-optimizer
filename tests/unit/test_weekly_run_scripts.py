"""The planner's Start button runs `scripts/weekly_run.ps1`; its pieces are pinned here.

The script decides four things before it runs the weekly command: the open gameweek (from
the published fixtures document), the run id and site suffix (from the kind and the clock),
the cadence's argument line, and the tag the release will take (the first unused one under
the naming rule). It refuses a dirty checkout, a checkout off `develop` and a run already in
progress. Each piece is a function the script defines, run here by dot-sourcing the script
under Windows PowerShell 5.1 on synthetic inputs; nothing here starts a weekly run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "weekly_run.ps1"
WRAPPERS = (ROOT / "scripts" / "weekly_run_tuesday.ps1", ROOT / "scripts" / "weekly_run_friday.ps1")
POWERSHELL = shutil.which("powershell.exe")

pytestmark = [
    pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1"),
    pytest.mark.skipif(shutil.which("git") is None, reason="requires Git"),
]


def _powershell(*lines: str) -> str:
    """Dot-source the script's functions, then run `lines`; return stdout."""

    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "Set-StrictMode -Version 2.0",
            f". '{SCRIPT}' -Kind friday",
            *lines,
        ]
    )
    completed = subprocess.run(
        [POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def _fixtures(tmp_path: Path, deadlines: dict[int, str], season: str = "2026-27") -> Path:
    path = tmp_path / "fixtures.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": "fixtures_v1",
                "generated_at_utc": "2026-10-15T14:00:00Z",
                "payload": {
                    "season": season,
                    "gameweeks": [
                        {"gameweek": week, "deadline_utc": deadline}
                        for week, deadline in deadlines.items()
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_open_gameweek_is_the_first_deadline_still_ahead(tmp_path: Path) -> None:
    path = _fixtures(
        tmp_path,
        {6: "2026-10-10T10:00:00Z", 7: "2026-10-17T10:00:00Z", 8: "2026-10-23T17:30:00Z"},
    )
    out = _powershell(
        f"Resolve-OpenGameweek '{path}' "
        "([datetime]::Parse('2026-10-15T14:00:00Z').ToUniversalTime())",
        f"Resolve-OpenGameweek '{path}' "
        "([datetime]::Parse('2026-10-17T10:00:01Z').ToUniversalTime())",
        f"Weekly-Season '{path}'",
    )
    assert out.splitlines() == ["7", "8", "2026-27"]


def test_a_season_with_no_deadline_ahead_refuses(tmp_path: Path) -> None:
    path = _fixtures(tmp_path, {38: "2027-05-23T13:00:00Z"})
    command = (
        f". '{SCRIPT}' -Kind friday\n"
        f"try {{ Resolve-OpenGameweek '{path}' ([datetime]::Parse('2027-06-01T00:00:00Z')) }}"
        " catch { Write-Output ('refused: ' + $_.Exception.Message) }"
    )
    completed = subprocess.run(
        [POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert "refused: No gameweek deadline lies ahead" in completed.stdout


def test_a_club_news_capture_rides_on_the_rotation_stage() -> None:
    news = "club-news-20261023T050000Z-abc"
    out = _powershell(
        f"(Build-WeeklyArguments '2026-27' 8 15 'rid' 'friday-20261023' '{news}') -join ' '",
        f"Captured-NewsId @('Read          41 documents', 'Capture       {news}')",
        "\"[{0}]\" -f (Captured-NewsId @('Refused: no key'))",
    )
    arguments, captured, none = out.splitlines()
    assert f"--rotation --rotation-capture {news} --record-advice" in arguments
    assert captured == news
    assert none == "[]"


def test_run_id_suffix_and_argument_line_follow_the_cadence() -> None:
    out = _powershell(
        "$now = [datetime]::Parse('2026-10-16T06:00:00Z').ToUniversalTime()",
        "Weekly-RunId 'friday' '2026-27' 7 $now",
        "Weekly-Suffix 'friday' $now",
        "(Build-WeeklyArguments '2026-27' 7 15 'rid' 'friday-20261016') -join ' '",
    )
    run_id, suffix, arguments = out.splitlines()
    assert run_id == "2026-27-gw07-friday-20261016T0600Z"
    assert suffix == "friday-20261016"
    assert arguments == (
        "-m squadopt.platform.weekly_operations --season 2026-27 --gameweek 7 "
        "--league-list config/leagues.json --workers 15 --projection component-only "
        "--rotation --record-advice --publish --publish-suffix friday-20261016 --run-id rid"
    )


@pytest.mark.parametrize(
    "kind,gameweek,existing,expected",
    [
        ("friday", 7, [], "site-2026-27-gw07-decision"),
        ("friday", 7, ["site-2026-27-gw07-decision"], "site-2026-27-gw07-fix1"),
        (
            "friday",
            7,
            ["site-2026-27-gw07-decision", "site-2026-27-gw07-fix1", "site-2026-27-gw07-fix2"],
            "site-2026-27-gw07-fix3",
        ),
        ("tuesday", 7, [], "site-2026-27-gw06-settled"),
        ("tuesday", 7, ["site-2026-27-gw06-settled"], "site-2026-27-gw06-fix1"),
        (
            "tuesday",
            8,
            ["site-2026-27-gw07-decision", "site-2026-27-gw07-settled", "site-2026-27-gw07-fix1"],
            "site-2026-27-gw07-fix2",
        ),
    ],
)
def test_the_suggested_tag_is_the_first_unused_one(
    kind: str, gameweek: int, existing: list[str], expected: str
) -> None:
    listed = ", ".join(f"'{tag}'" for tag in existing) or "''"
    out = _powershell(f"Suggested-Tag '{kind}' '2026-27' {gameweek} @({listed})")
    assert out == expected


def _git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.test", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _assert_runnable(repository: Path) -> str:
    return _powershell(
        f"try {{ Assert-RunnableCheckout '{repository}'; Write-Output 'ok' }}"
        " catch { Write-Output ('refused: ' + $_.Exception.Message) }"
    )


def test_the_checkout_must_be_clean_and_on_develop(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "develop")
    (repository / "README.md").write_text("synthetic\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-q", "-m", "synthetic")

    assert _assert_runnable(repository) == "ok"

    (repository / "README.md").write_text("changed\n", encoding="utf-8")
    assert _assert_runnable(repository).startswith("refused: Checkout is not clean (1 changed path")

    _git(repository, "checkout", "-q", "--", "README.md")
    _git(repository, "checkout", "-q", "-b", "feature/x")
    assert _assert_runnable(repository) == (
        "refused: Checkout must be on develop (it is on 'feature/x')."
    )


def test_the_pull_request_line_is_read_from_the_log(tmp_path: Path) -> None:
    log = tmp_path / "run.log"
    log.write_text(
        "Weekly run: rid\nPR: https://github.com/MyManDev/football-squad-optimizer/pull/1107\n",
        encoding="utf-8",
    )
    assert _powershell(f"Published-PullRequest '{log}'") == (
        "https://github.com/MyManDev/football-squad-optimizer/pull/1107"
    )
    (tmp_path / "empty.log").write_text("Weekly run: rid\n", encoding="utf-8")
    assert _powershell(f"\"[{{0}}]\" -f (Published-PullRequest '{tmp_path / 'empty.log'}')") == "[]"


def test_the_wrappers_pass_their_kind_to_the_script() -> None:
    for wrapper in WRAPPERS:
        text = wrapper.read_text(encoding="utf-8")
        kind = wrapper.stem.removeprefix("weekly_run_")
        assert f"Kind = '{kind}'" in text
        assert "weekly_run.ps1" in text
        assert "exit $LASTEXITCODE" in text
        assert "ClubNewsSettings = $ClubNewsSettings" in text
