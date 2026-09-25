"""The operator scripts find their checkout when run as documented, with `powershell -File`.

Windows PowerShell 5.1 leaves `$PSScriptRoot`, `$PSCommandPath` and
`$MyInvocation.MyCommand.Path` empty while it binds the parameter defaults of an advanced
script (one with `[CmdletBinding()]` or a `[Parameter()]` attribute) started with `-File`.
They are set in the script body, and in the defaults when the script is called with `&`, from
`-Command` or from another script; a plain script sees them in its defaults under `-File` too.
Both scripts that failed declared `[CmdletBinding()]`, so their default of `Split-Path -Parent
$PSScriptRoot` failed before either ran, with "Cannot bind argument to parameter 'Path'
because it is an empty string", unless `-RepoRoot` was passed. The first PowerShell test below
measures that rule on the machine running the suite. The static check holds every param block
under `scripts/` to it whatever its attributes, on purpose: a plain script that gains an
attribute later would break the same way.

The mocked tests elsewhere always pass `-RepoRoot` or invoke the script with `&`, so none of
them could see it. The runs here use scratch scripts, or copy each fixed script into a
disposable checkout and start it the documented way; none reaches a live process, port 8000
or the network.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = shutil.which("powershell.exe")
SCRIPTS = sorted((ROOT / "scripts").rglob("*.ps1"))
windows_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="requires Windows PowerShell 5.1"
)


def _param_block(path: Path) -> str:
    """The script's parameter block without comments."""

    text = re.sub(r"<#.*?#>", "", path.read_text(encoding="ascii"), flags=re.DOTALL)
    block = text.split("param(", 1)[1].split("\n)", 1)[0]
    return "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))


def test_every_script_is_checked() -> None:
    names = {path.relative_to(ROOT).as_posix() for path in SCRIPTS}
    assert {
        "scripts/start_backend_at_logon.ps1",
        "scripts/run_backend_local.ps1",
        "scripts/release/restart_backend.ps1",
    } <= names


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda path: path.name)
def test_no_parameter_default_reads_the_script_location(path: Path) -> None:
    assert "param(" in path.read_text(encoding="ascii"), path
    found = re.search(r"\$(PSScriptRoot|PSCommandPath|MyInvocation)\b", _param_block(path), re.I)
    assert found is None, f"{path.name} reads {found.group(0) if found else ''} in param()"


_PROBE = """{binding}param(
    {attribute}[string]$Root = "[$PSScriptRoot]",
    [string]$Command = "[$PSCommandPath]",
    [string]$Invocation = "[$($MyInvocation.MyCommand.Path)]"
)
Write-Output "$Root|$Command|$Invocation|[$PSScriptRoot]"
"""


@windows_powershell
@pytest.mark.parametrize(
    ("kind", "launch", "empty"),
    [
        ("plain", "file", False),
        ("cmdletbinding", "file", True),
        ("parameter-attribute", "file", True),
        ("cmdletbinding", "command", False),
        ("cmdletbinding", "call-from-file", False),
    ],
)
def test_only_an_advanced_script_under_file_loses_its_location_in_defaults(
    tmp_path: Path, kind: str, launch: str, empty: bool
) -> None:
    """The rule the module docstring states, measured on the PowerShell running the suite."""

    probe = tmp_path / "probe.ps1"
    probe.write_text(
        _PROBE.format(
            binding="[CmdletBinding()]\n" if kind == "cmdletbinding" else "",
            attribute="[Parameter()]" if kind == "parameter-attribute" else "",
        ),
        encoding="ascii",
    )
    if launch == "file":
        target = ["-File", str(probe)]
    elif launch == "command":
        target = ["-Command", f"& '{probe}'"]
    else:
        caller = tmp_path / "caller.ps1"
        caller.write_text("& (Join-Path $PSScriptRoot 'probe.ps1')\n", encoding="ascii")
        target = ["-File", str(caller)]
    result = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", *target],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    root, command, invocation, body = result.stdout.strip().split("|")
    assert body == f"[{tmp_path}]"
    if empty:
        assert (root, command, invocation) == ("[]", "[]", "[]")
    else:
        assert (root, command, invocation) == (f"[{tmp_path}]", f"[{probe}]", f"[{probe}]")


@windows_powershell
def test_the_documented_logon_dry_run_needs_no_repo_root(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(
        ROOT / "scripts/start_backend_at_logon.ps1", scripts / "start_backend_at_logon.ps1"
    )
    (scripts / "run_backend_local.ps1").write_text("throw 'must not execute'", encoding="ascii")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # A closed loopback port: the dry run's one health probe is refused at once.
    port = 20000 + zlib.crc32(str(tmp_path).encode()) % 20000
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(scripts / "start_backend_at_logon.ps1"),
            "-DryRun",
            "-Port",
            str(port),
            "-TunnelName",
            "test-tunnel",
            "-ConnectorLabel",
            "test-repo-root",
            "-Cloudflared",
            str(tmp_path / "absent/cloudflared.exe"),
        ],
        cwd=elsewhere,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "Cannot bind argument" not in result.stderr
    assert result.returncode == 0, result.stderr
    # The launcher was found at <checkout>\scripts, or the script would have thrown.
    assert f"would ask the launcher to start the backend on 127.0.0.1:{port}" in result.stdout
    assert not (checkout / "data").exists()


@windows_powershell
@pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")
def test_the_documented_restart_dry_run_needs_no_repo_root(tmp_path: Path) -> None:
    """It reaches the checkout guard, which reads the disposable repository's branch."""

    checkout = tmp_path / "checkout"
    release = checkout / "scripts/release"
    release.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/release/restart_backend.ps1", release / "restart_backend.ps1")
    subprocess.run(
        ["git", "-c", "init.defaultBranch=probe", "init", "--quiet", str(checkout)],
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(release / "restart_backend.ps1"),
            "-AcceptedGeneratedAt",
            "2026-09-22T22:04:06Z",
            "-DryRun",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "Cannot bind argument" not in result.stderr
    assert result.returncode != 0
    assert "Checkout must be on develop." in result.stderr
