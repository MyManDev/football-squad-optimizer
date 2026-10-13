"""The operator entry points of `platform` answer the way the runbooks call them.

ADR 0011 (decision 8) names the operator entry points that keep working while Phase 3 moves
`platform` into subpackages: `python -m squadopt.platform.weekly_operations` and
`python -m squadopt.platform.advice_worker`; the console script `squadopt`, whose string in
`pyproject.toml` stays `squadopt.platform.cli:main`; `advice_load`, `backup_recovery`,
`benchmark_capture` and `capture_measurement`, run the same way; and
`squadopt.api.runtime:build_app`, the factory `uvicorn --factory` calls. Two more things sit on
that surface: `scripts/release/restart_backend.ps1` imports `squadopt.api.runtime` and
`squadopt.platform.advice_worker` in a fresh interpreter before it stops the running backend,
and `package_fingerprint()` in `weekly_operations` writes a digest of every `.py` file of the
installed package into each run record.

This file characterizes that surface on today's tree, so a move that changes a prog name, a
usage line, the console script's target, the import smoke or the hashed tree fails here:

- each of the seven commands answers `--help` with exit 0 and its usage line in a subprocess
  started the way an operator starts it (`sys.executable -m`, `PYTHONPATH` to this checkout's
  `src`, the checkout as the working directory), and exposes `main(argv=None, ...)` behind a
  `__main__` guard;
- the console script resolves to `squadopt.platform.cli:main`, in `pyproject.toml` and, where
  the package is installed, through `importlib.metadata`;
- the restart smoke imports in a fresh interpreter, `build_app` takes no arguments, and the
  launchers name that factory and the worker module;
- `package_fingerprint()` equals the digest recomputed over `Path(squadopt.__file__).parent`
  by the same rule, so the hashed tree is the whole package.

All seven commands build an `argparse` parser today, so each pins its usage line as well as
its `main`. argparse wraps usage at the terminal width, and the wrap point moved between
Python 3.11 and 3.13 (3.13 fits one more option on the first line), so `COLUMNS` is fixed
at 80 and the first line of the help must start with the pinned prefix. Four other
`platform` modules carry a `__main__` guard (`club_news_acquire`, `cohort_capture`,
`elite_capture` and `weekly_publish`); the runbook reaches them through their `scripts/`
shims and ADR 0011 does not list them, so this file does not read them.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import os
import subprocess
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import squadopt
from squadopt.api import runtime
from squadopt.platform import cli, weekly_operations

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPOSITORY_ROOT / "pyproject.toml"
RESTART_SCRIPT = REPOSITORY_ROOT / "scripts" / "release" / "restart_backend.ps1"
LOCAL_LAUNCHER = REPOSITORY_ROOT / "scripts" / "run_backend_local.ps1"
COMPOSE = REPOSITORY_ROOT / "deploy" / "compose.yaml"

#: The start of the first line each command prints for `--help` at 80 columns: the prog
#: name, which argparse takes from the module's file name unless the parser sets it, as
#: `cli` does, and the options that fit on that line under every supported Python.
USAGE_LINES: dict[str, str] = {
    "cli": "usage: squadopt [-h] {gameweek,season} ...",
    "weekly_operations": (
        "usage: weekly_operations.py [-h] [--workspace WORKSPACE] [--season SEASON]"
    ),
    "advice_worker": "usage: advice_worker.py [-h] [--max-jobs MAX_JOBS]",
    "advice_load": "usage: advice_load.py [-h] --origin ORIGIN --requests REQUESTS",
    "backup_recovery": "usage: backup_recovery.py [-h] {create,verify,restore} ...",
    "benchmark_capture": "usage: benchmark_capture.py [-h] --snapshot-root SNAPSHOT_ROOT",
    "capture_measurement": "usage: capture_measurement.py [-h] --snapshot-root SNAPSHOT_ROOT",
}
COMMANDS = tuple(USAGE_LINES)

#: The console script string in `pyproject.toml`, which ADR 0011 keeps as it is.
CONSOLE_SCRIPT = "squadopt.platform.cli:main"

#: What `restart_backend.ps1` runs on the pulled code before it stops the running backend.
RESTART_SMOKE = "import squadopt.api.runtime, squadopt.platform.advice_worker"

#: The factory uvicorn is told to call, and the worker module the launchers start.
FACTORY = "squadopt.api.runtime:build_app"
WORKER_MODULE = "squadopt.platform.advice_worker"


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the interpreter the way an operator does: from the checkout, on this checkout's src."""

    return subprocess.run(
        [sys.executable, *arguments],
        cwd=REPOSITORY_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(REPOSITORY_ROOT / "src"),
            "PYTHONIOENCODING": "utf-8",
            "COLUMNS": "80",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_answers_help_with_its_usage_line(command: str) -> None:
    result = _run(["-m", f"squadopt.platform.{command}", "--help"])

    assert result.returncode == 0, result.stdout + result.stderr
    first_line = result.stdout.splitlines()[0]
    assert first_line.startswith(USAGE_LINES[command]), first_line


@pytest.mark.parametrize("command", COMMANDS)
def test_each_command_exposes_main_behind_a_main_guard(command: str) -> None:
    """`python -m` and the tests call one function, `main(argv=None, ...)`, for an exit code."""

    module = importlib.import_module(f"squadopt.platform.{command}")

    assert callable(module.main)
    first = next(iter(inspect.signature(module.main).parameters.values()))
    assert (first.name, first.default) == ("argv", None)
    assert 'if __name__ == "__main__":' in inspect.getsource(module)


def test_the_console_script_is_declared_as_the_cli_main() -> None:
    with PYPROJECT.open("rb") as handle:
        project = tomllib.load(handle)["project"]

    assert project["scripts"] == {"squadopt": CONSOLE_SCRIPT}
    module_name, _, attribute = CONSOLE_SCRIPT.partition(":")
    assert getattr(importlib.import_module(module_name), attribute) is cli.main


def test_the_installed_console_script_resolves_through_importlib_metadata() -> None:
    found = metadata.entry_points(group="console_scripts", name="squadopt")
    if not found:
        pytest.skip("the package is not installed in this interpreter: no console script")

    (entry_point,) = found
    assert entry_point.value == CONSOLE_SCRIPT
    assert entry_point.load() is cli.main


def test_the_restart_smoke_imports_in_a_fresh_interpreter() -> None:
    assert RESTART_SMOKE in RESTART_SCRIPT.read_text(encoding="utf-8")

    result = _run(["-c", RESTART_SMOKE])

    assert result.returncode == 0, result.stdout + result.stderr


def test_build_app_is_a_factory_uvicorn_calls_without_arguments() -> None:
    assert "build_app" in runtime.__all__
    assert callable(runtime.build_app)
    assert list(inspect.signature(runtime.build_app).parameters) == []


def test_the_launchers_name_the_factory_and_the_worker_module() -> None:
    for launcher in (LOCAL_LAUNCHER, COMPOSE):
        text = launcher.read_text(encoding="utf-8")

        assert FACTORY in text, launcher
        assert WORKER_MODULE in text, launcher


def _digest_of(package: Path) -> str:
    """Recompute the way `package_fingerprint` does: each `.py` file in order, path and bytes."""

    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def test_the_package_fingerprint_hashes_the_whole_package() -> None:
    package = Path(squadopt.__file__).resolve().parent

    assert weekly_operations.package_fingerprint() == _digest_of(package)
    # The helper tells trees apart, so the equality above fixes which tree is hashed.
    assert _digest_of(package / "platform") != _digest_of(package)
