"""The path-noise diagnostic of the held free transfer's value, and the owner's level 1.2.

    python -m scripts.diagnose_component_banked_transfer_value --walk-owner-level 2022-23 \
        --handoff-dir <component handoff>
    python -m scripts.diagnose_component_banked_transfer_value --read

Declared in ``docs/research/component_banked_transfer_value_path_diagnostic.md`` after the
pre-registered record was read. The budget 6 and 10 chains are walked by
``scripts.measure_component_banked_transfer_value`` with ``--deterministic-time-limit`` and
``--json-output artifacts/component_banked_transfer_value/budget<B>/<season>.json``.
``--walk-owner-level`` walks the owner's banked value 1.2 on the primary cell at budgets 6, 8
and 10 for one season. ``--read`` writes
``docs/research/component_banked_transfer_value_path_diagnostic.json``. Measurement only.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    measurement_optimization_config,
    repository_provenance,
    write_json,
)
from scripts.measure_component_banked_transfer_value import run_arms

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.component_banked_transfer_value import (
    POLICY_BANKED_VALUE,
    PRIMARY_CELL,
    arm_label,
    build_arms,
)
from squadopt.experiments.component_chain import load_component_chain_inputs
from squadopt.experiments.component_hit_margin import gate
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    chain_comparison,
    season_fixture_counts,
)

ROOT = REPOSITORY_ROOT / "artifacts" / "component_banked_transfer_value"
RECORD = (
    REPOSITORY_ROOT / "docs" / "research" / "component_banked_transfer_value_path_diagnostic.json"
)
OWNER_LEVEL = 1.2
BUDGETS = (6.0, 8.0, 10.0)
CELL_NAME = "_".join(PRIMARY_CELL)


def _walk_owner_level(season: str, archive: Path, handoff_dir: Path) -> int:
    panel = build_panel(archive)
    inputs = load_component_chain_inputs(handoff_dir, panel)
    counts = season_fixture_counts(archive, season)
    records: list[dict[str, object]] = []
    for budget in BUDGETS:
        config = replace(
            measurement_optimization_config(),
            solver_time_limit_seconds=max(60.0, 6.0 * budget),
            solver_deterministic_time_limit=budget,
        )
        arms = build_arms(season, *PRIMARY_CELL, config, levels=(OWNER_LEVEL,))
        for record in run_arms(panel, counts, arms, inputs.projections[season]):
            record["budget"] = budget
            records.append(record)
    output = ROOT / "owner_level" / f"{season}.json"
    write_json(output, {"season": season, "provenance": repository_provenance(), "chains": records})
    print(f"Wrote {output}")
    return 0


def _chains(budget: float) -> list[dict[str, object]]:
    seasons = DEFAULT_DEVELOPMENT_SEASONS
    files = (
        [ROOT / f"{s}-{CELL_NAME}.json" for s in seasons]
        if budget == 8.0
        else [ROOT / f"budget{budget:g}" / f"{s}.json" for s in seasons]
    )
    chains: list[dict[str, object]] = []
    for path in files:
        chains.extend(json.loads(path.read_text(encoding="utf-8"))["chains"])
    for path in sorted((ROOT / "owner_level").glob("*.json")):
        for chain in json.loads(path.read_text(encoding="utf-8"))["chains"]:
            if float(chain["budget"]) == budget:
                chains.append(chain)
    return chains


def _read() -> int:
    baseline = arm_label(*PRIMARY_CELL, POLICY_BANKED_VALUE)
    by_budget = {budget: _chains(budget) for budget in BUDGETS}
    net = {
        budget: {(c["season"], c["variant"]): float(str(c["net_points"])) for c in chains}
        for budget, chains in by_budget.items()
    }
    floor = {
        f"{budget:g}": {
            s: net[budget][(s, baseline)] - net[8.0][(s, baseline)]
            for s in DEFAULT_DEVELOPMENT_SEASONS
        }
        for budget in BUDGETS
        if budget != 8.0
    }
    readings: dict[str, dict[str, object]] = {}
    for budget, chains in by_budget.items():
        rows: dict[str, object] = {}
        for variant in sorted({str(c["variant"]) for c in chains} - {baseline}):
            comparison = chain_comparison(
                variant, baseline, chains, resamples=2_000, block_length=4
            )
            if comparison is not None:
                rows[variant.rsplit("bank", 1)[1].replace("p", ".")] = {
                    "comparison": comparison,
                    "gate": gate(comparison),
                }
        readings[f"{budget:g}"] = rows
    write_json(
        RECORD,
        {
            "protocol": "docs/research/component_banked_transfer_value_path_diagnostic.md",
            "post_hoc": True,
            "provenance": repository_provenance(),
            "cell": CELL_NAME,
            "budgets": list(BUDGETS),
            "owner_level": OWNER_LEVEL,
            "policy_net_change_against_budget_8": floor,
            "against_policy_by_budget": readings,
            "changes_a_default": False,
        },
    )
    print(f"Wrote {RECORD}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-dir", type=Path, default=None)
    parser.add_argument("--walk-owner-level", default=None, metavar="SEASON")
    parser.add_argument("--read", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.read:
        return _read()
    season = arguments.walk_owner_level
    if season not in DEFAULT_DEVELOPMENT_SEASONS or arguments.handoff_dir is None:
        print("--walk-owner-level needs a development season and --handoff-dir.")
        return 1
    return _walk_owner_level(season, arguments.archive_root, arguments.handoff_dir)


if __name__ == "__main__":
    sys.exit(main())
