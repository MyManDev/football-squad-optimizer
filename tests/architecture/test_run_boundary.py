"""The product and the operational commands load no laboratory module when they run.

``lint-imports`` proves that the product packages never import the laboratory. It cannot see
``scripts/``: an operational command that imports a helper which imports
``squadopt.experiments`` loads the laboratory into a weekly run and breaks no contract. Five
commands did exactly that through ``scripts/_experiment_cli.py`` until they took their
provenance helpers from ``scripts/_provenance.py``, which imports the standard library only.

So this file checks what a run loads rather than what a module names. One fresh interpreter
imports every product entry point and every ``.py`` row of the "Operational commands" table
in ``scripts/README.md``, then reads ``sys.modules``. The rows are read from the README, so a
command added there is covered without editing this file. If the union loads no laboratory
module, no single one of them does.

A laboratory module is any module of a laboratory package, and also a module of
``squadopt.application`` whose name ends in ``_experiment``. Six such modules hold private
football model experiments inside ``application`` and are imported only by tests
(ARCHITECTURE.md, known violations). The contract that keeps the laboratory out of the
product does not cover them, because they sit in a product package, so the probe reports one
as soon as a product entry point or an operational command loads it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_README = REPOSITORY_ROOT / "scripts" / "README.md"

LABORATORY = (
    "experiments",
    "backtest",
    "bayesopt",
    "recalibration",
    "preflight",
)

#: The modules the probe reports: every module of a laboratory package, and a module of
#: ``application`` whose name ends in ``_experiment``.
LABORATORY_MODULE = re.compile(
    rf"squadopt\.(?:(?:{'|'.join(LABORATORY)})(?:\..+)?|application\.(?:\w+\.)*\w+_experiment)"
)

PRODUCT_ENTRY_POINTS = (
    "squadopt.api.app",
    "squadopt.api.runtime",
    "squadopt.platform.advice_worker",
    "squadopt.platform.weekly_operations",
    "squadopt.platform.weekly_publish",
    "squadopt.platform.cli",
    "squadopt.application",
)

#: Operational rows that are the laboratory's own tools, so loading it is their job.
LABORATORY_TOOLS = {
    "run_artifact_preflight": "validates artifacts with squadopt.preflight",
    "run_measurement_preflight": "validates a docs/ record with squadopt.preflight",
    "run_calendar_recalibration": "recalibrates with squadopt.preflight and squadopt.recalibration",
}

#: The commands that loaded the laboratory through scripts/_experiment_cli.py.
MOVED_TO_PROVENANCE = (
    "build_projection_handoff",
    "export_player_evidence",
    "export_rotation_evidence",
    "export_settled_outcomes",
    "seed_entry_registry",
)

# Imports each named module in order and reports the laboratory modules each one loaded
# first, so a failure names the import that brought the laboratory in. The first argument is
# the pattern of `LABORATORY_MODULE`.
PROBE = """
import importlib, json, re, sys
laboratory = re.compile(sys.argv[1])
seen = set()
loaded_by = {}
for name in sys.argv[2:]:
    importlib.import_module(name)
    new = sorted(
        module
        for module in sys.modules
        if laboratory.fullmatch(module) and module not in seen
    )
    seen.update(new)
    if new:
        loaded_by[name] = new
print(json.dumps(loaded_by))
"""


def operational_commands() -> list[str]:
    """The ``.py`` rows of the README's "Operational commands" table, as script names."""

    text = SCRIPTS_README.read_text(encoding="utf-8")
    section = text.split("\n## Operational commands\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `(\w+)\.py` \|", section, flags=re.MULTILINE)


def test_the_readme_table_names_the_commands_this_file_is_about() -> None:
    """A parser that read no rows would pass the boundary test below while checking nothing."""

    commands = operational_commands()

    assert set(MOVED_TO_PROVENANCE) <= set(commands)
    # An exclusion whose row is gone is an exclusion nobody can review.
    assert set(LABORATORY_TOOLS) <= set(commands)


def _laboratory_loaded_by(modules: list[str]) -> dict[str, list[str]]:
    """Import `modules` in order in a fresh interpreter; the laboratory each loaded first."""

    result = subprocess.run(
        [sys.executable, "-c", PROBE, LABORATORY_MODULE.pattern, *modules],
        cwd=REPOSITORY_ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join((str(REPOSITORY_ROOT / "src"), str(REPOSITORY_ROOT))),
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    loaded_by: dict[str, list[str]] = json.loads(result.stdout.splitlines()[-1])
    return loaded_by


def test_the_probe_reports_a_laboratory_module_that_lives_in_application() -> None:
    """A pattern that matched nothing would pass the boundary test while checking nothing."""

    assert LABORATORY_MODULE.fullmatch("squadopt.experiments")
    assert LABORATORY_MODULE.fullmatch("squadopt.preflight.validator")
    assert LABORATORY_MODULE.fullmatch("squadopt.application.football_unit_experiment")
    assert not LABORATORY_MODULE.fullmatch("squadopt.application")
    assert not LABORATORY_MODULE.fullmatch("squadopt.application.football_live")
    assert not LABORATORY_MODULE.fullmatch("squadopt.live.plan_selection")
    assert not LABORATORY_MODULE.fullmatch("squadopt.experiments_index")

    module = "squadopt.application.football_unit_experiment"
    assert module in _laboratory_loaded_by([module]).get(module, [])


def test_the_product_and_the_operational_commands_load_no_laboratory_module() -> None:
    modules = [
        *PRODUCT_ENTRY_POINTS,
        *(f"scripts.{name}" for name in operational_commands() if name not in LABORATORY_TOOLS),
    ]
    loaded_by = _laboratory_loaded_by(modules)
    assert loaded_by == {}, (
        f"laboratory modules loaded, by the import that loaded them first: {loaded_by}"
    )


def test_the_runners_on_the_experiment_helper_get_the_same_provenance_objects() -> None:
    """The move changed where the helpers live, not what those runners call or write."""

    from scripts import _experiment_cli, _provenance

    for name in (
        "REPOSITORY_ROOT",
        "DEFAULT_ARCHIVE_ROOT",
        "_git_revision",
        "write_json",
        "write_text",
    ):
        assert getattr(_experiment_cli, name) is getattr(_provenance, name), name
