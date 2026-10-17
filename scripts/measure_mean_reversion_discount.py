"""Measure a mean-reversion discount for the later weeks of a multi-week plan.

    python -m scripts.measure_mean_reversion_discount --seasons 2024-25 \\
        --development-scope v2 --json-output artifacts/mean_reversion_discount/2024-25.json
    python -m scripts.measure_mean_reversion_discount --merge a.json,b.json,c.json,d.json,e.json
    python -m scripts.measure_mean_reversion_discount --seasons 2024-25 --pilot-gameweeks 8

Protocol: ``docs/research/mean_reversion_discount_prereg.md``. The multi-week planner's later
weeks repeat the decision week's projection scaled by fixture count, and the rolling planner
loses to the weekly control through transfer churn. The candidate,
``mean_reversion_discount_v1`` (`squadopt.experiments.multi_gw_rehearsal`), discounts each
later week's deviation from the position mean by ``rho`` per week of offset, so a far week's
ranking regresses toward the mean while its level stays.

Arms, every one under the member planning policy as far as the chain expresses it (planning
hit cost 8, 4 charged, no banked value, discount 1.0, chips off, sell-on fee halved):

* ``L1``: lookahead 1, the weekly control, with no transfer cap (the live one-week plan has
  none);
* ``L3_naive``: lookahead 3 under ``naive_calendar_scaling_v1``, capped at one transfer a
  week with a second allowed from two banked free transfers (the member window's cap);
* ``L3_mr_<rho>``: lookahead 3 under ``mean_reversion_discount_v1`` at each ``--rhos`` value,
  same cap.

One season per process is the intended use: run each season to its own ``--json-output``
under ``artifacts/`` and combine them with ``--merge``, which writes the committed record,
its Markdown twin and the per-week expansion under ``artifacts/mean_reversion_discount/``.
``--pilot-gameweeks`` walks the first N decision gameweeks only, for timing, and refuses to
write under ``docs/``. Measurement only. The locked 2025-26 holdout is refused under
``--development-scope v1``; ``v2`` admits it as declared development data, never as a test.
"""

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    measurement_optimization_config,
    repository_provenance,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    MEAN_REVERSION_PROJECTION_RULE,
    NAIVE_PROJECTION_RULE,
    SEASON_CHAIN_CONTRACT_VERSION,
    ExperimentError,
    SeasonChain,
    SeasonChainConfig,
)
from squadopt.experiments.season_chain_runs import (
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    chain_comparison,
    chain_record,
    chain_rows,
    season_fixture_counts,
)
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
CONTRACT_VERSION = "mean_reversion_discount_v1"
PROTOCOL_PATH = "docs/research/mean_reversion_discount_prereg.md"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25,2025-26"
DEFAULT_RHOS = "0.75,0.9,0.6"
PRIMARY_RHO = 0.75
LOOKAHEAD = 3
PLANNING_HIT_COST = 8.0
HIT_POINTS_CHARGED = 4.0
NOISE_FLOOR_POINTS_PER_GAMEWEEK = 1.5
MAX_LOSING_SEASONS = 1
REVERSAL_WINDOW_GAMEWEEKS = 3
DEFAULT_DETERMINISTIC_TIME_LIMIT = 8.0
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "mean_reversion_discount"
DOCS_ROOT = REPOSITORY_ROOT / "docs"
RECORD_JSON = DOCS_ROOT / "research" / "mean_reversion_discount.json"
RECORD_MARKDOWN = DOCS_ROOT / "research" / "mean_reversion_discount.md"
CONTROL_LABEL = "L1"
NAIVE_LABEL = "L3_naive"


def rho_label(rho: float) -> str:
    return f"L3_mr_{rho:g}"


@dataclass(frozen=True, slots=True)
class Arm:
    """One chain configuration of the measurement, named."""

    label: str
    config: SeasonChainConfig


def _member_transfer_config(season: str, *, capped: bool) -> TransferPlanningConfig:
    """The member planning policy, with the member window's cap when ``capped``."""

    return TransferPlanningConfig(
        max_free_transfers=MAX_FREE_TRANSFERS.get(season, 5),
        transfer_hit_cost_points=PLANNING_HIT_COST,
        hit_points_charged=HIT_POINTS_CHARGED,
        banked_transfer_value_points=0.0,
        horizon_discount_factor=1.0,
        max_transfers_per_gameweek=1 if capped else None,
        allow_two_free_transfers=capped,
        chip_holding_value_points={},
    )


def build_arms(
    season: str,
    rhos: Sequence[float],
    optimization_config: OptimizationConfig,
    *,
    end_gameweek: int | None = None,
) -> tuple[Arm, ...]:
    """The arms of the protocol for one season, in the order they are run.

    The weekly control has no cap; every three-week arm carries the member window's cap of
    one transfer a week with a second allowed from two banked free transfers. Chips are off
    in every arm.
    """

    shared = {
        "season": season,
        "end_gameweek": end_gameweek,
        "form_window": 5,
        "candidate_pool_per_position": 20,
        "cheap_pool_per_position": 8,
        "chip_windows": (),
        "hit_points_charged": HIT_POINTS_CHARGED,
        "sell_on_fee_halved": True,
        "optimization_config": optimization_config,
    }
    arms = [
        Arm(
            CONTROL_LABEL,
            SeasonChainConfig(
                lookahead=1,
                projection_rule=NAIVE_PROJECTION_RULE,
                transfer_config=_member_transfer_config(season, capped=False),
                **shared,  # type: ignore[arg-type]
            ),
        ),
        Arm(
            NAIVE_LABEL,
            SeasonChainConfig(
                lookahead=LOOKAHEAD,
                projection_rule=NAIVE_PROJECTION_RULE,
                transfer_config=_member_transfer_config(season, capped=True),
                **shared,  # type: ignore[arg-type]
            ),
        ),
    ]
    for rho in rhos:
        arms.append(
            Arm(
                rho_label(rho),
                SeasonChainConfig(
                    lookahead=LOOKAHEAD,
                    projection_rule=MEAN_REVERSION_PROJECTION_RULE,
                    mean_reversion_factor=float(rho),
                    transfer_config=_member_transfer_config(season, capped=True),
                    **shared,  # type: ignore[arg-type]
                ),
            )
        )
    return tuple(arms)


ChainFactory = Callable[[object, object, SeasonChainConfig], SeasonChain]


def run_season(
    panel: object,
    counts: object,
    arms: Sequence[Arm],
    *,
    chain_factory: ChainFactory = SeasonChain,
) -> list[dict[str, object]]:
    """Walk every arm of one season and return its chain records, weeks included."""

    records: list[dict[str, object]] = []
    for arm in arms:
        LOGGER.info("Season %s: %s", arm.config.season, arm.label)
        started = datetime.now(UTC)
        result = chain_factory(panel, counts, arm.config).run()
        elapsed = (datetime.now(UTC) - started).total_seconds()
        record = chain_record(result, arm.label, elapsed)
        record["mean_reversion_factor"] = arm.config.mean_reversion_factor
        record["seconds_per_decision"] = elapsed / max(1, len(result.weeks))
        records.append(record)
        LOGGER.info(
            "  net %.0f (realized %.0f, hits %.0f), transfers %d, proven %.2f, %.0fs (%.1fs/week)",
            result.net_points,
            result.realized_points,
            result.transfer_hit_points,
            result.transfer_count,
            result.proven_share,
            elapsed,
            elapsed / max(1, len(result.weeks)),
        )
    return records


# -- reading the chains -----------------------------------------------------------------


def reversal_count(weeks: Sequence[Mapping[str, object]]) -> int:
    """Players sold within ``REVERSAL_WINDOW_GAMEWEEKS`` gameweeks of being bought.

    A purchase is a player in the squad after one decision who was not in it after the
    previous one; the opening squad is not a purchase. A sale of a purchased player at a
    decision gameweek at most three gameweeks after the purchase's is a reversal.
    """

    bought_at: dict[str, int] = {}
    reversals = 0
    previous: set[str] | None = None
    for week in weeks:
        gameweek = int(str(week["gameweek"]))
        squad = {str(player) for player in week["squad_player_ids"]}  # type: ignore[union-attr]
        if previous is not None:
            for player in previous - squad:
                bought = bought_at.pop(player, None)
                if bought is not None and gameweek - bought <= REVERSAL_WINDOW_GAMEWEEKS:
                    reversals += 1
            for player in squad - previous:
                bought_at[player] = gameweek
        previous = squad
    return reversals


def chain_summary(record: Mapping[str, object]) -> dict[str, object]:
    """What the committed record keeps of one chain: totals and a compact weekly series."""

    weeks = chain_rows(record["weeks"])
    gaps = [float(str(w["relative_gap"])) for w in weeks if w["relative_gap"] is not None]
    return {
        "season": record["season"],
        "variant": record["variant"],
        "lookahead": record["lookahead"],
        "mean_reversion_factor": record.get("mean_reversion_factor"),
        "decisions": record["decisions"],
        "gameweeks": record["gameweeks"],
        "realized_points": record["realized_points"],
        "transfer_hit_points": record["transfer_hit_points"],
        "net_points": record["net_points"],
        "transfer_count": record["transfer_count"],
        "paid_transfer_count": record["paid_transfer_count"],
        "reversals": reversal_count(weeks),
        "carried_blank_rows": record["carried_blank_rows"],
        "carried_unexplained_rows": record["carried_unexplained_rows"],
        "proven_share": record["proven_share"],
        "proven_decisions": sum(1 for w in weeks if w["solver_status"] == "OPTIMAL"),
        "mean_relative_gap": record["mean_relative_gap"],
        "max_relative_gap": max(gaps) if gaps else None,
        "elapsed_seconds": record["elapsed_seconds"],
        "seconds_per_decision": record.get("seconds_per_decision"),
        "opening_squad_ids": record["opening_squad_ids"],
        "diagnostics": record["diagnostics"],
        "weekly": [
            {
                "gameweek": w["gameweek"],
                "realized_points": w["realized_points"],
                "transfer_hit_points": w["transfer_hit_points"],
                "transfer_count": w["transfer_count"],
                "solver_status": w["solver_status"],
            }
            for w in weeks
        ],
    }


def decomposition(
    label: str, baseline_label: str, chains: Sequence[Mapping[str, object]]
) -> dict[str, object] | None:
    """Selection (realized points before hits) and hits, candidate minus baseline."""

    selection: dict[str, float] = {}
    hits: dict[str, float] = {}
    weekly_selection: list[float] = []
    weekly_hits: list[float] = []
    for candidate in chains:
        if candidate["variant"] != label:
            continue
        baseline = next(
            (
                row
                for row in chains
                if row["variant"] == baseline_label and row["season"] == candidate["season"]
            ),
            None,
        )
        if baseline is None:
            continue
        season = str(candidate["season"])
        selection[season] = float(str(candidate["realized_points"])) - float(
            str(baseline["realized_points"])
        )
        hits[season] = float(str(candidate["transfer_hit_points"])) - float(
            str(baseline["transfer_hit_points"])
        )
        base_weeks = {int(str(w["gameweek"])): w for w in chain_rows(baseline["weeks"])}
        for week in chain_rows(candidate["weeks"]):
            base = base_weeks.get(int(str(week["gameweek"])))
            if base is None:
                continue
            weekly_selection.append(
                float(str(week["realized_points"])) - float(str(base["realized_points"]))
            )
            weekly_hits.append(
                float(str(week["transfer_hit_points"])) - float(str(base["transfer_hit_points"]))
            )
    if not weekly_selection:
        return None
    return {
        "variant": label,
        "baseline": baseline_label,
        "season_selection_points": selection,
        "season_hit_points": hits,
        "mean_weekly_selection_points": sum(weekly_selection) / len(weekly_selection),
        "mean_weekly_hit_points": sum(weekly_hits) / len(weekly_hits),
    }


def verdict(primary: Mapping[str, object] | None) -> dict[str, object]:
    """The protocol's gate, read once from the primary comparison."""

    if primary is None:
        return {
            "certified": False,
            "status": "measured, not certified",
            "reason": "the primary comparison has no paired gameweeks",
        }
    mean = float(str(primary["mean_weekly_advantage_points"]))
    interval = primary["weekly_advantage_block_bootstrap_interval"]
    season_nets = dict(primary["season_net_advantage_points"])  # type: ignore[call-overload]
    losing = sorted(season for season, value in season_nets.items() if float(value) < 0.0)
    clears_floor = mean >= NOISE_FLOOR_POINTS_PER_GAMEWEEK
    excludes_zero = interval is not None and float(interval[0]) > 0.0  # type: ignore[index]
    few_losses = len(losing) <= MAX_LOSING_SEASONS
    certified = clears_floor and excludes_zero and few_losses
    return {
        "certified": certified,
        "status": "certified" if certified else "measured, not certified",
        "noise_floor_points_per_gameweek": NOISE_FLOOR_POINTS_PER_GAMEWEEK,
        "mean_weekly_advantage_points": mean,
        "clears_noise_floor": clears_floor,
        "interval_excludes_zero": excludes_zero,
        "losing_seasons": losing,
        "at_most_one_losing_season": few_losses,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


# -- the Markdown twin --------------------------------------------------------------------


def _interval_text(comparison: Mapping[str, object] | None) -> str:
    if comparison is None:
        return "none"
    interval = comparison["weekly_advantage_block_bootstrap_interval"]
    if interval is None:
        return "none"
    return f"[{float(interval[0]):+.2f}, {float(interval[1]):+.2f}]"  # type: ignore[index]


def _season_text(values: Mapping[str, object]) -> str:
    return ", ".join(
        f"{season} {float(str(value)):+.0f}" for season, value in sorted(values.items())
    )


def markdown_twin(document: Mapping[str, object]) -> str:
    seasons = [str(s) for s in document["seasons"]]  # type: ignore[union-attr]
    chains = [dict(row) for row in document["chains"]]  # type: ignore[union-attr]
    comparisons = {
        (str(c["variant"]), str(c["baseline"])): dict(c)
        for c in document["comparisons"]  # type: ignore[union-attr]
    }
    decompositions = {
        (str(c["variant"]), str(c["baseline"])): dict(c)
        for c in document["decompositions"]  # type: ignore[union-attr]
    }
    rhos = [float(r) for r in document["rhos"]]  # type: ignore[union-attr]
    primary_label = rho_label(float(str(document["primary_rho"])))
    primary = comparisons.get((primary_label, NAIVE_LABEL))
    gate = dict(document["verdict"])  # type: ignore[call-overload]
    labels = [CONTROL_LABEL, NAIVE_LABEL, *(rho_label(r) for r in rhos)]
    lines = [
        "# A mean-reversion discount for the later weeks of a multi-week plan",
        "",
        f"Protocol `{PROTOCOL_PATH}`, commit `{document['repository_commit']}`, archive commit "
        f"`{document['archive_commit']}`, run from {document['started_at_utc']} to "
        f"{document['finished_at_utc']}. Seasons {', '.join(seasons)} under development scope "
        f"`{document['development_scope']}`; 2025-26 is declared development data and never "
        "a test. Measurement only, nothing promoted.",
        "",
        "## Verdict",
        "",
        f"**{gate['status']}.** Primary comparison `{primary_label}` minus `{NAIVE_LABEL}`, "
        "realized points net of charged hits, paired per gameweek: mean "
        f"{gate.get('mean_weekly_advantage_points', float('nan')):+.2f} points per gameweek, "
        f"90% interval {_interval_text(primary)}, noise floor "
        f"{NOISE_FLOOR_POINTS_PER_GAMEWEEK} points per gameweek. "
        f"Clears the floor: {gate.get('clears_noise_floor')}. Interval excludes zero: "
        f"{gate.get('interval_excludes_zero')}. Seasons where the candidate's net is below "
        f"`{NAIVE_LABEL}`: {', '.join(gate.get('losing_seasons', [])) or 'none'} "
        f"(at most {MAX_LOSING_SEASONS} allowed).",
        "",
        "## The deciding table",
        "",
        "| Comparison | Paired weeks | Weekly mean | 90% interval | Weeks > 0 | Season nets |",
        "| --- | ---: | ---: | --- | ---: | --- |",
    ]
    ordered = (
        [(rho_label(r), NAIVE_LABEL) for r in rhos]
        + [(rho_label(r), CONTROL_LABEL) for r in rhos]
        + [(NAIVE_LABEL, CONTROL_LABEL)]
    )
    for key in ordered:
        comparison = comparisons.get(key)
        if comparison is None:
            continue
        marker = " (primary)" if key == (primary_label, NAIVE_LABEL) else ""
        lines.append(
            f"| `{key[0]}` minus `{key[1]}`{marker} | {comparison['paired_gameweeks']} | "
            f"{float(str(comparison['mean_weekly_advantage_points'])):+.2f} | "
            f"{_interval_text(comparison)} | "
            f"{float(str(comparison['positive_week_share'])):.2f} | "
            f"{_season_text(comparison['season_net_advantage_points'])} |"  # type: ignore[arg-type]
        )
    lines += [
        "",
        "## Season totals per arm (net of charged hits)",
        "",
        "| Season | Arm | Decisions | Realized | Hits | Net | Transfers | Paid | Reversals "
        "| Carried blank | Carried holes | Proven | Mean gap | Seconds per decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: | ---: |",
    ]
    for season in seasons:
        for label in labels:
            row = next((c for c in chains if c["season"] == season and c["variant"] == label), None)
            if row is None:
                continue
            gap = row["mean_relative_gap"]
            realized = float(str(row["realized_points"]))
            hits = float(str(row["transfer_hit_points"]))
            net = float(str(row["net_points"]))
            lines.append(
                f"| {season} | `{label}` | {row['decisions']} | {realized:.0f} "
                f"| {hits:.0f} | {net:.0f} "
                f"| {row['transfer_count']} | {row['paid_transfer_count']} | {row['reversals']} "
                f"| {row['carried_blank_rows']} | {row['carried_unexplained_rows']} "
                f"| {float(str(row['proven_share'])):.2f} "
                f"| {'none' if gap is None else f'{float(str(gap)):.3f}'} "
                f"| {float(str(row['seconds_per_decision'] or 0.0)):.1f} |"
            )
    lines += [
        "",
        "## Decomposition (candidate minus baseline)",
        "",
        "Selection is realized points before hits; hits are the charged hit points. Weekly "
        "means are over the paired gameweeks; season figures are season totals.",
        "",
        "| Comparison | Weekly selection | Weekly hits | Season selection | Season hits |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for key in ordered:
        piece = decompositions.get(key)
        if piece is None:
            continue
        lines.append(
            f"| `{key[0]}` minus `{key[1]}` | "
            f"{float(str(piece['mean_weekly_selection_points'])):+.2f} | "
            f"{float(str(piece['mean_weekly_hit_points'])):+.2f} | "
            f"{_season_text(piece['season_selection_points'])} | "  # type: ignore[arg-type]
            f"{_season_text(piece['season_hit_points'])} |"  # type: ignore[arg-type]
        )
    solver = dict(document["solver"])  # type: ignore[call-overload]
    bootstrap = dict(document["bootstrap"])  # type: ignore[call-overload]
    lines += [
        "",
        "## Solver and statistics",
        "",
        f"- Deterministic budget {solver['solver_deterministic_time_limit']} per solve, wall "
        f"clock cap {solver['solver_time_limit_seconds']} s; {solver['proven_decisions']} of "
        f"{solver['decisions']} decisions proved optimal; OR-Tools "
        f"{document['environment']['ortools']}.",  # type: ignore[index]
        f"- Intervals: 90% season-aware moving-block bootstrap, blocks of "
        f"{bootstrap['moving_block_length']} consecutive weeks, {bootstrap['resamples']} "
        f"resamples, seed {bootstrap['seed']}, on per-gameweek paired differences.",
        f"- Noise floor: an effect below {NOISE_FLOOR_POINTS_PER_GAMEWEEK} points per gameweek "
        "is not certified.",
        f"- Reversals: a purchased player sold within {REVERSAL_WINDOW_GAMEWEEKS} gameweeks of "
        "purchase.",
        "- Carried rows: squad members the chain carried at a zero projection because their "
        "club was blank that week (blank) or the archive had no row for them (holes). Under "
        "the mean-reversion rule such a member projects the position mean times one minus "
        "rho to the offset in a later week, where the naive rule keeps them at zero; the "
        "counts above size that side effect per chain.",
        "",
        "## Provenance",
        "",
        f"- Repository commit `{document['repository_commit']}`, working tree dirty: "
        f"{document['working_tree_dirty']}; archive commit `{document['archive_commit']}`.",
        f"- The chains ran at `{document['repository_commit']}`; this record was merged at "
        f"`{document['merge_repository_commit']}` (working tree dirty at the merge: "
        f"{document['merge_working_tree_dirty']}) from the per-season artifacts below, "
        "whose sha256 digests name the chain output the merge read. Where the two commits "
        "differ, the code that changed between them changed what the merge keeps of each "
        "chain and nothing in the chain, so the numbers stand (protocol step 4).",
        f"- Per-week expansion `{document['expansion']['path']}` (gitignored), sha256 "  # type: ignore[index]
        f"`{document['expansion']['sha256']}`.",  # type: ignore[index]
        f"- Machine: {document['environment']['platform']}, "  # type: ignore[index]
        f"{document['environment']['logical_cpu_count']} logical cores, Python "  # type: ignore[index]
        f"{document['environment']['python']}; one process per season in parallel.",  # type: ignore[index]
        "- Merged from: "
        + "; ".join(
            f"`{item['path']}` sha256 `{item['sha256']}`"  # type: ignore[index]
            for item in document["merged_from"]  # type: ignore[union-attr]
        )
        + ".",
        "",
    ]
    return "\n".join(lines)


# -- the command line ----------------------------------------------------------------------


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument(
        "--development-scope",
        choices=("v1", "v2"),
        default="v1",
        help="v2 admits 2025-26 as declared development data; v1 refuses it",
    )
    parser.add_argument("--rhos", default=DEFAULT_RHOS, help="mean-reversion factors, comma list")
    parser.add_argument(
        "--deterministic-time-limit", type=float, default=DEFAULT_DETERMINISTIC_TIME_LIMIT
    )
    parser.add_argument("--wall-time-limit", type=float, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
    parser.add_argument("--pilot-gameweeks", type=int, default=None)
    parser.add_argument("--merge", default=None, help="comma list of per-season artifacts")
    parser.add_argument("--json-output", type=Path, default=None)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--expansion-output", type=Path, default=ARTIFACT_ROOT / "weeks.json")
    return parser.parse_args(argv)


def _under_docs(path: Path) -> bool:
    try:
        path.resolve().relative_to(DOCS_ROOT.resolve())
    except ValueError:
        return False
    return True


def _merge(arguments: argparse.Namespace) -> int:
    sources = [Path(value.strip()) for value in str(arguments.merge).split(",")]
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in sources]
    if any(doc.get("contract_version") != CONTRACT_VERSION for doc in documents):
        print("Every merged artifact must carry the mean reversion discount contract.")
        return 1
    if any(doc.get("pilot_gameweeks") is not None for doc in documents):
        print("A pilot artifact is for timing and is not merged into a record.")
        return 1
    chains: list[dict[str, object]] = []
    seasons: list[str] = []
    for doc in documents:
        chains.extend(chain_rows(doc["chains"]))
        seasons.extend(str(season) for season in doc["seasons"])
    if len(set(seasons)) != len(seasons):
        print("Merged artifacts overlap in seasons; each season may appear once.")
        return 1
    commits = {str(doc["repository_commit"]) for doc in documents}
    if len(commits) != 1:
        print(f"Merged artifacts ran at different commits: {sorted(commits)!r}.")
        return 1
    rhos = [float(r) for r in documents[0]["rhos"]]
    if any([float(r) for r in doc["rhos"]] != rhos for doc in documents):
        print("Merged artifacts disagree on the rho grid.")
        return 1
    scopes = {str(doc["development_scope"]) for doc in documents}
    pilot = arguments.pilot_gameweeks is not None
    json_output = arguments.json_output or RECORD_JSON
    markdown_output = arguments.markdown_output or RECORD_MARKDOWN
    if pilot:
        print("--pilot-gameweeks and --merge do not combine.")
        return 1

    resamples = int(arguments.bootstrap_resamples)
    block_length = int(arguments.moving_block_length)
    pairs = [(rho_label(r), NAIVE_LABEL) for r in rhos]
    pairs += [(rho_label(r), CONTROL_LABEL) for r in rhos]
    pairs.append((NAIVE_LABEL, CONTROL_LABEL))
    comparisons = [
        comparison
        for label, baseline in pairs
        if (
            comparison := chain_comparison(
                label, baseline, chains, resamples=resamples, block_length=block_length
            )
        )
        is not None
    ]
    decompositions = [
        piece for label, baseline in pairs if (piece := decomposition(label, baseline, chains))
    ]
    primary = next(
        (
            c
            for c in comparisons
            if (c["variant"], c["baseline"]) == (rho_label(PRIMARY_RHO), NAIVE_LABEL)
        ),
        None,
    )
    gate = verdict(primary)

    expansion_path = Path(arguments.expansion_output)
    write_json(expansion_path, {"contract_version": CONTRACT_VERSION, "chains": chains})
    expansion_relative = (
        expansion_path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        if expansion_path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
        else str(expansion_path)
    )
    summaries = [chain_summary(row) for row in chains]
    solver = {
        **dict(documents[0]["solver_limits"]),
        "decisions": sum(int(str(s["decisions"])) for s in summaries),
        "proven_decisions": sum(int(str(s["proven_decisions"])) for s in summaries),
    }
    first = documents[0]
    merge_provenance = repository_provenance()
    document = {
        "contract_version": CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "protocol": PROTOCOL_PATH,
        "repository_commit": commits.pop(),
        "working_tree_dirty": any(bool(doc["working_tree_dirty"]) for doc in documents),
        "archive_commit": first["archive_commit"],
        "started_at_utc": min(str(doc["started_at_utc"]) for doc in documents),
        "finished_at_utc": max(str(doc["finished_at_utc"]) for doc in documents),
        "merged_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "merge_repository_commit": merge_provenance["repository_commit"],
        "merge_working_tree_dirty": merge_provenance["working_tree_dirty"],
        "merged_from": [{"path": str(path), "sha256": _sha256(path)} for path in sources],
        "provenance": first["provenance"],
        "environment": first["environment"],
        "development_scope": "v2" if "v2" in scopes else "v1",
        "locked_holdout_accessed": LOCKED_HOLDOUT_SEASON in seasons,
        "seasons": seasons,
        "arms": {
            CONTROL_LABEL: "lookahead 1, naive_calendar_scaling_v1, no transfer cap",
            NAIVE_LABEL: (
                "lookahead 3, naive_calendar_scaling_v1, one transfer a week with a second "
                "from two banked free transfers"
            ),
            **{
                rho_label(r): (
                    f"lookahead 3, mean_reversion_discount_v1 at rho {r:g}, one transfer a "
                    "week with a second from two banked free transfers"
                )
                for r in rhos
            },
        },
        "policy": {
            "planning_hit_cost_points": PLANNING_HIT_COST,
            "hit_points_charged": HIT_POINTS_CHARGED,
            "banked_transfer_value_points": 0.0,
            "horizon_discount_factor": 1.0,
            "chips": "off",
            "sell_on_fee_halved": True,
            "form_window": 5,
            "candidate_pool_per_position": 20,
            "cheap_pool_per_position": 8,
            "max_free_transfers": {s: MAX_FREE_TRANSFERS.get(s, 5) for s in seasons},
        },
        "rhos": rhos,
        "primary_rho": PRIMARY_RHO,
        "noise_floor_points_per_gameweek": NOISE_FLOOR_POINTS_PER_GAMEWEEK,
        "solver": solver,
        "bootstrap": {
            "resamples": resamples,
            "moving_block_length": block_length,
            "confidence_level": 0.90,
            "seed": 0,
        },
        "verdict": gate,
        "comparisons": comparisons,
        "decompositions": decompositions,
        "chains": summaries,
        "expansion": {"path": expansion_relative, "sha256": _sha256(expansion_path)},
        "measurement_only": True,
    }
    markdown = markdown_twin(document)
    write_json(json_output, document)
    write_text(markdown_output, markdown)
    print(markdown)
    print(f"Wrote {json_output}")
    print(f"Wrote {markdown_output}")
    print(f"Wrote {expansion_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if arguments.merge:
        return _merge(arguments)
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    seasons = tuple(value.strip() for value in str(arguments.seasons).split(","))
    scope = str(arguments.development_scope)
    if LOCKED_HOLDOUT_SEASON in seasons and scope != "v2":
        print(
            f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be walked under "
            f"--development-scope {scope}; v2 admits it as declared development data."
        )
        return 1
    rhos = [float(value.strip()) for value in str(arguments.rhos).split(",")]
    pilot = arguments.pilot_gameweeks
    stem = "pilot" if pilot is not None else "-".join(seasons)
    json_output = arguments.json_output or ARTIFACT_ROOT / f"{stem}.json"
    if pilot is not None and (
        _under_docs(json_output)
        or (arguments.markdown_output is not None and _under_docs(arguments.markdown_output))
    ):
        print("A pilot writes nowhere under docs/.")
        return 1
    if _under_docs(json_output):
        print("A per-season artifact belongs under artifacts/; --merge writes the record.")
        return 1

    deterministic = float(arguments.deterministic_time_limit)
    wall = arguments.wall_time_limit
    if wall is None:
        wall = max(60.0, 6.0 * deterministic)
    optimization_config = replace(
        measurement_optimization_config(),
        solver_time_limit_seconds=float(wall),
        solver_deterministic_time_limit=deterministic,
    )
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    records: list[dict[str, object]] = []
    try:
        for season in seasons:
            counts = season_fixture_counts(arguments.archive_root, season)
            arms = build_arms(
                season,
                rhos,
                optimization_config,
                end_gameweek=None if pilot is None else int(pilot) + 1,
            )
            records.extend(run_season(panel, counts, arms))
    except ExperimentError as error:
        print(f"Could not walk the chains:\n  {error}")
        return 1
    metadata = artifact_metadata(panel_rows=len(panel), created_utc=started_at)
    provenance = dict(metadata["provenance"])  # type: ignore[call-overload]
    document = {
        "contract_version": CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "protocol": PROTOCOL_PATH,
        "repository_commit": provenance["repository_commit"],
        "working_tree_dirty": provenance["working_tree_dirty"],
        "archive_commit": provenance["archive_commit"],
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": provenance,
        "environment": metadata["environment"],
        "development_scope": scope,
        "locked_holdout_accessed": LOCKED_HOLDOUT_SEASON in seasons,
        "seasons": list(seasons),
        "rhos": rhos,
        "pilot_gameweeks": pilot,
        "solver_limits": {
            "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
            "solver_deterministic_time_limit": optimization_config.solver_deterministic_time_limit,
        },
        "chains": records,
        "measurement_only": True,
    }
    write_json(json_output, document)
    print(f"Wrote {json_output}")
    for record in records:
        print(
            f"{record['season']} {record['variant']}: net {float(str(record['net_points'])):.0f}, "
            f"hits {float(str(record['transfer_hit_points'])):.0f}, "
            f"{float(str(record['seconds_per_decision'])):.1f} s per decision"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
