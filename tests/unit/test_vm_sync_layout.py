"""The ordinary sync must not report success over a separately mounted release."""

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts.release import check_vm_layout as guard


@pytest.fixture
def layout(tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    base = tmp_path / "squadopt"
    base.mkdir()
    roots = ("site", "snapshots", "handoffs", "artifacts")
    for name in roots:
        (base / name).mkdir()
    environment = {
        "SQUADOPT_BACKEND_SITE_DATA_ROOT": "/mnt/site",
        "SQUADOPT_BACKEND_SNAPSHOT_ROOT": "/mnt/snapshots",
        "SQUADOPT_BACKEND_HANDOFF_ROOT": "/mnt/handoffs",
        "SQUADOPT_BACKEND_ARTIFACT_ROOT": "/mnt/artifacts",
        "SENTINEL": "never-disclose-this-value",
    }
    config = {"services": {}}
    containers = []
    for service in ("api", "worker"):
        config["services"][service] = {
            "environment": environment.copy(),
            "volumes": [
                {
                    "type": "bind",
                    "source": str(base / name),
                    "target": f"/mnt/{name}",
                    "read_only": True,
                }
                for name in roots
            ],
        }
        containers.append(
            {
                "Config": {
                    "Labels": {"com.docker.compose.service": service},
                    "Env": [f"{key}={value}" for key, value in environment.items()],
                },
                "Mounts": [
                    {
                        "Type": "bind",
                        "Source": str(base / name),
                        "Destination": f"/mnt/{name}",
                        "RW": False,
                    }
                    for name in roots
                ],
            }
        )
    return config, containers, base


def test_matching_ordinary_layout_passes_without_changing_documents(layout: Any) -> None:
    original = copy.deepcopy(layout)
    guard.check_layout(*layout)
    assert layout == original


@pytest.mark.parametrize("service", (0, 1))
@pytest.mark.parametrize("root", range(4))
@pytest.mark.parametrize("configured", (False, True))
def test_any_retained_mount_refuses(layout: Any, service: int, root: int, configured: bool) -> None:
    config, containers, base = layout
    if configured:
        config["services"][("api", "worker")[service]]["volumes"][root]["source"] = str(
            base / "releases/gw07/payload"
        )
    else:
        containers[service]["Mounts"][root]["Source"] = str(base / "releases/gw07/payload")
    with pytest.raises(ValueError, match="complete release package"):
        guard.check_layout(*layout)


@pytest.mark.parametrize("configured", (False, True))
def test_runtime_root_must_name_the_checked_mount(layout: Any, configured: bool) -> None:
    config, containers, _ = layout
    if configured:
        config["services"]["worker"]["environment"]["SQUADOPT_BACKEND_ARTIFACT_ROOT"] = "/old"
    else:
        containers[0]["Config"]["Env"] = [
            item.replace("=/mnt/artifacts", "=/old") for item in containers[0]["Config"]["Env"]
        ]
    with pytest.raises(ValueError, match="runtime data root differs"):
        guard.check_layout(*layout)


@pytest.mark.parametrize("kind", ("missing", "duplicate", "writable", "nonbind"))
def test_incomplete_or_unsafe_mounts_refuse(layout: Any, kind: str) -> None:
    _, containers, _ = layout
    mounts = containers[1]["Mounts"]
    if kind == "missing":
        mounts.pop()
    elif kind == "duplicate":
        mounts.append(copy.deepcopy(mounts[0]))
    elif kind == "writable":
        mounts[0]["RW"] = True
    else:
        mounts[0]["Type"] = "volume"
    with pytest.raises(ValueError):
        guard.check_layout(*layout)


def test_a_missing_service_refuses(layout: Any) -> None:
    layout[1].pop()
    with pytest.raises(ValueError, match="both existing backend containers"):
        guard.check_layout(*layout)


def test_a_symlinked_destination_refuses(layout: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    selected = layout[2] / "artifacts"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == selected or original(path))
    with pytest.raises(ValueError, match="not symlinks"):
        guard.check_layout(*layout)


@pytest.mark.parametrize("bad_output", ("secret-value-not-json", '{"services": null}', "[]"))
def test_unreadable_layout_does_not_echo_command_output(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], bad_output: str
) -> None:
    calls = []

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout=bad_output, stderr="secret-value")

    monkeypatch.setattr(subprocess, "run", run)
    assert guard.main() == 1
    output = capsys.readouterr().out
    assert "secret-value" not in output
    assert all(command[1] in ("compose", "inspect") for command in calls)


def test_cli_reads_only_compose_and_inspect_and_emits_no_environment(
    layout: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config, containers, base = layout
    calls = []

    def run(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        document = config if arguments[1] == "compose" else containers
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(document), stderr="")

    monkeypatch.setattr(Path, "home", lambda: base.parent)
    monkeypatch.setattr(subprocess, "run", run)
    assert guard.main() == 0
    assert len(calls) == 2
    assert calls[0][-3:] == ["config", "--format", "json"]
    assert calls[1] == ["docker", "inspect", "squadopt-api-1", "squadopt-worker-1"]
    assert "never-disclose" not in capsys.readouterr().out


@pytest.mark.parametrize("script", ("vm_push.sh", "vm_sync.sh"))
def test_refused_preflight_stops_shell_before_transfer_or_checkout(
    tmp_path: Path, script: str
) -> None:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the VM shell entry points.")
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    staging = tmp_path / "checkout"
    (staging / "scripts/release").mkdir(parents=True)
    shutil.copy2(scripts / script, staging / "scripts" / script)
    shutil.copy2(
        scripts / "release/check_vm_layout.py", staging / "scripts/release/check_vm_layout.py"
    )
    binary = tmp_path / "bin"
    binary.mkdir()
    for command in ("ssh", "python3", "scp", "tar", "git", "rsync", "docker"):
        failure = command in ("ssh", "python3")
        program = binary / command
        program.write_text(
            "#!/usr/bin/env bash\n"
            + ("exit 19\n" if failure else 'printf forbidden > "$MUTATION_MARKER"\nexit 0\n'),
            encoding="utf-8",
        )
        program.chmod(0o755)
    marker = tmp_path / "mutation"
    environment = {
        **os.environ,
        "HOME": str(tmp_path),
        "PATH": str(binary) + os.pathsep + os.environ["PATH"],
        "VM_TEST_BIN": binary.as_posix(),
        "MUTATION_MARKER": str(marker),
        "SQUADOPT_VM_KEY": str(tmp_path / "key with spaces"),
        "SQUADOPT_VM_HOST": "unused.example",
    }
    result = subprocess.run(
        [
            bash,
            "-c",
            'export PATH="$(cd "$VM_TEST_BIN" && pwd -P):$PATH"; exec bash "$@"',
            "vm-sync-test",
            (staging / "scripts" / script).as_posix(),
            "site-2026-27-gw08-decision",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 19, result.stderr
    assert not marker.exists()
