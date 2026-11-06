"""The advice backend's side of the weekly schedule's host, read as text and run where it can be.

`deploy/weekly-schedule/backend.sh` sets the backend up as root beside the weekly run: Docker
and cloudflared, the layout `scripts/release/vm_football_release.py` keeps under `~/squadopt`,
the tunnel's unit and `squadopt-receive`. It cannot run here, so these tests hold what can be
held without the host: it parses, refuses a user who is not root before anything else, checks
before each step that changes the host, writes no secret, and names the paths the readiness
report and the unit name. The tunnel's configuration has exactly the rules of the Windows
example. `squadopt-receive` runs for real on a scratch checkout as this user: it takes data/
and artifacts/, refuses an archive with anything else and takes nothing then.
"""

from __future__ import annotations

import getpass
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_FILES = ROOT / "deploy" / "weekly-schedule"
BACKEND = HOST_FILES / "backend.sh"
RECEIVE = HOST_FILES / "squadopt-receive"
CHECK = HOST_FILES / "check_host.sh"
UNIT = HOST_FILES / "cloudflared-squadopt.service"
TUNNEL = HOST_FILES / "cloudflared.example.yml"
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    BASH is None or sys.platform == "win32", reason="the host scripts run under a POSIX bash"
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> list[str]:
    return [line for line in _text(path).splitlines() if not line.lstrip().startswith("#")]


def _readonly(path: Path) -> dict[str, str]:
    pairs = re.findall(r"^readonly ([A-Z_]+)=([^\s(]+)$", _text(path), flags=re.MULTILINE)
    return {name: value.strip('"') for name, value in pairs}


@needs_bash
@pytest.mark.parametrize("script", [BACKEND, RECEIVE], ids=lambda path: path.name)
def test_both_scripts_parse_and_stop_at_the_first_failure(script: Path) -> None:
    parsed = subprocess.run([BASH or "bash", "-n", str(script)], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
    lines = _text(script).splitlines()
    assert lines[0] == "#!/usr/bin/env bash"
    assert "set -euo pipefail" in lines


@needs_bash
@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="as root it would set this machine up"
)
def test_the_setup_refuses_a_user_who_is_not_root_before_anything_else() -> None:
    refused = subprocess.run(
        [BASH or "bash", str(BACKEND)],
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert (refused.returncode, refused.stderr.strip(), refused.stdout) == (
        1,
        "Refused: run as root: bash backend.sh",
        "",
    )


def test_preflight_comes_before_the_first_step_that_changes_the_host() -> None:
    main = _text(BACKEND).split("main() {", 1)[1].split("}", 1)[0].split()
    assert main == [
        "preflight",
        "cd",
        "/",
        "docker_engine",
        "cloudflared_package",
        "release_layout",
        "tunnel_unit",
        "receive_command",
        "follow_releases",
        "steps_left",
    ]


#: Each step that changes the host, and the check it makes first, so that a second run of the
#: script changes nothing the first one set up and never replaces what a release wrote.
GUARDED = [
    ('if [ ! -s "$KEYRINGS/docker.asc" ]; then', "https://download.docker.com/linux/ubuntu/gpg"),
    ('if [ ! -s "$KEYRINGS/cloudflare-main.gpg" ]; then', "https://pkg.cloudflare.com/"),
    ("if [ ! -e /etc/docker/daemon.json ]; then", "json-file"),
    ('if [ ! -d "$BASE/repo/.git" ]; then', 'git clone -q "$REPOSITORY" "$BASE/repo"'),
    ('if [ ! -e "$BASE/.env" ]; then', 'write_if_changed "$BASE/.env" 0600'),
    ('if [ ! -e "$BASE/compose.artifacts.yaml" ]; then', "services: {}"),
    ('if [ -s "$TUNNEL_CONFIG" ]; then', 'systemctl enable --now "$TUNNEL_UNIT"'),
]


@pytest.mark.parametrize("guard,step", GUARDED, ids=[step for _, step in GUARDED])
def test_each_step_that_changes_the_host_checks_first(guard: str, step: str) -> None:
    lines = _code(BACKEND)
    (at,) = [index for index, line in enumerate(lines) if guard in line]
    assert any(step in line for line in lines[at : at + 5]), (guard, lines[at : at + 5])


def test_nothing_starts_the_backend_and_nothing_is_appended() -> None:
    code = "\n".join(_code(BACKEND))
    assert "docker compose up" not in code and " up -d" not in code
    # The release and the cutover are a person's: the steps only name them at the end.
    steps = code.split("steps_left()", 1)[0]
    assert "vm_football_release" not in steps and "route dns" not in steps
    assert ">>" not in code


SECRETS = [
    re.compile(r"-----BEGIN"),
    re.compile(r"--token\b|tunnel token|cert\.pem"),
    re.compile(r"^\s*(export\s+)?[A-Z_]*(KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*=\S", re.MULTILINE),
]


@pytest.mark.parametrize("path", [BACKEND, RECEIVE, UNIT, TUNNEL], ids=lambda path: path.name)
def test_no_file_holds_or_handles_a_secret(path: Path) -> None:
    code = "\n".join(_code(path))
    assert [pattern.pattern for pattern in SECRETS if pattern.search(code)] == []


def test_the_environment_file_keeps_the_origins_and_ports_of_the_example() -> None:
    template = _text(BACKEND).split('write_if_changed "$BASE/.env" 0600 <<ENV', 1)[1]
    body = template.split("\n", 1)[1].split("\nENV\n", 1)[0].splitlines()
    keys = [line.split("=", 1)[0] for line in body]
    assert keys == [
        "SQUADOPT_BACKEND_IMAGE",
        "SQUADOPT_BACKEND_ALLOWED_ORIGINS",
        "SQUADOPT_STORE_PATH",
        "SQUADOPT_SITE_PATH",
        "SQUADOPT_SNAPSHOT_PATH",
        "SQUADOPT_HANDOFF_PATH",
        "SQUADOPT_API_PORT",
        "SQUADOPT_WORKER_METRICS_PORT",
    ]
    example = dict(
        line.split("=", 1)
        for line in _text(ROOT / "deploy" / "backend.env.example").splitlines()
        if "=" in line and not line.startswith("#")
    )
    assert _readonly(BACKEND)["ORIGINS"] == example["SQUADOPT_BACKEND_ALLOWED_ORIGINS"]
    assert "SQUADOPT_API_PORT=8000" in body and "SQUADOPT_WORKER_METRICS_PORT=9091" in body
    # The image's own user owns the store (Dockerfile).
    assert "--uid 10001" in _text(ROOT / "Dockerfile")
    assert _readonly(BACKEND)["CONTAINER_UID"] == "10001"


def test_the_setup_the_report_and_the_unit_name_one_layout() -> None:
    backend, check = _readonly(BACKEND), _readonly(CHECK)
    assert backend["BASE"] == check["BACKEND"] == "/root/squadopt"
    for name in ("TUNNEL_CONFIG", "TUNNEL_UNIT", "RECEIVE"):
        assert backend[name] == check[name], name
    assert backend["TUNNEL_UNIT"] == UNIT.name
    (start,) = [line for line in _text(UNIT).splitlines() if line.startswith("ExecStart=")]
    assert f"--config {backend['TUNNEL_CONFIG']} tunnel run" in start
    assert "--no-autoupdate" in start


def _ingress(path: Path) -> list[str]:
    after = _text(path).split("\ningress:\n", 1)[1]
    return [
        line.strip()
        for line in after.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_tunnel_has_exactly_the_rules_of_the_windows_example() -> None:
    windows = ROOT / "deploy" / "cloudflared" / "config.example.yml"
    assert _ingress(TUNNEL) == _ingress(windows)
    rules = _ingress(TUNNEL)
    assert rules[1] == r"path: ^/(metrics|docs|redoc|openapi\.json)"
    assert rules[2] == "service: http_status:404"
    assert rules[4] == "service: http://127.0.0.1:8000"
    assert rules[-1] == "- service: http_status:404"
    assert "credentials-file: /root/.cloudflared/<TUNNEL-UUID>.json" in _text(TUNNEL)


def _archive(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            bundle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _receive(tmp_path: Path, archive: bytes) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [BASH or "bash", str(RECEIVE)],
        input=archive,
        env={
            "PATH": os.environ.get("PATH", ""),
            "SQUADOPT_WEEKLY": str(tmp_path / "srv" / "weekly"),
            "SQUADOPT_SERVICE_USER": getpass.getuser(),
        },
        capture_output=True,
        timeout=60,
        check=False,
    )


needs_rsync = pytest.mark.skipif(
    shutil.which("rsync") is None, reason="squadopt-receive uses rsync"
)


@needs_bash
@needs_rsync
def test_the_stores_are_taken_into_the_checkout_and_kept_private(tmp_path: Path) -> None:
    weekly = tmp_path / "srv" / "weekly"
    (weekly / ".git").mkdir(parents=True)
    (weekly / "data" / "snapshots" / "old").mkdir(parents=True)
    (weekly / "data" / "snapshots" / "old" / "kept.json").write_text("{}", encoding="utf-8")
    taken = _receive(
        tmp_path,
        _archive(
            {
                "data/snapshots/fpl-live-1/bootstrap.json": b"{}",
                "artifacts/phase_b/evidence.csv": b"a,b\n",
            }
        ),
    )
    assert taken.returncode == 0, taken.stderr
    assert (weekly / "data" / "snapshots" / "fpl-live-1" / "bootstrap.json").read_bytes() == b"{}"
    assert (weekly / "data" / "snapshots" / "old" / "kept.json").exists()  # nothing deleted
    assert (weekly / "artifacts" / "phase_b" / "evidence.csv").stat().st_mode & 0o077 == 0
    assert (weekly / "data").stat().st_mode & 0o777 == 0o700
    assert list((tmp_path / "srv").glob("incoming.*")) == []


@needs_bash
@needs_rsync
def test_an_archive_with_anything_else_is_refused_and_nothing_is_taken(tmp_path: Path) -> None:
    weekly = tmp_path / "srv" / "weekly"
    (weekly / ".git").mkdir(parents=True)
    refused = _receive(
        tmp_path, _archive({"data/snapshots/x.json": b"{}", "etc/passwd": b"root:x:0:0\n"})
    )
    assert refused.returncode == 1
    assert refused.stderr.decode().strip() == (
        "Refused: the archive holds etc; only data/ and artifacts/ are taken"
    )
    assert not (weekly / "data").exists() and not (weekly / "etc").exists()
    assert list((tmp_path / "srv").glob("incoming.*")) == []


@needs_bash
def test_a_host_without_the_weekly_checkout_is_refused(tmp_path: Path) -> None:
    refused = _receive(tmp_path, _archive({"data/x.json": b"{}"}))
    assert refused.returncode == 1
    assert refused.stderr.decode().strip() == (
        f"Refused: no weekly checkout at {tmp_path / 'srv' / 'weekly'}"
    )


def test_the_new_files_hold_no_long_dash() -> None:
    for path in (BACKEND, RECEIVE, UNIT, TUNNEL):
        assert not {chr(0x2013), chr(0x2014)} & set(_text(path)), path
