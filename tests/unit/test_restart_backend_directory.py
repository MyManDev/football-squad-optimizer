"""The restart helper tells a site without the league directory from a broken read.

`scripts/release/restart_backend.ps1` runs under `$ErrorActionPreference = "Stop"`, where
Windows PowerShell 5.1 turns git's stderr line for an absent path into a terminating error
even when it is redirected. The site published no `data/leagues.json` before the directory,
so asking whether a ref holds it must answer False there, not throw. The function is taken
from the script itself and run under the script's own preference.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/restart_backend.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = [
    pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1"),
    pytest.mark.skipif(shutil.which("git") is None, reason="requires Git"),
]


def _git(cwd: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.test", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _exists(repository: Path, ref: str) -> str:
    """Published-Directory-Exists -Ref <ref>, defined from the script's own text."""

    find = (
        "{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]"
        " -and $node.Name -eq 'Published-Directory-Exists' }"
    )
    command = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            "Set-StrictMode -Version 2.0",
            "$tokens = $null; $errors = $null",
            "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
            f"'{SCRIPT}', [ref]$tokens, [ref]$errors)",
            f"$function = $ast.Find({find}, $true)",
            "Invoke-Expression $function.Extent.Text",
            f"$RepoRoot = '{repository}'",
            f"Write-Output (Published-Directory-Exists -Ref '{ref}')",
        ]
    )
    completed = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_a_ref_without_the_directory_is_a_site_from_before_it(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    data = repository / "web" / "public" / "data"
    data.mkdir(parents=True)
    (data / "index.json").write_text("{}", encoding="utf-8")
    _git(repository, "init", "-q")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "before the directory")
    assert _exists(repository, "HEAD") == "False"

    (data / "leagues.json").write_text("{}", encoding="utf-8")
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "the directory")
    assert _exists(repository, "HEAD") == "True"
