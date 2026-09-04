"""Shared pieces of the season-chain measurement runners.

The development-season rule assumptions (first-wildcard split, free-transfer cap), the
chip windows they imply, the archive's fixture counts per club, and the chain record /
paired comparison the runners write. Kept here so the chip-search and
transfer-discipline runners import a package module rather than another script.
"""

from collections.abc import Mapping
from pathlib import Path
from statistics import pstdev
from typing import Final

import pandas as pd

from squadopt.data.sources.vaastav import build_fixture_panel, load_team_codes
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.season_chain import ChipWindowRule, SeasonChainResult
from squadopt.experiments.statistics import season_aware_moving_block_interval

LOCKED_HOLDOUT_SEASON: Final = "2025-26"
DEFAULT_DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")

# Assumed development-season rules: the gameweek the first wildcard expires after, and
# the free-transfer bank cap. Not read from any capture; recorded as an assumption.
FIRST_WILDCARD_LAST_GAMEWEEK: dict[str, int] = {
    "2021-22": 20,
    "2022-23": 16,
    "2023-24": 20,
    "2024-25": 19,
}
MAX_FREE_TRANSFERS: dict[str, int] = {
    "2021-22": 2,
    "2022-23": 2,
    "2023-24": 2,
    "2024-25": 5,
}


def season_fixture_counts(archive_root: Path, season: str) -> pd.DataFrame:
    """Fixture counts per (gameweek, club name) of one archive season."""

    fixtures = build_fixture_panel(archive_root, seasons=(season,))
    codes = load_team_codes(archive_root, season)
    name_by_code = {
        int(code): str(name)
        for name, code in zip(codes["name"].tolist(), codes["code"].tolist(), strict=True)
    }
    counts = (
        fixtures.groupby(["gameweek", "team_id"], sort=True)
        .size()
        .reset_index(name="fixture_count")
    )
    counts["team_id"] = counts["team_id"].map(lambda code: name_by_code[int(code)])
    return counts


def chip_windows_for(season: str) -> tuple[ChipWindowRule, ...]:
    """The assumed chip windows of one development season."""

    split = FIRST_WILDCARD_LAST_GAMEWEEK.get(season, 19)
    return (
        ChipWindowRule("wildcard", 1, split),
        ChipWindowRule("wildcard", split + 1, 38),
        ChipWindowRule("bboost", 1, 38),
        ChipWindowRule("3xc", 1, 38),
        ChipWindowRule("freehit", 1, 38),
    )


def parse_holding_values(text: str) -> dict[str, float]:
    """Parse ``name=points,...`` into the planner's chip holding values."""

    values: dict[str, float] = {}
    for token in str(text).split(","):
        token = token.strip()
        if not token:
            continue
        name, _, number = token.partition("=")
        values[name.strip()] = float(number)
    return values


def chain_record(result: SeasonChainResult, label: str, elapsed: float) -> dict[str, object]:
    weeks = [week.as_record() for week in result.weeks]
    return {
        "season": result.season,
        "variant": label,
        "lookahead": result.lookahead,
        "chips_enabled": result.chips_enabled,
        "gameweeks": list(result.gameweeks),
        "decisions": len(result.weeks),
        "realized_points": result.realized_points,
        "transfer_hit_points": result.transfer_hit_points,
        "net_points": result.net_points,
        "transfer_count": result.transfer_count,
        "paid_transfer_count": sum(week.paid_transfer_count for week in result.weeks),
        "chips_played": {str(week): name for week, name in sorted(result.chips_played.items())},
        "chip_realized_gains": result.chip_realized_gains,
        "proven_share": result.proven_share,
        "mean_relative_gap": _mean(
            [week.relative_gap for week in result.weeks if week.relative_gap is not None]
        ),
        "carried_blank_rows": sum(week.carried_blank_rows for week in result.weeks),
        "carried_unexplained_rows": sum(week.carried_unexplained_rows for week in result.weeks),
        "final_squad_sell_value_tenths": result.weeks[-1].squad_sell_value_tenths,
        "final_bank_tenths": result.weeks[-1].bank_after_tenths,
        "elapsed_seconds": elapsed,
        "opening_squad_ids": [str(player) for player in result.opening_squad_ids],
        "diagnostics": dict(result.diagnostics),
        "weeks": weeks,
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def paired_weekly_differences(
    candidate: Mapping[str, object], baseline: Mapping[str, object]
) -> list[tuple[str, float]]:
    """Per-gameweek net-point differences (candidate minus baseline), season-tagged."""

    base_by_week = {
        int(str(week["gameweek"])): float(str(week["net_points"]))
        for week in chain_rows(baseline["weeks"])
    }
    return [
        (
            str(candidate["season"]),
            float(str(week["net_points"])) - base_by_week[int(str(week["gameweek"]))],
        )
        for week in chain_rows(candidate["weeks"])
        if int(str(week["gameweek"])) in base_by_week
    ]


def chain_rows(value: object) -> list[dict[str, object]]:
    assert isinstance(value, list)
    return [dict(item) for item in value]


def chain_comparison(
    label: str,
    baseline_label: str,
    chains: list[dict[str, object]],
    *,
    resamples: int,
    block_length: int,
) -> dict[str, object] | None:
    pairs: list[tuple[str, float]] = []
    season_totals: dict[str, float] = {}
    hits_delta: dict[str, float] = {}
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
        pairs.extend(paired_weekly_differences(candidate, baseline))
        season = str(candidate["season"])
        season_totals[season] = float(str(candidate["net_points"])) - float(
            str(baseline["net_points"])
        )
        hits_delta[season] = float(str(candidate["transfer_hit_points"])) - float(
            str(baseline["transfer_hit_points"])
        )
    if not pairs:
        return None
    values = [value for _, value in pairs]
    stdev = float(pstdev(values)) if len(values) > 1 else 0.0
    interval: tuple[float, float] | None = None
    if len(pairs) >= 2:
        policy = PromotionPolicy(bootstrap_resamples=resamples, moving_block_length=block_length)
        interval = season_aware_moving_block_interval(
            pairs, policy=policy, candidate_id=f"{label}_vs_{baseline_label}"
        )
    return {
        "variant": label,
        "baseline": baseline_label,
        "seasons": len(season_totals),
        "paired_gameweeks": len(values),
        "mean_season_net_advantage_points": sum(season_totals.values()) / len(season_totals),
        "season_net_advantage_points": season_totals,
        "season_hit_points_delta": hits_delta,
        "mean_weekly_advantage_points": sum(values) / len(values),
        "weekly_advantage_standard_error": stdev / len(values) ** 0.5,
        "positive_week_share": sum(1 for value in values if value > 0) / len(values),
        "weekly_advantage_block_bootstrap_interval": interval,
        "positive_season_share": (
            sum(1 for value in season_totals.values() if value > 0) / len(season_totals)
        ),
    }
