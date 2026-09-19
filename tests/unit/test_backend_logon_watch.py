"""Exercise the PowerShell watch loop with probes and launches replaced, never live PIDs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/start_backend_at_logon.ps1"


def _quoted(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _run(tmp_path: Path, *, health: str, connector: str, dry_run: bool = False) -> str:
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
""".replace("HEALTH", health)
        .replace("CONNECTOR", connector)
        .replace("ACTIONS", _quoted(tmp_path / "actions.txt"))
        .replace("SCRIPT", _quoted(SCRIPT))
        .replace("ROOT", _quoted(tmp_path))
        .replace("EXE", _quoted(executable))
        .replace("DRYRUN", "-DryRun" if dry_run else ""),
        encoding="ascii",
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
    assert actions.count("START") == 1
    assert "tick=5" in actions
    assert "-Port 18763" in actions
    assert "-RepoRoot" in actions
    assert "--label" not in actions


def test_watch_ignores_another_label_and_starts_only_its_connector(tmp_path: Path) -> None:
    _run(tmp_path, health="$true", connector=PRESENT.replace("test-watch", "test-watch-other"))
    actions = (tmp_path / "actions.txt").read_text(encoding="utf-16")
    assert actions.count("START") == 2
    assert "tick=2" in actions and "tick=5" in actions
    assert '--label test-watch run "test-tunnel"' in actions
    assert "-Workers" not in actions


def test_failed_process_probe_is_not_treated_as_missing(tmp_path: Path) -> None:
    output = _run(tmp_path, health="$true", connector="throw 'listing unavailable'")
    assert "connector check failed" in output
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
