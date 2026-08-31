"""Walk every development season as one decision chain, with and without chips.

    python -m scripts.run_season_chain_seasons
    python -m scripts.run_season_chain_seasons --seasons 2023-24 --lookaheads 1,3 --chips off,on

The windowed measurements (`docs/planner_horizon_seasons.md`, `docs/planner_horizon_rolling.md`)
found no horizon that beats the weekly baseline and showed the rolling planner trading
selection loss for transfer-hit churn. They could not ask two questions, because a
window starts from a fresh squad and cannot own a once-per-season resource: what a
chip is worth on the realized sheet, and whether the rolling planner's churn becomes
chip use when chips exist. This runner asks both by walking each season once — one
squad from the first decision gameweek to the last, free transfers banked, hits paid,
each chip spent at most once inside its window — under a small factorial of controls:

* lookahead 1 (the myopic weekly baseline) versus a rolling horizon;
* chips off, chips on (bench boost, triple captain, wildcard offered to the planner
  wherever their windows are open; free hit is out of the planner's contract and so out
  of this measurement), and chips reserved (bench boost and triple captain offered only
  in double gameweeks — the common human rule, standing in for the option value a
  finite horizon cannot price).

Every variant shares the projection rule, the pool rule, the opening squad, the sell
rule, and the scoring, so the season totals are paired. Statistics: a season is one
observation, four seasons are four; the per-gameweek paired differences are the
evidence, and their block-bootstrap interval treats consecutive weeks as dependent
because a carried squad makes them so.

Development-season chip windows are not published in the archive. The table below is
the runner's assumption — one wildcard per half with the split at the turn of the
year, one bench boost and one triple captain per season — and it is recorded in the
artifact as an assumption. The 2026-27 rules (two chip sets, one per half) come from
the capture via `season_rules_v1` and can be expressed with the same table.

Measurement only. The locked 2025-26 holdout is refused.
"""

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
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
from squadopt.experiments.season_chain_runs import (
    FIRST_WILDCARD_LAST_GAMEWEEK,
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    chain_comparison,
    chain_record,
    chain_rows,
    chip_windows_for,
    parse_holding_values,
    season_fixture_counts,
)
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
SEASON_CHAIN_SEASONS_CONTRACT_VERSION = "season_chain_seasons_v1"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument("--lookaheads", default="1,3", help="comma list; 1 is the myopic baseline")
    parser.add_argument(
        "--chips",
        default="off,on,reserve",
        help="comma subset of off,on,reserve,value,hybrid,tuned: on offers every open chip "
        "to the planner; reserve offers bench boost and triple captain only in double "
        "gameweeks; value offers every open chip but holds each at its "
        "--chip-holding-values; hybrid reserves the bench boost for doubles and holds "
        "triple captain and wildcard at their holding values; tuned is hybrid with the "
        "--tuned-holding-values and --tuned-hit-cost (the Bayesian-search candidate)",
    )
    parser.add_argument(
        "--chip-holding-values",
        # Recorded discrepancy: freehit is 15 here and 20.0 in
        # experiments/terminal_value.py's HOLDING_VALUE_POINTS. The committed chain
        # artifacts used this 15; the GP study compared against the module's 20.0.
        # Neither changes a recorded verdict, and neither is silently edited to match
        # the other — see the note beside HOLDING_VALUE_POINTS.
        default="bboost=20,3xc=18,wildcard=12,freehit=15",
        help="terminal value of an unplayed chip under --chips value, points per chip",
    )
    parser.add_argument(
        "--tuned-holding-values",
        default="bboost=0,3xc=20,wildcard=24,freehit=0",
        help="holding values of the tuned mode (default: the chip_bayesopt candidate)",
    )
    parser.add_argument(
        "--tuned-hit-cost",
        type=float,
        default=7.0,
        help="the planner's own hit cost under the tuned mode (default: the chip_bayesopt "
        "candidate; the game's charge stays 4 in the ledger)",
    )
    parser.add_argument(
        "--projection-rule",
        choices=PROJECTION_RULES,
        default=NAIVE_PROJECTION_RULE,
        help="naive_calendar_scaling_v1 scales the control projection by fixture count; "
        "control_calendar_blind_v1 is the control as evaluated (a double projects like a single)",
    )
    parser.add_argument("--start-gameweek", type=int, default=None)
    parser.add_argument("--end-gameweek", type=int, default=None)
    parser.add_argument(
        "--max-free-transfers",
        type=int,
        default=None,
        help="override the per-season free-transfer cap table",
    )
    parser.add_argument(
        "--deterministic-time-limit",
        type=float,
        default=None,
        help="CP-SAT deterministic work budget per solve; when set, the wall-clock cap "
        "is raised so the deterministic budget binds and the run is reproducible",
    )
    parser.add_argument("--wall-time-limit", type=float, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument(
        "--merge",
        default=None,
        help="comma list of per-season JSON artifacts written by earlier runs of this "
        "script (one process per season keeps a long run parallel); their chains are "
        "combined and the paired comparisons recomputed across seasons",
    )
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "season_chain.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "season_chain.md"
    )
    return parser.parse_args()


CHIP_MODES = ("off", "on", "reserve", "value", "hybrid", "tuned")


def _variant_label(lookahead: int, mode: str) -> str:
    return f"L{lookahead}_chips_{mode}"


def _fmt(value: object, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:+.{digits}f}" if digits else f"{value:.0f}"
    return str(value)


def _markdown(
    seasons: tuple[str, ...],
    chains: list[dict[str, object]],
    comparisons: list[dict[str, object]],
    assumptions: dict[str, object],
) -> str:
    lines = [
        "# Season-long decision chains: lookahead by chips",
        "",
        "One squad per season, carried from the first decision gameweek to the last; free",
        "transfers banked, hits paid, prices moving under the game's sell rule, chips spent at",
        "most once inside their window. Every variant shares the projection rule, the pool",
        "rule, the opening squad, and the scoring. Measurement only; nothing is promoted.",
        "",
        "## Season totals (net of hits)",
        "",
        "| Season | Variant | Decisions | Realized | Hits | Net | Transfers | Chips played "
        "| Chip gains | Proven |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for row in chains:
        chips = ", ".join(
            f"GW{week} {name}"
            for week, name in sorted(
                dict(row["chips_played"]).items(),  # type: ignore[call-overload]
                key=lambda item: int(item[0]),
            )
        )
        gains = ", ".join(
            f"{name} {value:+.0f}"
            for name, value in dict(row["chip_realized_gains"]).items()  # type: ignore[call-overload]
        )
        lines.append(
            f"| {row['season']} | {row['variant']} | {row['decisions']} "
            f"| {float(str(row['realized_points'])):.0f} "
            f"| {float(str(row['transfer_hit_points'])):.0f} "
            f"| {float(str(row['net_points'])):.0f} | {row['transfer_count']} "
            f"| {chips or '—'} | {gains or '—'} "
            f"| {float(str(row['proven_share'])):.2f} |"
        )
    lines += [
        "",
        "## Paired comparisons",
        "",
        "Season advantage is the difference of season nets; the weekly interval is a",
        "season-aware moving-block bootstrap (90%) on per-gameweek paired differences,",
        "blocks of consecutive weeks because a carried squad makes weeks dependent.",
        "",
        "| Variant | vs | Seasons | Mean season delta | Season delta by season "
        "| Hits delta by season | Weekly mean ± SE | 90% interval | Weeks > 0 |",
        "| --- | --- | ---: | ---: | --- | --- | ---: | --- | ---: |",
    ]
    for row in comparisons:
        by_season = ", ".join(
            f"{season} {value:+.0f}"
            for season, value in dict(row["season_net_advantage_points"]).items()  # type: ignore[call-overload]
        )
        hits = ", ".join(
            f"{season} {value:+.0f}"
            for season, value in dict(row["season_hit_points_delta"]).items()  # type: ignore[call-overload]
        )
        interval = row["weekly_advantage_block_bootstrap_interval"]
        interval_text = (
            f"[{interval[0]:+.2f}, {interval[1]:+.2f}]"  # type: ignore[index]
            if interval is not None
            else "—"
        )
        lines.append(
            f"| {row['variant']} | {row['baseline']} | {row['seasons']} "
            f"| {_fmt(row['mean_season_net_advantage_points'])} | {by_season} | {hits} "
            f"| {_fmt(row['mean_weekly_advantage_points'])} ± "
            f"{float(str(row['weekly_advantage_standard_error'])):.2f} | {interval_text} "
            f"| {float(str(row['positive_week_share'])):.2f} |"
        )
    lines += [
        "",
        "## Assumptions recorded with this run",
        "",
        f"- Projection rule: `{assumptions.get('projection_rule', NAIVE_PROJECTION_RULE)}` "
        "(the decision-time operational control projection, scaled by the known fixture "
        "count under naive_calendar_scaling_v1, unscaled under control_calendar_blind_v1); the "
        "measurement is of the planning mechanism.",
        "- Chip windows per development season are assumed, not read from a capture: "
        + "; ".join(
            f"{season}: first wildcard through GW{split}"
            for season, split in dict(assumptions["first_wildcard_last_gameweek"]).items()  # type: ignore[call-overload]
        )
        + "; one bench boost, one triple captain, and one free hit per season.",
        "- Free-transfer bank cap per season: "
        + ", ".join(
            f"{season} {cap}"
            for season, cap in dict(assumptions["max_free_transfers"]).items()  # type: ignore[call-overload]
        )
        + ".",
        "- Sell price: purchase price plus half of any rise, rounded down to a tenth; buy price "
        "is the week's market price. No automatic substitutions; a blank-team squad member "
        "scores zero.",
        "- The first decision gameweek is the season's second (in-season features need one "
        "prior gameweek); the opening squad is optimized from that week's pool.",
        f"- Seasons: {', '.join(seasons)}. The 2025-26 holdout was not read.",
        "",
    ]
    return "\n".join(lines)


def _comparisons(
    chains: list[dict[str, object]],
    lookaheads: tuple[int, ...],
    chip_modes: tuple[str, ...],
    *,
    resamples: int,
    block_length: int,
) -> list[dict[str, object]]:
    baseline_label = _variant_label(1, "off")
    comparisons: list[dict[str, object]] = []
    for lookahead in lookaheads:
        for mode in chip_modes:
            label = _variant_label(lookahead, mode)
            if label == baseline_label:
                continue
            comparison = chain_comparison(
                label, baseline_label, chains, resamples=resamples, block_length=block_length
            )
            if comparison is not None:
                comparisons.append(comparison)
    # The tuned candidate against hybrid at the same lookahead: what the search bought.
    if {"tuned", "hybrid"} <= set(chip_modes):
        for lookahead in lookaheads:
            comparison = chain_comparison(
                _variant_label(lookahead, "tuned"),
                _variant_label(lookahead, "hybrid"),
                chains,
                resamples=resamples,
                block_length=block_length,
            )
            if comparison is not None:
                comparisons.append(comparison)
    # Chips against no chips at the same lookahead: what the chips themselves buy.
    if "off" in chip_modes:
        for lookahead in lookaheads:
            for mode in chip_modes:
                if mode == "off":
                    continue
                comparison = chain_comparison(
                    _variant_label(lookahead, mode),
                    _variant_label(lookahead, "off"),
                    chains,
                    resamples=resamples,
                    block_length=block_length,
                )
                if comparison is not None and comparison["baseline"] != baseline_label:
                    comparisons.append(comparison)
    return comparisons


def _merge(arguments: argparse.Namespace) -> int:
    """Combine per-season artifacts of this script into one cross-season document."""

    sources = [Path(value.strip()) for value in str(arguments.merge).split(",")]
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in sources]
    if any(
        doc.get("contract_version") != SEASON_CHAIN_SEASONS_CONTRACT_VERSION for doc in documents
    ):
        print("Every merged artifact must carry the season chain seasons contract.")
        return 1
    chains: list[dict[str, object]] = []
    seasons: list[str] = []
    for doc in documents:
        chains.extend(chain_rows(doc["chains"]))
        seasons.extend(str(season) for season in doc["seasons"])
    if len(set(seasons)) != len(seasons):
        print("Merged artifacts overlap in seasons; each season may appear once.")
        return 1
    lookaheads = tuple(sorted({int(str(row["lookahead"])) for row in chains}))
    chip_modes = tuple(
        mode for mode in CHIP_MODES if any(str(row["variant"]).endswith(mode) for row in chains)
    )
    comparisons = _comparisons(
        chains,
        lookaheads,
        chip_modes,
        resamples=arguments.bootstrap_resamples,
        block_length=arguments.moving_block_length,
    )
    first = documents[0]
    assumptions = dict(first["assumptions"])
    assumptions["first_wildcard_last_gameweek"] = {
        key: value
        for doc in documents
        for key, value in dict(doc["assumptions"]["first_wildcard_last_gameweek"]).items()
    }
    assumptions["max_free_transfers"] = {
        key: value
        for doc in documents
        for key, value in dict(doc["assumptions"]["max_free_transfers"]).items()
    }
    document = {
        **{key: first[key] for key in ("created_utc", "provenance", "environment")},
        "contract_version": SEASON_CHAIN_SEASONS_CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "projection_rule": first.get("projection_rule", NAIVE_PROJECTION_RULE),
        "merged_from": [str(path) for path in sources],
        "seasons": seasons,
        "lookaheads": list(lookaheads),
        "chip_modes": list(chip_modes),
        "start_gameweek": first.get("start_gameweek"),
        "end_gameweek": first.get("end_gameweek"),
        "solver_limits": first["solver_limits"],
        "bootstrap": {
            "resamples": arguments.bootstrap_resamples,
            "moving_block_length": arguments.moving_block_length,
            "confidence_level": 0.90,
        },
        "assumptions": assumptions,
        "comparisons": comparisons,
        "chains": chains,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(tuple(seasons), chains, comparisons, assumptions)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if arguments.merge:
        return _merge(arguments)
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    seasons = tuple(value.strip() for value in str(arguments.seasons).split(","))
    if LOCKED_HOLDOUT_SEASON in seasons:
        print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be walked.")
        return 1
    lookaheads = tuple(int(value.strip()) for value in str(arguments.lookaheads).split(","))
    chip_modes = tuple(value.strip() for value in str(arguments.chips).split(","))
    if any(mode not in CHIP_MODES for mode in chip_modes):
        print(f"--chips must be a comma subset of {','.join(CHIP_MODES)}.")
        return 1
    holding_values = parse_holding_values(arguments.chip_holding_values)
    tuned_holding_values = parse_holding_values(arguments.tuned_holding_values)
    tuned_hit_cost = float(arguments.tuned_hit_cost)

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

    chains: list[dict[str, object]] = []
    caps: dict[str, int] = {}
    try:
        for season in seasons:
            counts = season_fixture_counts(arguments.archive_root, season)
            cap = (
                int(arguments.max_free_transfers)
                if arguments.max_free_transfers is not None
                else MAX_FREE_TRANSFERS.get(season, 5)
            )
            caps[season] = cap
            for lookahead in lookaheads:
                for mode in chip_modes:
                    chips = mode != "off"
                    if mode == "tuned":
                        transfer_config = TransferPlanningConfig(
                            max_free_transfers=cap,
                            transfer_hit_cost_points=tuned_hit_cost,
                            chip_holding_value_points=tuned_holding_values,
                        )
                    else:
                        transfer_config = TransferPlanningConfig(
                            max_free_transfers=cap,
                            chip_holding_value_points=(
                                holding_values if mode in {"value", "hybrid"} else {}
                            ),
                        )
                    label = _variant_label(lookahead, mode)
                    LOGGER.info("Season %s: %s", season, label)
                    config = SeasonChainConfig(
                        season=season,
                        lookahead=lookahead,
                        start_gameweek=arguments.start_gameweek,
                        end_gameweek=arguments.end_gameweek,
                        form_window=arguments.form_window,
                        candidate_pool_per_position=arguments.candidate_pool_per_position,
                        cheap_pool_per_position=arguments.cheap_pool_per_position,
                        chip_windows=chip_windows_for(season) if chips else (),
                        chip_policy=(
                            "double_gameweeks_only"
                            if mode == "reserve"
                            else "hybrid"
                            if mode in {"hybrid", "tuned"}
                            else "planner"
                        ),
                        projection_rule=str(arguments.projection_rule),
                        optimization_config=optimization_config,
                        transfer_config=transfer_config,
                    )
                    started = datetime.now(UTC)
                    result = SeasonChain(panel, counts, config).run()
                    elapsed = (datetime.now(UTC) - started).total_seconds()
                    record = chain_record(result, label, elapsed)
                    chains.append(record)
                    LOGGER.info(
                        "  net %.0f (realized %.0f, hits %.0f), transfers %d, chips %s, "
                        "proven %.2f, %.0fs",
                        result.net_points,
                        result.realized_points,
                        result.transfer_hit_points,
                        result.transfer_count,
                        result.chips_played or "-",
                        result.proven_share,
                        elapsed,
                    )
    except ExperimentError as error:
        print(f"Could not walk the season chains:\n  {error}")
        return 1

    comparisons = _comparisons(
        chains,
        lookaheads,
        chip_modes,
        resamples=arguments.bootstrap_resamples,
        block_length=arguments.moving_block_length,
    )

    assumptions: dict[str, object] = {
        "first_wildcard_last_gameweek": {
            season: FIRST_WILDCARD_LAST_GAMEWEEK.get(season, 19) for season in seasons
        },
        "max_free_transfers": caps,
        "chip_windows_source": "assumed; not read from a capture",
        "projection_rule": str(arguments.projection_rule),
        "chip_holding_values_points": (
            holding_values if {"value", "hybrid"} & set(chip_modes) else None
        ),
        "tuned_mode": (
            {"holding_values_points": tuned_holding_values, "planning_hit_cost": tuned_hit_cost}
            if "tuned" in chip_modes
            else None
        ),
        "sell_rule": "purchase plus half of any rise, rounded down to a tenth",
        "automatic_substitutions": False,
        "free_hit_modelled": True,
    }
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": SEASON_CHAIN_SEASONS_CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "projection_rule": str(arguments.projection_rule),
        "seasons": list(seasons),
        "lookaheads": list(lookaheads),
        "chip_modes": list(chip_modes),
        "start_gameweek": arguments.start_gameweek,
        "end_gameweek": arguments.end_gameweek,
        "solver_limits": {
            "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
            "solver_deterministic_time_limit": optimization_config.solver_deterministic_time_limit,
        },
        "bootstrap": {
            "resamples": arguments.bootstrap_resamples,
            "moving_block_length": arguments.moving_block_length,
            "confidence_level": 0.90,
        },
        "assumptions": assumptions,
        "comparisons": comparisons,
        "chains": chains,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(seasons, chains, comparisons, assumptions)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
