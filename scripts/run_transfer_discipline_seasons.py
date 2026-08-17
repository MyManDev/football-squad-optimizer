"""Transfer-discipline factorial on the season-long chain.

    python -m scripts.run_transfer_discipline_seasons
    python -m scripts.run_transfer_discipline_seasons --seasons 2024-25 --lookaheads 1

The season chains (`docs/season_chain_note.md`) showed the weekly control paying about
forty hits a season under naive projections and the rolling planner far more: a hit is
taken whenever a one-week projected gain clears four points, and a free transfer is
spent on any positive gain because a finite horizon gives an unused one no value. This
runner asks whether discipline pays, with three planner controls that leave the game's
rules untouched — the sheet still charges four points a hit:

* **planning hit cost** — the cost the planner charges itself per paid transfer; above
  the rule's four it is a hit threshold (a winner's-curse haircut on projected gains);
* **transfer cap** — at most this many transfers a gameweek (a wildcard week is exempt);
* **banked transfer value** — terminal value of a free transfer carried past the
  horizon, so a small gain no longer spends one for nothing.

Full factorial at each lookahead, every cell against the rule cell (cost 4, no cap,
value 0) at the same lookahead and chip mode; DoE-style main effects average each
level over the other factors. Same protocol as the chains: naive calendar scaling,
same opening squads, sell rule, chips reserved for doubles unless told otherwise.

Measurement only. The locked 2025-26 holdout is refused.
"""

import argparse
import itertools
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)
from scripts.run_season_chain_seasons import (
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    _chain_record,
    _comparison,
    _fixture_counts,
    chip_windows_for,
    parse_holding_values,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    NAIVE_PROJECTION_RULE,
    PROJECTION_RULES,
    SEASON_CHAIN_CONTRACT_VERSION,
    ExperimentError,
    SeasonChain,
    SeasonChainConfig,
)
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
TRANSFER_DISCIPLINE_CONTRACT_VERSION = "transfer_discipline_seasons_v1"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"
RULE_HIT_COST = 4.0


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument("--lookaheads", default="1")
    parser.add_argument("--chips", default="reserve", help="one of off,on,reserve,value,hybrid")
    parser.add_argument(
        "--chip-holding-values",
        default="bboost=20,3xc=18,wildcard=12",
        help="terminal value of an unplayed chip under --chips value or hybrid",
    )
    parser.add_argument("--hit-costs", default="4,6,8", help="planning hit costs (points)")
    parser.add_argument("--transfer-caps", default="none,2,1", help="per-gameweek caps")
    parser.add_argument("--banked-values", default="0,1,2", help="terminal free-transfer values")
    parser.add_argument("--deterministic-time-limit", type=float, default=None)
    parser.add_argument("--wall-time-limit", type=float, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument(
        "--projection-rule", choices=PROJECTION_RULES, default=NAIVE_PROJECTION_RULE
    )
    parser.add_argument("--merge", default=None, help="comma list of per-season artifacts")
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "transfer_discipline.json"
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "transfer_discipline.md",
    )
    return parser.parse_args()


def _cap_label(cap: int | None) -> str:
    return "none" if cap is None else str(cap)


def _label(lookahead: int, mode: str, hit: float, cap: int | None, value: float) -> str:
    return f"L{lookahead}_chips_{mode}_hit{hit:g}_cap{_cap_label(cap)}_ftv{value:g}"


def _parse_caps(text: str) -> tuple[int | None, ...]:
    caps: list[int | None] = []
    for token in str(text).split(","):
        token = token.strip()
        caps.append(None if token in {"none", "None", ""} else int(token))
    return tuple(caps)


def _main_effects(
    chains: list[dict[str, object]],
    baseline_label: str,
    *,
    factor: str,
    levels: tuple[object, ...],
    lookahead: int,
    mode: str,
) -> dict[str, object]:
    """Mean season net delta versus the rule cell, per level, over the other factors."""

    baseline = {
        str(row["season"]): float(str(row["net_points"]))
        for row in chains
        if row["variant"] == baseline_label
    }
    out: dict[str, object] = {}
    for level in levels:
        deltas: list[float] = []
        hits: list[float] = []
        for row in chains:
            if row["lookahead"] != lookahead or str(row["variant"]).find(f"chips_{mode}_") < 0:
                continue
            factors = row["factors"]
            assert isinstance(factors, Mapping)
            if factors[factor] != level:
                continue
            season = str(row["season"])
            if season not in baseline:
                continue
            deltas.append(float(str(row["net_points"])) - baseline[season])
            hits.append(float(str(row["transfer_hit_points"])))
        if factor == "transfer_cap":
            key = _cap_label(None if level is None else int(str(level)))
        else:
            key = f"{float(str(level)):g}"
        out[key] = {
            "cells": len(deltas),
            "mean_season_net_delta": sum(deltas) / len(deltas) if deltas else None,
            "mean_hit_points": sum(hits) / len(hits) if hits else None,
        }
    return out


def _markdown(
    seasons: tuple[str, ...],
    chains: list[dict[str, object]],
    comparisons: list[dict[str, object]],
    effects: dict[str, object],
) -> str:
    lines = [
        "# Transfer discipline on the season-long chain",
        "",
        "Planning hit cost, per-gameweek transfer cap, and terminal value of a banked free",
        "transfer, as a full factorial on the season chain; the sheet charges the rule's four",
        "points a hit throughout. Every cell against the rule cell (cost 4, no cap, value 0) at",
        "the same lookahead and chip mode. Measurement only; nothing is promoted.",
        "",
        "## Main effects (mean season net delta vs the rule cell, over the other factors)",
        "",
    ]
    for key, table in effects.items():
        lines += [
            f"### {key}",
            "",
            "| Level | Cells | Mean season net delta | Mean hit points |",
            "| --- | ---: | ---: | ---: |",
        ]
        assert isinstance(table, Mapping)
        for level, stats in table.items():
            assert isinstance(stats, Mapping)
            delta = stats["mean_season_net_delta"]
            hits = stats["mean_hit_points"]
            lines.append(
                f"| {level} | {stats['cells']} | "
                f"{'—' if delta is None else f'{float(str(delta)):+.1f}'} | "
                f"{'—' if hits is None else f'{float(str(hits)):.0f}'} |"
            )
        lines.append("")
    lines += [
        "## Cells (mean over seasons)",
        "",
        "| Variant | Seasons | Mean net | Mean realized | Mean hits | Mean transfers "
        "| Mean season delta vs rule | Weekly mean ± SE | 90% interval |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    by_variant: dict[str, list[dict[str, object]]] = {}
    for row in chains:
        by_variant.setdefault(str(row["variant"]), []).append(row)
    comparison_by = {str(row["variant"]): row for row in comparisons}
    for variant, rows in by_variant.items():
        count = len(rows)
        net = sum(float(str(r["net_points"])) for r in rows) / count
        realized = sum(float(str(r["realized_points"])) for r in rows) / count
        hits = sum(float(str(r["transfer_hit_points"])) for r in rows) / count
        moves = sum(int(str(r["transfer_count"])) for r in rows) / count
        comparison = comparison_by.get(variant)
        if comparison is None:
            delta = "rule"
            weekly = "—"
            interval_text = "—"
        else:
            delta = f"{float(str(comparison['mean_season_net_advantage_points'])):+.1f}"
            weekly = (
                f"{float(str(comparison['mean_weekly_advantage_points'])):+.2f} ± "
                f"{float(str(comparison['weekly_advantage_standard_error'])):.2f}"
            )
            interval = comparison["weekly_advantage_block_bootstrap_interval"]
            interval_text = (
                f"[{interval[0]:+.2f}, {interval[1]:+.2f}]"  # type: ignore[index]
                if interval is not None
                else "—"
            )
        lines.append(
            f"| {variant} | {count} | {net:.0f} | {realized:.0f} | {hits:.0f} | {moves:.0f} "
            f"| {delta} | {weekly} | {interval_text} |"
        )
    lines += [
        "",
        f"Seasons: {', '.join(seasons)}. Projection rule `{NAIVE_PROJECTION_RULE}`; the 2025-26 "
        "holdout was not read.",
        "",
    ]
    return "\n".join(lines)


def _document(
    *,
    metadata: Mapping[str, object],
    seasons: tuple[str, ...],
    lookaheads: tuple[int, ...],
    mode: str,
    hit_costs: tuple[float, ...],
    caps: tuple[int | None, ...],
    values: tuple[float, ...],
    chains: list[dict[str, object]],
    solver_limits: Mapping[str, object],
    bootstrap: Mapping[str, object],
) -> tuple[dict[str, object], str]:
    comparisons: list[dict[str, object]] = []
    effects: dict[str, object] = {}
    for lookahead in lookaheads:
        baseline_label = _label(lookahead, mode, RULE_HIT_COST, None, 0.0)
        for hit, cap, value in itertools.product(hit_costs, caps, values):
            label = _label(lookahead, mode, hit, cap, value)
            if label == baseline_label:
                continue
            comparison = _comparison(
                label,
                baseline_label,
                chains,
                resamples=int(str(bootstrap["resamples"])),
                block_length=int(str(bootstrap["moving_block_length"])),
            )
            if comparison is not None:
                comparisons.append(comparison)
        effects[f"L{lookahead}: planning hit cost"] = _main_effects(
            chains,
            baseline_label,
            factor="planning_hit_cost",
            levels=hit_costs,
            lookahead=lookahead,
            mode=mode,
        )
        effects[f"L{lookahead}: transfer cap"] = _main_effects(
            chains,
            baseline_label,
            factor="transfer_cap",
            levels=caps,
            lookahead=lookahead,
            mode=mode,
        )
        effects[f"L{lookahead}: banked transfer value"] = _main_effects(
            chains,
            baseline_label,
            factor="banked_transfer_value",
            levels=values,
            lookahead=lookahead,
            mode=mode,
        )
    document = {
        **metadata,
        "contract_version": TRANSFER_DISCIPLINE_CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "projection_rule": (
            str(dict(chains[0]["diagnostics"]).get("projection_rule", NAIVE_PROJECTION_RULE))  # type: ignore[call-overload]
            if chains
            else NAIVE_PROJECTION_RULE
        ),
        "seasons": list(seasons),
        "lookaheads": list(lookaheads),
        "chip_mode": mode,
        "factors": {
            "planning_hit_cost": list(hit_costs),
            "transfer_cap": [_cap_label(cap) for cap in caps],
            "banked_transfer_value": list(values),
        },
        "rule_cell": {
            "planning_hit_cost": RULE_HIT_COST,
            "transfer_cap": None,
            "banked_transfer_value": 0.0,
        },
        "solver_limits": dict(solver_limits),
        "bootstrap": dict(bootstrap),
        "main_effects": effects,
        "comparisons": comparisons,
        "chains": chains,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    return document, _markdown(seasons, chains, comparisons, effects)


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    hit_costs = tuple(float(v.strip()) for v in str(arguments.hit_costs).split(","))
    caps = _parse_caps(arguments.transfer_caps)
    values = tuple(float(v.strip()) for v in str(arguments.banked_values).split(","))
    lookaheads = tuple(int(v.strip()) for v in str(arguments.lookaheads).split(","))
    mode = str(arguments.chips).strip()
    if mode not in {"off", "on", "reserve", "value", "hybrid"}:
        print("--chips must be one of off,on,reserve,value,hybrid.")
        return 1
    holding_values = parse_holding_values(arguments.chip_holding_values)
    bootstrap = {
        "resamples": arguments.bootstrap_resamples,
        "moving_block_length": arguments.moving_block_length,
        "confidence_level": 0.90,
    }

    if arguments.merge:
        import json

        sources = [Path(v.strip()) for v in str(arguments.merge).split(",")]
        documents = [json.loads(path.read_text(encoding="utf-8")) for path in sources]
        chains: list[dict[str, object]] = []
        seasons: list[str] = []
        for doc in documents:
            if doc.get("contract_version") != TRANSFER_DISCIPLINE_CONTRACT_VERSION:
                print("Every merged artifact must carry the transfer discipline contract.")
                return 1
            chains.extend(dict(row) for row in doc["chains"])
            seasons.extend(str(s) for s in doc["seasons"])
        first = documents[0]
        metadata = {key: first[key] for key in ("created_utc", "provenance", "environment")}
        metadata["merged_from"] = [str(path) for path in sources]
        document, markdown = _document(
            metadata=metadata,
            seasons=tuple(seasons),
            lookaheads=tuple(int(v) for v in first["lookaheads"]),
            mode=str(first["chip_mode"]),
            hit_costs=tuple(float(v) for v in first["factors"]["planning_hit_cost"]),
            caps=_parse_caps(",".join(str(v) for v in first["factors"]["transfer_cap"])),
            values=tuple(float(v) for v in first["factors"]["banked_transfer_value"]),
            chains=chains,
            solver_limits=first["solver_limits"],
            bootstrap=bootstrap,
        )
        write_json(arguments.json_output, document)
        write_text(arguments.markdown_output, markdown)
        print(markdown)
        return 0

    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    seasons_tuple = tuple(v.strip() for v in str(arguments.seasons).split(","))
    if LOCKED_HOLDOUT_SEASON in seasons_tuple:
        print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be walked.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    optimization_config = OptimizationConfig()
    if arguments.deterministic_time_limit is not None or arguments.wall_time_limit is not None:
        wall = arguments.wall_time_limit
        if wall is None:
            wall = max(60.0, 6.0 * float(arguments.deterministic_time_limit or 10.0))
        optimization_config = OptimizationConfig(
            solver_time_limit_seconds=wall,
            solver_deterministic_time_limit=arguments.deterministic_time_limit,
        )
    records: list[dict[str, object]] = []
    try:
        for season in seasons_tuple:
            counts = _fixture_counts(arguments.archive_root, season)
            cap_free = MAX_FREE_TRANSFERS.get(season, 5)
            for lookahead in lookaheads:
                for hit, cap, value in itertools.product(hit_costs, caps, values):
                    label = _label(lookahead, mode, hit, cap, value)
                    LOGGER.info("Season %s: %s", season, label)
                    config = SeasonChainConfig(
                        season=season,
                        lookahead=lookahead,
                        form_window=arguments.form_window,
                        candidate_pool_per_position=arguments.candidate_pool_per_position,
                        cheap_pool_per_position=arguments.cheap_pool_per_position,
                        chip_windows=chip_windows_for(season) if mode != "off" else (),
                        chip_policy=(
                            "double_gameweeks_only"
                            if mode == "reserve"
                            else "hybrid"
                            if mode == "hybrid"
                            else "planner"
                        ),
                        hit_points_charged=RULE_HIT_COST,
                        projection_rule=str(arguments.projection_rule),
                        optimization_config=optimization_config,
                        transfer_config=TransferPlanningConfig(
                            max_free_transfers=cap_free,
                            transfer_hit_cost_points=hit,
                            max_transfers_per_gameweek=cap,
                            banked_transfer_value_points=value,
                            chip_holding_value_points=(
                                holding_values if mode in {"value", "hybrid"} else {}
                            ),
                        ),
                    )
                    started = datetime.now(UTC)
                    result = SeasonChain(panel, counts, config).run()
                    elapsed = (datetime.now(UTC) - started).total_seconds()
                    record = _chain_record(result, label, elapsed)
                    record["factors"] = {
                        "planning_hit_cost": hit,
                        "transfer_cap": cap,
                        "banked_transfer_value": value,
                    }
                    records.append(record)
                    LOGGER.info(
                        "  net %.0f (realized %.0f, hits %.0f), transfers %d, %.0fs",
                        result.net_points,
                        result.realized_points,
                        result.transfer_hit_points,
                        result.transfer_count,
                        elapsed,
                    )
    except ExperimentError as error:
        print(f"Could not walk the discipline chains:\n  {error}")
        return 1
    document, markdown = _document(
        metadata=artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        seasons=seasons_tuple,
        lookaheads=lookaheads,
        mode=mode,
        hit_costs=hit_costs,
        caps=caps,
        values=values,
        chains=records,
        solver_limits={
            "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
            "solver_deterministic_time_limit": optimization_config.solver_deterministic_time_limit,
        },
        bootstrap=bootstrap,
    )
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
