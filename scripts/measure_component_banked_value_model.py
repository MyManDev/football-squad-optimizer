"""Measure a carried free transfer valued by a Bellman model on the component forecast.

Usage::

    python -m scripts.measure_component_banked_value_model --probe 2024-25 --handoff-dir <dir>
    python -m scripts.measure_component_banked_value_model --walk 2024-25 --handoff-dir <dir>
    python -m scripts.measure_component_banked_value_model --read

Protocol: ``docs/research/component_banked_value_model_prereg.md``. ``--probe`` walks the
policy chain of the primary cell (component forecast, bank cap 5, value 0) and solves
``P(0..5)`` at every decision, writing ``artifacts/component_banked_transfer_value/model/
probe-<season>.json``. ``--walk`` builds a season's value function from the other three
seasons' probes and walks the model's chain, writing ``model/<season>.json``. ``--read`` pairs
the model's chains with the fixed-level chains (0, 0.5, 1.12) and writes
``docs/research/component_banked_value_model.json``. Measurement only: no default moves. The
locked 2025-26 season is refused.
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
    PRIMARY_CELL,
    build_arms,
    free_transfer_use,
)
from squadopt.experiments.component_banked_value_model import (
    HALF_LABEL,
    MODEL_LABEL,
    OWNER_LABEL,
    POLICY_LABEL,
    BankValueModelChain,
    GainProbeChain,
    bellman_values,
    marginal_values,
    model_reading,
    opportunity,
)
from squadopt.experiments.component_chain import load_component_chain_inputs
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    LOCKED_HOLDOUT_SEASON,
    chain_comparison,
    chain_record,
    season_fixture_counts,
)

LOGGER = logging.getLogger(__name__)

ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "component_banked_transfer_value"
MODEL_ROOT = ARTIFACT_ROOT / "model"
RECORD_PATH = REPOSITORY_ROOT / "docs" / "research" / "component_banked_value_model.json"
SEASON_GAMEWEEKS = range(1, 39)
ALL_SEASONS_ROWS = 14
"""Rows of the all-seasons table: decisions remaining after this one, 0..13; by thirteen the
values have settled to the stationary row at two decimals."""


def all_seasons_value_table(samples: Sequence[Sequence[float]]) -> list[list[float]]:
    """The 2nd..5th carried transfer's value by decisions remaining (0..13), from every
    development season's opportunities: what a product policy would carry."""

    values = bellman_values(SEASON_GAMEWEEKS, samples, CURRENT_FREE_TRANSFER_CAP)
    last = SEASON_GAMEWEEKS[-1]
    return [
        [round(x, 2) for x in marginal_values(values[last - remaining])]
        for remaining in range(ALL_SEASONS_ROWS)
    ]
PROTOCOL_PATH = "docs/research/component_banked_value_model_prereg.md"
FIXED_CELL = "component_rules_2026_27"


def _setup(arguments: argparse.Namespace, season: str) -> tuple[Any, Any, Any, Any] | None:
    if season == LOCKED_HOLDOUT_SEASON or season not in DEFAULT_DEVELOPMENT_SEASONS:
        print(f"{season} is not a development season; {LOCKED_HOLDOUT_SEASON} is locked.")
        return None
    if arguments.handoff_dir is None or not arguments.handoff_dir.is_dir():
        print("The component forecast needs --handoff-dir, the directory of the frozen handoff.")
        return None
    deterministic = float(arguments.deterministic_time_limit)
    config = replace(
        measurement_optimization_config(),
        solver_time_limit_seconds=max(60.0, 6.0 * deterministic),
        solver_deterministic_time_limit=deterministic,
    )
    panel = build_panel(arguments.archive_root)
    inputs = load_component_chain_inputs(arguments.handoff_dir, panel)
    matches = handoff_matches_record(inputs.identity(), COMPONENT_RECORD)
    if not all(matches.values()):
        print(f"The component handoff is not the recorded one: {matches!r}.")
        return None
    counts = season_fixture_counts(arguments.archive_root, season)
    (arm,) = build_arms(
        season, *PRIMARY_CELL, config, levels=(0.0,), end_gameweek=arguments.end_gameweek
    )
    return panel, counts, arm.config, inputs.projections[season]


def _probe(arguments: argparse.Namespace) -> int:
    season = str(arguments.probe)
    setup = _setup(arguments, season)
    if setup is None:
        return 1
    panel, counts, config, projections = setup
    try:
        chain = GainProbeChain(panel, counts, config, decision_projections=projections)
        result = chain.run()
    except ExperimentError as error:
        print(f"Could not walk the probe:\n  {error}")
        return 1
    output = arguments.json_output or MODEL_ROOT / f"probe-{season}.json"
    write_json(
        output,
        {
            "protocol": PROTOCOL_PATH,
            "season": season,
            "provenance": repository_provenance(),
            "decisions": len(result.weeks),
            "net_points": result.net_points,
            "objectives": {str(gw): list(v) for gw, v in sorted(chain.objectives.items())},
            "free_transfers": {str(gw): v for gw, v in sorted(chain.free_transfers.items())},
            "measurement_only": True,
        },
    )
    print(f"Wrote {output}: {len(chain.objectives)} decisions, net {result.net_points:.0f}")
    return 0


def _samples(excluded: str) -> list[tuple[float, ...]]:
    samples: list[tuple[float, ...]] = []
    for season in DEFAULT_DEVELOPMENT_SEASONS:
        if season == excluded:
            continue
        probe = json.loads((MODEL_ROOT / f"probe-{season}.json").read_text(encoding="utf-8"))
        samples.extend(opportunity(values) for values in probe["objectives"].values())
    return samples


def _walk(arguments: argparse.Namespace) -> int:
    season = str(arguments.walk)
    setup = _setup(arguments, season)
    if setup is None:
        return 1
    panel, counts, config, projections = setup
    samples = _samples(season)
    try:
        probe_chain = BankValueModelChain(
            panel, counts, config, decision_projections=projections, values={}
        )
        gameweeks = probe_chain.chain_gameweeks
        values = bellman_values(gameweeks, samples, CURRENT_FREE_TRANSFER_CAP)
        chain = BankValueModelChain(
            panel, counts, config, decision_projections=projections, values=values
        )
        started = datetime.now(UTC)
        result = chain.run()
    except ExperimentError as error:
        print(f"Could not walk the model:\n  {error}")
        return 1
    elapsed = (datetime.now(UTC) - started).total_seconds()
    record = chain_record(result, MODEL_LABEL, elapsed)
    record["model_choices"] = {str(gw): c for gw, c in sorted(chain.choices.items())}
    output = arguments.json_output or MODEL_ROOT / f"{season}.json"
    write_json(
        output,
        {
            "protocol": PROTOCOL_PATH,
            "season": season,
            "provenance": repository_provenance(),
            "samples": len(samples),
            "value_function": {str(gw): list(row) for gw, row in sorted(values.items())},
            "chains": [record],
            "measurement_only": True,
        },
    )
    print(f"Wrote {output}: net {float(str(record['net_points'])):.0f}, {elapsed:.0f} s")
    return 0


def _load(path: Path) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["chains"])


def _read(arguments: argparse.Namespace) -> int:
    seasons = DEFAULT_DEVELOPMENT_SEASONS
    chains: list[dict[str, Any]] = []
    tables: dict[str, Any] = {}
    for season in seasons:
        chains.extend(
            c
            for c in _load(ARTIFACT_ROOT / f"{season}-{FIXED_CELL}.json")
            if c["variant"] in (POLICY_LABEL, HALF_LABEL)
        )
        chains.extend(_load(ARTIFACT_ROOT / "level_1p12" / f"{season}.json"))
        walked = json.loads((MODEL_ROOT / f"{season}.json").read_text(encoding="utf-8"))
        chains.extend(walked["chains"])
        rows = walked["value_function"]
        ordered = sorted(rows, key=int)
        tables[season] = {
            label: {
                "gameweek": int(gw),
                "marginal_values": [round(x, 3) for x in marginal_values(rows[gw])],
            }
            for label, gw in (
                ("first", ordered[0]),
                ("middle", ordered[len(ordered) // 2]),
                ("last_but_one", ordered[-2]),
            )
        }

    def compare(baseline: str) -> dict[str, Any]:
        result = chain_comparison(
            MODEL_LABEL,
            baseline,
            chains,
            resamples=arguments.bootstrap_resamples,
            block_length=arguments.moving_block_length,
        )
        if result is None:
            raise SystemExit(f"No paired chains against {baseline}.")
        return result

    comparisons = {label: compare(label) for label in (OWNER_LABEL, POLICY_LABEL, HALF_LABEL)}
    reading = model_reading(
        comparisons[OWNER_LABEL], comparisons[POLICY_LABEL], comparisons[HALF_LABEL]
    )
    samples = [
        opportunity(v)
        for season in seasons
        for v in json.loads((MODEL_ROOT / f"probe-{season}.json").read_text(encoding="utf-8"))[
            "objectives"
        ].values()
    ]
    by_key = {(c["season"], c["variant"]): c for c in chains}
    described = {
        "mean_opportunity": [
            round(statistics.fmean(g[k] for g in samples), 3)
            for k in range(CURRENT_FREE_TRANSFER_CAP)
        ],
        "share_first_transfer_worth_zero": round(
            sum(1 for g in samples if g[0] == 0.0) / len(samples), 3
        ),
        "value_tables": tables,
        "all_seasons_value_table": all_seasons_value_table(samples),
        "free_transfer_use": {
            season: free_transfer_use(by_key[(season, MODEL_LABEL)], CURRENT_FREE_TRANSFER_CAP)
            for season in seasons
        },
        "net_points": {season: by_key[(season, MODEL_LABEL)]["net_points"] for season in seasons},
    }
    document = {
        "protocol": PROTOCOL_PATH,
        "provenance": repository_provenance(),
        "bootstrap": {
            "resamples": arguments.bootstrap_resamples,
            "block_length": arguments.moving_block_length,
        },
        "comparisons": comparisons,
        "reading": reading,
        "described": described,
        "measurement_only": True,
    }
    write_json(arguments.json_output or RECORD_PATH, document)
    for label, comparison in comparisons.items():
        print(
            label,
            round(comparison["mean_weekly_advantage_points"], 2),
            [round(x, 2) for x in comparison["weekly_advantage_block_bootstrap_interval"]],
            {s: round(x) for s, x in comparison["season_net_advantage_points"].items()},
        )
    print(json.dumps(reading, indent=1))
    print(json.dumps(described, indent=1, default=str))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-dir", type=Path, default=None)
    parser.add_argument("--probe", default=None, help="one development season")
    parser.add_argument("--walk", default=None, help="one development season")
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
    if arguments.probe:
        return _probe(arguments)
    if arguments.walk:
        return _walk(arguments)
    print("One of --probe, --walk or --read is required.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
