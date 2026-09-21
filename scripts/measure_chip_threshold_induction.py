r"""Compute chip holding thresholds by backward induction, and walk the chains they hold.

    python -m scripts.measure_chip_threshold_induction --stage 1
    python -m scripts.measure_chip_threshold_induction --stage 2

Protocol: ``docs/chip_threshold_induction_prereg.md``. Stage 1 reads
``docs/chip_forecast_rule.json``, computes each season's thresholds from the other seasons'
chains only, and replays the sixteen chips on the recorded weeks; it runs no solver. Stage 2
walks the ``induction`` chains and compares them with the chains that record already holds,
which are not walked again. The stage 1 record is committed before stage 2 runs, and stage 2
is skipped when the replay plays every chip in the gameweek the ``decaying`` chain did.

The locked holdout is never loaded; the runner names its seasons and refuses to overwrite its
record.
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
from scripts.measure_chip_forecast_rule import (
    HISTORY_SEASONS,
    HIT_COST,
    HOLDING_VALUES,
    expired_chips,
    two_set_windows,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.chip_threshold import (
    CHIP_THRESHOLD_INDUCTION_CONTRACT_VERSION,
    CHIP_VALUE_FIELDS,
    WindowThresholds,
    classify_gameweek_kinds,
    leave_one_season_out_thresholds,
)
from squadopt.experiments.season_chain import (
    ChipWindowRule,
    SeasonChain,
    SeasonChainConfig,
    decayed_holding_value,
)
from squadopt.experiments.season_chain_runs import (
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    chain_comparison,
    chain_record,
    season_fixture_counts,
)
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger("chip_threshold_induction")
DEFAULT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
#: The arm whose squads are nearest the ones the new arm holds, fixed by the protocol.
SOURCE_ARM = "decaying"
#: The comparison the protocol says decides, and the two it says to report beside it.
COMPARISONS: tuple[tuple[str, str], ...] = (
    ("induction", "decaying"),
    ("induction", "threshold_only"),
    ("induction", "off"),
)
DEFAULT_RECORD = REPOSITORY_ROOT / "docs" / "chip_forecast_rule.json"
DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "chip_threshold_induction.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "chip_threshold_induction.md"


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stage", type=int, choices=(1, 2), required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--chip-forecast-record", type=Path, default=DEFAULT_RECORD)
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    parser.add_argument("--block-length", type=int, default=4)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument(
        "--render-only",
        action="store_true",
        help=(
            "rewrite the markdown from the committed record and measure nothing. The record is "
            "read, never written, so this cannot re-read a gate"
        ),
    )
    return parser.parse_args(argv)


def covered_windows(windows: Sequence[ChipWindowRule]) -> tuple[ChipWindowRule, ...]:
    """The windows of the chips the induction covers; the others keep the decay."""

    return tuple(window for window in windows if window.name in CHIP_VALUE_FIELDS)


def replay(
    season: str,
    weeks: Sequence[Mapping[str, object]],
    thresholds: WindowThresholds,
    played: Mapping[str, str],
) -> dict[str, Any]:
    """The gameweek the rule would have played one chip in, beside the one the chain did.

    The rule is the protocol's: the first gameweek of the window whose recorded value
    exceeds its threshold. It is read off the recorded weeks, so it ignores that playing a
    chip in another week moves the transfers of every later one; it carries no verdict.
    """

    column = CHIP_VALUE_FIELDS[thresholds.chip]
    by_gameweek = {int(str(week["gameweek"])): week for week in weeks}
    chosen: int | None = None
    for gameweek in thresholds.gameweeks:
        week = by_gameweek.get(gameweek)
        value = None if week is None else week.get(column)
        if value is None:
            continue
        if float(str(value)) > thresholds.threshold_at(gameweek):
            chosen = gameweek
            break
    chain_week = next(
        (
            int(week)
            for week, name in played.items()
            if name == thresholds.chip and _covers(thresholds, int(week))
        ),
        None,
    )

    def seen(gameweek: int | None) -> dict[str, object]:
        if gameweek is None:
            return {"gameweek": None}
        week = by_gameweek.get(gameweek, {})
        realized = (
            "captain_realized_points" if thresholds.chip == "3xc" else "bench_realized_points"
        )
        return {
            "gameweek": gameweek,
            "threshold": thresholds.threshold_at(gameweek),
            "projected_value": week.get(column),
            "realized_value": week.get(realized),
        }

    return {
        "season": season,
        "chip": thresholds.chip,
        "window": f"{thresholds.start_gameweek}-{thresholds.stop_gameweek}",
        "induction": seen(chosen),
        "chain": seen(chain_week),
        "same_gameweek": chosen == chain_week,
        "pooled_fallback_kinds": list(thresholds.pooled_fallback_kinds),
        "sample_seasons": list(thresholds.sample_seasons),
        "sample_sizes": dict(thresholds.sample_sizes),
    }


def _covers(thresholds: WindowThresholds, gameweek: int) -> bool:
    return thresholds.start_gameweek <= gameweek <= thresholds.stop_gameweek


def unpriced_gameweeks(thresholds: WindowThresholds) -> list[int]:
    """The window's gameweeks the threshold table does not price.

    A window covers a range; the table holds a threshold only for the gameweeks the season's
    classification knows. A gameweek it does not know has no threshold, so the schedule does
    not price it and the chain falls back to the linear decay there, quietly. The archive
    classifies every gameweek of every development season, so this is expected to be empty;
    it is counted and recorded rather than trusted, because a silent fallback is exactly the
    thing a record should not leave to a reader to work out.
    """

    priced = set(thresholds.gameweeks)
    return [
        gameweek
        for gameweek in range(thresholds.start_gameweek, thresholds.stop_gameweek + 1)
        if gameweek not in priced
    ]


def _decay_line(chip: str, thresholds: WindowThresholds) -> dict[str, float]:
    window = ChipWindowRule(chip, thresholds.start_gameweek, thresholds.stop_gameweek)
    constant = float(HOLDING_VALUES.get(chip, 0.0))
    return {
        str(gameweek): decayed_holding_value(constant, window, gameweek)
        for gameweek in thresholds.gameweeks
    }


def _stage_one(arguments: argparse.Namespace) -> dict[str, Any]:
    document = json.loads(arguments.chip_forecast_record.read_text(encoding="utf-8"))
    chains = [chain for chain in document["chains"] if chain["variant"] == SOURCE_ARM]
    seasons = sorted(str(chain["season"]) for chain in chains)
    if LOCKED_HOLDOUT_SEASON in seasons:
        raise SystemExit("The locked holdout is not read.")
    if seasons != sorted(DEFAULT_SEASONS):
        raise SystemExit(
            f"The {SOURCE_ARM!r} arm covers {seasons!r}, not {list(DEFAULT_SEASONS)!r}."
        )
    windows = covered_windows(two_set_windows())
    kinds_by_season = {
        season: classify_gameweek_kinds(season_fixture_counts(arguments.archive_root, season))
        for season in seasons
    }
    by_season = leave_one_season_out_thresholds(
        chains, kinds_by_season, windows, variant=SOURCE_ARM
    )
    weeks_by_season = {str(chain["season"]): chain["weeks"] for chain in chains}
    played_by_season = {str(chain["season"]): chain["chips_played"] for chain in chains}
    replays = [
        replay(season, weeks_by_season[season], thresholds, played_by_season[season])
        for season in seasons
        for thresholds in by_season[season]
    ]
    return {
        "contract_version": CHIP_THRESHOLD_INDUCTION_CONTRACT_VERSION,
        "prereg": "docs/chip_threshold_induction_prereg.md",
        "stage": 1,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "source_record": str(arguments.chip_forecast_record.name),
        "source_arm": SOURCE_ARM,
        "source_created_utc": document.get("created_utc"),
        "seasons": seasons,
        "locked_holdout_accessed": False,
        "covered_chips": sorted(CHIP_VALUE_FIELDS),
        "gameweek_kinds": {
            season: {str(week): kind for week, kind in sorted(kinds.items())}
            for season, kinds in kinds_by_season.items()
        },
        "thresholds": {
            season: [
                {
                    **item.as_record(),
                    "linear_decay": _decay_line(item.chip, item),
                    "unpriced_gameweeks": unpriced_gameweeks(item),
                }
                for item in by_season[season]
            ]
            for season in seasons
        },
        "unpriced_gameweeks_total": sum(
            len(unpriced_gameweeks(item)) for season in seasons for item in by_season[season]
        ),
        "replay": replays,
        "replay_agrees_everywhere": all(item["same_gameweek"] for item in replays),
        "stage_two_runs": not all(item["same_gameweek"] for item in replays),
    }


def deciding_comparison(document: Mapping[str, Any]) -> str:
    """Which comparison the protocol says decides, read from the forecast record.

    ``docs/chip_threshold_induction_prereg.md`` makes this conditional rather than fixed:
    ``induction - decaying`` decides, "if the pending chip forecast measurement drops the
    reservation, the forecast's rule is ``threshold_only``, and then
    ``induction - threshold_only`` is the comparison that decides".

    Whether the reservation dropped is not a judgement either. ``chip_forecast_prereg.md``'s
    amendment fixes it: ``decaying - threshold_only`` "decides whether the forecast keeps the
    reservation: it keeps it when the pooled difference is positive, and drops it otherwise".
    So this reads that comparison out of the committed record and applies the rule.

    It is a predicate rather than a constant on purpose. The name was hard-coded here as
    ``induction_minus_decaying``, which is the branch the conditional does **not** take on the
    committed record, and a constant cannot notice that. Deriving it also means the choice
    cannot be revisited once stage 2's own numbers are visible, which is the failure a
    pre-registration exists to prevent.
    """

    for comparison in document["comparisons"]:
        if str(comparison["variant"]) == "decaying" and str(comparison["baseline"]) == (
            "threshold_only"
        ):
            difference = float(comparison["mean_weekly_advantage_points"])
            kept = difference > 0.0
            return "induction_minus_decaying" if kept else "induction_minus_threshold_only"
    raise SystemExit(
        "The chip forecast record carries no `decaying - threshold_only` comparison, so which "
        "arm the forecast's rule is cannot be read and the deciding comparison cannot be named."
    )


def _stage_two(arguments: argparse.Namespace, stage_one: Mapping[str, Any]) -> dict[str, Any]:
    document = json.loads(arguments.chip_forecast_record.read_text(encoding="utf-8"))
    seasons = list(stage_one["seasons"])
    windows = two_set_windows()
    optimization = measurement_optimization_config()
    panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
    chains: list[dict[str, Any]] = [
        chain
        for chain in document["chains"]
        if chain["variant"] in {"decaying", "threshold_only", "off"}
    ]
    for season in seasons:
        schedules = tuple(
            WindowThresholds(
                chip=str(item["chip"]),
                start_gameweek=int(item["start_gameweek"]),
                stop_gameweek=int(item["stop_gameweek"]),
                # Sorted by the integer gameweek, never by the string key a JSON object carries:
                # "10" sorts before "9" as text, and the pair would keep its partner while the
                # window read backwards.
                gameweeks=tuple(sorted(int(week) for week in item["thresholds"])),
                thresholds=tuple(
                    float(item["thresholds"][key]) for key in sorted(item["thresholds"], key=int)
                ),
                pooled_fallback_kinds=tuple(item["pooled_fallback_kinds"]),
                sample_seasons=tuple(item["sample_seasons"]),
                sample_sizes=tuple(
                    (kind, int(size)) for kind, size in item["sample_sizes"].items()
                ),
            ).as_schedule()
            for item in stage_one["thresholds"][season]
        )
        counts = season_fixture_counts(arguments.archive_root, season)
        config = SeasonChainConfig(
            season=season,
            lookahead=1,
            chip_windows=windows,
            # The two covered chips are held by their schedules, so their reservation is
            # lifted; the free hit keeps the one `decaying` gave it.
            chip_policy="hybrid",
            chip_threshold="induction",
            chip_holding_schedule=schedules,
            optimization_config=optimization,
            transfer_config=TransferPlanningConfig(
                max_free_transfers=MAX_FREE_TRANSFERS.get(season, 5),
                transfer_hit_cost_points=HIT_COST,
                chip_holding_value_points=HOLDING_VALUES,
            ),
        )
        LOGGER.info("Season %s: induction", season)
        started = datetime.now(UTC)
        result = SeasonChain(panel, counts, config).run()
        record = chain_record(result, "induction", (datetime.now(UTC) - started).total_seconds())
        record["expired_chips"] = expired_chips(record, windows)
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
    walked = [chain for chain in chains if chain["variant"] == "induction"]
    return {
        "stage": 2,
        "generated_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "chains_walked_here": [chain["variant"] for chain in walked],
        "chains_read_from_the_forecast_record": sorted(
            {str(chain["variant"]) for chain in chains if chain["variant"] != "induction"}
        ),
        "solver": {
            "deterministic_time_limit": optimization.solver_deterministic_time_limit,
            "wall_time_limit_seconds": optimization.solver_time_limit_seconds,
            "mean_proven_share": sum(float(str(c["proven_share"])) for c in walked) / len(walked),
        },
        "chains": chains,
        "comparisons": comparisons,
        "deciding_comparison": deciding_comparison(document),
        "deciding_comparison_source": (
            "Read from the forecast record rather than fixed here: "
            "`chip_forecast_prereg.md`'s amendment keeps the reservation when "
            "`decaying - threshold_only` is positive and drops it otherwise, and "
            "`chip_threshold_induction_prereg.md` says the dropped case makes "
            "`induction - threshold_only` the comparison that decides. Both are reported "
            "either way, as that protocol requires."
        ),
    }


def _threshold_table(record: Mapping[str, Any]) -> list[str]:
    lines = [
        "",
        "| Season | Chip | Window | Gameweek | Induction | Linear decay | Pooled fallback |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for season, items in record["thresholds"].items():
        for item in items:
            decay = item["linear_decay"]
            # Sorted numerically here rather than trusted from the mapping. The thresholds are
            # keyed by gameweek and `write_json` writes with `sort_keys=True`, so a record read
            # back from disk offers them as text: 1, 10, 11 ... 19, 2, 3. Stage 1 rendered from
            # the in-memory mapping and looked right; stage 2 re-renders from the file and did
            # not. The table's whole point is a threshold falling across a window, so the order
            # is part of its meaning and the renderer imposes it instead of inheriting it.
            for gameweek, value in sorted(
                item["thresholds"].items(), key=lambda pair: int(pair[0])
            ):
                lines.append(
                    f"| {season} | `{item['chip']}` | "
                    f"{item['start_gameweek']}-{item['stop_gameweek']} | {gameweek} | "
                    f"{float(value):.2f} | {float(decay[gameweek]):.2f} | "
                    f"{', '.join(item['pooled_fallback_kinds']) or 'none'} |"
                )
    return lines


def _markdown(record: Mapping[str, Any]) -> str:
    lines = [
        "# A chip's holding threshold by backward induction",
        "",
        f"Contract `{record['contract_version']}`. Protocol: "
        "`docs/chip_threshold_induction_prereg.md`. Thresholds are computed for each season "
        f"from the other seasons' `{record['source_arm']}` chains only, over "
        f"{', '.join(record['seasons'])}. No solver runs in stage 1.",
        "",
        "## The replay on the recorded weeks",
        "",
        "Descriptive: playing a chip in another week moves the transfers of every later "
        "week, which a replay cannot see, so it carries no verdict. It decides only whether "
        "stage 2 runs.",
        "",
        "| Season | Chip | Window | Induction | Its value | Chain | Its value | Same |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in record["replay"]:
        induction, chain = item["induction"], item["chain"]
        lines.append(
            f"| {item['season']} | `{item['chip']}` | {item['window']} | "
            f"{induction['gameweek'] or 'none'} | "
            f"{_number(induction.get('projected_value'))} | {chain['gameweek'] or 'none'} | "
            f"{_number(chain.get('projected_value'))} | "
            f"{'yes' if item['same_gameweek'] else 'no'} |"
        )
    lines += [
        "",
        (
            "The replay plays every chip in the gameweek the chain did, so the two rules are "
            "the same rule on these seasons and stage 2 is not run."
            if record["replay_agrees_everywhere"]
            else "The replay differs somewhere, so stage 2 runs."
        ),
        "",
        "## The thresholds",
        "",
        (
            "Every gameweek of every covered window is priced by the table."
            if record["unpriced_gameweeks_total"] == 0
            else f"**{record['unpriced_gameweeks_total']} gameweeks of the covered windows are "
            "not priced by the table** and fall back to the linear decay; they are named per "
            "window in the JSON."
        ),
    ]
    lines += _threshold_table(record)
    stage_two = record.get("stage_two")
    if isinstance(stage_two, dict):
        lines += [
            "",
            "## Stage 2: the chains",
            "",
            "| Season | Arm | Net | Chips played | Expired unplayed |",
            "| --- | --- | ---: | --- | --- |",
        ]
        for chain in stage_two["chains"]:
            # Numerically, for the reason the threshold table is: this mapping is keyed by
            # gameweek and comes back from JSON sorted as text, so a season's chips read
            # GW13, GW2, GW20, GW3 and the order a reader takes for chronology is not one.
            played = ", ".join(
                f"GW{week} {name}"
                for week, name in sorted(
                    chain["chips_played"].items(), key=lambda pair: int(pair[0])
                )
            )
            lines.append(
                f"| {chain['season']} | `{chain['variant']}` | {chain['net_points']:.0f} | "
                f"{played or 'none'} | {', '.join(chain['expired_chips']) or 'none'} |"
            )
        lines += [
            "",
            "| Comparison | Mean per season | Mean per gameweek | 90% interval | Seasons ahead |",
            "| --- | ---: | ---: | --- | ---: |",
        ]
        for comparison in stage_two["comparisons"]:
            interval = comparison["weekly_advantage_block_bootstrap_interval"]
            shown = "n/a" if interval is None else f"[{interval[0]:+.2f}, {interval[1]:+.2f}]"
            lines.append(
                f"| `{comparison['variant']}` minus `{comparison['baseline']}` | "
                f"{comparison['mean_season_net_advantage_points']:+.1f} | "
                f"{comparison['mean_weekly_advantage_points']:+.2f} | {shown} | "
                f"{comparison['positive_season_share']:.2f} |"
            )
        lines += ["", *_stage_two_verdict(stage_two)]
    return "\n".join(lines) + "\n"


def _stage_two_verdict(stage_two: Mapping[str, Any]) -> list[str]:
    """What the deciding comparison's interval licenses, computed rather than written.

    The record used to end at the comparison table, so its verdict lived only in the index row
    and the pull request. A later reader finds the artifact, and the figure nearest the top of
    that table is a positive mean whose interval contains zero and whose sign three of the four
    seasons disagree with. Both sentences below are derived from the record so that neither the
    verdict nor the one-season caveat can drift from the numbers above them.
    """

    name = str(stage_two["deciding_comparison"])
    baseline = name.removeprefix("induction_minus_")
    (deciding,) = [
        comparison
        for comparison in stage_two["comparisons"]
        if str(comparison["baseline"]) == baseline
    ]
    interval = deciding["weekly_advantage_block_bootstrap_interval"]
    separated = interval is not None and float(interval[0]) > 0.0
    seasons = deciding["season_net_advantage_points"]
    behind = sorted(season for season, value in seasons.items() if float(value) < 0.0)
    lines = [
        f"**Deciding comparison: `induction` minus `{baseline}`.** It is not fixed in this "
        "runner: the forecast keeps its reservation only when `decaying - threshold_only` is "
        "positive, the committed forecast record says otherwise, and this protocol makes the "
        "dropped case decide on `threshold_only`.",
        "",
    ]
    if separated:
        lines.append(
            "Its interval lies entirely above zero, which is the one condition under which the "
            "protocol replaces the linear decay."
        )
    else:
        lines.append(
            "**Verdict: `not separated`.** Its interval does not lie entirely above zero, so by "
            "the rule fixed before this ran the linear decay stays the forecast's threshold and "
            "nothing is promoted."
        )
    if behind:
        lines += [
            "",
            f"**The mean is not what the seasons did.** `induction` is behind in "
            f"{len(behind)} of {len(seasons)} seasons ({', '.join(behind)}), so a positive "
            "pooled figure here is carried by the rest. Read the per-season column before "
            "quoting the mean.",
        ]
    return lines


def _number(value: object) -> str:
    return f"{float(str(value)):.2f}" if value is not None else "n/a"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.chip_forecast_record.is_file():
        print(f"{arguments.chip_forecast_record} does not exist; run the chip forecast first.")
        return 1
    if arguments.render_only:
        # The record is the measurement; the markdown is a view of it. Re-rendering reads the
        # JSON and never writes it, so a verdict cannot be re-read and no number can move.
        if not arguments.json_output.is_file():
            print(f"{arguments.json_output} does not exist; there is nothing to render.")
            return 1
        record = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        write_text(arguments.markdown_output, _markdown(record))
        print(f"Rendered {arguments.markdown_output} from {arguments.json_output}.")
        return 0
    if arguments.stage == 1:
        if arguments.json_output.exists():
            print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
            return 1
        record = _stage_one(arguments)
    else:
        if not arguments.json_output.is_file():
            print(f"{arguments.json_output} does not exist; commit stage 1 before stage 2.")
            return 1
        record = json.loads(arguments.json_output.read_text(encoding="utf-8"))
        if record.get("stage_two") is not None:
            print("Stage 2 is already in the record; retire it in its own commit first.")
            return 1
        if not record["stage_two_runs"]:
            print("The replay agreed everywhere, so the protocol does not run stage 2.")
            return 1
        record["stage_two"] = _stage_two(arguments, record)
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
