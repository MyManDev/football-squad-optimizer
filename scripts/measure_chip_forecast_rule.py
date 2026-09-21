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
  its half and the reservation lifted in a half's last gameweek;
* ``threshold_only``: the decaying holding values with no reservation at all, which asks
  whether saving the bench boost for a double still pays when a double may never come
  before the half ends.

The record keeps each chain, the chips played and the chips that expired unplayed, and the
paired comparisons the protocol names. Nights only; it refuses to overwrite its record.

    python -m scripts.measure_chip_forecast_rule --archive-root <archive>
"""

import argparse
import json
import logging
from collections.abc import Mapping, Sequence
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
#: Keys a reading of a record may add to a chain. A walk writes them too; what matters is
#: that comparing a record with its own rereading ignores them on both sides, or the guard
#: below would call a record that gained one of them a record whose chains changed.
DERIVED_CHAIN_KEYS = ("max_relative_gap", "chip_windows_offered")
ARMS = ("off", "planner", "fixed", "decaying", "threshold_only")
COMPARISONS = (
    ("decaying", "fixed"),
    ("decaying", "threshold_only"),
    # The arm the two verdicts above adopt, against the arm with the highest pooled net. Without
    # it the adopted rule is never read directly against the rule it displaces, and the reader has
    # to chain two comparisons that were each measured with their own interval.
    ("threshold_only", "fixed"),
    ("fixed", "off"),
    ("decaying", "off"),
    ("threshold_only", "off"),
    ("planner", "off"),
)


def max_relative_gap(record: Mapping[str, Any]) -> float | None:
    """The widest optimality gap of one chain's weeks, or None when no week states one.

    The chain already records ``mean_relative_gap``, and a proved week enters that mean as a
    zero, so a chain with one week at a quarter of its objective reads under one per cent. The
    widest week is what says whether any number in the record rests on an unproved solve.
    """

    gaps = [
        float(str(week["relative_gap"]))
        for week in record.get("weeks", ())
        if week.get("relative_gap") is not None
    ]
    return max(gaps) if gaps else None


def derived_blocks(
    chains: list[dict[str, Any]], *, resamples: int, block_length: int
) -> dict[str, Any]:
    """Everything the record holds that is arithmetic over the chains it already walked.

    Kept apart from the walk so that a committed record can be re-read without solving
    anything again: the chains are the measurement, and these are a reading of them.
    """

    return {
        "comparisons": [
            comparison
            for label, baseline in COMPARISONS
            if (
                comparison := chain_comparison(
                    label, baseline, chains, resamples=resamples, block_length=block_length
                )
            )
            is not None
        ],
        "bootstrap": {
            "resamples": resamples,
            "block_length": block_length,
            "interval_level": 0.90,
            "unit": "gameweek, resampled in blocks within season",
        },
    }


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
    parser.add_argument(
        "--recompute",
        action="store_true",
        help=(
            "Read the committed record and rewrite only what is arithmetic over the chains it "
            "already holds. No season is walked and no solver runs; the chains are copied "
            "through unchanged and the run that produced them keeps its own identity."
        ),
    )
    return parser.parse_args(argv)


def _expiries(chain: Mapping[str, Any]) -> str:
    """What a chain lost, and ``n/a`` for the arm that was never offered a chip.

    ``off`` runs with no windows at all, so nothing of it could expire; printing ``none`` there
    puts it in the same cell as the arms that were offered eight chips and played every one.
    """

    if not chain.get("chip_windows_offered", True):
        return "n/a, no chip was offered"
    return ", ".join(chain["expired_chips"]) or "none"


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
            f"{_expiries(chain)} |"
        )
    unproved = [
        (chain["season"], chain["variant"], chain["max_relative_gap"])
        for chain in record["chains"]
        if chain.get("max_relative_gap")
    ]
    if unproved:
        lines += [
            "",
            "Weeks that returned an incumbent rather than a proof, by the widest gap of the "
            "chain that holds them. The mean gap each chain records counts every proved week "
            "as a zero, so it is not the number to read here:",
            "",
            "| Season | Arm | Widest weekly gap | Mean over all weeks |",
            "| --- | --- | ---: | ---: |",
        ]
        for season, variant, widest in unproved:
            mean = next(
                c["mean_relative_gap"]
                for c in record["chains"]
                if c["season"] == season and c["variant"] == variant
            )
            lines.append(f"| {season} | `{variant}` | {widest:.4f} | {mean:.4f} |")
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


def recompute(record: dict[str, Any], *, resamples: int, block_length: int) -> dict[str, Any]:
    """The same record, with its derived blocks read again from the chains it already holds.

    The chains are the measurement and are copied through untouched, so this cannot change a
    net, a chip played or a week. What it may change is what the record says *about* them: the
    comparisons it carries, the widest gap of each chain, and the bootstrap settings behind its
    intervals. ``created_utc`` stays the walk's own, and ``recomputed_utc`` says a reading was
    added afterwards, so the record never claims the new blocks came out of the original run.
    """

    chains = [dict(chain) for chain in record["chains"]]
    for chain in chains:
        chain["max_relative_gap"] = max_relative_gap(chain)
        # Written by the walk since this change; a record walked before it says so by its arm.
        chain.setdefault("chip_windows_offered", chain["variant"] != "off")
    return {
        **record,
        "chains": chains,
        "recomputed_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        **derived_blocks(chains, resamples=resamples, block_length=block_length),
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if arguments.recompute:
        if not arguments.json_output.is_file():
            print(f"{arguments.json_output} does not exist; there is nothing to read again.")
            return 1
        committed = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        if committed.get("contract_version") != CONTRACT_VERSION:
            print(f"{arguments.json_output} is not a {CONTRACT_VERSION} record.")
            return 1
        reread = recompute(
            committed,
            resamples=int(arguments.bootstrap_resamples),
            block_length=int(arguments.block_length),
        )

        # The one thing this mode must never do.
        # Strip the derived key from both sides: reading a record twice must be reading the
        # same chains twice, and the second read starts from a record the first one wrote.
        def walked(chains: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
            return [
                {key: value for key, value in chain.items() if key not in DERIVED_CHAIN_KEYS}
                for chain in chains
            ]

        if not reread["chains"] or walked(reread["chains"]) != walked(committed["chains"]):
            print("Recomputing changed a chain; that is not what this mode may do.")
            return 1
        write_json(arguments.json_output, reread)
        write_text(arguments.markdown_output, _markdown(reread))
        print(_markdown(reread))
        return 0
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
            held = arm in {"fixed", "decaying", "threshold_only"}
            config = SeasonChainConfig(
                season=season,
                lookahead=1,
                chip_windows=() if arm == "off" else windows,
                chip_policy="hybrid" if arm in {"fixed", "decaying"} else "planner",
                chip_threshold="fixed" if arm in {"off", "planner", "fixed"} else "decaying",
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
            record["chip_windows_offered"] = arm != "off"
            record["expired_chips"] = [] if arm == "off" else expired_chips(record, windows)
            chains.append(record)
            LOGGER.info(
                "  net %.0f, chips %s, expired %s, proven %.2f",
                result.net_points,
                record["chips_played"],
                record["expired_chips"],
                result.proven_share,
            )
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
        **derived_blocks(
            chains,
            resamples=int(arguments.bootstrap_resamples),
            block_length=int(arguments.block_length),
        ),
    }
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _markdown(document))
    print(_markdown(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
