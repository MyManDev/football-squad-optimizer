"""Measure a held free transfer's value computed each week on the component forecast.

Usage::

    python -m scripts.measure_component_computed_banked_value --season 2024-25 \\
        --handoff-dir <component handoff>
    python -m scripts.measure_component_computed_banked_value --read

Protocol: ``docs/research/component_computed_banked_value_prereg.md``. One season per process
walks the primary cell of the fixed-level record (component forecast, bank cap 5) with the
banked value computed at every decision, and writes
``artifacts/component_banked_transfer_value/computed/<season>.json``. ``--read`` pairs those
chains with the fixed-level record's own chains of the same cell (0, 0.5 and 1.2) and writes
``docs/research/component_computed_banked_value.json``. Measurement only: no default moves.
The locked 2025-26 season is refused.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    measurement_optimization_config,
    repository_provenance,
    write_json,
)
from scripts.measure_component_hit_margin import COMPONENT_RECORD, handoff_matches_record

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import ExperimentError
from squadopt.experiments.component_banked_transfer_value import (
    CURRENT_FREE_TRANSFER_CAP,
    free_transfer_use,
)
from squadopt.experiments.component_chain import load_component_chain_inputs
from squadopt.experiments.component_computed_banked_value import (
    COMPUTED_LABEL,
    POLICY_LABEL,
    SECONDARY_LABELS,
    ComputedBankValueChain,
    build_computed_arm,
    computed_reading,
)
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    LOCKED_HOLDOUT_SEASON,
    chain_comparison,
    chain_record,
    season_fixture_counts,
)

LOGGER = logging.getLogger(__name__)

ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "component_banked_transfer_value"
COMPUTED_ROOT = ARTIFACT_ROOT / "computed"
RECORD_PATH = REPOSITORY_ROOT / "docs" / "research" / "component_computed_banked_value.json"
PROTOCOL_PATH = "docs/research/component_computed_banked_value_prereg.md"
FIXED_CELL = "component_rules_2026_27"


def _walk(arguments: argparse.Namespace) -> int:
    season = str(arguments.season).strip()
    if season == LOCKED_HOLDOUT_SEASON or season not in DEFAULT_DEVELOPMENT_SEASONS:
        print(f"{season} is not a development season; {LOCKED_HOLDOUT_SEASON} is locked.")
        return 1
    if arguments.handoff_dir is None or not arguments.handoff_dir.is_dir():
        print("The component forecast needs --handoff-dir, the directory of the frozen handoff.")
        return 1
    deterministic = float(arguments.deterministic_time_limit)
    config = replace(
        measurement_optimization_config(),
        solver_time_limit_seconds=max(60.0, 6.0 * deterministic),
        solver_deterministic_time_limit=deterministic,
    )
    panel = build_panel(arguments.archive_root)
    try:
        inputs = load_component_chain_inputs(arguments.handoff_dir, panel)
        matches = handoff_matches_record(inputs.identity(), COMPONENT_RECORD)
        if not all(matches.values()):
            print(f"The component handoff is not the recorded one: {matches!r}.")
            return 1
        counts = season_fixture_counts(arguments.archive_root, season)
        arm = build_computed_arm(season, config, end_gameweek=arguments.end_gameweek)
        started = datetime.now(UTC)
        chain = ComputedBankValueChain(
            panel, counts, arm.config, decision_projections=inputs.projections[season]
        )
        result = chain.run()
    except ExperimentError as error:
        print(f"Could not walk the chain:\n  {error}")
        return 1
    elapsed = (datetime.now(UTC) - started).total_seconds()
    record = chain_record(result, arm.label, elapsed)
    record["computed_banked_values"] = {
        str(gameweek): value for gameweek, value in sorted(chain.computed_values.items())
    }
    output = arguments.json_output or COMPUTED_ROOT / f"{season}.json"
    write_json(
        output,
        {
            "protocol": PROTOCOL_PATH,
            "season": season,
            "provenance": repository_provenance(),
            "solver_deterministic_time_limit": deterministic,
            "end_gameweek": arguments.end_gameweek,
            "chains": [record],
            "measurement_only": True,
        },
    )
    print(f"Wrote {output}: net {float(str(record['net_points'])):.0f}, {elapsed:.0f} s")
    return 0


def _load(path: Path) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["chains"])


def _held_where_policy_spends(computed: dict[str, Any], policy: dict[str, Any]) -> int:
    spent = {int(w["gameweek"]): int(w["transfer_count"]) for w in policy["weeks"]}
    return sum(
        1
        for week in computed["weeks"]
        if int(week["transfer_count"]) == 0 and spent.get(int(week["gameweek"]), 0) > 0
    )


def _read(arguments: argparse.Namespace) -> int:
    seasons = DEFAULT_DEVELOPMENT_SEASONS
    fixed: list[dict[str, Any]] = []
    computed: list[dict[str, Any]] = []
    for season in seasons:
        fixed.extend(_load(ARTIFACT_ROOT / f"{season}-{FIXED_CELL}.json"))
        computed.extend(_load(COMPUTED_ROOT / f"{season}.json"))
    fixed.extend(
        chain
        for path in sorted((ARTIFACT_ROOT / "owner_level").glob("*.json"))
        for chain in _load(path)
        if float(str(chain.get("budget", 8.0))) == 8.0
    )
    chains = [c for c in fixed if c["variant"] in (POLICY_LABEL, *SECONDARY_LABELS)] + computed

    def compare(baseline: str) -> dict[str, object]:
        result = chain_comparison(
            COMPUTED_LABEL,
            baseline,
            chains,
            resamples=arguments.bootstrap_resamples,
            block_length=arguments.moving_block_length,
        )
        if result is None:
            raise SystemExit(f"No paired chains for {COMPUTED_LABEL} against {baseline}.")
        return result

    primary = compare(POLICY_LABEL)
    secondary = {label: compare(label) for label in SECONDARY_LABELS}
    described: dict[str, object] = {}
    by_key = {(c["season"], c["variant"]): c for c in chains}
    for season in seasons:
        chain = by_key[(season, COMPUTED_LABEL)]
        values = [float(v) for v in chain["computed_banked_values"].values()]
        described[season] = {
            "net_points": chain["net_points"],
            "mean_value": round(statistics.fmean(values), 3),
            "median_value": round(statistics.median(values), 3),
            "max_value": round(max(values), 3),
            "share_zero": round(sum(1 for v in values if v == 0.0) / len(values), 3),
            "free_transfer_use": free_transfer_use(chain, CURRENT_FREE_TRANSFER_CAP),
            "held_where_policy_spends": _held_where_policy_spends(
                chain, by_key[(season, POLICY_LABEL)]
            ),
        }
    document = {
        "protocol": PROTOCOL_PATH,
        "provenance": repository_provenance(),
        "bootstrap": {
            "resamples": arguments.bootstrap_resamples,
            "block_length": arguments.moving_block_length,
        },
        "primary": primary,
        "secondary": secondary,
        "reading": computed_reading(primary, secondary),
        "described": described,
        "measurement_only": True,
    }
    write_json(arguments.json_output or RECORD_PATH, document)
    print(json.dumps(document["reading"], indent=1))
    print(json.dumps(described, indent=1, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-dir", type=Path, default=None)
    parser.add_argument("--season", default=None)
    parser.add_argument("--end-gameweek", type=int, default=None)
    parser.add_argument("--deterministic-time-limit", type=float, default=8.0)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--read", action="store_true")
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if arguments.read:
        return _read(arguments)
    if arguments.season is None:
        print("--season is required unless --read is given.")
        return 1
    return _walk(arguments)


if __name__ == "__main__":
    sys.exit(main())
