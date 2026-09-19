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
    tmp_path: Path, *, health: str, connector: str, dry_run: bool = False, setup: str = ""
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
    if ($Uri -ne 'http://127.0.0.1:18763/health') { throw 'wrong target' }
    if (HEALTH) { return @{StatusCode=200} }
    throw 'offline'
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
        -Cloudflared EXE -Watch DRYRUN
} catch {
    if ($_.Exception.Message -ne 'TEST_FINISHED') { throw }
}
Write-Output ('TICKS=' + $global:tick)
""".replace("HEALTH", health)
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


def test_watch_ignores_another_label_and_starts_only_its_connector(tmp_path: Path) -> None:
    _run(tmp_path, health="$true", connector=PRESENT.replace("test-watch", "test-watch-other"))
    actions = (tmp_path / "actions.txt").read_text(encoding="utf-16")
    assert actions.count("START") == 3
    assert all(f"tick={tick}" in actions for tick in (0, 3, 6))
    assert '--label test-watch run "test-tunnel"' in actions
    assert "-Workers" not in actions


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


def test_existing_watcher_exits_without_probing_or_launching(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "run_backend_local.ps1").touch()
    command = (
        "$mutex = New-Object System.Threading.Mutex($true, "
        '"Local\\SquadOpt-backend-18764-test-lock"); '
        f"try {{ & powershell.exe -NoProfile -File {_quoted(SCRIPT)} "
        f"-RepoRoot {_quoted(tmp_path)} -Port 18764 -ConnectorLabel test-lock -Watch -DryRun; "
        "if ($LASTEXITCODE -ne 0) { throw 'second watcher failed' } } "
        "finally { $mutex.ReleaseMutex(); $mutex.Dispose() }"
    )
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.count("watcher already active") == 1
    assert not (tmp_path / "data").exists()


def test_registered_shortcut_runs_watch() -> None:
    source = SCRIPT.read_text(encoding="ascii")
    assert '$link.Arguments += " -Watch -ConnectorLabel' in source
    assert "with -Watch to start and watch now" in source
