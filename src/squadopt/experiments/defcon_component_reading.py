"""The declared DEFCON gate, evaluated once on paired whole gameweeks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from squadopt.evaluation.live_projection_audit import PRIOR_MINUTES_BUCKETS
from squadopt.prediction.defcon_component import DEFCON_PRIOR_APPEARANCES

BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20261007
RANK_BOUNDARY = -0.005
MINIMUM_WEEKS = 5


@dataclass(frozen=True, slots=True)
class PairedDefconRow:
    gameweek: int
    player_code: int
    position: str
    comparator: float
    candidate: float
    realized: float
    term_unconditional: float
    term_decided: float
    awarded_defcon: int
    prior_minutes: float
    # False when a realized award failed its checks: both diagnostic sides leave the player.
    defcon_diagnostic: bool = True


def summarize(
    rows: tuple[PairedDefconRow, ...], *, scored_weeks: tuple[int, ...]
) -> dict[str, Any]:
    """Equal week MSE weights and identical eligible rank groups in both arms."""
    if len(scored_weeks) != 7 or len(set(scored_weeks)) != 7:
        raise ValueError("The frozen window must contain seven distinct gameweeks.")
    seen: set[tuple[int, int]] = set()
    by_week: dict[int, list[PairedDefconRow]] = defaultdict(list)
    groups: dict[tuple[int, str], list[PairedDefconRow]] = defaultdict(list)
    for row in rows:
        key = (row.gameweek, row.player_code)
        if (
            key in seen
            or row.gameweek not in scored_weeks
            or row.position not in ("DEF", "MID", "FWD")
        ):
            raise ValueError("The paired population has an invalid or duplicate key.")
        seen.add(key)
        if not all(
            np.isfinite(value)
            for value in (
                row.comparator,
                row.candidate,
                row.realized,
                row.term_unconditional,
                row.term_decided,
                row.awarded_defcon,
                row.prior_minutes,
            )
        ):
            raise ValueError("The paired population has a non-finite value.")
        by_week[row.gameweek].append(row)
        groups[(row.gameweek, row.position)].append(row)
    weekly = []
    deltas = []
    for week, held in sorted(by_week.items()):
        base = float(np.mean([(row.comparator - row.realized) ** 2 for row in held]))
        candidate = float(np.mean([(row.candidate - row.realized) ** 2 for row in held]))
        deltas.append(candidate - base)
        weekly.append(
            {
                "gameweek": week,
                "players": len(held),
                "comparator_mse": base,
                "candidate_mse": candidate,
                "delta": candidate - base,
            }
        )
    rank_groups: list[dict[str, Any]] = []
    excluded = []
    ranks: dict[str, dict[str, Any]] = {}
    for (week, position), held in sorted(groups.items()):
        observed = pd.Series([row.realized for row in held])
        base_values = pd.Series([row.comparator for row in held])
        candidate_values = pd.Series([row.candidate for row in held])
        if (
            len(held) < 3
            or min(observed.nunique(), base_values.nunique(), candidate_values.nunique()) < 2
        ):
            excluded.append(
                {
                    "gameweek": week,
                    "position": position,
                    "players": len(held),
                    "reason": "fewer_than_three_or_constant_in_either_arm",
                }
            )
            continue
        # Average ranks implement Spearman with the audit's tie convention.
        rank_groups.append(
            {
                "gameweek": week,
                "position": position,
                "players": len(held),
                "comparator": float(base_values.rank().corr(observed.rank())),
                "candidate": float(candidate_values.rank().corr(observed.rank())),
            }
        )
    for position in ("DEF", "MID", "FWD"):
        valid = [group for group in rank_groups if group["position"] == position]
        count = sum(group["players"] for group in valid)
        base_rank = (
            sum(group["players"] * group["comparator"] for group in valid) / count
            if count
            else None
        )
        candidate_rank = (
            sum(group["players"] * group["candidate"] for group in valid) / count if count else None
        )
        ranks[position] = {
            "groups": len(valid),
            "players": count,
            "comparator": base_rank,
            "candidate": candidate_rank,
            "delta": candidate_rank - base_rank
            if candidate_rank is not None and base_rank is not None
            else None,
        }
    interval = None
    if deltas:
        values = np.array(deltas, dtype=float)
        rng = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED))
        draws = rng.choice(values, size=(BOOTSTRAP_DRAWS, len(values)), replace=True).mean(axis=1)
        bounds = np.quantile(draws, [0.05, 0.95], method="linear")
        interval = {"lower": float(bounds[0]), "upper": float(bounds[1])}
    verdict = "insufficient_evidence"
    if len(weekly) >= MINIMUM_WEEKS:
        passed = (
            interval is not None
            and interval["upper"] < 0
            and all(
                ranks[position]["delta"] is not None and ranks[position]["delta"] >= RANK_BOUNDARY
                for position in ("DEF", "MID")
            )
        )
        verdict = "passed" if passed else "failed"
    diagnostics = {}
    for position in ("DEF", "MID", "FWD"):
        held = [row for row in rows if row.position == position]
        kept = [row for row in held if row.defcon_diagnostic]
        diagnostics[position] = {
            "players": len(kept),
            "excluded_players": len(held) - len(kept),
            "term_unconditional": sum(row.term_unconditional for row in kept),
            "term_decided": sum(row.term_decided for row in kept),
            "awarded_defcon": sum(row.awarded_defcon for row in kept),
        }
    buckets = {}
    for label, low, high in PRIOR_MINUTES_BUCKETS:
        held = [
            row
            for row in rows
            if (
                row.prior_minutes == 0
                if high == 0
                else row.prior_minutes > 0 and low <= row.prior_minutes < high
            )
        ]
        buckets[label] = {
            "players": len(held),
            "comparator_forecast": sum(row.comparator for row in held),
            "candidate_forecast": sum(row.candidate for row in held),
            "realized_points": sum(row.realized for row in held),
            "comparator_mse": float(np.mean([(row.comparator - row.realized) ** 2 for row in held]))
            if held
            else None,
            "candidate_mse": float(np.mean([(row.candidate - row.realized) ** 2 for row in held]))
            if held
            else None,
        }
    return {
        "verdict": verdict,
        "numerical_environment": {"numpy": np.__version__, "pandas": pd.__version__},
        "promotion": False,
        "weekly": weekly,
        "valid_weeks": len(weekly),
        "delta": float(np.mean(deltas)) if deltas else None,
        "interval_90": interval,
        "ranks": ranks,
        "rank_groups": rank_groups,
        "excluded_rank_groups": excluded,
        "defcon_by_position": diagnostics,
        "prior_minutes_buckets": buckets,
        "constants": reading_constants(),
    }


def reading_constants() -> dict[str, Any]:
    """Keep constants available even if the numerical summary cannot complete."""
    return {
        "prior_fixture_appearances": DEFCON_PRIOR_APPEARANCES,
        "bootstrap_draws": BOOTSTRAP_DRAWS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "quantile_method": "linear",
        "rank_boundary": RANK_BOUNDARY,
        "minimum_weeks": MINIMUM_WEEKS,
        "gameweek_weights": "equal",
    }
