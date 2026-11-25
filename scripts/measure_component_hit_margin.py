"""Measure the member planner's hit margin on the component forecast.

    python -m scripts.measure_component_hit_margin --season 2024-25 --forecast component \\
        --handoff-dir <component handoff>
    python -m scripts.measure_component_hit_margin --season 2024-25 --forecast control
    python -m scripts.measure_component_hit_margin --merge a.json,b.json,...
    python -m scripts.measure_component_hit_margin --season 2024-25 --forecast component \\
        --handoff-dir <component handoff> --pilot-gameweeks 5

Protocol: ``docs/research/component_hit_margin_prereg.md``. The member planning policy plans
an extra transfer at 8 points while the game charges 4, a margin chosen on a season chain
walked on the form-window control. This runner walks the same chain on the Phase C component
base, the forecast that decides the served squads, at every planning hit cost from 4 to 12,
and walks the form-window control beside it on the same seasons as the reference.

One season and one forecast per process is the intended use: each writes its own artifact
under ``artifacts/component_hit_margin/``, and ``--merge`` combines the eight into the
committed record, its Markdown twin and the per-week expansion under ``artifacts/``.
``--handoff-dir`` holds ``phase_c_component_oof_v1.csv``, its ``.roster.csv`` and its
``.manifest.json``; the component arm refuses a handoff that is not the one
``docs/phase_c_component_evaluation.json`` names. ``--pilot-gameweeks`` walks the first N
decision gameweeks for timing, prints seconds only and writes nowhere under ``docs/``.
Measurement only: no default moves. The locked 2025-26 season is refused.
"""

import argparse
import hashlib
import json
import logging
import sys
from collections.abc import Mapping, Sequence
from dataclasses import replace
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
    SEASON_CHAIN_CONTRACT_VERSION,
    DecisionWeekProjections,
    ExperimentError,
    SeasonChain,
)
from squadopt.experiments.component_chain import load_component_chain_inputs
from squadopt.experiments.component_hit_margin import (
    COMPONENT,
    COMPONENT_HIT_MARGIN_CONTRACT_VERSION,
    CONTROL,
    FORECASTS,
    GAME_HIT_CHARGE,
    HIT_COST_LEVELS,
    MAX_LOSING_SEASONS,
    NOISE_FLOOR_POINTS_PER_GAMEWEEK,
    POLICY_HIT_COST,
    Arm,
    arm_label,
    build_arms,
    comparison_pairs,
    forecast_gap,
    reading,
)
from squadopt.experiments.season_chain_runs import (
    DEFAULT_DEVELOPMENT_SEASONS,
    LOCKED_HOLDOUT_SEASON,
    MAX_FREE_TRANSFERS,
    chain_comparison,
    chain_record,
    chain_rows,
    season_fixture_counts,
)

LOGGER = logging.getLogger(__name__)
PROTOCOL_PATH = "docs/research/component_hit_margin_prereg.md"
COMPONENT_RECORD = REPOSITORY_ROOT / "docs" / "phase_c_component_evaluation.json"
DEFAULT_DETERMINISTIC_TIME_LIMIT = 8.0
ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "component_hit_margin"
DOCS_ROOT = REPOSITORY_ROOT / "docs"
RECORD_JSON = DOCS_ROOT / "research" / "component_hit_margin.json"
RECORD_MARKDOWN = DOCS_ROOT / "research" / "component_hit_margin.md"
HANDOFF_DIGESTS = ("table_sha256", "roster_sha256", "manifest_sha256")


def handoff_matches_record(identity: Mapping[str, object], record_path: Path) -> dict[str, bool]:
    """Whether the handoff read is the one the component evaluation record names."""

    source = json.loads(record_path.read_text(encoding="utf-8"))["source"]
    return {
        **{name: identity[name] == source[name] for name in HANDOFF_DIGESTS},
        "model_version": identity["model_version"] == source["model_version"],
        "producer_repository_commit": (
            identity["producer_repository_commit"] == source["producer_repository_commit"]
        ),
    }


def run_arms(
    panel: object,
    counts: object,
    arms: Sequence[Arm],
    projections: DecisionWeekProjections | None,
) -> list[dict[str, object]]:
    """Walk every arm of one season and one forecast and return its chain records."""

    records: list[dict[str, object]] = []
    for arm in arms:
        LOGGER.info("Season %s: %s", arm.config.season, arm.label)
        started = datetime.now(UTC)
        result = SeasonChain(
            panel,  # type: ignore[arg-type]
            counts,  # type: ignore[arg-type]
            arm.config,
            decision_projections=projections,
        ).run()
        elapsed = (datetime.now(UTC) - started).total_seconds()
        record = chain_record(result, arm.label, elapsed)
        record["forecast"] = arm.forecast
        record["hit_cost"] = arm.hit_cost
        record["seconds_per_decision"] = elapsed / max(1, len(result.weeks))
        records.append(record)
        LOGGER.info(
            "  walked %d decisions, proven %.2f, %.0fs (%.1fs a decision)",
            len(result.weeks),
            result.proven_share,
            elapsed,
            elapsed / max(1, len(result.weeks)),
        )
    return records


def chain_summary(record: Mapping[str, object]) -> dict[str, object]:
    """One chain's totals for the committed record; its weeks stay in the expansion."""

    weeks = chain_rows(record["weeks"])
    proven = sum(1 for week in weeks if str(week["solver_status"]).lower() == "optimal")
    return {
        "season": record["season"],
        "variant": record["variant"],
        "forecast": record["forecast"],
        "hit_cost": record["hit_cost"],
        "decisions": record["decisions"],
        "net_points": record["net_points"],
        "realized_points": record["realized_points"],
        "transfer_hit_points": record["transfer_hit_points"],
        "transfer_count": record["transfer_count"],
        "paid_transfer_count": record["paid_transfer_count"],
        "proven_decisions": proven,
        "proven_share": record["proven_share"],
        "mean_relative_gap": record["mean_relative_gap"],
        "carried_blank_rows": record["carried_blank_rows"],
        "carried_unexplained_rows": record["carried_unexplained_rows"],
        "elapsed_seconds": record["elapsed_seconds"],
        "forecast_gap": forecast_gap(record),
    }


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def pooled_by_level(summaries: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Per forecast and hit cost: season means of net, hits and paid transfers."""

    pooled: dict[str, dict[str, object]] = {}
    for forecast in FORECASTS:
        levels: dict[str, object] = {}
        for level in sorted({int(str(s["hit_cost"])) for s in summaries}):
            rows = [
                s
                for s in summaries
                if s["forecast"] == forecast and int(str(s["hit_cost"])) == level
            ]
            if not rows:
                continue
            decisions = sum(int(str(row["decisions"])) for row in rows)
            net = sum(float(str(row["net_points"])) for row in rows)
            gap = 0.0
            for row in rows:
                per_decision = _mapping(row["forecast_gap"])["mean_projected_minus_realized"]
                gap += float(str(per_decision)) * int(str(row["decisions"]))
            levels[str(level)] = {
                "seasons": len(rows),
                "decisions": decisions,
                "mean_season_net": net / len(rows),
                "net_points_per_week": net / decisions,
                "mean_season_hit_points": sum(float(str(r["transfer_hit_points"])) for r in rows)
                / len(rows),
                "paid_transfers": sum(int(str(r["paid_transfer_count"])) for r in rows),
                "transfers": sum(int(str(r["transfer_count"])) for r in rows),
                "season_net": {str(r["season"]): float(str(r["net_points"])) for r in rows},
                "mean_projected_minus_realized": gap / decisions,
                "proven_share": sum(int(str(r["proven_decisions"])) for r in rows) / decisions,
            }
        pooled[forecast] = levels
    return pooled


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _signed(value: object, digits: int = 2) -> str:
    return f"{float(str(value)):+.{digits}f}"


def _interval_text(comparison: Mapping[str, object]) -> str:
    interval = comparison.get("weekly_advantage_block_bootstrap_interval")
    if not isinstance(interval, list | tuple) or len(interval) != 2:
        return "no interval"
    return f"[{_signed(interval[0])}, {_signed(interval[1])}]"


def markdown_twin(document: Mapping[str, object]) -> str:
    """The record as a page: reading first, then the tables behind it."""

    verdict = dict(document["reading"])  # type: ignore[call-overload]
    pooled = dict(document["pooled_by_level"])  # type: ignore[call-overload]
    comparisons = [dict(item) for item in document["comparisons"]]  # type: ignore[attr-defined]
    seasons = [str(season) for season in document["seasons"]]  # type: ignore[attr-defined]
    handoff = dict(document["component_handoff"])  # type: ignore[call-overload]
    solver = dict(document["solver"])  # type: ignore[call-overload]
    lines = [
        "# The member planner's hit margin on the component forecast",
        "",
        f"Protocol: [pre-registration](component_hit_margin_prereg.md). Record: "
        f"`{RECORD_JSON.name}`. Measurement only, no default moved.",
        "",
        "## Reading",
        "",
        f"**{verdict['reading']}**"
        + (
            f", candidate planning hit cost {verdict['candidate_hit_cost']}."
            if verdict["candidate_hit_cost"] is not None
            else "."
        ),
        "",
        f"- Levels passing the gate against {POLICY_HIT_COST} on the component arm: "
        f"{verdict['levels_passing_against_policy'] or 'none'}.",
        f"- {POLICY_HIT_COST} against the game's {GAME_HIT_CHARGE} on the component arm passes "
        f"the gate: {dict(verdict['policy_against_game_charge'])['passed']}.",
        f"- Highest pooled mean on the component arm: level "
        f"{verdict['highest_pooled_mean_level']}"
        + (
            ", on the edge of the grid, so the optimum is not bracketed."
            if verdict["highest_pooled_mean_on_grid_edge"]
            else ", inside the grid."
        ),
        f"- Gate: mean paired gain of at least {NOISE_FLOOR_POINTS_PER_GAMEWEEK} points a "
        f"gameweek, 90% interval above zero, lower season net in at most "
        f"{MAX_LOSING_SEASONS} season.",
        "",
    ]
    for forecast, title in ((COMPONENT, "Component base"), (CONTROL, "Form-window control")):
        lines += [
            f"## {title}: season chains by planning hit cost",
            "",
            "| Hit cost | Net a week | Mean season net | Mean season hits | Paid transfers | "
            + " | ".join(seasons)
            + " | Projected minus realized | Proven |",
            "| ---: | ---: | ---: | ---: | ---: | "
            + " | ".join("---:" for _ in seasons)
            + " | ---: | ---: |",
        ]
        for level, row in dict(pooled.get(forecast, {})).items():
            item = dict(row)
            season_net = dict(item["season_net"])
            lines.append(
                f"| {level} | {float(item['net_points_per_week']):.2f} | "
                f"{float(item['mean_season_net']):.1f} | "
                f"{float(item['mean_season_hit_points']):.1f} | {item['paid_transfers']} | "
                + " | ".join(f"{float(season_net[s]):.0f}" for s in seasons)
                + f" | {_signed(item['mean_projected_minus_realized'])} | "
                f"{float(item['proven_share']):.3f} |"
            )
        lines.append("")
        for baseline in (POLICY_HIT_COST, GAME_HIT_CHARGE):
            label = arm_label(forecast, baseline)
            rows = [c for c in comparisons if c["baseline"] == label]
            if not rows:
                continue
            lines += [
                f"### {title}: each level against {baseline}",
                "",
                "| Level | Mean a week | 90% interval | Paired weeks | "
                + " | ".join(seasons)
                + " |",
                "| ---: | ---: | --- | ---: | " + " | ".join("---:" for _ in seasons) + " |",
            ]
            for row in rows:
                season_gain = dict(row["season_net_advantage_points"])
                lines.append(
                    f"| {str(row['variant']).rsplit('hit', 1)[1]} | "
                    f"{_signed(row['mean_weekly_advantage_points'])} | {_interval_text(row)} | "
                    f"{row['paired_gameweeks']} | "
                    + " | ".join(_signed(season_gain[s], 0) for s in seasons)
                    + " |"
                )
            lines.append("")
    lines += [
        "## What was walked",
        "",
        f"- Seasons: {', '.join(seasons)}; one squad a season from its first decision "
        "gameweek to its last, lookahead 1, chips off, no transfer cap, the game's charge of "
        f"{GAME_HIT_CHARGE} on the sheet, sell-on fee halved, no automatic substitution.",
        f"- Component handoff: table `{str(handoff['table_sha256'])[:12]}`, "
        f"{handoff['folds']} folds, model `{handoff['model_version']}`; digests equal to the "
        f"component record's: {handoff['matches_record']}.",
        f"- Solver: deterministic budget {solver['solver_deterministic_time_limit']}, "
        f"{solver['proven_decisions']} of {solver['decisions']} decisions proved.",
        f"- Code: `{str(document['repository_commit'])[:12]}`, working tree dirty: "
        f"{document['working_tree_dirty']}. Per-week rows: "
        f"`{dict(document['expansion'])['path']}`.",  # type: ignore[call-overload]
        "",
        "[Research guide](README.md).",
        "",
    ]
    return "\n".join(lines)


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--handoff-dir", type=Path, default=None)
    parser.add_argument("--season", default=None, help="one development season")
    parser.add_argument("--forecast", choices=FORECASTS, default=None)
    parser.add_argument(
        "--deterministic-time-limit", type=float, default=DEFAULT_DETERMINISTIC_TIME_LIMIT
    )
    parser.add_argument("--wall-time-limit", type=float, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
    parser.add_argument("--pilot-gameweeks", type=int, default=None)
    parser.add_argument("--merge", default=None, help="comma list of per-process artifacts")
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
    if any(
        doc.get("contract_version") != COMPONENT_HIT_MARGIN_CONTRACT_VERSION for doc in documents
    ):
        print("Every merged artifact must carry the component hit margin contract.")
        return 1
    if any(doc.get("pilot_gameweeks") is not None for doc in documents):
        print("A pilot artifact is for timing and is not merged into a record.")
        return 1
    cells = [(str(doc["season"]), str(doc["forecast"])) for doc in documents]
    wanted = [
        (season, forecast) for season in DEFAULT_DEVELOPMENT_SEASONS for forecast in FORECASTS
    ]
    if sorted(cells) != sorted(wanted):
        print(f"The record needs each season under each forecast once; got {sorted(cells)!r}.")
        return 1
    commits = {str(doc["repository_commit"]) for doc in documents}
    if len(commits) != 1:
        print(f"Merged artifacts ran at different commits: {sorted(commits)!r}.")
        return 1
    if any(
        [int(level) for level in doc["hit_costs"]] != list(HIT_COST_LEVELS) for doc in documents
    ):
        print("Merged artifacts must each hold the protocol's hit cost grid.")
        return 1
    handoffs = [dict(doc["component_handoff"]) for doc in documents if doc["forecast"] == COMPONENT]
    if any(item != handoffs[0] for item in handoffs):
        print("The component artifacts read different handoffs.")
        return 1
    json_output = arguments.json_output or RECORD_JSON
    markdown_output = arguments.markdown_output or RECORD_MARKDOWN

    order = {cell: index for index, cell in enumerate(wanted)}
    chains: list[dict[str, object]] = []
    for doc in sorted(documents, key=lambda d: order[(str(d["season"]), str(d["forecast"]))]):
        chains.extend(chain_rows(doc["chains"]))
    resamples = int(arguments.bootstrap_resamples)
    block_length = int(arguments.moving_block_length)
    comparisons = [
        comparison
        for label, baseline in comparison_pairs()
        if (
            comparison := chain_comparison(
                label, baseline, chains, resamples=resamples, block_length=block_length
            )
        )
        is not None
    ]
    summaries = [chain_summary(row) for row in chains]
    expansion_path = Path(arguments.expansion_output)
    write_json(
        expansion_path,
        {"contract_version": COMPONENT_HIT_MARGIN_CONTRACT_VERSION, "chains": chains},
    )
    expansion_relative = (
        expansion_path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
        if expansion_path.resolve().is_relative_to(REPOSITORY_ROOT.resolve())
        else str(expansion_path)
    )
    first = documents[0]
    merge_provenance = repository_provenance()
    document = {
        "contract_version": COMPONENT_HIT_MARGIN_CONTRACT_VERSION,
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
        "merged_from": [{"path": path.name, "sha256": _sha256(path)} for path in sources],
        "provenance": first["provenance"],
        "environment": first["environment"],
        "development_scope": "v1",
        "locked_holdout_accessed": False,
        "seasons": list(DEFAULT_DEVELOPMENT_SEASONS),
        "forecasts": {
            COMPONENT: "the Phase C component base's decision-week forecast, "
            "supplied_decision_week_v1",
            CONTROL: "the form-window control, naive_calendar_scaling_v1",
        },
        "hit_cost_levels": list(HIT_COST_LEVELS),
        "policy": {
            "policy_hit_cost": POLICY_HIT_COST,
            "hit_points_charged": float(GAME_HIT_CHARGE),
            "lookahead": 1,
            "banked_transfer_value_points": 0.0,
            "horizon_discount_factor": 1.0,
            "max_transfers_per_gameweek": None,
            "chips": "off",
            "sell_on_fee_halved": True,
            "form_window": 5,
            "candidate_pool_per_position": 20,
            "cheap_pool_per_position": 8,
            "max_free_transfers": {
                season: MAX_FREE_TRANSFERS.get(season, 5) for season in DEFAULT_DEVELOPMENT_SEASONS
            },
            "automatic_substitutions": False,
        },
        "component_handoff": handoffs[0],
        "noise_floor_points_per_gameweek": NOISE_FLOOR_POINTS_PER_GAMEWEEK,
        "max_losing_seasons": MAX_LOSING_SEASONS,
        "solver": {
            **dict(first["solver_limits"]),
            "decisions": sum(int(str(s["decisions"])) for s in summaries),
            "proven_decisions": sum(int(str(s["proven_decisions"])) for s in summaries),
        },
        "bootstrap": {
            "resamples": resamples,
            "moving_block_length": block_length,
            "confidence_level": 0.90,
            "seed": 0,
        },
        "reading": reading(comparisons),
        "pooled_by_level": pooled_by_level(summaries),
        "comparisons": comparisons,
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
    if arguments.season is None or arguments.forecast is None:
        print("--season and --forecast are required unless --merge is given.")
        return 1
    season = str(arguments.season).strip()
    forecast = str(arguments.forecast)
    if season == LOCKED_HOLDOUT_SEASON or season not in DEFAULT_DEVELOPMENT_SEASONS:
        print(
            f"{season} is not a development season of this protocol "
            f"({', '.join(DEFAULT_DEVELOPMENT_SEASONS)}); {LOCKED_HOLDOUT_SEASON} is locked."
        )
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    if forecast == COMPONENT and (
        arguments.handoff_dir is None or not arguments.handoff_dir.is_dir()
    ):
        print("The component forecast needs --handoff-dir, the directory of the frozen handoff.")
        return 1
    pilot = arguments.pilot_gameweeks
    stem = f"pilot-{season}-{forecast}" if pilot is not None else f"{season}-{forecast}"
    json_output = arguments.json_output or ARTIFACT_ROOT / f"{stem}.json"
    if _under_docs(json_output):
        print("A per-process artifact belongs under artifacts/; --merge writes the record.")
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
    projections: DecisionWeekProjections | None = None
    handoff: dict[str, object] | None = None
    try:
        if forecast == COMPONENT:
            inputs = load_component_chain_inputs(arguments.handoff_dir, panel)
            handoff = inputs.identity()
            matches = handoff_matches_record(handoff, COMPONENT_RECORD)
            handoff["matches_record"] = all(matches.values())
            if not all(matches.values()):
                print(
                    "The component handoff is not the one "
                    f"docs/phase_c_component_evaluation.json names: {matches!r}. "
                    "No other projection is substituted."
                )
                return 1
            projections = inputs.projections[season]
        counts = season_fixture_counts(arguments.archive_root, season)
        arms = build_arms(
            season,
            forecast,
            optimization_config,
            end_gameweek=None if pilot is None else int(pilot) + 1,
        )
        records = run_arms(panel, counts, arms, projections)
    except ExperimentError as error:
        print(f"Could not walk the chains:\n  {error}")
        return 1
    metadata = artifact_metadata(panel_rows=len(panel), created_utc=started_at)
    provenance = dict(metadata["provenance"])  # type: ignore[call-overload]
    document = {
        "contract_version": COMPONENT_HIT_MARGIN_CONTRACT_VERSION,
        "chain_contract_version": SEASON_CHAIN_CONTRACT_VERSION,
        "protocol": PROTOCOL_PATH,
        "repository_commit": provenance["repository_commit"],
        "working_tree_dirty": provenance["working_tree_dirty"],
        "archive_commit": provenance["archive_commit"],
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": provenance,
        "environment": metadata["environment"],
        "season": season,
        "forecast": forecast,
        "hit_costs": list(HIT_COST_LEVELS),
        "pilot_gameweeks": pilot,
        "component_handoff": handoff,
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
            f"{record['season']} {record['variant']}: {record['decisions']} decisions, "
            f"{float(str(record['seconds_per_decision'])):.1f} s a decision"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
