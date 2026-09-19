"""Measure the chip forecast's rule under two sets of chips, on the development seasons.

The protocol is ``docs/chip_forecast_prereg.md``. 2026-27 gives every chip twice, once in
gameweeks 1 (wildcard and free hit: 2) to 19 and once in 20 to 38, and a chip not played by
the end of its half is lost. No development season had that rule, so it is laid over their
fixtures: each season is walked as a lookahead-1 chain four times,

* ``off``: no chips;
* ``planner``: every open chip offered every week, no holding value ("as soon as it helps");
* ``fixed``: the hybrid reservation with the recorded holding values, constant to the end
  of each half, which is how the committed chains held chips under one set;
* ``decaying``: the same, with each holding value falling linearly to zero at the end of
  its half and the reservation lifted in a half's last gameweek.

The record keeps each chain, the chips played and the chips that expired unplayed, and the
paired comparisons the protocol names. Nights only; it refuses to overwrite its record.

    python -m scripts.measure_chip_forecast_rule --archive-root <archive>
"""

import argparse
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    measurement_optimization_config,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import ChipWindowRule, SeasonChain, SeasonChainConfig
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    chain_comparison,
    chain_record,
    season_fixture_counts,
)
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)

CONTRACT_VERSION = "chip_forecast_rule_v1"
#: One season of prior history ahead of the development population, and nothing else: the
#: loader's own default is every supported season, which includes the locked holdout.
HISTORY_SEASONS = ("2020-21", *DEFAULT_DEVELOPMENT_SEASONS)
HALF_SPLIT = 19
#: The constants of the committed chain records (``run_season_chain_seasons.py``).
HOLDING_VALUES = {"bboost": 20.0, "3xc": 18.0, "wildcard": 12.0, "freehit": 15.0}
HIT_COST = 4.0
ARMS = ("off", "planner", "fixed", "decaying")
COMPARISONS = (("decaying", "fixed"), ("fixed", "off"), ("decaying", "off"), ("planner", "off"))


def two_set_windows() -> tuple[ChipWindowRule, ...]:
    """This season's rule: every chip once per half, wildcard and free hit from gameweek 2."""

    windows: list[ChipWindowRule] = []
    for name, first in (("wildcard", 2), ("freehit", 2), ("bboost", 1), ("3xc", 1)):
        windows.append(ChipWindowRule(name, first, HALF_SPLIT))
        windows.append(ChipWindowRule(name, HALF_SPLIT + 1, 38))
    return tuple(windows)


def expired_chips(record: dict[str, Any], windows: Sequence[ChipWindowRule]) -> list[str]:
    """The windows that closed with their chip unplayed, as ``name:start-stop``."""

    played = {int(week): str(name) for week, name in dict(record["chips_played"]).items()}
    walked = {int(str(week)) for week in record["gameweeks"]}
    expired: list[str] = []
    for window in windows:
        reachable = [week for week in walked if window.covers(week)]
        if not reachable:
            continue
        if not any(name == window.name and window.covers(week) for week, name in played.items()):
            expired.append(f"{window.name}:{window.start_gameweek}-{window.stop_gameweek}")
    return expired


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=",".join(DEFAULT_DEVELOPMENT_SEASONS))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--block-length", type=int, default=4)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "chip_forecast_rule.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "chip_forecast_rule.md"
    )
    return parser.parse_args(argv)


def _markdown(record: dict[str, Any]) -> str:
    lines = [
        "# The chip forecast's rule under two sets of chips",
        "",
        "Protocol: `docs/chip_forecast_prereg.md`. Lookahead-1 chains over "
        f"{', '.join(record['seasons'])}, this season's two chip windows laid over each.",
        "",
        "| Season | Arm | Net | Hits | Chips played | Expired unplayed |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for chain in record["chains"]:
        played = ", ".join(f"GW{week} {name}" for week, name in chain["chips_played"].items())
        lines.append(
            f"| {chain['season']} | `{chain['variant']}` | {chain['net_points']:.0f} | "
            f"{chain['transfer_hit_points']:.0f} | {played or 'none'} | "
            f"{', '.join(chain['expired_chips']) or 'none'} |"
        )
    lines += [
        "",
        "| Comparison | Mean per season | Mean per gameweek | 90% interval, per gameweek | "
        "Seasons ahead |",
        "| --- | ---: | ---: | --- | ---: |",
    ]
    for comparison in record["comparisons"]:
        interval = comparison["weekly_advantage_block_bootstrap_interval"]
        shown = "n/a" if interval is None else f"[{interval[0]:+.2f}, {interval[1]:+.2f}]"
        lines.append(
            f"| `{comparison['variant']}` minus `{comparison['baseline']}` | "
            f"{comparison['mean_season_net_advantage_points']:+.1f} | "
            f"{comparison['mean_weekly_advantage_points']:+.2f} | {shown} | "
            f"{comparison['positive_season_share']:.2f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seasons = [value.strip() for value in str(arguments.seasons).split(",") if value.strip()]
    arms = [value.strip() for value in str(arguments.arms).split(",") if value.strip()]
    if LOCKED_HOLDOUT_SEASON in seasons or any(
        s not in DEFAULT_DEVELOPMENT_SEASONS for s in seasons
    ):
        print("Only the four development seasons may be walked.")
        return 1
    if any(arm not in ARMS for arm in arms):
        print(f"--arms must be a comma subset of {','.join(ARMS)}.")
        return 1
    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
    loaded = sorted(str(value) for value in panel["season"].unique())
    windows = two_set_windows()
    optimization = measurement_optimization_config()
    chains: list[dict[str, Any]] = []
    for season in seasons:
        counts = season_fixture_counts(arguments.archive_root, season)
        cap = MAX_FREE_TRANSFERS.get(season, 5)
        for arm in arms:
            held = arm in {"fixed", "decaying"}
            config = SeasonChainConfig(
                season=season,
                lookahead=1,
                chip_windows=() if arm == "off" else windows,
                chip_policy="hybrid" if held else "planner",
                chip_threshold="decaying" if arm == "decaying" else "fixed",
                optimization_config=optimization,
                transfer_config=TransferPlanningConfig(
                    max_free_transfers=cap,
                    transfer_hit_cost_points=HIT_COST,
                    chip_holding_value_points=HOLDING_VALUES if held else {},
                ),
            )
            LOGGER.info("Season %s: %s", season, arm)
            started = datetime.now(UTC)
            result = SeasonChain(panel, counts, config).run()
            record = chain_record(result, arm, (datetime.now(UTC) - started).total_seconds())
            record["expired_chips"] = [] if arm == "off" else expired_chips(record, windows)
            chains.append(record)
            LOGGER.info(
                "  net %.0f, chips %s, expired %s, proven %.2f",
                result.net_points,
                record["chips_played"],
                record["expired_chips"],
                result.proven_share,
            )
    comparisons = [
        comparison
        for label, baseline in COMPARISONS
        if (
            comparison := chain_comparison(
                label,
                baseline,
                chains,
                resamples=int(arguments.bootstrap_resamples),
                block_length=int(arguments.block_length),
            )
        )
        is not None
    ]
    document: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "protocol": "docs/chip_forecast_prereg.md",
        "created_utc": created_utc,
        "seasons": seasons,
        "loaded_seasons": loaded,
        "locked_holdout_accessed": LOCKED_HOLDOUT_SEASON in loaded,
        "chip_windows": [
            {"name": w.name, "start_gameweek": w.start_gameweek, "stop_gameweek": w.stop_gameweek}
            for w in windows
        ],
        "holding_values": HOLDING_VALUES,
        "planning_hit_cost_points": HIT_COST,
        "solver": {
            "deterministic_time_limit": optimization.solver_deterministic_time_limit,
            "wall_time_limit_seconds": optimization.solver_time_limit_seconds,
            "mean_proven_share": sum(float(str(c["proven_share"])) for c in chains) / len(chains),
        },
        "chains": chains,
        "comparisons": comparisons,
    }
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _markdown(document))
    print(_markdown(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
