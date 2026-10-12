"""The native Windows launcher and the tunnel example say what the code says.

Static checks hold the shared CORS and environment facts and the tunnel ingress order.
Windows-only tests also run the real launcher with its child processes, listener and HTTP
probes replaced, so durable artifact selection is exercised without starting a backend.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from squadopt.platform.backend_runtime import SITE_ORIGINS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY_ROOT / "scripts" / "run_backend_local.ps1"
LOGON = REPOSITORY_ROOT / "scripts" / "start_backend_at_logon.ps1"
PARENTAGE = REPOSITORY_ROOT / "scripts" / "backend_parentage.ps1"
# The variables an agent sets for its shells (scripts/backend_parentage.ps1).
AGENT_MARKERS = {
    "CLAUDECODE",
    "CODEX_SANDBOX",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_SESSION_ID",
}
TUNNEL = REPOSITORY_ROOT / "deploy" / "cloudflared" / "config.example.yml"
BACKEND_RUNTIME = REPOSITORY_ROOT / "src" / "squadopt" / "platform" / "backend_runtime.py"


def _launcher_code(path: Path = LAUNCHER) -> str:
    """The script without its comments, so a commented-out variable is not counted."""

    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_launcher_allows_exactly_the_published_origins() -> None:
    match = re.search(r'\$AllowedOrigins = "([^"]*)"', LAUNCHER.read_text(encoding="utf-8"))
    assert match is not None, "the launcher no longer declares its CORS allowlist default"
    assert tuple(match.group(1).split(",")) == SITE_ORIGINS


def test_every_backend_variable_the_launcher_sets_is_one_the_backend_reads() -> None:
    """A misspelt name is not an error anywhere: the backend would run on its default."""

    known = BACKEND_RUNTIME.read_text(encoding="utf-8")
    names = set(re.findall(r"\bSQUADOPT_BACKEND_[A-Z_]+\b", _launcher_code()))
    assert {
        "SQUADOPT_BACKEND_STORE_ROOT",
        "SQUADOPT_BACKEND_SITE_DATA_ROOT",
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT",
        "SQUADOPT_BACKEND_HANDOFF_ROOT",
        "SQUADOPT_BACKEND_ALLOWED_ORIGINS",
    } <= names
    assert sorted(name for name in names if f'"{name}"' not in known) == []


@pytest.mark.parametrize(
    "path", [LAUNCHER, LOGON, PARENTAGE], ids=["launcher", "logon", "parentage"]
)
def test_the_launcher_parses_under_windows_powershell_5_1(path: Path) -> None:
    """5.1 reads a file without a byte order mark as ANSI, and has neither && nor ?:."""

    raw = path.read_bytes()
    assert all(byte < 128 for byte in raw), "non-ASCII bytes would be misread by 5.1"
    code = _launcher_code(path)
    assert "&&" not in code
    assert "||" not in code
    assert re.search(r"\?\s*[^:\n]+\s*:\s", code) is None, "a ternary is PowerShell 7 syntax"


def test_logon_forwarded_options_exist_in_the_launcher_param_block() -> None:
    parameters = _launcher_code().split("param(", 1)[1].split("\n)", 1)[0]
    forwarded = _launcher_code(LOGON).split("-ArgumentList @(", 1)[1].split(")", 1)[0]
    for name in ("Workers", "Port"):
        assert f'"-{name}"' in forwarded
        assert re.search(rf"\${name}\s*=", parameters)


def test_the_api_listens_on_loopback_and_trusts_only_loopback_for_forwarded_headers() -> None:
    code = _launcher_code()
    assert '"--host", "127.0.0.1"' in code
    assert '"--forwarded-allow-ips", "127.0.0.1"' in code
    assert "0.0.0.0" not in code


def _ingress_rules() -> list[dict[str, str]]:
    """The ingress list, read without a YAML parser: the file is flat enough to be held to
    this shape, and the test environment does not declare one."""

    rules: list[dict[str, str]] = []
    in_ingress = False
    for line in TUNNEL.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "ingress:":
            in_ingress = True
            continue
        if not in_ingress:
            continue
        if stripped.startswith("- "):
            rules.append({})
            stripped = stripped[2:]
        key, _, value = stripped.partition(":")
        rules[-1][key.strip()] = value.strip()
    return rules


def test_the_tunnel_refuses_metrics_before_it_forwards_anything() -> None:
    rules = _ingress_rules()
    assert len(rules) == 3
    refused, forwarded, catch_all = rules

    assert refused["service"] == "http_status:404"
    pattern = re.compile(refused["path"])
    for path in ("/metrics", "/metrics/", "/docs", "/openapi.json"):
        assert pattern.search(path), path
    for path in ("/health", "/ready", "/api/v1/leagues/352490", "/api/v1/advice-jobs/x"):
        assert pattern.search(path) is None, path

    assert forwarded["hostname"] == refused["hostname"]
    assert "path" not in forwarded
    # The literal address: uvicorn trusts forwarded headers from 127.0.0.1, not from ::1.
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+", forwarded["service"])

    assert catch_all == {"service": "http_status:404"}


def test_the_tunnel_hostname_is_one_label_under_the_zone() -> None:
    """Universal SSL covers the zone and its first-level names; a deeper one gets no
    certificate on the Free plan (docs/backend_free_hosting.md)."""

    hostnames = {rule["hostname"] for rule in _ingress_rules() if "hostname" in rule}
    assert hostnames == {"squadopt-api.mymandev.com"}


POWERSHELL = shutil.which("powershell.exe")
WINDOWS_ONLY = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")


def _ps_quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _run_selected_launcher(
    root: Path, *, arguments: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    for directory in ("src", "web/public/data", "data/snapshots", "data/handoffs", "artifacts"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    python = root / "fake-python.exe"
    python.touch()
    harness = root / "launcher-probe.ps1"
    flags = " ".join(
        value
        if value in {"-Stop", "-Status", "-ArtifactRoot"}
        else "'" + value.replace("'", "''") + "'"
        for value in arguments
    )
    harness.write_text(
        r"""
$ErrorActionPreference = 'Stop'
$env:SQUADOPT_REPOSITORY_COMMIT = '1111111111111111111111111111111111111111'
$env:SQUADOPT_BACKEND_ARTIFACT_ROOT = 'inherited-value-must-not-select-root'
$global:launchCount = 0
$global:fakeStartedAt = [datetime]'2026-01-01T00:00:00Z'
function New-Object {
    param($TypeName, $ArgumentList)
    if ($TypeName -ne 'System.Net.Sockets.TcpListener') { throw 'unexpected object' }
    $listener = [pscustomobject]@{}
    $listener | Add-Member -MemberType ScriptMethod -Name Start -Value { }
    $listener | Add-Member -MemberType ScriptMethod -Name Stop -Value { }
    return $listener
}
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $RedirectStandardOutput,
          $RedirectStandardError, $WindowStyle, [switch]$PassThru)
    if ($WindowStyle -ne 'Hidden') { throw 'visible child process' }
    $global:launchCount++
    @{args=@($ArgumentList); artifact_root=$env:SQUADOPT_BACKEND_ARTIFACT_ROOT} |
        ConvertTo-Json -Compress | Out-File -FilePath @ACTIONS@ -Append -Encoding utf8
    return [pscustomobject]@{Id=(1000 + $global:launchCount); StartTime=$global:fakeStartedAt}
}
function Get-Process {
    param($Id, $ErrorAction)
    if ($Id -lt 1001 -or $Id -gt 1003) { throw 'unexpected process inspection' }
    return [pscustomobject]@{StartTime=$global:fakeStartedAt}
}
function Get-CimInstance { return @() }
function Stop-Process { throw 'must not stop real processes' }
function Start-Sleep { }
function Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -notmatch '^http://127\.0\.0\.1:18763/(health|ready|metrics)$') {
        throw 'unexpected HTTP target'
    }
    $body = if ($Uri -like '*/metrics') { 'advice_queue_depth 0' } else { '{}' }
    return @{StatusCode=200; Content=$body}
}
& @SCRIPT@ -RepoRoot @ROOT@ -Python @PYTHON@ -Port 18763 -Workers 2 @FLAGS@
""".replace("@ACTIONS@", _ps_quote(root / "actions.jsonl"))
        .replace("@SCRIPT@", _ps_quote(LAUNCHER))
        .replace("@ROOT@", _ps_quote(root))
        .replace("@PYTHON@", _ps_quote(python))
        .replace("@FLAGS@", flags),
        encoding="ascii",
    )
    return subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-File", str(harness)],
        # Whatever started pytest is no agent here; test_backend_parentage.py covers the guard.
        env={
            **{name: value for name, value in os.environ.items() if name not in AGENT_MARKERS},
            "SQUADOPT_AGENT_APPLICATIONS": "no-agent-application.exe",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _selection_file(root: Path, text: str) -> Path:
    path = root / "artifacts/backend-artifact-root.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@WINDOWS_ONLY
@pytest.mark.parametrize("selection", ["absent", "absolute", "relative", "explicit"])
def test_artifact_selection_reaches_api_workers_and_registry(
    tmp_path: Path, selection: str
) -> None:
    selected = tmp_path / "retained artifacts"
    selected.mkdir()
    arguments: tuple[str, ...] = ()
    expected = tmp_path / "artifacts"
    if selection in {"absolute", "relative"}:
        value = str(selected) if selection == "absolute" else selected.name
        _selection_file(tmp_path, json.dumps({"artifact_root": value}))
        expected = selected
    elif selection == "explicit":
        _selection_file(tmp_path, "not JSON: explicit argument must win")
        arguments = ("-ArtifactRoot", str(selected))
        expected = selected

    completed = _run_selected_launcher(tmp_path, arguments=arguments)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    calls = [
        json.loads(line)
        for line in (tmp_path / "actions.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    assert len(calls) == 3
    assert calls[0]["args"][:2] == ["-m", "uvicorn"]
    assert all(call["args"] == ["-m", "squadopt.platform.advice_worker"] for call in calls[1:])
    assert all(Path(call["artifact_root"]) == expected for call in calls)
    registry = json.loads(
        (tmp_path / "data/runtime/backend/run/backend.pids.json").read_text(encoding="utf-8-sig")
    )
    assert Path(registry["artifact_root"]) == expected
    assert len(registry["processes"]) == 3


@WINDOWS_ONLY
@pytest.mark.parametrize(
    "document",
    [
        "",
        "not JSON",
        "{}",
        '{"artifact_root":""}',
        '{"artifact_root":"   "}',
        '{"artifact_root":null}',
        '{"artifact_root":42}',
        '{"artifact_root":"missing-directory"}',
        '{"artifact_root":"fake-python.exe"}',
        '{"ARTIFACT_ROOT":"artifacts"}',
        '{"artifact_root":"artifacts","unexpected":true}',
        '{"artifact_root":"artifacts","artifact_root":"artifacts"}',
        '[{"artifact_root":"artifacts"}]',
        '{"artifact_root":"artifacts"} false',
    ],
)
def test_invalid_artifact_selection_refuses_before_any_start(tmp_path: Path, document: str) -> None:
    _selection_file(tmp_path, document)

    completed = _run_selected_launcher(tmp_path)

    assert completed.returncode != 0
    assert "Artifact selection" in completed.stderr
    assert not (tmp_path / "actions.jsonl").exists()
    assert not (tmp_path / "data/runtime/backend/run/backend.pids.json").exists()


@WINDOWS_ONLY
@pytest.mark.parametrize("operation", ["-Stop", "-Status"])
@pytest.mark.parametrize("recorded_root", [None, "retained artifacts"])
def test_bad_selection_does_not_prevent_stop_or_status(
    tmp_path: Path, operation: str, recorded_root: str | None
) -> None:
    _selection_file(tmp_path, "invalid but irrelevant to existing process control")
    registry_path = tmp_path / "data/runtime/backend/run/backend.pids.json"
    registry_path.parent.mkdir(parents=True)
    registry: dict[str, object] = {"port": 18763, "processes": []}
    if recorded_root is not None:
        registry["artifact_root"] = recorded_root
    registry_path.write_text(json.dumps(registry), encoding="ascii")

    completed = _run_selected_launcher(tmp_path, arguments=(operation,))

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not (tmp_path / "actions.jsonl").exists()
    if operation == "-Stop":
        assert not registry_path.exists()
        assert "Stopped 0 process(es)" in completed.stdout
    else:
        assert registry_path.exists()
        assert (recorded_root or "unrecorded (legacy launcher)") in completed.stdout


@WINDOWS_ONLY
def test_explicit_empty_artifact_option_does_not_silently_use_the_file(tmp_path: Path) -> None:
    _selection_file(tmp_path, json.dumps({"artifact_root": "artifacts"}))

    completed = _run_selected_launcher(tmp_path, arguments=("-ArtifactRoot", ""))

    assert completed.returncode != 0
    assert "Explicit ArtifactRoot must not be empty" in completed.stderr
    assert not (tmp_path / "actions.jsonl").exists()
