"""The opt-in host hook, with Docker and privileged operations held at their boundary."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

HOST = Path(__file__).resolve().parents[2] / "deploy/weekly-schedule"
IMAGE = "sha256:" + "a" * 64


@pytest.fixture
def host():
    loader = importlib.machinery.SourceFileLoader(
        "history_host", str(HOST / "squadopt-requested-history")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def running(host):
    return {
        "image": IMAGE,
        "running": True,
        "mounts": [{"Type": "bind", "Source": str(host.STORE), "Destination": "/mnt/store"}],
    }


@pytest.mark.parametrize(
    "damage", ["tag", "stopped", "different_image", "different_store", "volume", "duplicate"]
)
def test_unready_or_different_backend_is_refused_before_a_copy(host, monkeypatch, damage):
    first, second = running(host), running(host)
    if damage == "tag":
        second["image"] = "backend:latest"
    elif damage == "stopped":
        second["running"] = False
    elif damage == "different_image":
        second["image"] = "sha256:" + "b" * 64
    elif damage == "different_store":
        second["mounts"][0]["Source"] = "/another/store"
    elif damage == "volume":
        second["mounts"][0]["Type"] = "volume"
    else:
        second["mounts"] *= 2
    replies = iter((first, second))
    monkeypatch.setattr(host, "command", lambda _: json.dumps(next(replies)))
    with pytest.raises(ValueError):
        host.image()


@pytest.mark.parametrize("failed", [False, True])
def test_host_uses_isolated_nonroot_image_and_cleans_its_own_container(host, monkeypatch, failed):
    calls, cleanup = [], []
    monkeypatch.setattr(host, "require_root", lambda: None)
    monkeypatch.setattr(host, "prepare_output", lambda gid: calls.append(["prepare", gid]))
    monkeypatch.setattr(host, "capacity", lambda: calls.append(["capacity"]))

    def invoke(arguments):
        calls.append(arguments)
        if arguments[0] == "systemctl":
            return "{ argv[]=/usr/bin/python -m squadopt.platform.weekly_schedule ; }"
        if arguments[0] == "id":
            return "1000"
        if arguments[1] == "inspect":
            return json.dumps(running(host))
        if failed:
            raise subprocess.TimeoutExpired(arguments, 300)
        return "{}"

    monkeypatch.setattr(host, "command", invoke)
    monkeypatch.setattr(host.subprocess, "run", lambda args, **kw: cleanup.append(args))
    assert host.main() == int(failed)
    (copy,) = [call for call in calls if call[:2] == ["docker", "run"]]
    assert copy[copy.index("--user") + 1] == "10001:1000"
    assert copy[copy.index(IMAGE) + 1 :][:3] == [
        "python",
        "-m",
        "squadopt.platform.requested_history_snapshot",
    ]
    for flag in (
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--pull=never",
        "--reuse-unchanged",
    ):
        assert flag in copy
    assert copy.count("--mount") == 2
    assert all("--privileged" not in arg for arg in copy)
    name = copy[copy.index("--name") + 1]
    assert cleanup == [["/usr/bin/docker", "rm", "--force", name]]
    assert calls.index(["capacity"]) < calls.index(copy)


def test_privileged_command_ignores_checkout_python_and_ambient_docker_settings(host, monkeypatch):
    calls = []
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.invalid:1234")
    monkeypatch.setenv("PYTHONPATH", "/user/writable/checkout")

    def invoke(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="1000")

    monkeypatch.setattr(host.subprocess, "run", invoke)
    assert host.command(["id", "-g", "squadopt"]) == "1000"
    assert calls[0][0] == ["/usr/bin/id", "-g", "squadopt"]
    assert calls[0][1]["env"]["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert "PYTHONPATH" not in calls[0][1]["env"]
    assert (HOST / "squadopt-requested-history").read_text().splitlines()[
        0
    ] == "#!/usr/bin/python3 -I"


@pytest.mark.parametrize("group", ["0", "-1", "1000\n0", "root"])
def test_invalid_service_group_never_reaches_docker(host, monkeypatch, group):
    calls = []
    monkeypatch.setattr(host, "require_root", lambda: None)
    monkeypatch.setattr(
        host,
        "command",
        lambda args: calls.append(args) or ("weekly" if args[0] == "systemctl" else group),
    )
    assert host.main() == 1
    assert [call[0] for call in calls] == ["systemctl", "id"]


def test_actual_systemd_dry_run_command_never_copies_or_inspects_the_backend(host, monkeypatch):
    calls = []
    monkeypatch.setattr(host, "require_root", lambda: None)
    monkeypatch.setattr(
        host,
        "command",
        lambda args: calls.append(args) or "{ argv[]=/usr/bin/python -m gate --dry-run ; }",
    )
    assert host.main() == 0
    assert [call[0] for call in calls] == ["systemctl"]


@pytest.mark.parametrize("used,free,accepted", [(1, 100, True), (16, 100, False), (1, 4, False)])
def test_capacity_refuses_without_removing_existing_history(
    host, tmp_path, monkeypatch, used, free, accepted
):
    held = tmp_path / "retained.json"
    held.write_bytes(b"x" * used)
    monkeypatch.setattr(host, "OUTPUT", tmp_path)
    monkeypatch.setattr(host, "SNAPSHOT_BYTES", 2)
    monkeypatch.setattr(host, "RESERVE_BYTES", 1)
    monkeypatch.setattr(host, "TOTAL_BYTES", 20)
    monkeypatch.setattr(host.shutil, "disk_usage", lambda _: SimpleNamespace(free=free))
    if accepted:
        host.capacity()
    else:
        with pytest.raises(ValueError, match="capacity"):
            host.capacity()
    assert held.read_bytes() == b"x" * used


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink fixture")
def test_capacity_does_not_follow_links(host, tmp_path, monkeypatch):
    output = tmp_path / "history"
    output.mkdir()
    (output / "escape").symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(host, "OUTPUT", output)
    with pytest.raises(ValueError, match="linked"):
        host.capacity()


def test_pre_run_hook_is_opt_in_and_does_not_change_the_weekly_command():
    dropin = (HOST / "requested-history.conf").read_text(encoding="utf-8")
    assert "ExecStartPre=+/usr/local/sbin/squadopt-requested-history" in dropin
    assert (
        "Environment=SQUADOPT_REQUESTED_HISTORY_STORE=/var/lib/squadopt/requested-history/latest.json"
        in dropin
    )
    assert "\nExecStart=" not in dropin
    assert "requested-history.conf" not in (HOST / "provision.sh").read_text(encoding="utf-8")
