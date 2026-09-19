r"""Solve each member's window twice, once with the named chip forced, once with no chip.

    python -m scripts.measure_forced_chip_window --snapshot-id fpl-live-...

Protocol: ``docs/forced_chip_window_prereg.md``. The reading is whether the **first week**
differs, because that is the only week a member acts on. The plan's value is context: a forced
free chip can only raise it inside the model.

Both arms go through ``plan_transfer_horizon`` with the arguments ``solve_window_plan`` uses,
including the window's own budget and linearization level, and differ only by
``ChipAvailability``. The runner checks that against the product's own function before it reads
anything, so "the window exactly as the product solves it today" is verified rather than
asserted.

Which rule named the weeks is part of the record, not background: it is read from
``MEASURED_THRESHOLD_POLICY`` and ``MEASURED_RESERVATION``, which carry what
``chip_forecast_rule`` settled.
"""

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.application.advice import (
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
    solve_window_plan,
    window_horizon,
)
from squadopt.application.chip_forecast import (
    BENCH_BOOST,
    MEASURED_RESERVATION,
    MEASURED_THRESHOLD_POLICY,
    PROTOCOL_HOLDING_VALUES,
    TRIPLE_CAPTAIN,
    ChipForecastInputs,
    GameweekFixtures,
    HeldChip,
    SquadRow,
    chip_forecast,
)
from squadopt.application.entries import EntryPicks, held_squad_from_picks
from squadopt.data.sources import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.data.sources.fpl_live import fixture_snapshot
from squadopt.live.transfers import plan_transfer_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.planning import ChipAvailability
from squadopt.platform.capture_context import (
    AdviceCaptureContext,
    load_capture_context,
    load_capture_identity,
)

CONTRACT_VERSION = "forced_chip_window_v1"
#: The chips whose later week the weekly rule can name at all: the two with a weekly value.
NAMEABLE_CHIPS = (TRIPLE_CAPTAIN, BENCH_BOOST)
DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "forced_chip_window.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "forced_chip_window.md"


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--windows", default="3,5")
    parser.add_argument("--entries", default="all")
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def calendar_from(
    fixtures: pd.DataFrame, gameweeks: Sequence[int], clubs: Sequence[int]
) -> list[GameweekFixtures]:
    """One entry per gameweek, every club stated, a blank stated as a zero.

    Seeding every club with a zero before counting is the step that matters: a club with no
    fixture row that week is blank, and a count built only from the rows present would make
    the week look like an ordinary one.
    """

    counted = (
        fixtures.loc[fixtures["gameweek"].isin(list(gameweeks)), ["gameweek", "team_id"]]
        .groupby(["gameweek", "team_id"])
        .size()
    )
    return [
        GameweekFixtures(
            gameweek=int(week),
            fixture_count_by_club={int(club): int(counted.get((week, club), 0)) for club in clubs},
        )
        for week in sorted(gameweeks)
    ]


def squad_rows(
    picks: EntryPicks, projection: pd.DataFrame, players: pd.DataFrame
) -> list[SquadRow]:
    """The member's fifteen as the forecast reads them, from this capture's own numbers.

    The bench is the squad less the starting eleven, in the squad's own order, which is the
    order the capture states. A player the projection has no number for is carried at zero
    here only because the forecast needs a number for the bench sum; the projection's own
    record of unprojected players is what says a number is missing, and this runner refuses
    a squad that holds one rather than quietly adding zeros.
    """

    points = dict(
        zip(
            projection["player_id"].astype("int64"),
            projection["expected_points"].astype(float),
            strict=True,
        )
    )
    clubs = dict(
        zip(players["player_id"].astype("int64"), players["team_id"].astype("int64"), strict=True)
    )
    positions = dict(
        zip(players["player_id"].astype("int64"), players["position"].astype(str), strict=True)
    )
    missing = [int(p) for p in picks.squad if int(p) not in points]
    if missing:
        raise SystemExit(
            f"Entry {picks.entry_id} holds {missing!r}, which the projection has no number "
            "for; a bench sum built over a zero would be a number nobody computed."
        )
    starting = {int(p) for p in picks.starting_xi}
    bench = [int(p) for p in picks.squad if int(p) not in starting]
    return [
        SquadRow(
            player_id=int(player),
            club_id=int(clubs[int(player)]),
            position=positions[int(player)],
            expected_points=float(points[int(player)]),
            bench_order=(bench.index(int(player)) + 1 if int(player) in set(bench) else None),
            is_captain=int(player) == int(picks.captain),
        )
        for player in picks.squad
    ]


def named_weeks(forecast: Mapping[str, Any], *, first: int, last: int) -> dict[str, int]:
    """Each chip the rule points at a later gameweek for, and which gameweek that is.

    A chip the rule says to play now is not read here: this measurement is about preparing
    for a week that has not come. A chip with no later week named, or one named outside the
    window being solved, is not read either.
    """

    named: dict[str, int] = {}
    for chip in forecast["chips"]:
        at = chip.get("points_at_gameweek")
        if chip["verdict"] != "hold" or not isinstance(at, dict):
            continue
        week = int(at["gameweek"])
        if first <= week <= last:
            named[str(chip["name"])] = week
    return named


def _window_solve(
    context: AdviceCaptureContext,
    picks: EntryPicks,
    window: int,
    chips: ChipAvailability | None,
) -> Any:
    """The window exactly as the product solves it, plus an optional chip availability."""

    inputs = context.inputs
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    plan, _ = plan_transfer_horizon(
        inputs,
        window_horizon(inputs, window, context.horizon_builder),
        held_squad_from_picks(picks, current_prices=prices),
        context.rules,
        optimization=OptimizationConfig(
            solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
            solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * window,
        ),
        chips=chips,
        linearization_level=WINDOW_LINEARIZATION_LEVEL,
    )
    return plan


def first_week(plan: Any) -> dict[str, Any]:
    """What a member does this week under one plan: the only week they act on."""

    week = plan.weeks[0]
    return {
        "gameweek": int(week.gameweek),
        "transfers_in": sorted(int(p) for p in week.transfers_in["player_id"]),
        "transfers_out": sorted(int(p) for p in week.transfers_out["player_id"]),
        "captain_id": None if week.captain is None else int(week.captain["player_id"]),
        "starting_xi": sorted(int(p) for p in week.starting_xi["player_id"]),
        "paid_transfers": int(week.paid_transfer_count),
    }


def _row(plan: Any, arm: str) -> dict[str, Any]:
    diagnostics = plan.diagnostics
    return {
        "arm": arm,
        "solver_status": plan.solver_status.name,
        "plan_value": diagnostics.get("scaled_model_objective_value"),
        "absolute_gap": diagnostics.get("absolute_optimality_gap"),
        "deterministic_time_used": diagnostics.get("deterministic_time_used"),
        "wall_seconds": diagnostics.get("solve_time_seconds"),
        "first_week": first_week(plan),
    }


def compare(no_chip: Mapping[str, Any], forced: Mapping[str, Any]) -> dict[str, Any]:
    """What differs, and whether the value difference may be attributed to the chip."""

    proved = no_chip["solver_status"] == "OPTIMAL" and forced["solver_status"] == "OPTIMAL"
    differs = {
        field: (no_chip["first_week"][field], forced["first_week"][field])
        for field in (
            "transfers_in",
            "transfers_out",
            "captain_id",
            "starting_xi",
            "paid_transfers",
        )
        if no_chip["first_week"][field] != forced["first_week"][field]
    }
    gap = max(
        float(no_chip["absolute_gap"] or 0.0),
        float(forced["absolute_gap"] or 0.0),
    )
    return {
        "first_week_differs": bool(differs),
        "first_week_differences": differs,
        "plan_value_difference": float(forced["plan_value"]) - float(no_chip["plan_value"]),
        "both_arms_proved": proved,
        "largest_open_gap": None if proved else gap,
        "value_difference_attributable": proved,
    }


def _markdown(record: Mapping[str, Any]) -> str:
    rows = record["comparisons"]
    lines = [
        "# The window solved with a named chip forced",
        "",
        f"Capture `{record['snapshot_id']}`, gameweek {record['gameweek']}. "
        f"**The weeks were named by the rule `chip_forecast_rule` settled on 2026-09-19: the "
        f"`{record['threshold_policy']}` threshold, reservation "
        f"{'kept' if record['reserve'] else 'dropped'}.** A record written under another rule is "
        "another record and says so here.",
        "",
        "Every value below is what our own projection says under the same numbers in both arms, "
        "for gameweeks that have not been played. None of it is points the season will pay.",
        "",
        "| Entry | Window | Chip | Named week | Weeks ahead | First week differs | "
        "Plan value difference | Both proved |",
        "| ---: | ---: | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for row in rows:
        c = row["comparison"]
        value = (
            f"{c['plan_value_difference']:+.3f}"
            if c["both_arms_proved"]
            else f"{c['plan_value_difference']:+.3f} (gap {c['largest_open_gap']:.2f})"
        )
        lines.append(
            f"| {row['entry_id']} | {row['window']} | `{row['chip']}` | {row['named_gameweek']} | "
            f"{row['weeks_ahead']} | {'yes' if c['first_week_differs'] else 'no'} | {value} | "
            f"{'yes' if c['both_arms_proved'] else 'no'} |"
        )
    summary = record["by_distance"]
    lines += [
        "",
        "## By how far away the named week is",
        "",
        "Without this split a reader cannot tell two reasons for no difference apart: a chip "
        "named for the next gameweek that changes nothing this week is a finding, and a chip "
        "named for the last week of a five week window that changes nothing is close to "
        "arithmetic.",
        "",
        "| Weeks ahead | Comparisons | First week differs | Both proved |",
        "| ---: | ---: | ---: | ---: |",
    ]
    for distance, cell in sorted(summary.items(), key=lambda kv: int(kv[0])):
        lines.append(
            f"| {distance} | {cell['comparisons']} | {cell['first_week_differs']} | "
            f"{cell['both_proved']} |"
        )
    lines += [
        "",
        f"Total: {record['first_week_differs']} of {len(rows)} comparisons change the first "
        f"week. Solver cost, this machine: {record['total_wall_seconds']:.0f} wall seconds over "
        f"{record['solves']} solves.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
        return 1
    root = Path(arguments.data_root)
    identity = load_capture_identity(
        snapshot_root=root / "snapshots",
        snapshot_id=arguments.snapshot_id,
        handoff_root=root / "handoffs",
        advice_contract_version=CONTRACT_VERSION,
        repository_commit=CONTRACT_VERSION,
        configuration_fingerprint=CONTRACT_VERSION,
    )
    context = load_capture_context(identity)
    inputs = context.inputs
    gameweek = int(inputs.deadline.gameweek)
    windows = [int(value) for value in str(arguments.windows).split(",") if value.strip()]
    if arguments.entries == "all":
        records = root / "snapshots" / arguments.snapshot_id / "payloads"
        entries = sorted(
            {
                int(path.name.removeprefix("entry-").split("-")[0])
                for path in records.glob("entry-*-picks-*.json")
            }
        )
    else:
        entries = [int(value) for value in str(arguments.entries).split(",")]
    if not entries:
        print(f"{arguments.snapshot_id} holds no member picks.")
        return 1
    started = datetime.now(UTC)

    snapshot = identity.snapshot
    fixtures = fixture_snapshot(
        snapshot.payloads[FIXTURES_PAYLOAD],
        snapshot.payloads[BOOTSTRAP_PAYLOAD],
        season=str(inputs.season),
        snapshot_id=arguments.snapshot_id,
        captured_at_utc=str(inputs.captured_at_utc),
    )
    clubs = sorted({int(value) for value in inputs.players["team_id"].astype("int64")})
    rows: list[dict[str, Any]] = []
    mirrored = False
    for entry_id in entries:
        picks = context.provider.picks(entry_id, str(inputs.season), gameweek - 1)
        squad = squad_rows(picks, context.projection.table, inputs.players)
        for window in windows:
            last = gameweek + window - 1
            forecast = chip_forecast(
                ChipForecastInputs(
                    decision_gameweek=gameweek,
                    # Every chip is asked for; the rule decides which it points a week at.
                    chips=tuple(HeldChip(name, gameweek, last, None) for name in NAMEABLE_CHIPS),
                    squad=tuple(squad),
                    calendar=tuple(calendar_from(fixtures, range(gameweek, last + 1), clubs)),
                    holding_values=PROTOCOL_HOLDING_VALUES,
                    threshold=MEASURED_THRESHOLD_POLICY,
                    reserve=MEASURED_RESERVATION,
                )
            )
            named = named_weeks(forecast, first=gameweek + 1, last=last)
            if not named:
                continue
            plain = _window_solve(context, picks, window, None)
            if not mirrored:
                # The no-chip arm has to be the window the product solves, not one like it.
                product = solve_window_plan(
                    picks,
                    inputs,
                    context.rules,
                    window_horizon(inputs, window, context.horizon_builder),
                    window=window,
                )
                mirrored = True
                if first_week(product) != first_week(plain):
                    print("The no-chip arm does not reproduce solve_window_plan's first week.")
                    return 1
            for chip, week in sorted(named.items()):
                forced = _window_solve(
                    context,
                    picks,
                    window,
                    ChipAvailability(available={chip: frozenset({week})}, forced={week: chip}),
                )
                no_chip_row, forced_row = _row(plain, "no_chip"), _row(forced, "forced")
                rows.append(
                    {
                        "entry_id": entry_id,
                        "window": window,
                        "chip": chip,
                        "named_gameweek": week,
                        "weeks_ahead": week - gameweek,
                        "arms": {"no_chip": no_chip_row, "forced": forced_row},
                        "comparison": compare(no_chip_row, forced_row),
                    }
                )

    by_distance: dict[str, dict[str, int]] = {}
    for row in rows:
        cell = by_distance.setdefault(
            str(row["weeks_ahead"]), {"comparisons": 0, "first_week_differs": 0, "both_proved": 0}
        )
        cell["comparisons"] += 1
        cell["first_week_differs"] += int(row["comparison"]["first_week_differs"])
        cell["both_proved"] += int(row["comparison"]["both_arms_proved"])
    record = {
        "contract_version": CONTRACT_VERSION,
        "prereg": "docs/forced_chip_window_prereg.md",
        "generated_at_utc": started.replace(microsecond=0).isoformat(),
        "snapshot_id": arguments.snapshot_id,
        "gameweek": gameweek,
        "season": str(inputs.season),
        "threshold_policy": MEASURED_THRESHOLD_POLICY,
        "reserve": MEASURED_RESERVATION,
        "rule_source": "docs/chip_forecast_rule.json",
        "holding_values": dict(PROTOCOL_HOLDING_VALUES),
        "window_linearization_level": WINDOW_LINEARIZATION_LEVEL,
        "deterministic_units_per_week": WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
        "members": len(entries),
        "windows": windows,
        "comparisons": rows,
        "solves": sum(1 for _ in rows) + len({(r["entry_id"], r["window"]) for r in rows}),
        "first_week_differs": sum(int(r["comparison"]["first_week_differs"]) for r in rows),
        "by_distance": by_distance,
        "total_wall_seconds": sum(
            float(r["arms"]["forced"]["wall_seconds"] or 0.0)
            + float(r["arms"]["no_chip"]["wall_seconds"] or 0.0)
            for r in rows
        ),
        "elapsed_seconds": (datetime.now(UTC) - started).total_seconds(),
    }
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(json.dumps({k: v for k, v in record.items() if k != "comparisons"}, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
