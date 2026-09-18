"""The native Windows launcher and the tunnel example say what the code says.

Neither file can be executed here: one is PowerShell for a Windows machine, the other is
read by a binary this repository does not install. What can be held is the part of each
that is a copy of a fact kept elsewhere, because copies drift: the CORS allowlist, the
environment variable names the composition root reads, the interpreter the script has to
parse under, and the one rule in the tunnel that must come before the rule it guards.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from squadopt.platform.backend_runtime import SITE_ORIGINS

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPOSITORY_ROOT / "scripts" / "run_backend_local.ps1"
LOGON = REPOSITORY_ROOT / "scripts" / "start_backend_at_logon.ps1"
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


@pytest.mark.parametrize("path", [LAUNCHER, LOGON], ids=["launcher", "logon"])
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
