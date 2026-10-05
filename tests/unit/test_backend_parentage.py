"""The backend is never started from an agent application's process tree.

On 2026-10-04 a Microsoft Store update of the Codex app replaced its sandbox service, and
the api and the six workers started from that sandbox the day before died with it. The
launcher (``scripts/run_backend_local.ps1``) and the restart helper
(``scripts/release/restart_backend.ps1``) now refuse to start a backend when an agent
application is among their ancestors (``scripts/backend_parentage.ps1``). These tests run
the real scripts under Windows PowerShell 5.1: the walk on a made-up process table, and the
refusal on this test's own process tree, by naming as the agent the ``python.exe`` that
runs pytest, which is a real ancestor of every PowerShell the tests start.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPOSITORY_ROOT / "scripts" / "backend_parentage.ps1"
LAUNCHER = REPOSITORY_ROOT / "scripts" / "run_backend_local.ps1"
RESTART = REPOSITORY_ROOT / "scripts" / "release" / "restart_backend.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")


#: The variables an agent sets for its shells; whatever ran pytest may have set them.
MARKERS = ("CLAUDECODE", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED", "CODEX_SESSION_ID")


def _powershell(
    *arguments: str, agents: str | None = None, marker: str | None = None
) -> subprocess.CompletedProcess[str]:
    assert POWERSHELL is not None
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in MARKERS and name != "SQUADOPT_AGENT_APPLICATIONS"
    }
    if agents is not None:
        environment["SQUADOPT_AGENT_APPLICATIONS"] = agents
    if marker is not None:
        environment[marker] = "1"
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", *arguments],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=environment,
    )


def _flat(text: str) -> str:
    """An error as a reader sees it: PowerShell wraps it at the console width."""

    return " ".join(text.split())


def _walk(table: str, start: int, agents: str = "claude.exe,codex.exe") -> str:
    """Run Find-AgentAncestor on a made-up process table and print what it finds."""

    script = (
        f". '{HELPER}'\n"
        "function P($id, $parent, $name, $created) {\n"
        "  [pscustomobject]@{ ProcessId = $id; ParentProcessId = $parent; Name = $name;"
        " CreationDate = [datetime]$created }\n"
        "}\n"
        f"$table = @{{}}\n{table}\n"
        f"$found = Find-AgentAncestor -ProcessId {start} -Table $table\n"
        "if ($null -eq $found) { 'none' } else { $found.Name + ' ' + $found.ProcessId }\n"
    )
    completed = _powershell("-Command", script, agents=agents)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_the_walk_finds_an_agent_any_number_of_steps_up_and_ignores_case() -> None:
    table = (
        "$table[10] = P 10 20 'python.exe' '2026-10-05 10:00'\n"
        "$table[20] = P 20 30 'cmd.exe' '2026-10-05 09:00'\n"
        "$table[30] = P 30 40 'Claude.EXE' '2026-10-05 08:00'\n"
        "$table[40] = P 40 1 'explorer.exe' '2026-10-05 07:00'\n"
    )
    assert _walk(table, 10) == "Claude.EXE 30"


def test_the_walk_stops_at_a_reused_pid_a_missing_parent_and_a_cycle() -> None:
    # Pid 30 now belongs to an agent started after its supposed child: Windows reused it.
    reused = (
        "$table[10] = P 10 30 'powershell.exe' '2026-10-05 10:00'\n"
        "$table[30] = P 30 1 'codex.exe' '2026-10-05 11:00'\n"
    )
    assert _walk(reused, 10) == "none"
    missing = "$table[10] = P 10 99 'powershell.exe' '2026-10-05 10:00'\n"
    assert _walk(missing, 10) == "none"
    cycle = (
        "$table[10] = P 10 20 'powershell.exe' '2026-10-05 10:00'\n"
        "$table[20] = P 20 10 'cmd.exe' '2026-10-05 10:00'\n"
    )
    assert _walk(cycle, 10) == "none"


def test_a_plain_console_or_the_watch_task_is_not_an_agent() -> None:
    task = (
        "$table[10] = P 10 20 'powershell.exe' '2026-10-05 10:00'\n"
        "$table[20] = P 20 30 'powershell.exe' '2026-10-05 09:00'\n"
        "$table[30] = P 30 2 'svchost.exe' '2026-09-21 12:15'\n"
    )
    assert _walk(task, 10, agents="claude.exe,codex.exe,codex-windows-sandbox-service.exe") == (
        "none"
    )


def test_the_default_lists_name_the_agents_the_codex_app_and_their_markers() -> None:
    text = HELPER.read_text(encoding="ascii")
    assert (
        "@('claude.exe', 'ChatGPT.exe', 'codex.exe', 'codex-windows-sandbox-service.exe')" in text
    )
    assert "@('" + "', '".join(MARKERS) + "')" in text


def test_the_launcher_refuses_to_start_under_an_agent_and_starts_nothing(tmp_path: Path) -> None:
    store = tmp_path / "store"
    completed = _powershell(
        "-File",
        str(LAUNCHER),
        "-RepoRoot",
        str(tmp_path),
        "-StoreRoot",
        str(store),
        "-Port",
        "18791",
        agents="python.exe",
    )
    assert completed.returncode != 0
    assert "Refusing to start the backend: this runs under python.exe" in _flat(completed.stderr)
    assert not store.exists(), "the refusal must come before anything is written"


@pytest.mark.parametrize("marker", MARKERS)
def test_a_start_detached_from_an_agent_shell_is_refused_by_the_marker_it_inherits(
    tmp_path: Path, marker: str
) -> None:
    # No agent among the ancestors (none is named), as when the shell that started the
    # launcher has exited; the variable the agent set for that shell is still here.
    store = tmp_path / "store"
    completed = _powershell(
        "-File",
        str(LAUNCHER),
        "-RepoRoot",
        str(tmp_path),
        "-StoreRoot",
        str(store),
        agents="no-agent-application.exe",
        marker=marker,
    )
    assert completed.returncode != 0
    assert f"this runs with {marker} set" in _flat(completed.stderr)
    assert not store.exists()


def test_the_launcher_still_stops_and_reports_under_an_agent(tmp_path: Path) -> None:
    for action in ("-Stop", "-Status"):
        completed = _powershell(
            "-File", str(LAUNCHER), "-RepoRoot", str(tmp_path), action, agents="python.exe"
        )
        assert "Refusing to" not in completed.stdout + completed.stderr


def test_the_restart_refuses_under_an_agent_but_a_dry_run_is_not_refused(tmp_path: Path) -> None:
    arguments = ("-File", str(RESTART), "-AcceptedGeneratedAt", "2026-10-02T16:56:19Z")
    real = _powershell(*arguments, "-RepoRoot", str(tmp_path), agents="python.exe")
    assert real.returncode != 0
    refusal = _flat(real.stderr)
    assert "Refusing to restart the backend: this runs under python.exe" in refusal
    # The watch task starts a missing backend; it never replaces a running one.
    assert "Run it from a plain Windows PowerShell window." in refusal
    assert "SquadOptBackendWatch" not in refusal
    dry = _powershell(*arguments, "-RepoRoot", str(tmp_path), "-DryRun", agents="python.exe")
    assert "Refusing to" not in dry.stdout + dry.stderr
