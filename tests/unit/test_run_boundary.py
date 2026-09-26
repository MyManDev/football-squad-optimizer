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
    "risk",
    "uncertainty",
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
# first, so a failure names the import that brought the laboratory in.
PROBE = """
import importlib, json, sys
laboratory = set(sys.argv[1].split(","))
seen = set()
loaded_by = {}
for name in sys.argv[2:]:
    importlib.import_module(name)
    new = sorted(
        module
        for module in sys.modules
        if module.startswith("squadopt.")
        and module.split(".")[1] in laboratory
        and module not in seen
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


def test_the_product_and_the_operational_commands_load_no_laboratory_module() -> None:
    modules = [
        *PRODUCT_ENTRY_POINTS,
        *(f"scripts.{name}" for name in operational_commands() if name not in LABORATORY_TOOLS),
    ]
    result = subprocess.run(
        [sys.executable, "-c", PROBE, ",".join(LABORATORY), *modules],
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
    loaded_by = json.loads(result.stdout.splitlines()[-1])
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
