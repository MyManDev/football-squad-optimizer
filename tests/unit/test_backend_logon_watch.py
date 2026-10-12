"""Exercise the PowerShell watch loop with probes and launches replaced, never live PIDs."""

from __future__ import annotations

import shutil
import subprocess
import zlib
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/start_backend_at_logon.ps1"


def _quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _run(
    tmp_path: Path,
    *,
    health: str,
    connector: str,
    dry_run: bool = False,
    setup: str = "",
    ready: str = "$true",
    github: str = "$true",
) -> str:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_backend_local.ps1").write_text("throw 'must not execute'", encoding="ascii")
    executable = tmp_path / "cloudflared.exe"
    executable.touch()
    harness = tmp_path / "probe.ps1"
    harness.write_text(
        """
$ErrorActionPreference = 'Stop'
$global:tick = 0
SETUP
function Invoke-WebRequest {
    param([switch]$UseBasicParsing, $TimeoutSec, $Uri)
    if ($Uri -eq 'http://127.0.0.1:18763/ready') {
        if (READY) { return @{StatusCode=200; Content='{"ready":true}'} }
        throw 'not ready'
    }
    if ($Uri -ne 'http://127.0.0.1:18763/health') { throw 'wrong target' }
    if (HEALTH) { return @{StatusCode=200} }
    throw 'offline'
}
function Fake-GitHub {
    Write-Output ('DISPATCH tick=' + $global:tick + ' ' + ($args -join ' ')) |
        Out-File -FilePath DISPATCHES -Append
    if (GITHUB) { $global:LASTEXITCODE = 0 } else { $global:LASTEXITCODE = 1; 'denied' }
}
function Get-CimInstance {
    param($ClassName, $Filter, $ErrorAction)
    CONNECTOR
}
function Start-Process {
    param($FilePath, $WindowStyle, $WorkingDirectory, $ArgumentList,
          $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne 'Hidden') { throw 'visible process' }
    Write-Output ('START tick=' + $global:tick + ' args=' + ($ArgumentList -join ' ')) |
        Out-File -FilePath ACTIONS -Append
}
function Start-Sleep {
    param($Seconds)
    if ($Seconds -ne 60) { throw 'wrong interval' }
    $global:tick++
    if ($global:tick -eq 8) { throw 'TEST_FINISHED' }
}
function Stop-Process { throw 'must never stop a process' }
function taskkill { throw 'must never kill a process' }
try {
    & SCRIPT -RepoRoot ROOT -Port 18763 -TunnelName test-tunnel -ConnectorLabel test-watch `
        -Cloudflared EXE -GitHubCli Fake-GitHub -Watch DRYRUN
} catch {
    if ($_.Exception.Message -ne 'TEST_FINISHED') { throw }
}
Write-Output ('TICKS=' + $global:tick)
""".replace("HEALTH", health)
        .replace("READY", ready)
        .replace("GITHUB", github)
        .replace("DISPATCHES", _quoted(tmp_path / "dispatches.txt"))
        .replace("SETUP", setup)
        .replace("CONNECTOR", connector)
        .replace("ACTIONS", _quoted(tmp_path / "actions.txt"))
        .replace("SCRIPT", _quoted(SCRIPT))
        .replace("ROOT", _quoted(tmp_path))
        .replace("EXE", _quoted(executable))
        .replace("DRYRUN", "-DryRun" if dry_run else ""),
        # Distinct mutex keys allow these independent mocked tests to run concurrently.
        encoding="ascii",
    )
    port = 20000 + zlib.crc32(str(tmp_path).encode()) % 20000
    harness.write_text(
        harness.read_text(encoding="ascii").replace("18763", str(port)), encoding="ascii"
    )
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout


PRESENT = "return @{CommandLine='cloudflared tunnel --label test-watch run test-tunnel'}"


def test_watch_resets_after_recovery_and_only_starts_missing_backend(tmp_path: Path) -> None:
    _run(tmp_path, health="$global:tick -in @(2, 6)", connector=PRESENT)
    actions = (tmp_path / "actions.txt").read_text(encoding="utf-16")
    assert actions.count("START") == 2
    assert "tick=0" in actions and "tick=5" in actions
    assert "-Port " in actions
    assert "-RepoRoot" in actions
    assert "--label" not in actions
    assert _dispatches(tmp_path) == [], "a launch that brought the backend back is not reported"


def test_watch_ignores_another_label_and_starts_only_its_connector(tmp_path: Path) -> None:
    output = _run(
        tmp_path, health="$true", connector=PRESENT.replace("test-watch", "test-watch-other")
    )
    actions = (tmp_path / "actions.txt").read_text(encoding="utf-16")
    assert actions.count("START") == 3
    assert all(f"tick={tick}" in actions for tick in (0, 3, 6))
    assert '--label test-watch run "test-tunnel"' in actions
    assert "-Workers" not in actions
    assert output.count("started tunnel connector") == 3


def test_every_backend_launch_is_logged(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$false", connector=PRESENT)
    assert output.count("asked the launcher") == 3
    assert (tmp_path / "actions.txt").read_text(encoding="utf-16").count("START") == 3


def test_failed_process_probe_is_not_treated_as_missing(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$true", connector="throw 'listing unavailable'")
    assert output.count("connector check failed") == 1
    assert not (tmp_path / "actions.txt").exists()


def test_dry_run_prints_actions_without_starting_or_writing_logs(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$false", connector="return", dry_run=True)
    assert "would ask the launcher" in output
    assert "would start tunnel test-tunnel with label test-watch" in output
    assert not (tmp_path / "actions.txt").exists()
    assert not (tmp_path / "data").exists()


def test_script_parses_with_windows_powershell(tmp_path: Path) -> None:
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile({_quoted(SCRIPT)}, "
        "[ref]$tokens, [ref]$errors) | Out-Null; if ($errors.Count) { throw $errors[0] }"
    )
    subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        timeout=30,
    )


def test_null_connector_command_line_is_unknown(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$true", connector="return @{CommandLine=$null}")
    assert output.count("connector command line unavailable") == 1
    assert not (tmp_path / "actions.txt").exists()


def test_healthy_dry_run_reports_both_components(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$true", connector=PRESENT, dry_run=True)
    assert "backend healthy" in output and "tunnel connector healthy" in output

    assert "TICKS=0" in output
    assert not (tmp_path / "data").exists()


def test_logging_failure_does_not_end_watch(tmp_path: Path) -> None:
    output = _run(
        tmp_path,
        health="$global:tick -ne 7",
        connector=PRESENT,
        setup="function Out-File { throw 'log is locked' }",
    )
    assert "backend healthy" in output and "tunnel connector healthy" in output
    assert "TICKS=8" in output


def test_live_recorded_workers_block_launch_without_repeated_logs(tmp_path: Path) -> None:
    registry = tmp_path / "data/runtime/backend/run"
    registry.mkdir(parents=True)
    (registry / "backend.pids.json").write_text(
        '{"processes":[{"pid":123,"start_ticks_utc":"0"}]}', encoding="ascii"
    )
    output = _run(
        tmp_path,
        health="$false",
        connector=PRESENT,
        setup=(
            "function Get-Process { param($Id,$ErrorAction); "
            "return @{StartTime=[datetime]::MinValue} }"
        ),
    )
    assert output.count("operator intervention needed") == 1
    assert not (tmp_path / "actions.txt").exists()
    assert not list((tmp_path / "data/runtime/backend/logs").glob("launcher-*"))


@pytest.mark.parametrize("dry_run", [False, True])
def test_existing_watcher_allows_only_dry_run_probes(tmp_path: Path, dry_run: bool) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_backend_local.ps1").touch()
    contender = tmp_path / "contender.ps1"
    contender.write_text(
        "function Invoke-WebRequest { return @{StatusCode=200; Content='{\"ready\":true}'} }\n"
        f"function Get-CimInstance {{ {PRESENT} }}\n"
        "function Start-Process { throw 'must not launch' }\n"
        "function Start-Sleep { throw 'must not loop' }\n"
        f"& {_quoted(SCRIPT)} -RepoRoot {_quoted(tmp_path)} -Port 18764 "
        "-ConnectorLabel test-watch -TunnelName test-tunnel -Watch "
        + ("-DryRun" if dry_run else ""),
        encoding="ascii",
    )
    command = (
        "$mutex = New-Object System.Threading.Mutex($true, "
        '"Global\\SquadOpt-backend-18764-test-watch"); '
        f"try {{ & powershell.exe -NoProfile -File {_quoted(contender)}; "
        "if ($LASTEXITCODE -ne 0) { throw 'second watcher failed' } } "
        "finally { $mutex.ReleaseMutex(); $mutex.Dispose() }"
    )
    port = 20000 + zlib.crc32(str(tmp_path).encode()) % 20000
    contender.write_text(
        contender.read_text(encoding="ascii").replace("18764", str(port)), encoding="ascii"
    )
    command = command.replace("18764", str(port))
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if dry_run:
        assert "backend healthy" in result.stdout and "tunnel connector healthy" in result.stdout
        assert "watcher already active" not in result.stdout
        assert not (tmp_path / "data").exists()
    else:
        assert result.stdout.count("watcher already active") == 1
        assert "healthy" not in result.stdout
        logs = list((tmp_path / "data/runtime/backend/logs").glob("startup-*.log"))
        assert len(logs) == 1
        assert "watcher already active" in logs[0].read_text(encoding="utf-8-sig")


def test_registered_shortcut_runs_watch() -> None:
    source = SCRIPT.read_text(encoding="ascii")
    assert '$link.Arguments += " -Watch -ConnectorLabel' in source
    assert '$link.Arguments += " -GitHubCli `"$GitHubCli`""' in source
    assert "with -Watch to start and watch now" in source


def _dispatches(tmp_path: Path) -> list[str]:
    path = tmp_path / "dispatches.txt"
    return path.read_text(encoding="utf-16").splitlines() if path.exists() else []


def test_an_api_that_stays_not_ready_is_reported_once_and_again_when_ready(tmp_path: Path) -> None:
    output = _run(
        tmp_path, health="$true", connector=PRESENT, ready="$global:tick -notin @(1, 2, 3, 4)"
    )
    dispatches = _dispatches(tmp_path)
    assert [line.split()[1] for line in dispatches] == ["tick=3", "tick=5"]
    assert all(
        "workflow run backend-uptime.yml -f dry_run=false -R MyManDev/football-squad-optimizer"
        in line
        for line in dispatches
    )
    assert "/ready is not ready" in output
    assert "asked GitHub to run the uptime check now" in output
    assert not (tmp_path / "actions.txt").exists(), "a backend that answers is never relaunched"
    assert not (tmp_path / "data/runtime/backend/run/watch-alert.txt").exists()


def test_a_short_not_ready_spell_is_not_reported(tmp_path: Path) -> None:
    _run(tmp_path, health="$true", connector=PRESENT, ready="$global:tick -notin @(2, 3)")
    assert _dispatches(tmp_path) == []


def test_a_silent_api_with_live_recorded_processes_is_reported_once(tmp_path: Path) -> None:
    registry = tmp_path / "data/runtime/backend/run"
    registry.mkdir(parents=True)
    (registry / "backend.pids.json").write_text(
        '{"processes":[{"pid":123,"start_ticks_utc":"0"}]}', encoding="ascii"
    )
    _run(
        tmp_path,
        health="$false",
        connector=PRESENT,
        setup=(
            "function Get-Process { param($Id,$ErrorAction); "
            "return @{StartTime=[datetime]::MinValue} }"
        ),
    )
    assert [line.split()[1] for line in _dispatches(tmp_path)] == ["tick=0"]
    assert not (tmp_path / "actions.txt").exists()
    assert (registry / "watch-alert.txt").exists(), "the open episode is kept for the next watcher"


def test_a_backend_a_launch_did_not_bring_back_is_reported_once(tmp_path: Path) -> None:
    _run(tmp_path, health="$false", connector=PRESENT)
    actions = (tmp_path / "actions.txt").read_text(encoding="utf-16")
    assert actions.count("START") == 3
    assert [line.split()[1] for line in _dispatches(tmp_path)] == ["tick=3"]


def test_a_refused_request_is_logged_and_the_watch_goes_on(tmp_path: Path) -> None:
    output = _run(
        tmp_path,
        health="$true",
        connector=PRESENT,
        ready="$global:tick -lt 3",
        github="$false",
    )
    assert "could not ask GitHub to run the uptime check" in output
    assert "TICKS=8" in output


def _ticks(tmp_path: Path) -> list[str]:
    return [line.split()[1] for line in _dispatches(tmp_path)]


def test_a_refused_alert_is_asked_again_at_the_fifth_check(tmp_path: Path) -> None:
    _run(
        tmp_path,
        health="$true",
        connector=PRESENT,
        ready="$false",
        github="$global:tick -ne 2",
    )
    assert _ticks(tmp_path) == ["tick=2", "tick=7"]
    assert (tmp_path / "data/runtime/backend/run/watch-alert.txt").exists()


def test_a_refused_recovery_keeps_the_episode_open(tmp_path: Path) -> None:
    _run(
        tmp_path,
        health="$true",
        connector=PRESENT,
        ready="$global:tick -ge 3",
        github="$global:tick -ne 3",
    )
    assert _ticks(tmp_path) == ["tick=2", "tick=3"]
    assert (tmp_path / "data/runtime/backend/run/watch-alert.txt").exists()


def test_a_restarted_watcher_still_asks_for_the_run_that_closes_the_incident(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "data/runtime/backend/run/watch-alert.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("2026-10-05T12:00:00", encoding="ascii")
    output = _run(tmp_path, health="$true", connector=PRESENT)
    assert _ticks(tmp_path) == ["tick=0"]
    assert "the backend is healthy and ready again" in output
    assert not marker.exists()


def test_a_dry_run_only_says_what_it_would_ask(tmp_path: Path) -> None:
    registry = tmp_path / "data/runtime/backend/run"
    registry.mkdir(parents=True)
    (registry / "backend.pids.json").write_text(
        '{"processes":[{"pid":123,"start_ticks_utc":"0"}]}', encoding="ascii"
    )
    output = _run(
        tmp_path,
        health="$false",
        connector=PRESENT,
        dry_run=True,
        setup=(
            "function Get-Process { param($Id,$ErrorAction); "
            "return @{StartTime=[datetime]::MinValue} }"
        ),
    )
    assert "would ask GitHub to run the uptime check now" in output
    assert _dispatches(tmp_path) == []
    assert not (registry / "watch-alert.txt").exists()
    assert not (tmp_path / "data/runtime/backend/logs").exists()
