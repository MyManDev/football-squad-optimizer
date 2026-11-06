"""The ordinary sync must not report success over a separately mounted release."""

import copy
import json
import os
import shutil
import subprocess
import sys
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
    with pytest.raises(ValueError, match="separately prepared package"):
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
        calls.append((arguments, kwargs.get("cwd")))
        document = config if arguments[1] == "compose" else containers
        return subprocess.CompletedProcess(arguments, 0, stdout=json.dumps(document), stderr="")

    monkeypatch.setattr(Path, "home", lambda: base.parent)
    monkeypatch.setattr(subprocess, "run", run)
    assert guard.main() == 0
    assert calls == [
        (
            [
                "docker",
                "compose",
                "--env-file",
                str(base / ".env"),
                "-f",
                "deploy/compose.yaml",
                "-f",
                str(base / "compose.artifacts.yaml"),
                "config",
                "--format",
                "json",
            ],
            base / "repo",
        ),
        (["docker", "inspect", "squadopt-api-1", "squadopt-worker-1"], None),
    ]
    assert "never-disclose" not in capsys.readouterr().out


SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
TAG = "site-2026-27-gw08-decision"

#: A stub line that appends `command<TAB>physical working directory<TAB>arguments` to
#: $CALL_LOG. The subshell keeps the tab separator out of the rest of the stub.
LOG_CALL = (
    '( IFS=$\'\\t\'; printf \'%s\\t%s\\t%s\\n\' "${0##*/}" "$(pwd -P)" "$*" ) >> "$CALL_LOG"\n'
)


def _bash() -> str:
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    bash = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the VM shell entry points.")
    return bash


def _stubs(tmp_path: Path, programs: dict[str, str]) -> Path:
    """Write each command as a Bash stub in a new directory that goes first on PATH."""
    binary = tmp_path / "bin"
    binary.mkdir()
    for command, body in programs.items():
        program = binary / command
        program.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        program.chmod(0o755)
    return binary


def _run(
    script: Path, home: Path, binary: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _bash(),
            "-c",
            'export PATH="$(cd "$VM_TEST_BIN" && pwd -P):$PATH"; exec bash "$@"',
            "vm-sync-test",
            script.as_posix(),
            TAG,
        ],
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": str(binary) + os.pathsep + os.environ["PATH"],
            "VM_TEST_BIN": binary.as_posix(),
            **environment,
        },
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def _calls(log: Path) -> list[tuple[str, str, list[str]]]:
    calls = []
    for line in log.read_text(encoding="utf-8").splitlines():
        command, directory, *arguments = line.split("\t")
        calls.append((command, directory, arguments))
    return calls


@pytest.mark.parametrize("script", ("vm_push.sh", "vm_sync.sh"))
def test_refused_preflight_stops_shell_before_transfer_or_checkout(
    tmp_path: Path, script: str
) -> None:
    _bash()
    staging = tmp_path / "checkout"
    (staging / "scripts/release").mkdir(parents=True)
    shutil.copy2(SCRIPTS / script, staging / "scripts" / script)
    shutil.copy2(
        SCRIPTS / "release/check_vm_layout.py", staging / "scripts/release/check_vm_layout.py"
    )
    binary = _stubs(
        tmp_path,
        {
            command: (
                "exit 19\n"
                if command in ("ssh", "python3")
                else 'printf forbidden > "$MUTATION_MARKER"\nexit 0\n'
            )
            for command in ("ssh", "python3", "scp", "tar", "git", "rsync", "docker")
        },
    )
    marker = tmp_path / "mutation"
    result = _run(
        staging / "scripts" / script,
        tmp_path,
        binary,
        MUTATION_MARKER=str(marker),
        SQUADOPT_VM_KEY=str(tmp_path / "key with spaces"),
        SQUADOPT_VM_HOST="unused.example",
    )
    assert result.returncode == 19, result.stderr
    assert not marker.exists()


def test_target_release_refusal_stops_vm_sync_after_its_checkout(tmp_path: Path) -> None:
    """The second preflight reads the checked-out release; its refusal must stop the rest."""
    _bash()
    log = tmp_path / "calls.log"
    binary = _stubs(
        tmp_path,
        {
            # Passes its first call and refuses its second, with an exit code of its own.
            "python3": LOG_CALL + '[ ! -e "$FIRST_PASSED" ] || exit 23\n: > "$FIRST_PASSED"\n',
            "git": LOG_CALL + '[ "${3:-}" != rev-parse ] || echo ' + "0" * 40 + "\n",
            **{command: LOG_CALL for command in ("rsync", "docker", "sed", "curl")},
        },
    )
    result = _run(
        SCRIPTS / "vm_sync.sh",
        tmp_path,
        binary,
        CALL_LOG=str(log),
        FIRST_PASSED=str(tmp_path / "first-preflight-passed"),
    )
    assert result.returncode == 23, result.stderr
    calls = _calls(log)
    # Checkout ran; rsync, the image build, the .env edit and the Compose restart did not.
    assert [command for command, _, _ in calls] == ["python3", "git", "git", "git", "python3"]
    assert calls[2][2][2:] == ["checkout", "-q", TAG]
    for _, _, arguments in (calls[0], calls[4]):
        assert arguments[-1].endswith("/vm_check_layout.py")


@pytest.mark.skipif(
    os.name == "nt", reason="The preflight starts docker natively; the stub is a Bash script."
)
def test_vm_sync_preflight_resolves_compose_exactly_as_its_restart(
    layout: Any, tmp_path: Path
) -> None:
    """Both preflights read Compose from the restart's directory with the restart's arguments."""
    _bash()
    config, containers, base = layout
    (base / "repo").mkdir()
    (base / ".env").write_text("SQUADOPT_BACKEND_IMAGE=squadopt-backend:old\n", encoding="utf-8")
    shutil.copy2(SCRIPTS / "release/check_vm_layout.py", tmp_path / "vm_check_layout.py")
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (documents / "inspect.json").write_text(json.dumps(containers), encoding="utf-8")
    capabilities = json.dumps(
        {"capture_snapshot_id": "fpl-live-test", "top100": False, "managers_word": False}
    )
    log = tmp_path / "calls.log"
    binary = _stubs(
        tmp_path,
        {
            # The real preflight runs, and its docker calls reach the stub below.
            "python3": LOG_CALL + 'exec "$REAL_PYTHON" "$@"\n',
            "docker": LOG_CALL
            + 'if [ "$1" = inspect ]; then cat "$DOCUMENTS/inspect.json"; fi\n'
            + 'if [ "$1" = compose ] && [ "${@: -3:1}" = config ]; then\n'
            + '  cat "$DOCUMENTS/config.json"\n'
            + "fi\n",
            "git": LOG_CALL + '[ "${3:-}" != rev-parse ] || echo ' + "0" * 40 + "\n",
            "rsync": LOG_CALL,
            "sed": LOG_CALL,
            "curl": LOG_CALL
            + 'case "$*" in\n'
            + "  *' -w '*) printf 200 ;;\n"
            + f"  */capabilities) printf '%s' '{capabilities}' ;;\n"
            + "  *) printf '{}' ;;\n"
            + "esac\n",
        },
    )
    result = _run(
        SCRIPTS / "vm_sync.sh",
        base.parent,
        binary,
        CALL_LOG=str(log),
        DOCUMENTS=str(documents),
        REAL_PYTHON=sys.executable,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "capture fpl-live-test" in result.stdout
    assert "never-disclose" not in result.stdout + result.stderr
    calls = _calls(log)
    commands = [command for command, _, _ in calls]
    assert commands[:13] == [
        *("python3", "docker", "docker"),
        *("git", "git", "git"),
        *("python3", "docker", "docker"),
        *("rsync", "docker", "sed", "docker"),
    ]
    # The last curl and python3 share a pipeline, so either may log first.
    assert sorted(commands[13:]) == ["curl", "curl", "curl", "python3"]
    checks = [call for call in calls if call[0] == "docker" and call[2][-3:-2] == ["config"]]
    restarts = [call for call in calls if call[0] == "docker" and call[2][-2:] == ["up", "-d"]]
    assert len(checks) == 2
    assert len(restarts) == 1
    _, restart_directory, restart_arguments = restarts[0]
    assert restart_directory == str((base / "repo").resolve())
    assert restart_arguments[0] == "compose"
    for _, directory, arguments in checks:
        assert directory == restart_directory
        assert arguments[:-3] == restart_arguments[:-2]
        assert arguments[-3:] == ["config", "--format", "json"]
